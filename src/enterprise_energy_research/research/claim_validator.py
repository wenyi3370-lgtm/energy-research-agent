from __future__ import annotations

from collections import defaultdict
from typing import Any

from enterprise_energy_research.domain.enums import ConflictStatus, SourceLevel, VerificationStatus
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
            if claim.value in (None, "", []):
                # No value, no fact to conflict over: these claims never join
                # a conflict group (avoids conflict/claim status drift).
                continue
            groups[(claim.entity_id, claim.field_name, claim.as_of_date, claim.scope)].append(claim)

        conflicts: list[ConflictGroup] = []
        conflicting_ids: dict[str, str] = {}
        selected_ids: set[str] = set()
        for key, group in groups.items():
            value_groups: dict[str, list[Claim]] = defaultdict(list)
            for claim in group:
                value_groups[canonical_json({
                    "value": claim.value, "unit": claim.unit, "currency": claim.currency,
                })].append(claim)
            if len(value_groups) <= 1:
                continue
            conflict_id = new_sortable_id("CONFLICT")
            for claim in group:
                conflicting_ids[claim.claim_id] = conflict_id
            ranked_values = sorted(
                value_groups.items(),
                key=lambda item: self._value_rank(item[1], sources_by_id),
                reverse=True,
            )
            selected_value, winners = ranked_values[0]
            winners = sorted(
                winners,
                key=lambda claim: self._claim_rank(claim, sources_by_id[claim.source_id]),
                reverse=True,
            )
            selected_ids.update(claim.claim_id for claim in winners)
            primary = winners[0]
            primary_source = sources_by_id[primary.source_id]
            # A conflicting value only auto-resolves when the winner is an
            # authoritative A-level source or is corroborated by >=2
            # independent origins. Otherwise the conflict stays OPEN and
            # drives an R3 triangulation round (P1-1).
            winner_origins = {
                (sources_by_id[claim.source_id].publisher or sources_by_id[claim.source_id].source_domain).casefold()
                for claim in winners
            }
            triangulated = primary_source.source_level == SourceLevel.SOURCE_A or len(winner_origins) >= 2
            conflicts.append(ConflictGroup(
                conflict_group_id=conflict_id,
                entity_id=key[0],
                field_name=key[1],
                claim_ids=[claim.claim_id for claim in group],
                analysis={
                    "same_period": key[2] is not None,
                    "same_scope": key[3] is not None,
                    "distinct_values": len(value_groups),
                    "automatic_adjudication": triangulated,
                    "selected_value": selected_value,
                    "selected_source_level": primary_source.source_level.value,
                    "selected_source_domain": primary_source.source_domain,
                    "independent_origins": len(winner_origins),
                    "ranking_order": [value for value, _claims in ranked_values],
                },
                resolution="select_authoritative" if triangulated else "unresolved",
                selected_claim_ids=[claim.claim_id for claim in winners],
                rationale=(
                    "Automatic credibility adjudication selected the best-supported value using "
                    "source authority, independent-origin support, recency, qualifier precision and "
                    f"deterministic tie-breaking; primary claim={primary.claim_id}. "
                    "All alternatives remain attached for audit."
                ),
                status=ConflictStatus.RESOLVED if triangulated else ConflictStatus.OPEN,
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
            # A claim without a value carries no fact to verify.
            if claim.value in (None, "", []):
                validated.append(claim.model_copy(update={
                    "verification_status": VerificationStatus.UNVERIFIED,
                    "confidence": 0.0,
                    "conflict_group_id": None,
                }))
                continue
            if claim.claim_id in selected_ids:
                status = (
                    VerificationStatus.VERIFIED
                    if source.source_level in {SourceLevel.SOURCE_A, SourceLevel.SOURCE_B}
                    else VerificationStatus.UNVERIFIED
                )
                confidence = self._verified_confidence(source.source_level)
                conflict_id = conflicting_ids[claim.claim_id]
            elif claim.claim_id in conflicting_ids:
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

    @staticmethod
    def _verified_confidence(level: SourceLevel) -> float:
        return {
            SourceLevel.SOURCE_A: 0.95,
            SourceLevel.SOURCE_B: 0.80,
            SourceLevel.SOURCE_C: 0.55,
            SourceLevel.SOURCE_D: 0.35,
        }[level]

    @classmethod
    def _claim_rank(cls, claim: Claim, source: Source) -> tuple[int, int, int, int, int, str]:
        level = {
            SourceLevel.SOURCE_A: 4,
            SourceLevel.SOURCE_B: 3,
            SourceLevel.SOURCE_C: 2,
            SourceLevel.SOURCE_D: 1,
        }[source.source_level]
        reason = source.grading_reason.casefold()
        authority = (
            3 if any(token in reason or token in source.source_domain for token in (
                "government", "sasac", "regulator", "filing", ".gov.cn",
            ))
            else 2 if any(token in reason for token in (
                "annual_report", "official_announcement", "official_manual",
            ))
            else 1 if source.source_level == SourceLevel.SOURCE_A else 0
        )
        qualifier = {
            "exact": 5, "at_least": 4, "at_most": 4,
            "approximately": 3, "range": 2, "unknown": 1,
        }[claim.qualifier]
        publication = source.publication_date.toordinal() if source.publication_date else 0
        context = min(9999, len(claim.context_text) + len(claim.raw_text))
        return level, authority, publication, qualifier, context, claim.claim_id

    @classmethod
    def _value_rank(
        cls, claims: list[Claim], sources_by_id: dict[str, Source]
    ) -> tuple[int, int, int, int, int, str]:
        claim_ranks = [cls._claim_rank(claim, sources_by_id[claim.source_id]) for claim in claims]
        origins = {
            (sources_by_id[claim.source_id].publisher or sources_by_id[claim.source_id].source_domain).casefold()
            for claim in claims
        }
        best = max(claim_ranks)
        authority_sum = sum(rank[0] * 10 + rank[1] for rank in claim_ranks)
        return best[0], len(origins), authority_sum, best[2], best[3], best[5]
