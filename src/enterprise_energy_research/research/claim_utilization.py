"""HighValueClaimUtilization (P1-3).

CRITICAL/HIGH verified claims must land in synthesis, Word/HTML body, formal
tables, charts or the appendix. The utilization audit writes
``unused_high_value_claims.json`` and targets >= 90% utilization — searching
100 important facts and publishing 5 is a pipeline failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim

from .contracts import GOAL_CONTRACTS
from .field_registry import CanonicalFieldRegistry

# Field families that carry decision weight when verified.
HIGH_VALUE_FAMILIES = {"IDENTITY", "OWNERSHIP", "BUSINESS", "FINANCIAL", "FACTORY", "CAPACITY", "PRODUCT", "ENERGY", "PROJECT"}

# Canonical fields whose goal-family contract is CRITICAL: verified claims
# for these fields are high value even when their field family is unlisted.
CRITICAL_CANONICAL_FIELDS = {
    CanonicalFieldRegistry.canonicalize(field)
    for contract in GOAL_CONTRACTS.values() if contract.criticality == "critical"
    for field in contract.expected_fields
}


def high_value_claim_ids(claims: list[Claim]) -> list[str]:
    result: list[str] = []
    for claim in claims:
        if claim.verification_status != VerificationStatus.VERIFIED:
            continue
        family = CanonicalFieldRegistry.family(claim.field_name)
        if family in HIGH_VALUE_FAMILIES or CanonicalFieldRegistry.canonicalize(claim.field_name) in CRITICAL_CANONICAL_FIELDS:
            result.append(claim.claim_id)
    return sorted(set(result))


class HighValueClaimUtilization(BaseModel):
    high_value_claim_count: int = Field(default=0, ge=0)
    utilized_claim_ids: list[str] = Field(default_factory=list)
    unused_high_value_claims: list[str] = Field(default_factory=list)
    utilization_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    target: float = 0.90

    def meets_target(self) -> bool:
        return self.utilization_ratio >= self.target

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "unused_high_value_claims.json"
        path.write_text(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


class ClaimUtilizationAuditor:
    def audit(
        self,
        claims: list[Claim],
        *,
        synthesis_claim_ids: list[str],
        artifact_claim_ids: list[str],
        table_claim_ids: list[str] | None = None,
        chart_claim_ids: list[str] | None = None,
    ) -> HighValueClaimUtilization:
        used = set(synthesis_claim_ids) | set(artifact_claim_ids)
        used |= set(table_claim_ids or []) | set(chart_claim_ids or [])
        high_value = high_value_claim_ids(claims)
        utilized = sorted(used & set(high_value))
        unused = sorted(set(high_value) - used)
        ratio = len(utilized) / len(high_value) if high_value else 1.0
        return HighValueClaimUtilization(
            high_value_claim_count=len(high_value),
            utilized_claim_ids=utilized,
            unused_high_value_claims=unused,
            utilization_ratio=round(ratio, 4),
        )
