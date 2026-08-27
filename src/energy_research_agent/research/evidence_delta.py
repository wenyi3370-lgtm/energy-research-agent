"""EvidenceSnapshot / EvidenceDelta (P1-2).

Saturation is judged on REAL deltas between round snapshots — never on a
default-empty "new_claims=[]" summary. When a delta cannot be computed the
result is PARTIAL/BLOCKED, never a silent PASS.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import Claim, ConflictGroup, DataGap, Entity, Factory, ImageEvidence, Product


class EvidenceSnapshot(BaseModel):
    label: str
    claims: list[str] = Field(default_factory=list)
    verified_claims: list[str] = Field(default_factory=list)
    high_priority_claims: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    factories: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @classmethod
    def capture(
        cls,
        label: str,
        *,
        claims: list[Claim] | None = None,
        entities: list[Entity] | None = None,
        factories: list[Factory] | None = None,
        products: list[Product] | None = None,
        images: list[ImageEvidence] | None = None,
        conflicts: list[ConflictGroup] | None = None,
        gaps: list[DataGap] | None = None,
        high_priority_fields: set[str] | None = None,
    ) -> "EvidenceSnapshot":
        claims = claims or []
        high_priority_fields = high_priority_fields or set()
        verified = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
        parameters = [
            f"{product.product_id}:{parameter.name}"
            for product in (products or []) for parameter in product.parameters
        ]
        return cls(
            label=label,
            claims=[claim.claim_id for claim in claims],
            verified_claims=[claim.claim_id for claim in verified],
            high_priority_claims=[
                claim.claim_id for claim in verified if claim.field_name in high_priority_fields
            ],
            entities=[entity.entity_id for entity in (entities or [])],
            factories=[factory.factory_id for factory in (factories or [])],
            products=[product.product_id for product in (products or [])],
            models=[product.product_id for product in (products or []) if product.model],
            parameters=parameters,
            images=[image.image_id for image in (images or [])],
            conflicts=[conflict.conflict_group_id for conflict in (conflicts or [])],
            gaps=[gap.gap_id for gap in (gaps or [])],
        )


class EvidenceDelta(BaseModel):
    before: EvidenceSnapshot
    after: EvidenceSnapshot
    new_claims: list[str] = Field(default_factory=list)
    new_verified_claims: list[str] = Field(default_factory=list)
    new_high_priority_claims: list[str] = Field(default_factory=list)
    new_entities: list[str] = Field(default_factory=list)
    new_factories: list[str] = Field(default_factory=list)
    new_products: list[str] = Field(default_factory=list)
    new_models: list[str] = Field(default_factory=list)
    new_parameters: list[str] = Field(default_factory=list)
    new_images: list[str] = Field(default_factory=list)
    new_conflicts: list[str] = Field(default_factory=list)
    new_gaps: list[str] = Field(default_factory=list)
    resolved_gaps: list[str] = Field(default_factory=list)
    resolved_conflicts: list[str] = Field(default_factory=list)
    computable: bool = True

    @classmethod
    def compute(cls, before: EvidenceSnapshot, after: EvidenceSnapshot) -> "EvidenceDelta":
        return cls(
            before=before, after=after,
            new_claims=sorted(set(after.claims) - set(before.claims)),
            new_verified_claims=sorted(set(after.verified_claims) - set(before.verified_claims)),
            new_high_priority_claims=sorted(set(after.high_priority_claims) - set(before.high_priority_claims)),
            new_entities=sorted(set(after.entities) - set(before.entities)),
            new_factories=sorted(set(after.factories) - set(before.factories)),
            new_products=sorted(set(after.products) - set(before.products)),
            new_models=sorted(set(after.models) - set(before.models)),
            new_parameters=sorted(set(after.parameters) - set(before.parameters)),
            new_images=sorted(set(after.images) - set(before.images)),
            new_conflicts=sorted(set(after.conflicts) - set(before.conflicts)),
            new_gaps=sorted(set(after.gaps) - set(before.gaps)),
            resolved_gaps=sorted(set(before.gaps) - set(after.gaps)),
            resolved_conflicts=sorted(set(before.conflicts) - set(after.conflicts)),
        )

    @property
    def marginal_yield(self) -> float:
        return len(self.new_high_priority_claims) + len(self.new_verified_claims)


class DeltaSaturation(BaseModel):
    """Saturation status derived strictly from an EvidenceDelta (P1-2)."""

    status: Literal["SATURATED", "SATURATION_PARTIAL", "SATURATION_BLOCKED"]
    reasoning: list[str] = Field(default_factory=list)

    @classmethod
    def assess(cls, deltas: list[EvidenceDelta], *, minimum_quiet_rounds: int = 2) -> "DeltaSaturation":
        if not deltas:
            return cls(status="SATURATION_BLOCKED", reasoning=["no evidence delta was computed"])
        computable = [delta for delta in deltas if delta.computable]
        if len(computable) < len(deltas):
            return cls(status="SATURATION_BLOCKED", reasoning=["one or more deltas could not be computed"])
        quiet = [delta for delta in computable if delta.marginal_yield == 0]
        if len(quiet) >= minimum_quiet_rounds:
            return cls(status="SATURATED", reasoning=[
                f"{len(quiet)} consecutive rounds with zero marginal high-priority yield"
            ])
        return cls(status="SATURATION_PARTIAL", reasoning=[
            f"only {len(quiet)} quiet round(s); need {minimum_quiet_rounds}"
        ])
