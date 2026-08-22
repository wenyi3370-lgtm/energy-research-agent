"""AdaptiveResearchRunner (P1-1): the real production pipeline.

R1 Discovery -> Extract -> Normalize -> Verify -> Detect Gap
-> gap_queries() -> R2 Depth -> Extract -> Merge -> Revalidate
-> Detect Conflict / critical triangulation need -> conflict_queries()
-> R3 Triangulation -> Merge -> Revalidate.

Every round is driven by REAL gaps/conflicts (never pre-planned wholesale).
Round evidence is MERGED into one cumulative, stable-ID evidence object and
revalidated before the next round runs; saturation is judged on EvidenceDelta
over those stable IDs; formal publication is guarded by the content gates
(P0-9/10/11), claim-bound synthesis (P0-18), utilization (P1-3) and the goal
pipeline trace (P0-12/13).
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from enterprise_energy_research.adapters.base import SearchAdapter, SearchHit, SearchRequest, SearchResultEnvelope
from enterprise_energy_research.analysis.energy import EnergyAnalyst
from enterprise_energy_research.analysis.solutions import SolutionEngine
from enterprise_energy_research.domain.enums import EnterpriseComplexity, RunStatus, SourceLevel, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim, DataGap, Entity, ExtractedEvidenceBatch, ResearchPlan, ResearchQuery, RunManifest, Source,
)
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.runner import Phase2Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.claim_utilization import ClaimUtilizationAuditor
from enterprise_energy_research.research.content_contract import (
    CHAPTER_CONTRACTS, CoreResearchReadinessGate, PlaceholderContentGate,
    chapter_substantive_facts,
)
from enterprise_energy_research.research.entity_mapper import EntityMapper
from enterprise_energy_research.research.evidence_delta import DeltaSaturation, EvidenceDelta, EvidenceSnapshot
from enterprise_energy_research.research.extractor import EvidenceExtractor
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver, ImageArchiveResult
from enterprise_energy_research.research.image_discovery import (
    ImageEvidenceBuilder, KimiImageDiscovery, KimiUsageTelemetry,
)
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.identity_evidence import IdentityEvidenceSynthesizer
from enterprise_energy_research.research.ingestor import EvidenceIngestor
from enterprise_energy_research.research.normalizer import EvidenceNormalizer, NormalizedEvidence
from enterprise_energy_research.research.pipeline_trace import GapReasonClassifier, GoalPipelineTrace
from enterprise_energy_research.research.planner import GOAL_FAMILIES, ResearchPlanner
from enterprise_energy_research.research.product_detector import ProductDetector
from enterprise_energy_research.research.product_detail_frontier import (
    BoundedBrowserWorkerPool,
    KimiProductDetailBrowser,
    ProductDetailFrontier,
)
from enterprise_energy_research.research.resolver import CompanyResolver
from enterprise_energy_research.research.source_grader import SourceGrader
from enterprise_energy_research.research.synthesis import ResearchSynthesizer, write_synthesis

HIGH_PRIORITY_FIELDS = {
    "revenue", "profit", "capacity", "employee_count", "investment",
    "canonical_company_name", "registered_name", "core_business",
    "product_family", "model", "parameter_name", "electricity_consumption",
    "energy_consumption", "roof_area", "project_name", "pv_capacity", "export",
}

# Only search-stage gap reasons drive R2 depth queries. Site-due-diligence
# and conflicting-value gaps are NOT searchable by more web queries.
SEARCHABLE_GAP_REASONS = {
    "missing", "stale", "unverifiable",
    "NOT_SEARCHED", "SEARCH_FAILED", "SEARCHED_NOT_FOUND", "FOUND_NOT_RETRIEVED",
    "RETRIEVED_NOT_EXTRACTED", "EXTRACTED_NOT_NORMALIZED", "NORMALIZED_NOT_VERIFIED",
    "VERIFIED_NOT_SYNTHESIZED", "SYNTHESIZED_NOT_PUBLISHED", "PUBLIC_EVIDENCE_GAP",
}


class RoundOutcome(BaseModel):
    round: str
    trigger: str
    query_ids: list[str] = Field(default_factory=list)
    round_queries: list[dict] = Field(default_factory=list)
    envelope_summaries: list[dict] = Field(default_factory=list)
    batch_count: int = 0
    snapshot_before: dict | None = None
    snapshot_after: dict | None = None
    delta: dict | None = None
    new_gap_ids: list[str] = Field(default_factory=list)
    new_conflict_ids: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class AdaptiveRunReport(BaseModel):
    run_id: str
    raw_company_name: str
    status: str
    rounds: list[RoundOutcome] = Field(default_factory=list)
    funnel: dict = Field(default_factory=dict)
    saturation: dict = Field(default_factory=dict)
    readiness: dict = Field(default_factory=dict)
    placeholder_gate: dict = Field(default_factory=dict)
    utilization: dict = Field(default_factory=dict)
    kimi_usage: dict = Field(default_factory=dict)
    catalog: dict = Field(default_factory=dict)
    trace_path: str | None = None
    synthesis_path: str | None = None
    unused_claims_path: str | None = None
    freeze_id: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


class AdaptiveResearchRunner:
    def __init__(
        self,
        adapters: dict[str, SearchAdapter],
        *,
        gateway=None,
        enterprise_rules: dict | None = None,
        fetcher=None,
        publishers: dict | None = None,
        store: EvidenceStore | None = None,
        minimum_substantive_claims: int = 20,
        max_gap_queries: int = 6,
        max_conflict_queries: int = 4,
        enable_image_archiving: bool = True,
        enable_publication: bool = True,
        extraction_workers: int = 4,
        fulltext_pages_per_query: int = 4,
        max_product_detail_pages: int = 12,
        browser_workers: int = 3,
    ) -> None:
        self.adapters = adapters
        self.gateway = gateway
        self.enterprise_rules = enterprise_rules or {}
        self.fetcher = fetcher
        self.publishers = publishers
        self.store = store
        self.minimum_substantive_claims = minimum_substantive_claims
        self.max_gap_queries = max_gap_queries
        self.max_conflict_queries = max_conflict_queries
        self.enable_image_archiving = enable_image_archiving
        self.enable_publication = enable_publication
        self.extraction_workers = extraction_workers
        self.fulltext_pages_per_query = fulltext_pages_per_query
        self.max_product_detail_pages = max_product_detail_pages
        if not 1 <= browser_workers <= 4:
            raise ValueError("browser_workers must be between 1 and 4")
        self.browser_workers = browser_workers
        self._pending_image_candidates: list = []
        # Official domains learned from resolution; later rounds prioritize
        # official pages for deep browsing (product catalog quality).
        self._official_domains_hint: set[str] = set()
        self.cumulative: NormalizedEvidence = NormalizedEvidence()

    # ------------------------------------------------------------------ run

    def run(
        self,
        raw_company_name: str,
        complexity: EnterpriseComplexity,
        budget: dict[str, int],
        output_dir: Path,
    ) -> AdaptiveRunReport:
        output_dir.mkdir(parents=True, exist_ok=True)
        store = self.store or EvidenceStore(output_dir / "evidence.sqlite3")
        run_id = new_sortable_id("RUN")
        request_id = new_sortable_id("REQ")
        store.create_run(RunManifest(
            run_id=run_id,
            request_id=request_id,
            status=RunStatus.RUNNING,
            config_hash="adaptive-runner",
            code_version="0.9.1",
            model_gateway={"mode": "adaptive-production"},
        ))
        self.cumulative = NormalizedEvidence()
        telemetry = KimiUsageTelemetry()
        planner = ResearchPlanner()
        plan = planner.build(run_id, "PENDING-ENTITY", raw_company_name, complexity, budget)
        trace = GoalPipelineTrace.blank(run_id, [family for family, _ in GOAL_FAMILIES])
        trace.record_plan(plan.queries)

        diagnostics: list[str] = []
        rounds: list[RoundOutcome] = []
        deltas: list[EvidenceDelta] = []
        pending_gaps: list[DataGap] = []
        pending_conflicts: list = []
        canonical_entity: Entity | None = None
        def snapshot_now(label: str) -> EvidenceSnapshot:
            return EvidenceSnapshot.capture(
                label,
                claims=self.cumulative.claims,
                entities=self.cumulative.entities,
                factories=self.cumulative.factories,
                products=self.cumulative.products,
                images=self.cumulative.images,
                conflicts=self.cumulative.conflicts,
                gaps=self.cumulative.gaps,
                high_priority_fields=HIGH_PRIORITY_FIELDS,
            )

        def execute_round(round_name: str, queries: list[ResearchQuery], trigger: str) -> tuple[list[SearchResultEnvelope], list[ExtractedEvidenceBatch]]:
            if not queries:
                return [], []
            mini_plan = ResearchPlan(
                plan_id=new_sortable_id("PLAN"), run_id=run_id, complexity=complexity,
                queries=queries,
                budget={"max_queries": len(queries) + 1, "max_pages": int(budget.get("max_pages", 120))},
                completion_contract=[query.topic for query in queries],
                canonical_company_name=raw_company_name,
            )
            from enterprise_energy_research.research.executor import SearchExecutor
            envelopes = SearchExecutor(self.adapters).execute(mini_plan)
            # Search results -> AnySearch full-text extraction (fast HTTP).
            envelopes = self._fulltext_pass(envelopes, queries)
            # Product-catalog topics: Kimi opens the REAL official product
            # center/detail pages (SPA content plain HTTP cannot see) — P0-17.
            envelopes = self._browser_depth_pass(envelopes, queries, telemetry)
            # Product detail pages: parameter tables and real product photos
            # live one level below the product center — follow the product
            # card links on the pages we already opened (P0-17 enumeration).
            envelopes = self._product_detail_pass(
                envelopes, telemetry,
                queue_path=output_dir / "02_research_quality" / "product_detail_queue.sqlite3",
            )
            # Kimi WebBridge is reserved for IMAGE discovery on real pages.
            self._image_pass(envelopes, telemetry)
            # Parallel structured extraction across pages (network-bound).
            batches: list[ExtractedEvidenceBatch] = []
            with ThreadPoolExecutor(max_workers=self.extraction_workers) as pool:
                results = pool.map(self._extract_one, envelopes)
                for envelope, extracted, failures in results:
                    batches.extend(extracted)
                    if failures:
                        diagnostics.extend(failures[:5])
                    trace.record_envelope(
                        envelope, len(extracted),
                        sum(len(batch.claims) for batch in extracted), 0,
                    )
            return envelopes, batches

        # ---- R1 discovery -------------------------------------------------
        r1_queries = [query for query in plan.queries if query.collection_round == "R1"]
        snapshot_before = snapshot_now("R1-before")
        envelopes, batches = execute_round("R1", r1_queries, "baseline")
        canonical_entity, gaps, conflicts, out_diags = self._process_round(
            raw_company_name, batches, output_dir=output_dir, telemetry=telemetry, trace=trace,
            canonical_entity=canonical_entity,
        )
        diagnostics.extend(out_diags)
        pending_gaps, pending_conflicts = gaps, conflicts
        snapshot_after = snapshot_now("R1-after")
        delta = EvidenceDelta.compute(snapshot_before, snapshot_after)
        deltas.append(delta)
        rounds.append(RoundOutcome(
            round="R1", trigger="baseline", query_ids=[query.query_id for query in r1_queries],
            round_queries=[self._query_summary(query) for query in r1_queries],
            envelope_summaries=self._summarize(envelopes), batch_count=len(batches),
            snapshot_before=snapshot_before.model_dump(mode="json"),
            snapshot_after=snapshot_after.model_dump(mode="json"),
            delta=delta.model_dump(mode="json"),
            new_gap_ids=sorted(set(snapshot_after.gaps) - set(snapshot_before.gaps)),
            new_conflict_ids=sorted(set(snapshot_after.conflicts) - set(snapshot_before.conflicts)),
            diagnostics=list(out_diags),
        ))

        # ---- R2 gap-driven depth -----------------------------------------
        r2_drivers = [gap for gap in pending_gaps if gap.reason in SEARCHABLE_GAP_REASONS]
        r2_queries = planner.gap_queries(plan, raw_company_name, r2_drivers)[: self.max_gap_queries] if r2_drivers else []
        if not r2_queries and pending_gaps:
            diagnostics.append(f"{len(pending_gaps)} gap(s) are not web-searchable; R2 depth round skipped")
        if r2_queries:
            snapshot_before = snapshot_now("R2-before")
            envelopes, batches = execute_round("R2", r2_queries, "gap")
            canonical_entity, gaps, conflicts, out_diags = self._process_round(
                raw_company_name, batches, output_dir=output_dir, telemetry=telemetry, trace=trace,
                canonical_entity=canonical_entity,
            )
            diagnostics.extend(out_diags)
            pending_gaps, pending_conflicts = gaps, conflicts
            snapshot_after = snapshot_now("R2-after")
            delta = EvidenceDelta.compute(snapshot_before, snapshot_after)
            deltas.append(delta)
            rounds.append(RoundOutcome(
                round="R2", trigger="gap", query_ids=[query.query_id for query in r2_queries],
                round_queries=[self._query_summary(query) for query in r2_queries],
                envelope_summaries=self._summarize(envelopes), batch_count=len(batches),
                snapshot_before=snapshot_before.model_dump(mode="json"),
                snapshot_after=snapshot_after.model_dump(mode="json"),
                delta=delta.model_dump(mode="json"),
                new_gap_ids=sorted(set(snapshot_after.gaps) - set(snapshot_before.gaps)),
                new_conflict_ids=sorted(set(snapshot_after.conflicts) - set(snapshot_before.conflicts)),
                diagnostics=list(out_diags),
            ))
        else:
            diagnostics.append("no gaps after R1; R2 depth round skipped")

        # ---- R3 conflict-driven triangulation ----------------------------
        r3_queries = planner.conflict_queries(plan, raw_company_name, pending_conflicts)[: self.max_conflict_queries] if pending_conflicts else []
        if r3_queries:
            snapshot_before = snapshot_now("R3-before")
            envelopes, batches = execute_round("R3", r3_queries, "conflict")
            canonical_entity, gaps, conflicts, out_diags = self._process_round(
                raw_company_name, batches, output_dir=output_dir, telemetry=telemetry, trace=trace,
                canonical_entity=canonical_entity,
            )
            diagnostics.extend(out_diags)
            pending_gaps, pending_conflicts = gaps, conflicts
            snapshot_after = snapshot_now("R3-after")
            delta = EvidenceDelta.compute(snapshot_before, snapshot_after)
            deltas.append(delta)
            rounds.append(RoundOutcome(
                round="R3", trigger="conflict", query_ids=[query.query_id for query in r3_queries],
                round_queries=[self._query_summary(query) for query in r3_queries],
                envelope_summaries=self._summarize(envelopes), batch_count=len(batches),
                snapshot_before=snapshot_before.model_dump(mode="json"),
                snapshot_after=snapshot_after.model_dump(mode="json"),
                delta=delta.model_dump(mode="json"),
                new_gap_ids=sorted(set(snapshot_after.gaps) - set(snapshot_before.gaps)),
                new_conflict_ids=sorted(set(snapshot_after.conflicts) - set(snapshot_before.conflicts)),
                diagnostics=list(out_diags),
            ))
        else:
            diagnostics.append("no unresolved conflicts after R2; R3 triangulation round skipped")

        # ---- gates, synthesis, utilization, publication --------------------
        trace.stopping_stage()
        evidence = self.cumulative
        claims, entities = evidence.claims, evidence.entities
        factories, products = evidence.factories, evidence.products
        images, edges = evidence.images, evidence.edges
        sources, gaps_now = evidence.sources, evidence.gaps
        conflicts_now = evidence.conflicts
        energy_profiles, solutions = evidence.energy_profiles, evidence.solutions

        readiness = CoreResearchReadinessGate().assess(
            entities=entities, claims=claims, edges=edges, factories=factories,
            products=products,
            is_large_enterprise=complexity in {EnterpriseComplexity.GROUP_LARGE, EnterpriseComplexity.ENTERPRISE_NORMAL},
            minimum_substantive_claims=self.minimum_substantive_claims,
        )
        trace.write(output_dir / "02_research_quality")
        saturation = DeltaSaturation.assess(deltas)
        synthesis = None
        synthesis_path = None
        if canonical_entity is not None:
            synthesis = ResearchSynthesizer().synthesize(
                run_id=run_id,
                entity=canonical_entity,
                entities=entities,
                claims=claims,
                sources=sources,
                edges=edges,
                factories=factories,
                products=products,
                energy_profiles=energy_profiles,
                gaps=gaps_now,
                solutions=solutions,
            )
            synthesis_path = str(write_synthesis(synthesis, output_dir / "02_research_quality"))
            trace.record_synthesis("synthesis", len(synthesis.findings), len(synthesis.findings))
        body_paragraphs: list[str] = []
        chapter_paragraphs: dict[str, list[str]] = {}
        for key, contract in CHAPTER_CONTRACTS.items():
            facts = chapter_substantive_facts(
                key, entities=entities, claims=claims, edges=edges, factories=factories,
                products=products, energy_profiles=energy_profiles,
            )
            ok, message = contract.assess(facts)
            chapter_paragraphs[key] = [str(fact) for fact in facts] or [message]
            body_paragraphs.extend(chapter_paragraphs[key])
            if not ok and contract.fallback_behavior == "block_report" and readiness["status"] == "PASS":
                readiness["status"] = "CHAPTER_CONTENT_BLOCKED"
                readiness["diagnostics"].append(f"{key}: {message}")
        placeholder_gate = PlaceholderContentGate(
            body_paragraphs=body_paragraphs, chapter_paragraphs=chapter_paragraphs,
        ).assess()

        synthesis_claim_ids = [
            claim_id for finding in (synthesis.findings if synthesis else [])
            for claim_id in finding.supporting_claim_ids
        ]
        status = "COMPLETED"
        if readiness["status"] != "PASS":
            status = readiness["status"]
        if placeholder_gate["blocked"] and status == "COMPLETED":
            status = "RESEARCH_CONTENT_BLOCKED"
        # A blocked run must RETAIN its evidence and diagnostics (fail-closed,
        # never evidence-less): ingest before the gates decide publication.
        EvidenceIngestor(store).ingest(run_id, 1, evidence)
        run_manifest = store.get_run(run_id)
        if canonical_entity is not None:
            run_manifest.canonical_entity_id = canonical_entity.entity_id
        run_manifest.complexity = complexity
        store.replace_run_manifest(run_manifest)
        # ---- publication when the content gates pass -----------------------
        freeze_id: str | None = None
        artifact_claim_ids: list[str] = []
        if status == "COMPLETED" and canonical_entity is not None:
            if self.enable_publication:
                try:
                    freeze_id, artifact_claim_ids = self._freeze_and_publish(store, run_id, output_dir)
                    if freeze_id is None:
                        status = "BLOCKED"
                except Exception as exc:  # noqa: BLE001 - surface, never silently publish nothing
                    diagnostics.append(f"publication failed: {type(exc).__name__}: {exc}")
                    status = "BLOCKED"
        elif status != "COMPLETED":
            diagnostic_path = output_dir / "diagnostic_report.json"
            diagnostic_path.write_text(json.dumps({
                "status": status,
                "readiness": readiness,
                "placeholder_gate": placeholder_gate,
                "goal_pipeline_trace": trace.model_dump(mode="json"),
                "evidence_breakdown": {
                    "claims_by_status": {
                        str(status.value): sum(1 for claim in evidence.claims if claim.verification_status == status)
                        for status in VerificationStatus
                    },
                    "claims_with_value": sum(1 for claim in evidence.claims if claim.value not in (None, "", [])),
                    "sources_by_level": {
                        str(level.value): sum(1 for source in evidence.sources if source.source_level == level)
                        for level in SourceLevel
                    },
                    "source_kinds_seen": sorted({
                        source.grading_reason.split(" ")[0] for source in evidence.sources
                    })[:20],
                },
                "diagnostics": diagnostics,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        utilization = ClaimUtilizationAuditor().audit(
            claims,
            synthesis_claim_ids=synthesis_claim_ids,
            artifact_claim_ids=artifact_claim_ids,
            table_claim_ids=[],
        )
        unused_path = str(utilization.write(output_dir / "02_research_quality"))

        funnel = {
            "search_hits": sum(entry.search_hits for entry in trace.goals.values()),
            "retrieved_pages": sum(entry.retrieved_pages for entry in trace.goals.values()),
            "extracted_claims": sum(entry.extracted_claims for entry in trace.goals.values()),
            "normalized_claims": sum(entry.normalized_claims for entry in trace.goals.values()),
            # Verified counts come from the merged evidence records — never
            # from envelope-time guesses.
            "verified_claims": sum(
                1 for claim in evidence.claims
                if claim.verification_status == VerificationStatus.VERIFIED and claim.value not in (None, "", [])
            ),
            "high_value_verified_claims": utilization.high_value_claim_count,
            "synthesis_findings": sum(entry.synthesis_findings for entry in trace.goals.values()),
            "published_findings": sum(entry.published_findings for entry in trace.goals.values()),
        }
        quality_dir = output_dir / "02_research_quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        (quality_dir / "kimi_telemetry.json").write_text(
            json.dumps(telemetry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (quality_dir / "evidence_deltas.json").write_text(
            json.dumps([delta.model_dump(mode="json") for delta in deltas], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (quality_dir / "readiness.json").write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (quality_dir / "placeholder_gate.json").write_text(
            json.dumps(placeholder_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        catalog_counts = self._catalog_summary()
        (quality_dir / "catalog_summary.json").write_text(
            json.dumps(catalog_counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        return AdaptiveRunReport(
            run_id=run_id,
            raw_company_name=raw_company_name,
            status=status,
            rounds=rounds,
            funnel=funnel,
            saturation={"status": saturation.status, "reasoning": saturation.reasoning},
            readiness=readiness,
            placeholder_gate=placeholder_gate,
            utilization=utilization.model_dump(mode="json"),
            kimi_usage=telemetry.model_dump(mode="json"),
            catalog=catalog_counts,
            trace_path=str(quality_dir / "goal_pipeline_trace.json"),
            synthesis_path=synthesis_path,
            unused_claims_path=unused_path,
            freeze_id=freeze_id,
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------- helpers

    def _extract_one(self, envelope: SearchResultEnvelope):
        extractor = EvidenceExtractor(self.gateway)
        return envelope, extractor.extract(envelope), extractor.last_failures

    def _browser_depth_pass(
        self,
        envelopes: list[SearchResultEnvelope],
        queries: list[ResearchQuery],
        telemetry: KimiUsageTelemetry,
    ) -> list[SearchResultEnvelope]:
        """Bounded deep browsing for product-catalog topics (P0-17).

        Official product centers are SPA pages; AnySearch discovers their
        URLs and Kimi opens the REAL pages (never search-result pages).
        Bounded: up to ``fulltext_pages_per_query`` pages per topic, hard
        per-round cap, so deep browsing never dominates the run.
        """
        kimi = self.adapters.get("kimi_webbridge")
        anysearch = self.adapters.get("anysearch")
        if kimi is None:
            return envelopes
        browser_topics = {
            query.topic for query in queries
            if query.requires_browser or query.adapter_preference == "kimi_webbridge"
        }
        visited_by_topic: dict[str, int] = {}
        round_pages = sum(
            1 for envelope in envelopes if envelope.adapter == "kimi_webbridge"
        )
        extended: list[SearchResultEnvelope] = list(envelopes)
        for envelope in envelopes:
            if envelope.topic not in browser_topics:
                continue
            candidates = [
                hit for hit in envelope.hits
                if hit.final_url and envelope.adapter != "kimi_webbridge"
            ]
            # Official-domain pages first: product evidence must come from the
            # company's own product center, not from third-party pages.
            candidates.sort(key=lambda hit: (
                0 if any(
                    (hit.final_url or "").startswith("https://" + domain)
                    or (hit.final_url or "").startswith("http://" + domain)
                    for domain in self._official_domains_hint
                ) else 1,
                -(len(hit.text or "")),
            ))
            for hit in candidates:
                topic_pages = visited_by_topic.get(envelope.topic, 0)
                if topic_pages >= self.fulltext_pages_per_query or round_pages >= 20:
                    break
                request = SearchRequest(
                    query_id=envelope.query_id,
                    query=str(hit.final_url),
                    entity_id="PENDING-ENTITY",
                    purpose=envelope.purpose or "",
                    requires_browser=True,
                    metadata={"url": str(hit.final_url), "target_page": True},
                )
                try:
                    deep = kimi.search(request)
                except Exception:  # noqa: BLE001 - one page failure never sinks the round
                    continue
                deep = deep.model_copy(update={
                    "topic": envelope.topic, "purpose": envelope.purpose,
                    "collection_round": envelope.collection_round,
                    "round_goal": envelope.round_goal, "trigger": envelope.trigger,
                    "target_gap_ids": envelope.target_gap_ids,
                    "target_conflict_ids": envelope.target_conflict_ids,
                    "target_claim_ids": envelope.target_claim_ids,
                    "canonical_company_name": envelope.canonical_company_name,
                    "expected_fields": envelope.expected_fields,
                })
                extended.append(deep)
                visited_by_topic[envelope.topic] = topic_pages + 1
                round_pages += 1
        return extended

    def _product_detail_pass(
        self,
        envelopes: list[SearchResultEnvelope],
        telemetry: KimiUsageTelemetry,
        *,
        queue_path: Path | None = None,
    ) -> list[SearchResultEnvelope]:
        """Run detail URLs through a persistent, normalized browser frontier.

        The queue is shared across R1/R2/R3, so successfully fetched URLs are
        not repeated and interrupted RUNNING rows are recovered on restart.
        Kimi's current-tab commands are lifecycle-locked while the generic
        pool still enforces the configured (<=4) page ceiling.
        """
        kimi = self.adapters.get("kimi_webbridge")
        if kimi is None:
            return envelopes
        candidate_pages = [
            envelope for envelope in envelopes
            if envelope.adapter == "kimi_webbridge"
            and envelope.topic in {"products", "product_series", "product_models", "product_parameters"}
        ]
        if not candidate_pages:
            return envelopes
        if queue_path is None:
            # Backward-compatible unit-test path. Production always supplies
            # a run-owned queue path above.
            import tempfile
            queue_path = Path(tempfile.mkdtemp(prefix="eer-product-frontier-")) / "queue.sqlite3"
        queue = ProductDetailFrontier(queue_path)
        for envelope in candidate_pages:
            for hit in envelope.hits:
                source_page = str(hit.final_url or hit.requested_url or "")
                if not source_page:
                    continue
                try:
                    if hasattr(kimi, "_command"):
                        kimi._command("find_tab", {"url": source_page, "active": False})
                    payload = kimi.evaluate(self.PRODUCT_LINKS_JS)
                except Exception:  # noqa: BLE001
                    continue
                context = {
                    "query_id": envelope.query_id, "topic": envelope.topic,
                    "purpose": envelope.purpose, "collection_round": envelope.collection_round,
                    "round_goal": envelope.round_goal, "trigger": envelope.trigger,
                    "target_gap_ids": envelope.target_gap_ids,
                    "target_conflict_ids": envelope.target_conflict_ids,
                    "target_claim_ids": envelope.target_claim_ids,
                    "canonical_company_name": envelope.canonical_company_name,
                    "expected_fields": envelope.expected_fields,
                }
                for link in (payload or {}).get("links") or []:
                    url = str(link.get("url") or "")
                    if not url:
                        continue
                    try:
                        queue.enqueue(url, source_page=source_page, checkpoint=context)
                    except ValueError:
                        continue

        shared_lifecycle_lock = threading.RLock()
        pool = BoundedBrowserWorkerPool(
            queue,
            lambda: KimiProductDetailBrowser(kimi, shared_lifecycle_lock),
            max_workers=self.browser_workers,
        )
        results = pool.run(limit=self.max_product_detail_pages)
        extended: list[SearchResultEnvelope] = list(envelopes)
        for result in results:
            context = result.task.checkpoint
            extended.append(SearchResultEnvelope(
                adapter="kimi_webbridge",
                query_id=str(context.get("query_id") or "PRODUCT-DETAIL"),
                status="ok" if result.text else "partial",
                hits=[SearchHit(
                    requested_url=result.task.url,
                    final_url=result.final_url,
                    title=result.title,
                    text=result.text,
                    status="ok" if result.text else "partial",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    metadata={
                        "target_page": True,
                        "product_detail": True,
                        "normalized_url": result.task.normalized_url,
                        "queue_task_id": result.task.task_id,
                        "discovered_images": result.discovered_images,
                    },
                )],
                topic=context.get("topic"), purpose=context.get("purpose"),
                collection_round=context.get("collection_round"), round_goal=context.get("round_goal"),
                trigger=context.get("trigger"), target_gap_ids=context.get("target_gap_ids") or [],
                target_conflict_ids=context.get("target_conflict_ids") or [],
                target_claim_ids=context.get("target_claim_ids") or [],
                canonical_company_name=context.get("canonical_company_name"),
                expected_fields=context.get("expected_fields") or [],
            ))
            telemetry.kimi_product_pages += 1
        # Internal validation evidence; never published as narrative text.
        metrics_path = queue_path.with_name("product_detail_browser_metrics.json")
        metrics_path.write_text(json.dumps({
            "configured_max_workers": pool.metrics.configured_max_workers,
            "max_active_pages": pool.metrics.max_active_pages,
            "opened_pages": pool.metrics.opened_pages,
            "closed_pages": pool.metrics.closed_pages,
            "succeeded": pool.metrics.succeeded,
            "failed": pool.metrics.failed,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return extended

    PRODUCT_LINKS_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return u || ''; } };
  document.querySelectorAll('a[href]').forEach(a => {
    const href = (a.getAttribute('href') || '').trim();
    if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:')) return;
    const absUrl = abs(href);
    if (!absUrl.startsWith(location.origin)) return;  // same-site detail pages only
    const text = (a.textContent || '').trim().slice(0, 60);
    if (!/product|products|detail|solution|系列|型号|详情/i.test(href + ' ' + text)) return;
    if (seen.has(absUrl)) return;
    seen.add(absUrl);
    out.push({url: absUrl, text});
  });
  return {links: out.slice(0, 12)};
})()
"""

    def _fulltext_pass(
        self,
        envelopes: list[SearchResultEnvelope],
        queries: list[ResearchQuery],
    ) -> list[SearchResultEnvelope]:
        """AnySearch search results -> AnySearch full-text extraction.

        Search snippets are discovery-only; the approved AnySearch runtime
        fetches the REAL target page text via its extract command (fast HTTP,
        no browser). Kimi WebBridge is reserved for image discovery.
        Extraction runs CONCURRENTLY (each call is a CLI subprocess), bounded
        by a worker pool.
        """
        anysearch = self.adapters.get("anysearch")
        if anysearch is None:
            return envelopes
        extended: list[SearchResultEnvelope] = list(envelopes)
        tasks: list[tuple[SearchResultEnvelope, SearchHit]] = []
        for envelope in envelopes:
            if envelope.adapter != "anysearch":
                continue
            for hit in envelope.hits:
                if hit.final_url and hit.metadata.get("snippet"):
                    tasks.append((envelope, hit))
        workers = max(2, min(self.extraction_workers, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._extract_fulltext, anysearch, envelope, hit): (envelope, hit)
                for envelope, hit in tasks[: self.fulltext_pages_per_query * len(envelopes)]
            }
            from concurrent.futures import as_completed
            for future in as_completed(futures):
                envelope, hit = futures[future]
                try:
                    full = future.result()
                except Exception:  # noqa: BLE001 - one page failure never sinks the round
                    continue
                if full is None:
                    continue
                for full_hit in full.hits:
                    if not full_hit.text:
                        continue
                    context = {
                        "topic": envelope.topic, "purpose": envelope.purpose,
                        "collection_round": envelope.collection_round,
                        "round_goal": envelope.round_goal, "trigger": envelope.trigger,
                        "target_gap_ids": envelope.target_gap_ids,
                        "target_conflict_ids": envelope.target_conflict_ids,
                        "target_claim_ids": envelope.target_claim_ids,
                        "canonical_company_name": envelope.canonical_company_name,
                        "expected_fields": envelope.expected_fields,
                    }
                    extended.append(full.model_copy(update={
                        **context,
                        "hits": [full_hit.model_copy(update={
                            "metadata": {**full_hit.metadata, "snippet": False},
                        })],
                    }))
        return extended

    @staticmethod
    def _extract_fulltext(anysearch, envelope: SearchResultEnvelope, hit: SearchHit):
        """One AnySearch extract call (subprocess) for a single target URL."""
        try:
            return anysearch.search(SearchRequest(
                query_id=envelope.query_id,
                query=str(hit.final_url),
                entity_id="PENDING-ENTITY",
                purpose=envelope.purpose or "",
                metadata={"url": str(hit.final_url), "extract": True},
            ))
        except Exception:  # noqa: BLE001
            return None

    def _image_pass(self, envelopes: list[SearchResultEnvelope], telemetry: KimiUsageTelemetry) -> None:
        """P0-16: image discovery on real pages via DOM inspection.

        Image goals visit image pages; product/factory topics visited by the
        browser depth pass contribute product/factory pages so images stay
        bound to what the page is actually about.
        """
        kimi = self.adapters.get("kimi_webbridge")
        if kimi is None or self.fetcher is None:
            return
        pages: list[dict] = []
        known_products = {
            product.name: product.product_id for product in self.cumulative.products
        }
        known_factories = {
            factory.name: factory.factory_id for factory in self.cumulative.factories if factory.name
        }
        for envelope in envelopes:
            topic = envelope.topic or ""
            if topic == "image_evidence":
                kind = "image"
            elif topic in {"products", "product_series", "product_models"}:
                kind = "product"
            elif topic in {"factories", "production_lines"}:
                kind = "factory"
            else:
                continue
            for hit in envelope.hits:
                if not hit.final_url or not str(hit.final_url).lower().startswith(("http://", "https://")):
                    continue
                page = {
                    "url": hit.final_url,
                    "kind": kind,
                    "source_kind": "official_company",
                    "publisher": hit.title,
                }
                if kind == "product":
                    matched = next(
                        (product_id for name, product_id in known_products.items()
                         if name and (name in (hit.title or "") or name in (hit.text or ""))),
                        None,
                    )
                    if matched:
                        page["product_key"] = matched
                if kind == "factory":
                    matched = next(
                        (factory_id for name, factory_id in known_factories.items()
                         if name and (name in (hit.title or "") or name in (hit.text or ""))),
                        None,
                    )
                    if matched:
                        page["factory_key"] = matched
                pages.append(page)
        if not pages:
            return
        discovery = KimiImageDiscovery(kimi, telemetry)
        candidates = discovery.discover(pages)
        self._pending_image_candidates.extend(candidates)

    def _process_round(
        self,
        raw_company_name: str,
        batches: list[ExtractedEvidenceBatch],
        *,
        output_dir: Path,
        telemetry: KimiUsageTelemetry,
        trace: GoalPipelineTrace,
        canonical_entity: Entity | None = None,
    ) -> tuple[Entity | None, list[DataGap], list, list[str]]:
        diagnostics: list[str] = []
        if not batches:
            # A round that found nothing must still record WHY each queried
            # goal family is empty (P0-13), so R2 can be gap-driven.
            gaps = self._field_gaps(NormalizedEvidence(), trace)
            self.cumulative.gaps.extend(gaps)
            return canonical_entity, gaps, [], diagnostics
        resolution = CompanyResolver().resolve(raw_company_name, batches)
        if resolution.status != "RESOLVED":
            return canonical_entity, [], [], [f"company resolution: {resolution.status}"]
        official_domains = {
            str(candidate.official_website.host).lower().removeprefix("www.")
            for candidate in resolution.candidates if candidate.official_website
        }
        self._official_domains_hint = official_domains
        # Deterministic source classification: pages on the company's own
        # verified domains ARE official pages — the LLM's free-text
        # source_kind must never downgrade them.
        from urllib.parse import urlparse as _urlparse
        upgraded: list[ExtractedEvidenceBatch] = []
        for batch in batches:
            page_host = _urlparse(str(batch.source_url)).netloc.lower().removeprefix("www.")
            if page_host and any(
                page_host == domain or page_host.endswith("." + domain) for domain in official_domains
            ):
                upgraded.append(batch.model_copy(update={"source_kind": "official_company"}))
            else:
                upgraded.append(batch)
        batches = upgraded
        healthy_batches = list(batches)
        try:
            round_evidence = EvidenceNormalizer().normalize(healthy_batches, official_domains=official_domains)
        except ValueError as exc:
            # One malformed batch must not sink the round: re-normalize
            # batch-by-batch and drop only the offending pages (宁缺毋滥).
            diagnostics.append(f"batch-level normalization recovery: {str(exc)[:160]}")
            round_evidence = NormalizedEvidence()
            healthy_batches = []
            for single in batches:
                try:
                    piece = EvidenceNormalizer().normalize([single], official_domains=official_domains)
                except ValueError as piece_exc:
                    diagnostics.append(f"dropped batch {single.source_url}: {str(piece_exc)[:120]}")
                    continue
                MergeEvidence.merge(round_evidence, piece)
                healthy_batches.append(single)
        round_evidence.claims.extend(
            IdentityEvidenceSynthesizer().synthesize(
                resolution, healthy_batches, round_evidence.entities, round_evidence.sources,
            )
        )
        # Discovered images -> ImageEvidence (P0-15/16), with page Sources.
        self._attach_discovered_images(round_evidence, telemetry, official_domains)
        # Merge into the cumulative evidence object with stable IDs.
        MergeEvidence.merge(self.cumulative, round_evidence)
        # Revalidate the merged evidence every round (P1-1 revalidation step).
        self.cumulative.claims, self.cumulative.conflicts = ClaimValidator().validate(
            self.cumulative.claims, self.cumulative.sources,
        )
        self.cumulative.entities, self.cumulative.edges = EntityMapper().apply_evidence(
            self.cumulative.entities, self.cumulative.edges, self.cumulative.claims,
        )
        image_validator = ImageValidator()
        self.cumulative.images = image_validator.validate(
            self.cumulative.images, self.cumulative.entities, self.cumulative.sources,
        )
        archive_result = ImageArchiveResult(images=self.cumulative.images)
        # Archiving depends on the IMAGES themselves, never on whether this
        # round produced text batches: the last round may attach discovered
        # images while contributing no new text evidence, and those images
        # must still be archived + visually verified before freeze.
        pending_images = [image for image in self.cumulative.images if not image.local_asset_ref]
        if self.enable_image_archiving and self.fetcher is not None and pending_images:
            # The discovery fetcher returns bytes; the archiver expects
            # (payload, content_type) so it can re-verify against the headers.
            archive_result = ImageAssetArchiver(
                fetcher=lambda url, referer: (self.fetcher(url, referer), None),
            ).archive(pending_images, output_dir)
            by_id = {image.image_id: image for image in archive_result.images}
            self.cumulative.images = [by_id.get(image.image_id, image) for image in self.cumulative.images]
            telemetry.images_archived = len(archive_result.archived_image_ids)
            telemetry.image_download_failures += len(archive_result.failed_image_ids)
            # P0: pixel-level visual verification runs AFTER archiving — a
            # vision verifier needs the local bytes, never context alone.
            self.cumulative.images = image_validator.visual_verify(
                self.cumulative.images, base_dir=output_dir,
            )
        self.cumulative.products, _ = ProductDetector().detect(
            self.cumulative.products, self.cumulative.images, self.cumulative.sources,
            self.cumulative.claims,
            require_archived_images=self.enable_image_archiving,
        )
        # P0-17: catalog items advance by real state, and coverage is computed
        # from the actual inventory (never from "pages we happened to open").
        self._reconcile_catalog()
        self.cumulative.energy_profiles, energy_gaps = EnergyAnalyst().analyze(
            self.cumulative.entities, self.cumulative.factories, self.cumulative.claims,
        )
        self.cumulative.solutions = SolutionEngine().generate(
            self.cumulative.entities, self.cumulative.energy_profiles, self.cumulative.claims,
        )
        self.cumulative.gaps.extend(energy_gaps)
        self.cumulative.gaps.extend(self._field_gaps(self.cumulative, trace))
        classifier = GapReasonClassifier()
        classified: list[DataGap] = []
        for gap in self.cumulative.gaps:
            if gap.reason in {"missing", "stale", "unverifiable"}:
                precise = classifier.classify(gap, trace)
                classified.append(gap.model_copy(update={"reason": precise}))
            else:
                classified.append(gap)
        self.cumulative.gaps = classified
        selected_candidate = next(
            candidate for candidate in resolution.candidates
            if candidate.candidate_id == resolution.selected_candidate_id
        )
        # Keep the canonical entity stable across rounds: later rounds may
        # resolve other co-mentioned entities, which must not displace it.
        if canonical_entity is not None and any(
            item.entity_id == canonical_entity.entity_id for item in self.cumulative.entities
        ):
            selected_entity = canonical_entity
        else:
            selected_entity = next(
                (entity for entity in self.cumulative.entities
                 if entity.canonical_name == selected_candidate.canonical_name
                 or MergeEvidence._norm_name(entity.canonical_name) == MergeEvidence._norm_name(selected_candidate.canonical_name)),
                None,
            )
        if selected_entity is None:
            return canonical_entity, [], [], ["resolved candidate did not map to a merged entity"]
        return selected_entity, self.cumulative.gaps, [
            conflict for conflict in self.cumulative.conflicts if conflict.resolution == "unresolved"
        ], diagnostics

    def _attach_discovered_images(
        self,
        evidence: NormalizedEvidence,
        telemetry: KimiUsageTelemetry,
        official_domains: set[str],
    ) -> None:
        candidates = self._pending_image_candidates
        self._pending_image_candidates = []
        if not candidates or self.fetcher is None:
            return
        builder = ImageEvidenceBuilder(self.fetcher)
        grader = SourceGrader()
        page_sources: dict[str, str] = {}
        selected_entity = evidence.entities[0] if evidence.entities else None
        known_products = {
            product.name: product.product_id for product in evidence.products if product.name
        }
        known_factories = {
            factory.name: factory.factory_id for factory in evidence.factories if factory.name
        }
        for candidate in candidates:
            if not str(candidate.page_url).lower().startswith(("http://", "https://")):
                telemetry.image_download_failures += 1
                continue
            context = " ".join(filter(None, (
                candidate.alt or "", candidate.surrounding_text or "", candidate.page_title or "",
            )))
            # Images found on product/factory pages bind to the concrete
            # product/factory by their own context (alt/surrounding/page
            # title) — never randomly assigned.  A context match also
            # corrects the page-kind fallback type.
            if candidate.product_key is None and (candidate.image_type == "product" or candidate.page_kind == "product"):
                matched = next(
                    (product_id for name, product_id in known_products.items()
                     if name and name in context),
                    None,
                )
                if matched:
                    candidate = candidate.model_copy(update={"product_key": matched, "image_type": "product"})
            if candidate.factory_key is None and (candidate.image_type == "factory" or candidate.page_kind == "factory"):
                matched = next(
                    (factory_id for name, factory_id in known_factories.items()
                     if name and name in context),
                    None,
                )
                if matched:
                    candidate = candidate.model_copy(update={"factory_key": matched, "image_type": "factory"})
            source_id = page_sources.get(candidate.page_url)
            if source_id is None:
                level, reason = grader.grade(candidate.page_url, candidate.source_kind, official_domains=official_domains)
                source_id = new_sortable_id("source")
                evidence.sources.append(Source(
                    source_id=source_id, canonical_url=candidate.page_url,  # type: ignore[arg-type]
                    source_title=candidate.page_title,
                    source_domain=candidate.page_url.split("/", 2)[2] if "//" in candidate.page_url else "",
                    publisher=candidate.publisher, source_level=level, content_type="text/html",
                    grading_reason=reason,
                ))
                page_sources[candidate.page_url] = source_id
            image = builder.build(
                candidate, source_id=source_id,
                entity_id=selected_entity.entity_id if selected_entity else None,
                factory_id=(
                    candidate.factory_key
                    if candidate.factory_key and candidate.factory_key in {factory.factory_id for factory in evidence.factories}
                    else None
                ),
                product_id=(
                    candidate.product_key
                    if candidate.product_key and candidate.product_key in {product.product_id for product in evidence.products}
                    else None
                ),
            )
            if image is None:
                telemetry.image_download_failures += 1
                continue
            evidence.images.append(image)
        telemetry.image_candidates_verified = len(evidence.images)

    def _reconcile_catalog(self) -> None:
        from enterprise_energy_research.research.catalog import CatalogInventory, CatalogTraverser
        if not hasattr(self, "catalog_inventory"):
            self.catalog_inventory = CatalogInventory()
        inventory: CatalogInventory = self.catalog_inventory
        traverser = CatalogTraverser()
        pages: list[dict] = []
        for product in self.cumulative.products:
            pages.append({
                "name": product.name,
                "level": "model" if product.model else "family",
                "entity_id": product.entity_id,
                "product_id": product.product_id,
                "url": None,
            })
        if pages:
            traverser.discover(inventory, pages)
            traverser.mark_extracted(
                inventory, [page["name"] for page in pages],
                product_id_by_name={page["name"]: page["product_id"] for page in pages},
            )
            traverser.reconcile(inventory, self.cumulative.products)

    def _catalog_summary(self) -> dict:
        from enterprise_energy_research.research.catalog import CatalogInventory
        inventory: CatalogInventory = getattr(self, "catalog_inventory", None) or CatalogInventory()
        return {
            "items": len(inventory.items),
            "by_state": inventory.by_state(),
            "coverage": inventory.coverage(),
            "complete": inventory.is_complete(),
        }

    @staticmethod
    def _field_gaps(evidence: NormalizedEvidence, trace: GoalPipelineTrace) -> list[DataGap]:
        """Gaps for critical goal families with zero verified evidence so far.

        Coverage is judged by the family's OWN expected fields (canonicalized),
        not by unrelated field-family names.
        """
        from enterprise_energy_research.research.contracts import GOAL_CONTRACTS
        from enterprise_energy_research.research.field_registry import CanonicalFieldRegistry
        gaps: list[DataGap] = []
        verified_canonical = {
            CanonicalFieldRegistry.canonicalize(claim.field_name)
            for claim in evidence.claims if claim.verification_status == VerificationStatus.VERIFIED
        }
        for family, contract in GOAL_CONTRACTS.items():
            if contract.criticality != "critical":
                continue
            expected = {CanonicalFieldRegistry.canonicalize(field) for field in contract.expected_fields}
            if verified_canonical & expected:
                continue
            entry = trace.goals.get(family)
            if entry is None or entry.queries == 0:
                continue  # never queried -> NOT_SEARCHED is recorded by trace, not a new gap
            gaps.append(DataGap(
                gap_id=new_sortable_id("GAP"),
                entity_id=None,
                field_name=family,
                importance="critical",
                reason="missing",
                next_action=f"{contract.business_question} 使用 R2 深度检索补齐 {', '.join(contract.expected_fields[:6])}",
            ))
        return gaps

    def _freeze_and_publish(self, store: EvidenceStore, run_id: str, output_dir: Path) -> tuple[str | None, list[str]]:
        from enterprise_energy_research.artifacts.publisher import ArtifactPublicationService
        from enterprise_energy_research.automation.executor import default_publishers
        run = store.get_run(run_id)
        state = ResearchState(
            run_id=run_id, request_id=run.request_id, status=RunStatus.RUNNING,
            canonical_entity_id=run.canonical_entity_id,
            complexity=run.complexity or EnterpriseComplexity.UNKNOWN,
        )
        final_state, manifest = Phase2Runner(store).finalize_evidence(
            state, output_dir=output_dir / "01_evidence",
        )
        if final_state.freeze_id is None or manifest is None:
            return None, []
        from enterprise_energy_research.evidence.freeze import FreezeService
        bundle = FreezeService(store).load_bundle(final_state.freeze_id)
        publishers = self.publishers or default_publishers()
        results = ArtifactPublicationService(publishers).publish(bundle, manifest, output_dir / "artifacts")
        used = sorted({claim_id for result in results for claim_id in result.used_claim_ids})
        return final_state.freeze_id, used

    @staticmethod
    def _summarize(envelopes: list[SearchResultEnvelope]) -> list[dict]:
        return [
            {
                "adapter": envelope.adapter, "query_id": envelope.query_id,
                "topic": envelope.topic, "round": envelope.collection_round,
                "status": envelope.status, "hits": len(envelope.hits),
            }
            for envelope in envelopes
        ]

    @staticmethod
    def _query_summary(query: ResearchQuery) -> dict:
        return {
            "query_id": query.query_id, "topic": query.topic,
            "trigger": query.trigger,
            "target_gap_ids": list(query.target_gap_ids),
            "target_conflict_ids": list(query.target_conflict_ids),
        }


