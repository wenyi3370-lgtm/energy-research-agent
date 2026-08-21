from __future__ import annotations

from collections import defaultdict

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, Entity, EnterpriseEdge

from .contracts import IDENTITY_FIELDS


def _normalize_name(value: str) -> str:
    return "".join(value.lower().split())


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
            entity_claims = claims_by_entity.get(entity.entity_id, [])
            verified_claims = [claim for claim in entity_claims if claim.verification_status == VerificationStatus.VERIFIED]
            # VERIFIED requires a verified identity Claim (canonical_company_name
            # or registered_name) whose value actually names this entity — a
            # verified financial claim alone must never verify an entity.
            identity = [
                claim for claim in verified_claims
                if claim.field_name in {"canonical_company_name", "registered_name"}
                and self._claims_this_entity(claim, entity)
            ]
            status = VerificationStatus.VERIFIED if identity else VerificationStatus.UNVERIFIED
            updated_entities.append(entity.model_copy(update={
                "verification_status": status,
                "supporting_claim_ids": [claim.claim_id for claim in verified_claims],
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

    @staticmethod
    def _claims_this_entity(claim: Claim, entity: Entity) -> bool:
        value = _normalize_name(str(claim.value or ""))
        names = {_normalize_name(entity.canonical_name), _normalize_name(entity.registered_name or "")}
        names.update(_normalize_name(alias) for alias in entity.aliases)
        names.discard("")
        return bool(value and any(value in name or name in value for name in names))


def identity_fields_covered(entity: Entity, claims: list[Claim]) -> list[str]:
    """Return identity fields with a non-empty supporting Claim for this entity."""
    covered: list[str] = []
    for claim in claims:
        if claim.entity_id == entity.entity_id and claim.field_name in IDENTITY_FIELDS and claim.value not in (None, "", []):
            covered.append(claim.field_name)
    return list(dict.fromkeys(covered))
