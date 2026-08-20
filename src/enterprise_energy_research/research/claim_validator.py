from __future__ import annotations

from collections import defaultdict
from typing import Any

from enterprise_energy_research.domain.enums import SourceLevel, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, ConflictGroup, Source
from enterprise_energy_research.evidence.store import canonical_json


CORE_FIELDS = {
    "canonical_company_name", "registered_name", "parent_company", "actual_controller",
    "revenue", "profit", "capacity", "employee_count", "investment",
    "product_model", "product_parameter", "energy_consumption", "export", "certification",
}


class ClaimValidator:
    def validate(self, claims: list[Claim], sources: list[Source]) -> tuple[list[Claim], list[ConflictGroup]]:
        sources_by_id = {source.source_id: source for source in sources}
        groups: dict[tuple[Any, ...], list[Claim]] = defaultdict(list)
        for claim in claims:
            groups[(claim.entity_id, claim.field_name, claim.as_of_date, claim.scope)].append(claim)

        conflicts: list[ConflictGroup] = []
        conflicting_ids: dict[str, str] = {}
        for key, group in groups.items():
            values = {canonical_json({"value": claim.value, "unit": claim.unit, "currency": claim.currency}) for claim in group}
            if len(values) <= 1:
                continue
            conflict_id = new_sortable_id("CONFLICT")
            for claim in group:
                conflicting_ids[claim.claim_id] = conflict_id
            conflicts.append(ConflictGroup(
                conflict_group_id=conflict_id,
                entity_id=key[0],
                field_name=key[1],
                claim_ids=[claim.claim_id for claim in group],
                analysis={"same_period": key[2] is not None, "same_scope": key[3] is not None, "distinct_values": len(values)},
                rationale="Different values remain for the same entity/field/date/scope; no silent selection was made.",
                status="BLOCKING" if key[1] in CORE_FIELDS else "OPEN",
            ))

        corroboration: dict[tuple[Any, ...], set[str]] = defaultdict(set)
        for claim in claims:
            source = sources_by_id[claim.source_id]
            if source.source_level == SourceLevel.SOURCE_B:
                origin = (source.publisher or source.source_domain).lower()
                corroboration[(claim.entity_id, claim.field_name, canonical_json(claim.value), claim.as_of_date, claim.scope)].add(origin)

        validated: list[Claim] = []
        for claim in claims:
            source = sources_by_id[claim.source_id]
            if claim.claim_id in conflicting_ids:
                status = VerificationStatus.CONFLICTING
                confidence = 0.35
                conflict_id = conflicting_ids[claim.claim_id]
            elif source.source_level == SourceLevel.SOURCE_A:
                status = VerificationStatus.VERIFIED
                confidence = 0.95
                conflict_id = None
            elif source.source_level == SourceLevel.SOURCE_B and len(corroboration[(
                claim.entity_id, claim.field_name, canonical_json(claim.value), claim.as_of_date, claim.scope,
            )]) >= 2:
                status = VerificationStatus.VERIFIED
                confidence = 0.80
                conflict_id = None
            else:
                status = VerificationStatus.UNVERIFIED
                confidence = 0.40 if source.source_level == SourceLevel.SOURCE_B else 0.20
                conflict_id = None
            validated.append(claim.model_copy(update={
                "verification_status": status,
                "confidence": confidence,
                "conflict_group_id": conflict_id,
            }))
        return validated, conflicts

