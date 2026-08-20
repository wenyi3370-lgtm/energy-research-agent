from __future__ import annotations

from enterprise_energy_research.domain.enums import (
    ArtifactStatus,
    ArtifactType,
    ProductDashboardDecision,
    VerificationStatus,
)
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    ArtifactBinding,
    ArtifactManifest,
    FrozenResearchBundle,
    ProductDetection,
)


class ArtifactPlanner:
    def plan(
        self,
        bundle: FrozenResearchBundle,
        product_detection: ProductDetection | None = None,
    ) -> ArtifactManifest:
        claim_ids = [item.claim_id for item in bundle.claims if item.verification_status == VerificationStatus.VERIFIED]
        image_ids = [item.image_id for item in bundle.images if item.verification_status == VerificationStatus.VERIFIED]
        bindings = [
            self._binding(ArtifactType.EXCEL, claim_ids, image_ids),
            self._binding(ArtifactType.WORD, claim_ids, image_ids),
            self._binding(ArtifactType.ENTERPRISE_HTML, claim_ids, image_ids),
        ]
        if product_detection and product_detection.dashboard_decision == ProductDashboardDecision.GENERATE:
            bindings.append(self._binding(ArtifactType.PRODUCT_HTML, claim_ids, image_ids))
        else:
            bindings.append(ArtifactBinding(
                artifact_id=new_sortable_id("ART"),
                type=ArtifactType.PRODUCT_HTML,
                status=ArtifactStatus.SKIPPED,
                skip_reason=(product_detection.reason if product_detection else "Product detection has not qualified physical products"),
            ))
        return ArtifactManifest(
            artifact_manifest_id=new_sortable_id("AM"),
            run_id=bundle.freeze.run_id,
            freeze_id=bundle.freeze.freeze_id,
            artifacts=bindings,
        )

    @staticmethod
    def _binding(artifact_type: ArtifactType, claim_ids: list[str], image_ids: list[str]) -> ArtifactBinding:
        return ArtifactBinding(
            artifact_id=new_sortable_id("ART"),
            type=artifact_type,
            claim_ids=list(claim_ids),
            image_ids=list(image_ids),
        )

