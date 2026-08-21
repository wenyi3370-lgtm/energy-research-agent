"""Executor boundary between the automation service and the research kernel (Phase 2).

Real search orchestration (planner -> anysearch -> extract) is a later,
independent phase; the executors defined here never perform network I/O.
They run the deterministic kernel over synthetic or caller-injected fixture
evidence batches: normalize -> ingest -> validate on the research side, and
freeze -> artifact plan -> publish -> consistency audit on the publish side.

Domain invariants preserved here:

- publishers never browse and never mutate evidence;
- freeze happens only after CoreValidator passes (enforced by Phase2Runner);
- the automation service calls :meth:`ResearchExecutor.freeze_and_publish`
  only after the run reached APPROVED, so the human gate always precedes
  the freeze.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from pydantic import Field

from ..adapters.base import ArtifactAdapter
from ..artifacts.excel import ExcelMasterFrozenPublisher
from ..artifacts.html import FrozenHtmlPublisher
from ..artifacts.publisher import ArtifactPublicationService
from ..artifacts.word import FrozenWordPublisher
from ..domain.enums import (
    ArtifactStatus,
    ArtifactType,
    EnterpriseComplexity,
    ProductDashboardDecision,
    RunStatus,
    SourceLevel,
    ValidationStatus,
    VerificationStatus,
)
from ..domain.ids import RunSequence, new_sortable_id
from ..domain.models import (
    Claim,
    Entity,
    ExtractedEvidenceBatch,
    ProductDetection,
    RunManifest,
    Source,
    StrictModel,
)
from ..evidence.freeze import FreezeService
from ..evidence.store import EvidenceStore
from ..graph.runner import Phase2Runner
from ..graph.state import ResearchState
from ..release.audit import ArtifactConsistencyAuditor
from ..research.ingestor import EvidenceIngestor
from ..research.normalizer import EvidenceNormalizer
from ..settings import Settings
from ..validation.core import CoreValidator
from .contracts import ArtifactRef, ResearchRequest
from .enums import RiskLevel

EVIDENCE_KINDS = (
    "entity", "factory", "product", "edge", "source", "retrieval", "claim",
    "conflict", "gap", "image", "energy_profile", "solution",
)


class ExecutionOutcome(StrictModel):
    """Structured output of one executor step, consumed by ResearchService."""

    validation_status: ValidationStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.LOW
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    gap_count: int = Field(default=0, ge=0)
    verified_claim_count: int = Field(default=0, ge=0)
    freeze_id: str | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    # usage counters (Phase 10): populated by orchestrating executors that
    # wrap a ModelGateway and run search adapters; zero when not applicable.
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    search_calls: int = Field(default=0, ge=0)


def mean_claim_confidence(store: EvidenceStore, run_id: str) -> float | None:
    claims = store.list(run_id, "claim")
    if not claims:
        return None
    verified = [item for item in claims if item.verification_status == VerificationStatus.VERIFIED]
    pool = verified or claims
    return round(sum(item.confidence for item in pool) / len(pool), 4)


def risk_for(status: ValidationStatus) -> RiskLevel:
    return {
        ValidationStatus.PASS: RiskLevel.LOW,
        ValidationStatus.PASS_WITH_WARNINGS: RiskLevel.MEDIUM,
        ValidationStatus.BLOCKED: RiskLevel.HIGH,
    }[status]


class ResearchExecutor(Protocol):
    """Two-phase executor contract used by ResearchService.

    The split exists so the validation/review gate sits between research and
    freeze: ``research_and_validate`` must never freeze, and
    ``freeze_and_publish`` is only invoked after the run reached APPROVED.
    """

    def research_and_validate(
        self, run_id: str, request: ResearchRequest, workdir: Path
    ) -> ExecutionOutcome:
        """Run research + evidence ingest + validation; never freezes."""
        ...

    def freeze_and_publish(self, run_id: str, workdir: Path) -> ExecutionOutcome:
        """Freeze validated evidence, plan artifacts, publish and audit them."""
        ...


def default_publishers() -> dict[ArtifactType, ArtifactAdapter]:
    """Frozen publishers that work fully offline.

    PPT is intentionally not wired: PptMasterFrozenPublisher needs an
    external render executor, so a planned PPT binding is reported as failed
    by ArtifactPublicationService and surfaced through
    ``ExecutionOutcome.review_reasons`` instead of being silently dropped.
    """

    return {
        ArtifactType.EXCEL: ExcelMasterFrozenPublisher(),
        ArtifactType.WORD: FrozenWordPublisher(),
        ArtifactType.ENTERPRISE_HTML: FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML),
        ArtifactType.PRODUCT_HTML: FrozenHtmlPublisher(ArtifactType.PRODUCT_HTML),
    }


class SyntheticKernelExecutor:
    """Default ResearchExecutor over synthetic/fixture evidence; no network I/O.

    ``fixture_batches`` maps ``task_id`` -> extracted evidence batches (the
    same fixture pattern as tests/test_phase3_workflow.py); tasks without an
    injected batch fall back to a minimal synthetic entity/source/claim
    triple mirroring ``cli.synthetic_run``. Run state lives under
    ``workdir / run_id`` so the two executor phases can run in separate
    service calls. Real search orchestration (planner -> anysearch ->
    extract) is a separate later phase and is out of scope here.
    """

    def __init__(
        self,
        fixture_batches: dict[str, list[ExtractedEvidenceBatch]] | None = None,
        publishers: dict[ArtifactType, ArtifactAdapter] | None = None,
        code_version: str = "0.6.1",
    ) -> None:
        self.fixture_batches = fixture_batches or {}
        self.publishers = publishers if publishers is not None else default_publishers()
        self.code_version = code_version

    # -- paths ------------------------------------------------------------

    @staticmethod
    def _run_dir(workdir: Path, run_id: str) -> Path:
        return Path(workdir) / run_id

    def _open_store(self, workdir: Path, run_id: str) -> EvidenceStore:
        return EvidenceStore(self._run_dir(workdir, run_id) / "evidence.sqlite3")

    # -- phase A: research + validate (never freezes) ---------------------

    def research_and_validate(
        self, run_id: str, request: ResearchRequest, workdir: Path
    ) -> ExecutionOutcome:
        run_dir = self._run_dir(workdir, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        settings = Settings(output_root=run_dir / "outputs")
        domain_request = request.to_domain_request(new_sortable_id("REQ"))
        store = self._open_store(workdir, run_id)
        store.create_run(RunManifest(
            run_id=run_id,
            request_id=domain_request.request_id,
            status=RunStatus.RUNNING,
            config_hash=settings.config_hash(),
            code_version=self.code_version,
            model_gateway={
                "primary_provider": settings.primary_provider,
                "fallback_provider": settings.fallback_provider,
                "mode": "fixture",
            },
        ))
        batches = self.fixture_batches.get(request.task_id)
        if batches:
            official_domains = {
                urlparse(str(entity.official_website)).netloc.lower().removeprefix("www.")
                for batch in batches
                for entity in batch.entities
                if entity.official_website
            }
            evidence = EvidenceNormalizer().normalize(batches, official_domains=official_domains)
            self._ingest_normalized(store, run_id, evidence)
        else:
            self._ingest_minimal_synthetic(store, run_id, domain_request.raw_company_name)
        report = CoreValidator(store).validate(run_id, 1)
        return ExecutionOutcome(
            validation_status=report.status,
            confidence=self._mean_claim_confidence(store, run_id),
            risk_level=self._risk_for(report.status),
            review_required=False,
            review_reasons=[f"{finding.code}: {finding.message}" for finding in report.findings],
            evidence_count=sum(len(store.list(run_id, kind)) for kind in EVIDENCE_KINDS),
            conflict_count=len(store.list(run_id, "conflict")),
            gap_count=len(store.list(run_id, "gap")),
            verified_claim_count=len([
                item for item in store.list(run_id, "claim")
                if item.verification_status == VerificationStatus.VERIFIED
            ]),
        )

    @staticmethod
    def _ingest_normalized(store: EvidenceStore, run_id: str, evidence: NormalizedEvidence) -> None:
        """Ingest the normalized evidence in kernel order, skipping absent kinds.

        ``EvidenceIngestor`` expects ``solution`` records, which only the
        Phase 3 SOLUTION_ENGINE step produces; the synthetic path here does
        not run that engine, so kinds missing from the normalized object are
        skipped instead of raising ``AttributeError``.
        """

        for kind in EvidenceIngestor.ORDER:
            for record in getattr(evidence, EvidenceIngestor.ATTR_BY_KIND[kind], ()):
                store.add(run_id, 1, kind, record)

    @staticmethod
    def _ingest_minimal_synthetic(store: EvidenceStore, run_id: str, company_name: str) -> None:
        """Mirror cli.synthetic_run: one verified entity/source/claim triple."""
        entity_id = new_sortable_id("ENT")
        sequence = RunSequence()
        source_id = sequence.next("source")
        claim_id = sequence.next("claim")
        store.add(run_id, 1, "entity", Entity(
            entity_id=entity_id,
            canonical_name=company_name,
            registered_name=company_name,
            verification_status=VerificationStatus.VERIFIED,
            supporting_claim_ids=[claim_id],
        ))
        store.add(run_id, 1, "source", Source(
            source_id=source_id,
            canonical_url="https://example.com/official/company-profile",
            source_title="Synthetic official company profile",
            source_domain="example.com",
            publisher=company_name,
            source_level=SourceLevel.SOURCE_A,
            grading_reason="official_company synthetic fixture",
            content_type="text/html",
        ))
        store.add(run_id, 1, "claim", Claim(
            claim_id=claim_id,
            entity_id=entity_id,
            field_name="canonical_company_name",
            value=company_name,
            value_type="string",
            qualifier="exact",
            source_id=source_id,
            raw_text=company_name,
            context_text=f"企业名称：{company_name}",
            verification_status=VerificationStatus.VERIFIED,
            confidence=1.0,
        ))

    # -- phase B: freeze + publish (only after APPROVED) -------------------

    def freeze_and_publish(self, run_id: str, workdir: Path) -> ExecutionOutcome:
        run_dir = self._run_dir(workdir, run_id)
        store = self._open_store(workdir, run_id)
        run = store.get_run(run_id)
        state = ResearchState(
            run_id=run_id,
            request_id=run.request_id,
            status=RunStatus.RUNNING,
            canonical_entity_id=run.canonical_entity_id,
            complexity=run.complexity or EnterpriseComplexity.UNKNOWN,
        )
        review_reasons: list[str] = []
        products = store.list(run_id, "product")
        if products:
            review_reasons.append(
                "product detection is not run by SyntheticKernelExecutor; product "
                f"dashboard skipped despite {len(products)} product records"
            )
        detection = ProductDetection(
            has_physical_products=False,
            product_confidence=1.0,
            product_count=0,
            qualifying_product_ids=[],
            dashboard_decision=ProductDashboardDecision.SKIP_PRODUCT_DASHBOARD,
            reason="SyntheticKernelExecutor does not run product detection",
        )
        final_state, manifest = Phase2Runner(store).finalize_evidence(
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
        review_reasons.extend(f"{finding.code}: {finding.message}" for finding in audit.findings)
        status_by_result = {
            "published": ArtifactStatus.PUBLISHED,
            "skipped": ArtifactStatus.SKIPPED,
            "failed": ArtifactStatus.FAILED,
        }
        validation_status = final_state.validation_status or ValidationStatus.PASS
        return ExecutionOutcome(
            validation_status=validation_status,
            confidence=self._mean_claim_confidence(store, run_id),
            risk_level=self._risk_for(validation_status),
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

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def _mean_claim_confidence(store: EvidenceStore, run_id: str) -> float | None:
        return mean_claim_confidence(store, run_id)

    @staticmethod
    def _risk_for(status: ValidationStatus) -> RiskLevel:
        return risk_for(status)
