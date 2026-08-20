from __future__ import annotations

from collections import defaultdict

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, Entity, EnterpriseEdge


class EntityMapper:
    def apply_evidence(
        self,
        entities: list[Entity],
        edges: list[EnterpriseEdge],
        claims: list[Claim],
    ) -> tuple[list[Entity], list[EnterpriseEdge]]:
        claims_by_entity: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            claims_by_entity[claim.entity_id].append(claim)
        updated_entities: list[Entity] = []
        for entity in entities:
            supporting = [claim.claim_id for claim in claims_by_entity.get(entity.entity_id, []) if claim.verification_status == VerificationStatus.VERIFIED]
            status = VerificationStatus.VERIFIED if any(
                claim.field_name in {"canonical_company_name", "registered_name"}
                for claim in claims_by_entity.get(entity.entity_id, [])
                if claim.verification_status == VerificationStatus.VERIFIED
            ) else VerificationStatus.UNVERIFIED
            updated_entities.append(entity.model_copy(update={
                "verification_status": status,
                "supporting_claim_ids": supporting,
            }))
        updated_edges: list[EnterpriseEdge] = []
        for edge in edges:
            linked_claims = [claim for claim in claims if claim.claim_id in edge.claim_ids]
            verified = bool(linked_claims) and all(claim.verification_status == VerificationStatus.VERIFIED for claim in linked_claims)
            updated_edges.append(edge.model_copy(update={
                "verification_status": VerificationStatus.VERIFIED if verified else VerificationStatus.UNVERIFIED,
                "confidence": 0.9 if verified else edge.confidence,
            }))
        return updated_entities, updated_edges

