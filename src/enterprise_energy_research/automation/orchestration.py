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
from pathlib import Path
from urllib.parse import urlparse

from ..adapters.anysearch import AnySearchCliAdapter
from .. import __version__
from ..adapters.base import SearchAdapter
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
from ..research.planner import ResearchPlanner
from ..research.quality import ResearchQualityCalculator, write_research_quality
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
        self, run_id: str, request: ResearchRequest, workdir: Path
    ) -> ExecutionOutcome:
        run_dir = Path(workdir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        settings = Settings(output_root=run_dir / "outputs")
        domain_request = request.to_domain_request(new_sortable_id("REQ"))
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
        ))

        plan = ResearchPlanner().build(
            run_id=run_id,
            entity_id=new_sortable_id("ENT"),
            canonical_name=domain_request.raw_company_name,
            complexity=EnterpriseComplexity.UNKNOWN,
            budget={
                key: value
                for key, value in self.budgets.get("default", {}).items()
                if isinstance(value, int)  # ResearchPlan.budget is dict[str, int]
            },
        )
        envelopes = SearchExecutor(self.adapters).execute(plan)
        batches, blocked = self._extract(envelopes)
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
            review_required=report.status == ValidationStatus.PASS_WITH_WARNINGS,
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
            for batch in extractor.extract(envelope):
                if batch not in batches:
                    batches.append(batch)
            failures.extend(extractor.last_failures)
        self._extraction_failures = failures
        return batches, blocked

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
                if hit.text:
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
                material_records=len(hits),
                inspected_sources=len(hits),
                raw_capture_refs=[ref for ref in raw_captures if ref],
                failure_reasons=list(envelope.diagnostics),
            ))
        return rows

    # -- phase B: freeze + publish (only after APPROVED) ----------------------

    def freeze_and_publish(self, run_id: str, workdir: Path) -> ExecutionOutcome:
        run_dir = Path(workdir) / run_id
        store = EvidenceStore(run_dir / "evidence.sqlite3")
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

    # -- persistence helpers --------------------------------------------------

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