class MergeEvidence:
    """Merge round evidence into a cumulative object with STABLE record IDs.

    Records already present (same canonical entity name, factory name,
    product name/model, source URL) keep their existing IDs; new round claims,
    edges and images are remapped onto those stable IDs before being appended.
    RunSequence IDs (CLAIM-/SOURCE-/RET-/IMAGE-) restart per round, so any
    collision receives a fresh globally-unique ID. This is the
    "Extract -> Merge -> Revalidate" step between rounds.
    """

    PREFIX_BY_KIND = {"claim": "CLAIM", "source": "SOURCE", "retrieval": "RET", "image": "IMAGE"}

    @staticmethod
    def _norm_name(value: str) -> str:
        """Suffix-insensitive name key so 全称/简称 variants aggregate."""
        suffixes = ("有限责任公司", "股份有限公司", "有限公司", "集团公司", "集团")
        folded = "".join(value.lower().split())
        for suffix in suffixes:
            if folded.endswith(suffix):
                folded = folded[: -len(suffix)]
        return folded

    @classmethod
    def merge(cls, cumulative: NormalizedEvidence, round_evidence: NormalizedEvidence) -> None:
        existing_ids = {
            kind: {str(getattr(item, id_field)) for item in getattr(cumulative, attr)}
            for kind, (attr, id_field) in {
                "claim": ("claims", "claim_id"), "source": ("sources", "source_id"),
                "retrieval": ("retrievals", "retrieval_id"), "image": ("images", "image_id"),
                "gap": ("gaps", "gap_id"), "conflict": ("conflicts", "conflict_group_id"),
                "energy_profile": ("energy_profiles", "energy_profile_id"),
                "solution": ("solutions", "solution_id"),
                "entity": ("entities", "entity_id"), "factory": ("factories", "factory_id"),
                "product": ("products", "product_id"), "edge": ("edges", "edge_id"),
            }.items()
        }

        def fresh(kind: str) -> str:
            while True:
                candidate = new_sortable_id(cls.PREFIX_BY_KIND.get(kind, kind.upper()))
                if candidate not in existing_ids[kind]:
                    existing_ids[kind].add(candidate)
                    return candidate

        def remap_id(record, id_field: str, kind: str):
            current = str(getattr(record, id_field))
            if current in existing_ids[kind]:
                return record.model_copy(update={id_field: fresh(kind)}), True
            existing_ids[kind].add(current)
            return record, False

        entity_map: dict[str, str] = {}
        for entity in round_evidence.entities:
            existing = next(
                (item for item in cumulative.entities
                 if item.canonical_name == entity.canonical_name
                 or cls._norm_name(item.canonical_name) == cls._norm_name(entity.canonical_name)),
                None,
            )
            if existing is None:
                remapped, _ = remap_id(entity, "entity_id", "entity")
                cumulative.entities.append(remapped)
                entity_map[entity.entity_id] = remapped.entity_id
            else:
                entity_map[entity.entity_id] = existing.entity_id
        factory_map: dict[str, str] = {}
        for factory in round_evidence.factories:
            operator_id = entity_map.get(factory.operator_entity_id, factory.operator_entity_id)
            existing = next(
                (item for item in cumulative.factories
                 if item.operator_entity_id == operator_id and (item.name or "") == (factory.name or "")),
                None,
            )
            if existing is None:
                updated = factory.model_copy(update={"operator_entity_id": operator_id})
                remapped, _ = remap_id(updated, "factory_id", "factory")
                cumulative.factories.append(remapped)
                factory_map[factory.factory_id] = remapped.factory_id
            else:
                factory_map[factory.factory_id] = existing.factory_id
        product_map: dict[str, str] = {}
        for product in round_evidence.products:
            owner_id = entity_map.get(product.entity_id, product.entity_id)
            existing = next(
                (item for item in cumulative.products
                 if item.entity_id == owner_id and item.name == product.name and (item.model or "") == (product.model or "")),
                None,
            )
            if existing is None:
                updated = product.model_copy(update={"entity_id": owner_id})
                remapped, _ = remap_id(updated, "product_id", "product")
                cumulative.products.append(remapped)
                product_map[product.product_id] = remapped.product_id
            else:
                product_map[product.product_id] = existing.product_id
        source_map: dict[str, str] = {}
        for source in round_evidence.sources:
            is_snippet = source.grading_reason.startswith("search snippet")
            existing = next(
                (item for item in cumulative.sources
                 if str(item.canonical_url) == str(source.canonical_url)
                 and item.grading_reason.startswith("search snippet") == is_snippet),
                None,
            )
            if existing is None:
                remapped, _ = remap_id(source, "source_id", "source")
                cumulative.sources.append(remapped)
                source_map[source.source_id] = remapped.source_id
            else:
                source_map[source.source_id] = existing.source_id
        for retrieval in round_evidence.retrievals:
            updated = retrieval.model_copy(update={
                "source_id": source_map.get(retrieval.source_id, retrieval.source_id),
            })
            remapped, _ = remap_id(updated, "retrieval_id", "retrieval")
            cumulative.retrievals.append(remapped)
        for claim in round_evidence.claims:
            updated = claim.model_copy(update={
                "entity_id": entity_map.get(claim.entity_id, claim.entity_id),
                "source_id": source_map.get(claim.source_id, claim.source_id),
            })
            remapped, _ = remap_id(updated, "claim_id", "claim")
            cumulative.claims.append(remapped)
        # Product source_ids reference round-level source ids; remap them onto
        # the merged source ids so referential integrity survives dedup.
        for index, product in enumerate(cumulative.products):
            remapped_sources = [source_map.get(source_id, source_id) for source_id in product.source_ids]
            if remapped_sources != product.source_ids:
                cumulative.products[index] = product.model_copy(update={"source_ids": remapped_sources})
        seen_edges = {(edge.from_id, edge.relation, edge.to_id) for edge in cumulative.edges}
        for edge in round_evidence.edges:
            updated = edge.model_copy(update={
                "from_id": entity_map.get(edge.from_id, edge.from_id),
                "to_id": entity_map.get(edge.to_id, factory_map.get(edge.to_id, product_map.get(edge.to_id, edge.to_id))),
            })
            key = (updated.from_id, updated.relation, updated.to_id)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            remapped, _ = remap_id(updated, "edge_id", "edge")
            cumulative.edges.append(remapped)
        for image in round_evidence.images:
            updated = image.model_copy(update={
                "entity_id": entity_map.get(image.entity_id, image.entity_id) if image.entity_id else None,
                "factory_id": factory_map.get(image.factory_id, image.factory_id) if image.factory_id else None,
                "product_id": product_map.get(image.product_id, image.product_id) if image.product_id else None,
                "source_id": source_map.get(image.source_id, image.source_id),
            })
            remapped, _ = remap_id(updated, "image_id", "image")
            cumulative.images.append(remapped)
        for gap in round_evidence.gaps:
            updated = gap.model_copy(update={
                "entity_id": entity_map.get(gap.entity_id, gap.entity_id) if gap.entity_id else None,
            })
            remapped, _ = remap_id(updated, "gap_id", "gap")
            cumulative.gaps.append(remapped)
        for conflict in round_evidence.conflicts:
            remapped, _ = remap_id(conflict, "conflict_group_id", "conflict")
            cumulative.conflicts.append(remapped)
        for profile in round_evidence.energy_profiles:
            updated = profile.model_copy(update={
                "entity_id": entity_map.get(profile.entity_id, profile.entity_id),
                "factory_id": factory_map.get(profile.factory_id, profile.factory_id) if profile.factory_id else None,
            })
            remapped, _ = remap_id(updated, "energy_profile_id", "energy_profile")
            cumulative.energy_profiles.append(remapped)
        for solution in round_evidence.solutions:
            updated = solution.model_copy(update={
                "target_ids": [entity_map.get(target, target) for target in solution.target_ids],
            })
            remapped, _ = remap_id(updated, "solution_id", "solution")
            cumulative.solutions.append(remapped)
