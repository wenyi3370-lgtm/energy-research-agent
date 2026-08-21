from __future__ import annotations

from pathlib import Path

from enterprise_energy_research.analysis.energy import EnergyAnalyst
from enterprise_energy_research.analysis.solutions import SolutionEngine
from enterprise_energy_research.domain.enums import RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import DataGap, ExtractedEvidenceBatch, ProductDetection
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.classifier import EnterpriseComplexityClassifier
from enterprise_energy_research.research.entity_mapper import EntityMapper
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver, ImageArchiveResult
from enterprise_energy_research.research.identity_evidence import IdentityEvidenceSynthesizer
from enterprise_energy_research.research.ingestor import EvidenceIngestor
from enterprise_energy_research.research.normalizer import EvidenceNormalizer
from enterprise_energy_research.research.product_detector import ProductDetector
from enterprise_energy_research.research.resolver import CompanyResolver

from .runner import Phase2Runner
from .state import ResearchState


class Phase3Runner:
    """Run deterministic Phase 3 processing on adapter-extracted evidence batches."""

    def __init__(
        self,
        store: EvidenceStore,
        enterprise_rules: dict,
        image_archiver: ImageAssetArchiver | None = None,
    ) -> None:
        self.store = store
        self.enterprise_rules = enterprise_rules
        self.image_archiver = image_archiver or ImageAssetArchiver()

    def process_batches(
        self,
        state: ResearchState,
        raw_company_name: str,
        batches: list[ExtractedEvidenceBatch],
        *,
        output_dir: Path,
    ) -> tuple[ResearchState, object | None, ProductDetection | None]:
        state, product_detection = self.process_batches_until_ingest(
            state, raw_company_name, batches, output_dir=output_dir
        )
        if state.status in (RunStatus.HUMAN_REVIEW, RunStatus.BLOCKED):
            return state, None, product_detection
        final_state, manifest = Phase2Runner(self.store).finalize_evidence(
            state, output_dir=output_dir, product_detection=product_detection,
        )
        return final_state, manifest, product_detection

    def process_batches_until_ingest(
        self,
        state: ResearchState,
        raw_company_name: str,
        batches: list[ExtractedEvidenceBatch],
        *,
        output_dir: Path,
    ) -> tuple[ResearchState, ProductDetection | None]:
        """Run all Phase 3 processing up to EVIDENCE_INGEST; never freezes.

        Split out so the automation service can validate before freeze. Identity
        ambiguity and claim conflicts are resolved deterministically by source
        credibility; the selected and rejected alternatives remain auditable.
        ``product_detection`` is returned so the freeze step can reuse it.
        """
        state.transition("COMPANY_RESOLVER", status=RunStatus.RUNNING)
        resolution = CompanyResolver().resolve(raw_company_name, batches)
        if resolution.status != "RESOLVED":
            state.blocking_findings.append(resolution.rationale)
            state.transition(
                "HUMAN_REVIEW" if resolution.status == "HUMAN_REVIEW" else "BLOCKED",
                status=RunStatus.HUMAN_REVIEW if resolution.status == "HUMAN_REVIEW" else RunStatus.BLOCKED,
            )
            return state, None

        official_domains = {
            candidate.official_website.host.lower().removeprefix("www.")
            for candidate in resolution.candidates if candidate.official_website
        }
        state.transition("EVIDENCE_NORMALIZER")
        evidence = EvidenceNormalizer().normalize(batches, official_domains=official_domains)
        # P0-1: official-page identity evidence becomes provenance-bound
        # identity Claims BEFORE validation, so a resolved company is never
        # left UNVERIFIED when its own page states its identity.
        evidence.claims.extend(
            IdentityEvidenceSynthesizer().synthesize(
                resolution, batches, evidence.entities, evidence.sources,
            )
        )
        selected_candidate = next(item for item in resolution.candidates if item.candidate_id == resolution.selected_candidate_id)
        selected_entity = next((item for item in evidence.entities if item.canonical_name == selected_candidate.canonical_name), None)
        if not selected_entity:
            state.blocking_findings.append("Resolved candidate did not map to a normalized entity")
            state.transition("BLOCKED", status=RunStatus.BLOCKED)
            return state, None
        state.canonical_entity_id = selected_entity.entity_id

        state.transition("EVIDENCE_VALIDATOR")
        evidence.claims, evidence.conflicts = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, evidence.edges = EntityMapper().apply_evidence(evidence.entities, evidence.edges, evidence.claims)
        image_validator = ImageValidator()
        evidence.images = image_validator.validate(evidence.images, evidence.entities, evidence.sources)
        archive_result = ImageArchiveResult(images=evidence.images)
        if any(batch.extraction_method != "recorded_fixture" for batch in batches):
            archive_result = self.image_archiver.archive(evidence.images, output_dir)
            evidence.images = archive_result.images
            # P0: pixel-level visual verification runs AFTER archiving — a
            # vision verifier needs the local bytes, never context alone.
            evidence.images = image_validator.visual_verify(evidence.images)
        evidence.products, product_detection = ProductDetector().detect(
            evidence.products,
            evidence.images,
            evidence.sources,
            evidence.claims,
            require_archived_images=any(batch.extraction_method != "recorded_fixture" for batch in batches),
        )

        state.transition("ENTERPRISE_CLASSIFIER")
        selected_entity = next(item for item in evidence.entities if item.entity_id == state.canonical_entity_id)
        complexity = EnterpriseComplexityClassifier(self.enterprise_rules).classify(
            selected_entity, evidence.entities, evidence.factories, evidence.edges, evidence.products,
        )
        state.complexity = complexity.complexity

        state.transition("ENERGY_ANALYST")
        evidence.energy_profiles, evidence.gaps = EnergyAnalyst().analyze(evidence.entities, evidence.factories, evidence.claims)
        if evidence.products and product_detection.coverage_status != "COMPLETE":
            evidence.gaps.append(DataGap(
                gap_id=new_sortable_id("GAP"),
                entity_id=state.canonical_entity_id,
                field_name="product_catalog_coverage",
                importance="major",
                reason="missing",
                next_action=(
                    "使用 AnySearch 发现官方产品中心/子公司产品域，并由 Kimi WebBridge 逐页枚举产品族、"
                    "型号、参数、应用与图片；记录 product_catalog_scope 后重新验收"
                ),
            ))
        if evidence.products and product_detection.parameterized_product_count == 0:
            evidence.gaps.append(DataGap(
                gap_id=new_sortable_id("GAP"),
                entity_id=state.canonical_entity_id,
                field_name="product_model_parameter_coverage",
                importance="major",
                reason="missing",
                next_action="逐个官方产品页采集型号、参数名、数值、单位、适用场景及对应 source_id",
            ))
        if archive_result.failed_image_ids:
            evidence.gaps.append(DataGap(
                gap_id=new_sortable_id("GAP"),
                entity_id=state.canonical_entity_id,
                field_name="product_image_asset_coverage",
                importance="major",
                reason="missing",
                next_action=(
                    f"重新归档 {len(archive_result.failed_image_ids)} 张已核验产品图片并核对哈希、格式、尺寸；"
                    "正式产品看板要求展示产品的本地图片覆盖率为100%"
                ),
            ))
        state.active_gaps = [gap.gap_id for gap in evidence.gaps]

        state.transition("SOLUTION_ENGINE")
        evidence.solutions = SolutionEngine().generate(evidence.entities, evidence.energy_profiles, evidence.claims)

        state.transition("EVIDENCE_INGEST")
        EvidenceIngestor(self.store).ingest(state.run_id, state.evidence_version, evidence)
        run = self.store.get_run(state.run_id)
        run.canonical_entity_id = state.canonical_entity_id
        run.complexity = state.complexity
        self.store.replace_run_manifest(run)

        return state, product_detection
