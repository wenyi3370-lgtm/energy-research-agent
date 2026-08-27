"""Real research orchestration wiring: planner -> search -> extract -> gate (编排接线).

This closes the break documented in ``docs/automation/architecture-audit.md``
§2.2: ``ResearchPlanner -> SearchExecutor -> EvidenceExtractor`` were
implemented but had no production runner. :class:`OrchestratingExecutor`
implements the automation ``ResearchExecutor`` protocol over the real
kernel, as a deterministic state-driven pipeline:

    plan -> search (page budget) -> extract -> saturation assessment
    -> Phase 3 ingest + validation (NO freeze) -> CoreValidator gate

and on the publish side (only ever called after APPROVED):

    Phase 2 finalize (re-validate -> freeze -> plan -> export)
    -> artifact publish -> consistency audit

Fail-closed rules:

- only adapters whose ``health()`` reports available are used; any other
  adapter preference is reported as a blocked envelope (zero evidence ->
  the run lands BLOCKED instead of guessing).
- a ``ModelGateway`` is optional; without one, only recorded fixture
  batches embedded in adapter output can be extracted.
- saturation findings are surfaced as review reasons, never silently
  dropped; the pipeline itself never fabricates records.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..adapters.anysearch import AnySearchCliAdapter
from .. import __version__
from ..adapters.base import SearchAdapter, SearchResultEnvelope
from ..adapters.kimi_webbridge import KimiWebBridgeAdapter
from ..adapters.unconfigured import UnconfiguredSearchAdapter
from ..artifacts.publisher import ArtifactPublicationService
from ..domain.enums import ArtifactStatus, EnterpriseComplexity, RunStatus, ValidationStatus, VerificationStatus
from ..domain.ids import new_sortable_id
from ..domain.models import ExtractedEvidenceBatch, ProductDetection, RunManifest
from ..evidence.freeze import FreezeService
from ..evidence.store import EvidenceStore
from ..gateway.base import ModelGateway
from ..graph.phase3_runner import Phase3Runner
from ..graph.runner import Phase2Runner
from ..graph.state import ResearchState
from ..release.audit import ArtifactConsistencyAuditor
from ..research.executor import SearchExecutor
from ..research.extractor import EvidenceExtractor
from ..research.fulltext_hydration import hydrate_target_pages, is_material_envelope
from ..research.planner import ResearchPlanner
from ..research.quality import ResearchQualityCalculator, write_research_quality
from ..research.requirement_routing import routing_manifest
from ..research.saturation import CollectionAttemptSummary, DataSaturationValidator
from ..settings import Settings, load_yaml
from ..validation.core import CoreValidator
from .contracts import ArtifactRef, ResearchRequest
from .enums import RiskLevel
from .executor import (
    EVIDENCE_KINDS,
    ExecutionOutcome,
    default_publishers,
    mean_claim_confidence,
    risk_for,
)
from .observability import CountingGateway, GatewayUsage

# Agent recovery rounds annotate their planned queries as note lines
# "第N轮补采：{query}" (agent/api.py). Recovery mode must execute those
# texts VERBATIM; feeding them back through the keyword template engine
# regenerated the same dead searches every round.
_RECOVERY_LINE = re.compile(r"^第(\d+)轮补采：(.+)$")


def split_recovery_notes(notes: str) -> tuple[list[str], int]:
    """Split recovery notes into (verbatim recovery query texts, max round).

    Non-matching lines (original user requirements) are intentionally not
    returned: during a recovery round the agent's planned queries are the
    whole search contract, and re-searching the round-0 requirement text
    only repeats already-covered ground.
    """
    texts: list[str] = []
    max_round = 0
    for line in (notes or "").splitlines():
        match = _RECOVERY_LINE.match(line.strip())
        if match:
            max_round = max(max_round, int(match.group(1)))
            if match.group(2).strip():
                texts.append(match.group(2).strip())
    return texts, max_round


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class OrchestratingExecutor:
    """Deterministic research pipeline over real search adapters and gateway."""

    def __init__(
        self,
        *,
        adapters: dict[str, SearchAdapter],
        gateway: ModelGateway | None = None,
        budgets_path: Path | None = None,
        saturation_policy_path: Path | None = None,
        enterprise_rules_path: Path | None = None,
        code_version: str = __version__,
        publishers: dict | None = None,
    ) -> None:
        self.adapters = {
            name: adapter for name, adapter in adapters.items() if adapter.health().available
        }
        self.missing_adapters = sorted(set(adapters) - set(self.adapters))
        self.gateway = gateway
        self.usage = GatewayUsage()
        self.wrapped_gateway = CountingGateway(gateway, usage=self.usage) if gateway else None
        self.code_version = code_version
        self.budgets = load_yaml(budgets_path or PROJECT_ROOT / "config" / "research_budgets.yaml")
        self.saturation_policy = load_yaml(
            saturation_policy_path or PROJECT_ROOT / "config" / "collection_saturation_policy.yaml"
        )
        self.enterprise_rules = load_yaml(
            enterprise_rules_path or PROJECT_ROOT / "config" / "enterprise_rules.yaml"
        )
        self.publishers = publishers if publishers is not None else default_publishers()
        # Portal research must hydrate discovery hits before evidence
        # extraction.  Search-result snippets are leads, never factual source
        # material.  Keep the limits explicit and configurable for Docker.
        self.fulltext_pages_per_query = max(
            1, int(os.environ.get("EER_FULLTEXT_PAGES_PER_QUERY", "3"))
        )
        self.fulltext_workers = max(
            1, min(12, int(os.environ.get("EER_FULLTEXT_WORKERS", "6")))
        )

    # -- ports ---------------------------------------------------------------

    @classmethod
    def from_environment(
        cls,
        gateway: ModelGateway | None = None,
        adapters: dict[str, SearchAdapter] | None = None,
    ) -> "OrchestratingExecutor":
        """Defaults for production: AnySearch + Kimi WebBridge, fail-closed.

        Any adapter that cannot be constructed (missing skill root, no
        credentials, daemon offline) is replaced by an
        ``UnconfiguredSearchAdapter`` so the run reports BLOCKED instead of
        guessing. Kimi WebBridge session name comes from
        ``EER_KIMI_WEB_SESSION`` (default ``default``).
        """
        if adapters is not None:
            return cls(adapters=adapters, gateway=gateway)
        import os

        resolved: dict[str, SearchAdapter] = {}
        try:
            resolved["anysearch"] = AnySearchCliAdapter()
        except Exception:  # noqa: BLE001 - fail-closed on construction errors
            resolved["anysearch"] = UnconfiguredSearchAdapter("anysearch")
        try:
            resolved["kimi_webbridge"] = KimiWebBridgeAdapter(
                os.environ.get("EER_KIMI_WEB_SESSION", "default"),
                daemon_url=os.environ.get(
                    "EER_KIMI_WEB_DAEMON_URL", "http://127.0.0.1:10086"
                ),
            )
        except Exception:  # noqa: BLE001
            resolved["kimi_webbridge"] = UnconfiguredSearchAdapter("kimi_webbridge")
        return cls(adapters=resolved, gateway=gateway)

    # -- phase A: plan -> search -> extract -> ingest -> validate ------------

    def research_and_validate(
        self, run_id: str, request: ResearchRequest, workdir: Path,
        *, recovery_only: bool = False,
    ) -> ExecutionOutcome:
        """One research pass.

        ``recovery_only=True`` executes only the round's targeted gap queries
        (deep_retry style, §22): the full plan is never re-run during recovery
        rounds, so evidence accumulates across rounds without re-collecting
        already-covered families.
        """
        run_dir = Path(workdir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        settings = Settings(output_root=run_dir / "outputs")
        domain_request = request.to_domain_request(new_sortable_id("REQ"))
        planner = ResearchPlanner()
        requirements = str(domain_request.optional_scope.get("notes") or "").strip()
        requirement_topics = [
            family for family, _focus in planner.requirement_intents(requirements)
        ]
        store = EvidenceStore(run_dir / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id,
            request_id=domain_request.request_id,
            status=RunStatus.RUNNING,
            config_hash=settings.config_hash(),
            code_version=self.code_version,
            model_gateway={
                "primary_provider": settings.primary_provider,
                "fallback_provider": settings.fallback_provider,
                "mode": "live" if self.gateway else "recorded-fixture-only",
            },
            adapter_versions={
                name: str(adapter.health().version) for name, adapter in self.adapters.items()
            },
            research_scope={
                "mode": "full_enterprise_plus_supplements",
                "requirements": requirements,
                "requirement_routes": routing_manifest(requirement_topics),
                "supplemental_requirement_key": (
                    hashlib.sha256(" ".join(requirements.split()).encode("utf-8")).hexdigest()
                    if requirements else ""
                ),
                "supplemental_attempts": 0,
                "supplemental_attempt_history": [],
            },
        ))

        entity_id = new_sortable_id("ENT")
        if recovery_only:
            # §22 recovery mode: never re-run the full plan. Agent-planned
            # recovery queries (第N轮补采：...) execute VERBATIM so an
            # LLM-directed search text is never re-templated into the dead
            # keyword combinations of the previous round.
            direct_texts, recovery_round = split_recovery_notes(requirements)
            if direct_texts:
                plan = planner.targeted_plan(
                    run_id, domain_request.raw_company_name, "",
                    entity_id=entity_id,
                    max_queries=max(1, len(direct_texts) * 3),
                    direct_recovery_texts=direct_texts,
                    recovery_round=recovery_round,
                )
            else:
                plan = planner.targeted_plan(
                    run_id, domain_request.raw_company_name, requirements,
                    entity_id=entity_id,
                    max_queries=max(1, len([line for line in requirements.splitlines() if line.strip()]) * 6),
                )
            envelopes = SearchExecutor(self.adapters).execute(plan)
            targeted = None
        else:
            plan = planner.build(
                run_id=run_id,
                entity_id=entity_id,
                canonical_name=domain_request.raw_company_name,
                complexity=EnterpriseComplexity.UNKNOWN,
                budget={
                    key: value
                    for key, value in self.budgets.get("default", {}).items()
                    if isinstance(value, int)  # ResearchPlan.budget is dict[str, int]
                },
            )
            envelopes = SearchExecutor(self.adapters).execute(plan)
            # The one-sentence portal path is intentionally two-lane: the fixed
            # full Goal-Family plan always runs with its original budget, then an
            # isolated additive plan reinforces every intent in the user's full
            # sentence.  The second lane cannot remove or consume a base query.
            targeted = None
            if requirements:
                targeted = planner.targeted_plan(
                    run_id, domain_request.raw_company_name, requirements,
                    entity_id=entity_id,
                )
                envelopes.extend(SearchExecutor(self.adapters).execute(targeted))
        envelopes = self._hydrate_fulltext_envelopes(envelopes)
        if targeted is not None:
            targeted_ids = {query.query_id for query in targeted.queries}
            targeted_envelopes = [
                envelope for envelope in envelopes
                if envelope.query_id in targeted_ids
            ]
            manifest = store.get_run(run_id)
            scope = dict(manifest.research_scope or {})
            scope["supplemental_initial_collection"] = {
                "query_count": len(targeted.queries),
                "topics": sorted({query.topic for query in targeted.queries}),
                "rounds": sorted({query.collection_round for query in targeted.queries}),
                "active_query_count": sum(
                    1 for envelope in targeted_envelopes
                    if envelope.status not in {"blocked", "error"}
                ),
                "material_envelopes": sum(
                    1 for envelope in targeted_envelopes
                    if is_material_envelope(envelope)
                ),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            store.replace_run_manifest(manifest.model_copy(update={"research_scope": scope}))
        batches, blocked = self._extract(envelopes)
        image_batches, image_reasons = self._image_discovery_pass(envelopes, run_dir)
        if image_batches:
            batches.extend(image_batches)
        attempts = self._attempt_summaries(plan, envelopes)
        saturation = DataSaturationValidator(self.saturation_policy).assess(
            attempts,
            budget_exhausted=any(
                "budget exhausted" in (diag or "")
                for envelope in envelopes
                for diag in envelope.diagnostics
            ),
            scoped_goal_families=plan.scoped_goal_families,
        )
        quality_dir = run_dir / "outputs" / "02_research_quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        (quality_dir / "saturation_report.json").write_text(
            json.dumps(saturation.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        reasons = list(saturation.findings)
        if self.missing_adapters:
            reasons.append(f"adapter not available: {', '.join(self.missing_adapters)}")
        if blocked:
            reasons.append(f"{blocked} search envelopes were blocked/errored")
        if getattr(self, "_extraction_failures", None):
            reasons.append(
                f"{len(self._extraction_failures)} page extraction(s) failed and were skipped: "
                + "; ".join(self._extraction_failures[:3])
            )
        reasons.extend(image_reasons)

        state = ResearchState(
            run_id=run_id,
            request_id=domain_request.request_id,
            status=RunStatus.RUNNING,
            evidence_version=1,
        )
        detection: ProductDetection | None = None
        if batches:
            output_dir = run_dir / "outputs" / "01_evidence"
            state, detection = Phase3Runner(store, self.enterprise_rules).process_batches_until_ingest(
                state, domain_request.raw_company_name, batches, output_dir=output_dir
            )
            if state.status in (RunStatus.HUMAN_REVIEW, RunStatus.BLOCKED):
                # 公司解析/证据处理被内核阻断：绝不能把空证据误判为 PASS
                reasons.extend(f"phase3 blocked: {reason}" for reason in state.blocking_findings[:3])
                return ExecutionOutcome(
                    validation_status=ValidationStatus.BLOCKED,
                    risk_level=RiskLevel.HIGH,
                    review_reasons=reasons,
                    evidence_count=0,
                    search_calls=len(envelopes),
                )
        if detection is not None:
            self._store_detection(run_dir, detection)
        quality = ResearchQualityCalculator.assess(
            saturation=saturation,
            sources=store.list(run_id, "source"),
            claims=store.list(run_id, "claim"),
            products=store.list(run_id, "product"),
            images=store.list(run_id, "image"),
            gaps=store.list(run_id, "gap"),
            conflicts=store.list(run_id, "conflict"),
            product_detection=detection,
        )
        write_research_quality(quality, quality_dir)

        if not batches:
            # Zero ingestible evidence is a BLOCKED outcome, never a silent
            # PASS: CoreValidator on an empty store would return PASS.
            reasons.append("no ingestible evidence; adapters unavailable or returned nothing")
            return ExecutionOutcome(
                validation_status=ValidationStatus.BLOCKED,
                risk_level=RiskLevel.HIGH,
                review_reasons=reasons,
                evidence_count=0,
                search_calls=len(envelopes),
            )

        report = CoreValidator(store).validate(run_id, 1)
        if report.status == ValidationStatus.BLOCKED:
            # Surface the blocking findings themselves, not just the
            # saturation summary, so BLOCKED runs are diagnosable.
            reasons.extend(
                f"{finding.code}: {finding.message}"
                for finding in report.findings
                if finding.severity.value in {"ERROR", "BLOCKER"}
            )
        return ExecutionOutcome(
            validation_status=report.status,
            confidence=mean_claim_confidence(store, run_id),
            risk_level=risk_for(report.status),
            review_required=False,
            review_reasons=reasons,
            evidence_count=sum(len(store.list(run_id, kind)) for kind in EVIDENCE_KINDS),
            conflict_count=len(store.list(run_id, "conflict")),
            gap_count=len(store.list(run_id, "gap")),
            verified_claim_count=len([
                item for item in store.list(run_id, "claim")
                if item.verification_status == VerificationStatus.VERIFIED
            ]),
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            llm_calls=self.usage.llm_calls,
            search_calls=len(envelopes),
        )

    def _extract(self, envelopes) -> tuple[list[ExtractedEvidenceBatch], int]:
        extractor = EvidenceExtractor(self.wrapped_gateway)
        batches: list[ExtractedEvidenceBatch] = []
        blocked = 0
        failures: list[str] = []
        for envelope in envelopes:
            if envelope.status in ("blocked", "error"):
                blocked += 1
                continue
            if not is_material_envelope(envelope):
                # Discovery snippets and browser search-result pages remain in
                # the attempt journal but never consume LLM calls or enter the
                # evidence store as pseudo-sources.
                continue
            for batch in extractor.extract(envelope):
                if batch not in batches:
                    batches.append(batch)
            failures.extend(extractor.last_failures)
        self._extraction_failures = failures
        return batches, blocked

    # -- phase A2: Kimi WebBridge image discovery (P0-14/P0-16) --------------

    def _image_discovery_pass(
        self,
        envelopes: list[SearchResultEnvelope],
        run_dir: Path,
    ) -> tuple[list[ExtractedEvidenceBatch], list[str]]:
        """Open real product/factory pages with Kimi WebBridge and harvest images.

        The portal pipeline used to never call :class:`KimiImageDiscovery`:
        image collection only existed in the standalone production runner.
        This pass reuses the SAME bounded handoff (discovery -> evidence
        builder -> kernel ingest) so ``image_discovery_status`` is always
        explainable (images == 0 must never be silent).
        """
        from ..research.image_discovery import (
            ImageEvidenceBuilder,
            KimiImageDiscovery,
            KimiUsageTelemetry,
        )
        from ..research.source_grader import normalize_source_kind

        telemetry = KimiUsageTelemetry()
        reasons: list[str] = []

        def finalize(status: str, note: str | None = None) -> tuple[list[ExtractedEvidenceBatch], list[str]]:
            telemetry.image_discovery_status = status
            if note:
                telemetry.reason = note
            quality_dir = run_dir / "outputs" / "02_research_quality"
            quality_dir.mkdir(parents=True, exist_ok=True)
            (quality_dir / "kimi_image_discovery.json").write_text(
                json.dumps(telemetry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summary = (
                f"image discovery: {telemetry.image_discovery_status}, "
                f"candidates={telemetry.image_candidates_found}, "
                f"verified={telemetry.image_candidates_verified}, "
                f"download_failures={telemetry.image_download_failures}"
            )
            if telemetry.reason:
                summary += f" ({telemetry.reason})"
            reasons.append(summary)
            return image_batches, reasons

        image_batches: list[ExtractedEvidenceBatch] = []
        kimi = self.adapters.get("kimi_webbridge")
        if kimi is None:
            return finalize("NOT_RUN", "kimi_webbridge adapter unavailable")

        # Same page-selection contract as the production runner's _image_pass:
        # only fulltext target pages of product/factory/image goals, never
        # office/PDF downloads and never search snippets.
        topic_kind = {
            "image_evidence": "image",
            "products": "product", "product_series": "product", "product_models": "product",
            "factories": "factory", "production_lines": "factory",
        }
        skip_suffixes = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
        pages: list[dict] = []
        seen_urls: set[str] = set()
        for envelope in envelopes:
            if envelope.status in ("blocked", "error"):
                continue
            kind = topic_kind.get(str(envelope.topic or ""))
            if kind is None:
                continue
            for hit in envelope.hits:
                url = str(hit.final_url or "").strip()
                if not url or not hit.text or hit.metadata.get("snippet"):
                    continue
                if url.lower().split("?")[0].endswith(skip_suffixes):
                    continue
                normalized = url.rstrip("/").lower()
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                pages.append({
                    "url": url,
                    "kind": kind,
                    "source_kind": "official_company",
                    "publisher": envelope.canonical_company_name,
                })
        if not pages:
            return finalize("NOT_RUN", "no product/factory/image fulltext pages collected")

        max_pages = max(1, int(os.environ.get("EER_IMAGE_DISCOVERY_PAGES", "8")))
        candidates = KimiImageDiscovery(kimi, telemetry, max_pages=max_pages).discover(pages)
        if telemetry.image_discovery_status == "BLOCKED":
            return finalize("BLOCKED")

        # Download + hash through the SAME fetcher the recovery path uses.
        builder = ImageEvidenceBuilder(self._fetch_binary)
        max_candidates = max(1, int(os.environ.get("EER_IMAGE_DISCOVERY_MAX_CANDIDATES", "24")))
        attempted = candidates[:max_candidates]
        allowed_image_types = {
            "logo", "headquarters", "factory", "office", "production_line",
            "product", "location", "certificate", "project", "other",
        }
        by_page: dict[str, list] = {}
        for candidate in attempted:
            if not str(candidate.url).startswith(("http://", "https://")):
                # data:/blob: URLs cannot enter the evidence store (HttpUrl).
                telemetry.image_download_failures += 1
                continue
            evidence = builder.build(candidate, source_id="pending")
            if evidence is None:
                telemetry.image_download_failures += 1
                continue
            telemetry.image_candidates_verified += 1
            by_page.setdefault(candidate.page_url, []).append((candidate, evidence))
        if not by_page:
            return finalize(
                "EMPTY" if not candidates else telemetry.image_discovery_status,
                "no candidate image could be downloaded" if candidates else None,
            )
        for page_url, items in by_page.items():
            images = []
            for candidate, evidence in items:
                images.append({
                    "image_key": new_sortable_id("IMG"),
                    "source_url": candidate.url,
                    "image_type": candidate.image_type if candidate.image_type in allowed_image_types else "other",
                    "width": evidence.width,
                    "height": evidence.height,
                    "mime_type": evidence.mime_type,
                    "sha256": evidence.sha256,
                    "phash": evidence.phash,
                    "alt_text": candidate.alt,
                    "surrounding_text": candidate.surrounding_text,
                })
            first = items[0][0]
            image_batches.append(ExtractedEvidenceBatch(
                source_url=page_url,
                source_title=first.page_title,
                publisher=first.publisher,
                source_kind=normalize_source_kind(first.source_kind),
                images=images,
                extraction_method="deterministic",
                retrieval_adapter="kimi_webbridge",
            ))
        return finalize("OK")

    def _hydrate_fulltext_envelopes(
        self,
        envelopes: list[SearchResultEnvelope],
    ) -> list[SearchResultEnvelope]:
        """Open discovery URLs and append real-page envelopes.

        The portal used to pass AnySearch result snippets straight to the
        extractor.  Evidence validation correctly downgraded every resulting
        source to ``SOURCE_D``, leaving reports with no verified enterprise
        facts.  Hydration is therefore a mandatory bridge between search and
        extraction, not an optional retry.

        URLs are fetched once and then rebound to every originating research
        goal so repeated results do not waste network calls while the full
        goal/subject context remains intact.
        """
        outcome = hydrate_target_pages(
            envelopes,
            self.adapters,
            pages_per_query=self.fulltext_pages_per_query,
            workers=self.fulltext_workers,
        )
        self._hydration_failures = outcome.failures
        return outcome.envelopes

    @staticmethod
    def _attempt_summaries(plan, envelopes) -> list[CollectionAttemptSummary]:
        """Honest round/goal summaries from adapter envelopes."""
        by_query = {query.query_id: query for query in plan.queries}
        rows: list[CollectionAttemptSummary] = []
        for envelope in envelopes:
            query = by_query.get(envelope.query_id)
            if query is None:
                continue
            hits = envelope.hits
            domains: set[str] = set()
            fulltext = 0
            raw_captures: list[str] = []
            for hit in hits:
                if hit.final_url:
                    domains.add(urlparse(hit.final_url).netloc.lower())
                # A search snippet is discovery metadata, not a captured page.
                if hit.text and not hit.metadata.get("snippet"):
                    fulltext += 1
                    raw_captures.append(hit.final_url or hit.requested_url or "")
            rows.append(CollectionAttemptSummary(
                goal_family=query.topic,
                round=query.collection_round,
                batch_id=envelope.query_id,
                attempted_queries=1,
                unique_sources=len(domains),
                source_types=set(domains),  # domain-level approximation
                fulltext_captures=fulltext,
                material_records=sum(
                    1 for hit in hits if hit.text and not hit.metadata.get("snippet")
                ),
                inspected_sources=len(hits),
                raw_capture_refs=[ref for ref in raw_captures if ref],
                failure_reasons=list(envelope.diagnostics),
            ))
        return rows

    # -- phase B: freeze + publish (only after APPROVED) ----------------------

    def freeze_and_publish(self, run_id: str, workdir: Path) -> ExecutionOutcome:
        run_dir = Path(workdir) / run_id
        store = EvidenceStore(self._active_evidence_store_path(run_dir))
        run = store.get_run(run_id)
        if run is None:
            raise RuntimeError(f"evidence run not found: {run_id}")
        state = ResearchState(
            run_id=run_id,
            request_id=run.request_id,
            status=RunStatus.RUNNING,
            canonical_entity_id=run.canonical_entity_id,
            complexity=run.complexity or EnterpriseComplexity.UNKNOWN,
        )
        detection = self._load_detection(run_dir)
        resolved = self._load_resolved_conflicts(run_dir)
        final_state, manifest = Phase2Runner(
            store, resolved_conflict_ids=frozenset(resolved)
        ).finalize_evidence(
            state,
            output_dir=run_dir / "outputs" / "01_evidence",
            product_detection=detection,
        )
        if final_state.freeze_id is None or manifest is None:
            raise ValueError(
                "kernel blocked the freeze of an approved run: "
                + "; ".join(final_state.blocking_findings)
            )
        bundle = FreezeService(store).load_bundle(final_state.freeze_id)
        from ..validation.formal_publication import ProductPublicationIntegrityValidator

        product_integrity = ProductPublicationIntegrityValidator().assess(bundle)
        quality_dir = run_dir / "outputs" / "02_research_quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        (quality_dir / "product_publication_integrity.json").write_text(
            json.dumps(
                product_integrity.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        if product_integrity.status != "PASS":
            raise RuntimeError(
                "product publication integrity blocked: "
                + "; ".join(product_integrity.diagnostics)
            )
        results = ArtifactPublicationService(self.publishers).publish(
            bundle, manifest, run_dir / "outputs" / "artifacts"
        )
        audit = ArtifactConsistencyAuditor().audit(bundle, manifest, results)
        review_reasons = [f"{finding.code}: {finding.message}" for finding in audit.findings]
        status_by_result = {
            "published": ArtifactStatus.PUBLISHED,
            "skipped": ArtifactStatus.SKIPPED,
            "failed": ArtifactStatus.FAILED,
        }
        validation_status = final_state.validation_status or ValidationStatus.PASS
        return ExecutionOutcome(
            validation_status=validation_status,
            confidence=mean_claim_confidence(store, run_id),
            risk_level=risk_for(validation_status),
            review_required=False,
            review_reasons=review_reasons,
            evidence_count=sum(len(store.list(run_id, kind)) for kind in EVIDENCE_KINDS),
            conflict_count=len(store.list(run_id, "conflict")),
            gap_count=len(store.list(run_id, "gap")),
            verified_claim_count=len([
                item for item in store.list(run_id, "claim")
                if item.verification_status == VerificationStatus.VERIFIED
            ]),
            freeze_id=final_state.freeze_id,
            artifacts=[
                ArtifactRef(
                    artifact_type=item.artifact_type,
                    status=status_by_result[item.status],
                    location=str(item.path) if item.path else None,
                )
                for item in results
            ],
        )

    def repair_publication(
        self,
        run_id: str,
        workdir: Path,
        *,
        failed_artifacts: list[ArtifactRef],
        attempt: int,
    ) -> str:
        """Repair one failed publication pass without weakening any QA gate.

        Evidence-related findings launch a targeted continuation search and
        switch the next freeze to a newly-created evidence store. Renderer-
        only failures simply request a clean rebuild on the next pass. Every
        decision is appended to ``publication_recovery.json`` for audit.
        """
        run_dir = Path(workdir) / run_id
        codes, messages = self._publication_qa_failures(run_dir)
        artifact_labels = [str(item.artifact_type) for item in failed_artifacts]
        requirements = self._publication_repair_requirements(codes, messages, attempt=attempt)
        renderer_codes = {
            "visual_render_failed", "word_visual_render_failed",
            "dashboard_visual_render_failed", "artifact_write_failed",
        }
        evidence_repair = bool(requirements) and not (
            codes and codes.issubset(renderer_codes)
        )
        event: dict[str, object] = {
            "attempt": attempt,
            "failed_artifacts": artifact_labels,
            "qa_codes": sorted(codes),
            "qa_messages": messages,
            "action": "rerender",
            "requirements": requirements,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if evidence_repair:
            from ..research.deep_retry import deep_retry, load_evidence

            active_path = self._active_evidence_store_path(run_dir)
            active_store = EvidenceStore(active_path)
            manifest = active_store.get_run(run_id)
            scope_requirement = str(
                (manifest.research_scope or {}).get("requirements") or ""
            ).strip()
            search_requirements = "；".join(filter(None, [
                f"原始专项要求：{scope_requirement}" if scope_requirement else "",
                requirements,
            ]))
            evidence = load_evidence(active_store, run_id)
            canonical = next(
                (
                    entity for entity in evidence.entities
                    if entity.entity_id == manifest.canonical_entity_id
                ),
                evidence.entities[0] if evidence.entities else None,
            )
            company = canonical.canonical_name if canonical is not None else ""
            recovery_dir = run_dir / "publication_recovery" / f"attempt-{attempt}"
            recovery_dir.mkdir(parents=True, exist_ok=True)
            result = deep_retry(
                active_store,
                recovery_dir,
                requirements=search_requirements,
                company=company,
                adapters=self.adapters,
                gateway=self.wrapped_gateway,
                fetcher=self._fetch_binary,
                include_images=True,
                max_pages=max(20, self.fulltext_pages_per_query * 8),
                recovery_round=attempt,
                scope_requirement=scope_requirement,
            )
            fixed_stores = sorted(
                recovery_dir.glob("evidence_fixed*.sqlite3"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            if not fixed_stores:
                raise RuntimeError(
                    "targeted publication recovery did not create an evidence store"
                )
            # Recompute the product gate from the supplemented immutable
            # evidence so newly recovered product/image records are visible
            # to the next Word/HTML publication pass.
            from ..research.product_detector import ProductDetector

            fixed_store = EvidenceStore(fixed_stores[0])
            fixed_evidence = load_evidence(fixed_store, run_id)
            _, detection = ProductDetector().detect(
                fixed_evidence.products,
                fixed_evidence.images,
                fixed_evidence.sources,
                fixed_evidence.claims,
                require_archived_images=True,
            )
            self._store_detection(run_dir, detection)
            pointer = run_dir / "active_evidence_store.json"
            pointer.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "path": str(fixed_stores[0].relative_to(run_dir)),
                        "attempt": attempt,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            event["action"] = "targeted_supplement"
            event["active_evidence_store"] = str(fixed_stores[0])
            event["result"] = result
        self._append_publication_recovery_event(run_dir, event)
        return f"{event['action']} for {', '.join(sorted(codes)) or 'publisher exception'}"

    # -- persistence helpers --------------------------------------------------

    @staticmethod
    def _active_evidence_store_path(run_dir: Path) -> Path:
        """Resolve the latest audited fix store, constrained to this run."""
        original = (run_dir / "evidence.sqlite3").resolve()
        pointer = run_dir / "active_evidence_store.json"
        if not pointer.is_file():
            return original
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            candidate = (run_dir / str(payload["path"])).resolve()
            candidate.relative_to(run_dir.resolve())
            if candidate.is_file():
                return candidate
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        return original

    @staticmethod
    def _publication_qa_failures(run_dir: Path) -> tuple[set[str], list[str]]:
        codes: set[str] = set()
        messages: list[str] = []
        eligibility_path = (
            run_dir / "outputs" / "02_research_quality"
            / "formal_publication_eligibility.json"
        )
        product_integrity_path = (
            run_dir / "outputs" / "02_research_quality"
            / "product_publication_integrity.json"
        )
        for gate_path in (eligibility_path, product_integrity_path):
            if not gate_path.is_file():
                continue
            try:
                eligibility = json.loads(gate_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                eligibility = {}
            if str(eligibility.get("status", "")).upper() != "PASS":
                product_integrity = eligibility.get("product_integrity") or eligibility
                if str(product_integrity.get("status", "")).upper() == "BLOCKED":
                    codes.add("product_publication_integrity")
                for message in eligibility.get("diagnostics", []):
                    message = str(message)
                    if message and message not in messages:
                        messages.append(message)
        artifact_root = run_dir / "outputs" / "artifacts"
        for path in artifact_root.rglob("publication_qa_report.json") if artifact_root.exists() else ():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(report.get("status", "")).lower() != "fail":
                continue
            for finding in report.get("findings", []):
                if str(finding.get("severity", "")).lower() not in {"error", "blocker"}:
                    continue
                code = str(finding.get("code") or "unknown_publication_failure")
                message = str(finding.get("message") or code)
                codes.add(code)
                if message not in messages:
                    messages.append(message)
        return codes, messages

    @staticmethod
    def _publication_repair_requirements(
        codes: set[str], messages: list[str], *, attempt: int = 1
    ) -> str:
        """Translate QA failures into entity-bound continuation research."""
        text = " ".join([*codes, *messages]).casefold()
        requirements: list[str] = []
        if any(token in text for token in (
            "length", "depth", "字数", "字符", "章节", "enterprise_specific",
        )):
            requirements.append(
                "只补充目标新能源企业及已核验集团成员的主营业务、产品技术、生产基地产能、"
                "销售渠道、财务经营和战略进展事实；数值必须带期间、单位和口径；"
                "竞品、客户供应商和政策机构证据单独归类，不计入目标企业事实"
            )
        if any(token in text for token in ("image", "图片", "product_image")):
            requirements.append(
                "查找并核验该企业官网产品中心、产品详情页、产品图册及可精确绑定产品型号的官方图片"
            )
        if any(token in text for token in (
            "product_publication_integrity", "publishable verified product",
            "产品事实", "产品对象",
        )):
            requirements.append(
                "重新执行目标企业及已核验集团成员的产品目录规范化与状态核验；"
                "将已核验产品事实绑定为产品对象，并核对产品名称、系列、型号、参数和A/B级来源；"
                "产品图片作为独立补采项，不得用图片缺失将可靠文字产品降级或删除"
            )
        if any(token in text for token in ("map", "地图", "坐标", "factory", "基地")):
            requirements.append(
                "补充该企业工厂、生产基地和产线的正式名称、完整地址、城市省份、运营主体及经纬度定位依据"
            )
        if any(token in text for token in ("chart", "图表", "visual", "可视化")):
            requirements.append(
                "补充可用于数据图表的时间序列、产能、销量、收入、投资额、产品参数等结构化量化事实"
            )
        if any(token in text for token in ("source", "evidence", "claim", "证据", "来源")):
            requirements.append(
                "增加企业官网、公告、政府或招投标平台及权威媒体来源，并交叉验证关键事实"
            )
        if any(token in text for token in ("channel", "渠道", "经销", "分销", "直销")):
            requirements.append(
                "补充目标企业销售渠道类型、经销或代理伙伴、覆盖区域及披露时间；渠道伙伴保持独立主体"
            )
        if any(token in text for token in ("policy", "政策", "监管", "法规", "补贴", "准入")):
            requirements.append(
                "补充政府政策原文、文号、发布与生效时间、适用地区和适用对象；政策机构保持公共权威主体"
            )
        if any(token in text for token in ("compet", "竞争", "竞品", "同业")):
            requirements.append(
                "补充同期间、同市场、同指标口径的竞品对比；竞品保持独立主体且仅进入竞争比较证据通道"
            )
        from ..research.planner import RECOVERY_STRATEGIES

        strategy = RECOVERY_STRATEGIES[(max(1, attempt) - 1) % len(RECOVERY_STRATEGIES)]
        requirements.append(f"第{attempt}轮补采策略：{strategy}")
        return "；".join(dict.fromkeys(requirements))

    @staticmethod
    def _append_publication_recovery_event(run_dir: Path, event: dict[str, object]) -> None:
        path = run_dir / "publication_recovery.json"
        payload: dict[str, object] = {"max_attempts": 10, "events": []}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            except (OSError, json.JSONDecodeError):
                pass
        # Old recovery journals may have been created under the former
        # five/nine-round policy. The current source contract is authoritative.
        payload["max_attempts"] = 10
        events = payload.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            payload["events"] = events
        events.append(event)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _fetch_binary(url: str, referer: str | None = None) -> bytes:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            )
        }
        if referer:
            headers["Referer"] = referer
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:  # noqa: S310 - audited source URL
            return response.read()

    @staticmethod
    def _store_detection(run_dir: Path, detection: ProductDetection) -> None:
        (run_dir / "product_detection.json").write_text(
            detection.model_dump_json(), encoding="utf-8"
        )

    @staticmethod
    def _load_detection(run_dir: Path) -> ProductDetection | None:
        path = run_dir / "product_detection.json"
        if not path.is_file():
            return None
        return ProductDetection.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_resolved_conflicts(run_dir: Path) -> list[str]:
        """Conflict groups a reviewer adjudicated (冲突裁决快照).

        Written by ``ResearchService.resolve_conflict``; consumed here so
        the re-validation during freeze treats them as resolved.
        """
        path = run_dir / "resolved_conflicts.json"
        if not path.is_file():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("conflict_group_ids", []))
