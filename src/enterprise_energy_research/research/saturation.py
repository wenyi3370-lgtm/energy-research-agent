from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field


RoundName = Literal["R1", "R2", "R3"]
SaturationStatus = Literal["SATURATED", "PARTIAL", "BLOCKED"]


class CollectionAttemptSummary(BaseModel):
    """Auditable summary for one query batch within one collection goal."""

    goal_family: str
    round: RoundName
    batch_id: str
    attempted_queries: int = Field(ge=0)
    unique_sources: int = Field(ge=0)
    source_types: set[str] = Field(default_factory=set)
    fulltext_captures: int = Field(default=0, ge=0)
    material_records: int = Field(default=0, ge=0)
    critical_claim_count: int = Field(default=0, ge=0)
    independently_verified_critical_claim_count: int = Field(default=0, ge=0)
    authoritative_critical_claim_count: int = Field(default=0, ge=0)
    inspected_sources: int = Field(default=0, ge=0)
    new_high_priority_ids: list[str] = Field(default_factory=list)
    raw_capture_refs: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)

    @property
    def marginal_high_priority_yield(self) -> float:
        denominator = max(self.inspected_sources, self.unique_sources, 1)
        return len(set(self.new_high_priority_ids)) / denominator


class SaturationAssessment(BaseModel):
    status: SaturationStatus
    marginal_high_priority_yield: float = Field(ge=0.0)
    missing_rounds: dict[str, list[RoundName]] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)


class DataSaturationValidator:
    """Apply the three-round, quantity-floor and marginal-yield stop contract."""

    def __init__(self, policy: dict) -> None:
        self.policy = policy

    def assess(
        self,
        attempts: list[CollectionAttemptSummary],
        *,
        critical_gap_ids: list[str] | None = None,
        unexpanded_high_priority_ids: list[str] | None = None,
        budget_exhausted: bool = False,
        scoped_goal_families: list[str] | None = None,
    ) -> SaturationAssessment:
        critical_gap_ids = critical_gap_ids or []
        unexpanded_high_priority_ids = unexpanded_high_priority_ids or []
        findings: list[str] = []
        expected_goals = set(scoped_goal_families or self.policy.get("goal_families", []))
        grouped: dict[str, dict[str, list[CollectionAttemptSummary]]] = defaultdict(lambda: defaultdict(list))
        for attempt in attempts:
            grouped[attempt.goal_family][attempt.round].append(attempt)

        required_rounds = list(self.policy["saturation"]["required_rounds"])
        missing_rounds: dict[str, list[RoundName]] = {}
        for goal in sorted(expected_goals):
            missing = [round_name for round_name in required_rounds if not grouped[goal].get(round_name)]
            if missing:
                missing_rounds[goal] = missing

        if missing_rounds:
            findings.append("Every scoped goal must complete R1 coverage, R2 depth and R3 triangulation")

        for goal, rounds in grouped.items():
            for round_name, round_policy in self.policy["rounds"].items():
                rows = rounds.get(round_name, [])
                if not rows:
                    continue
                attempted = sum(row.attempted_queries for row in rows)
                unique_sources = max((row.unique_sources for row in rows), default=0)
                source_types = set().union(*(row.source_types for row in rows))
                fulltext = sum(row.fulltext_captures for row in rows)
                records = sum(row.material_records for row in rows)
                critical_claims = sum(row.critical_claim_count for row in rows)
                verified_critical_claims = sum(row.independently_verified_critical_claim_count for row in rows)
                authoritative_critical_claims = sum(row.authoritative_critical_claim_count for row in rows)
                if attempted < int(round_policy.get("min_queries_per_goal", 0)):
                    findings.append(f"{goal}/{round_name} query floor not met")
                if unique_sources < int(round_policy.get("min_unique_sources_per_goal", 0)):
                    findings.append(f"{goal}/{round_name} source floor not met")
                if len(source_types) < int(round_policy.get("min_source_types_per_goal", 0)):
                    findings.append(f"{goal}/{round_name} source-type floor not met")
                if fulltext < int(round_policy.get("min_fulltext_captures_per_goal", 0)):
                    findings.append(f"{goal}/{round_name} full-text floor not met")
                if records < int(round_policy.get("min_material_records_per_goal", 0)):
                    findings.append(f"{goal}/{round_name} material-record floor not met")
                satisfied_critical_claims = verified_critical_claims + authoritative_critical_claims
                if round_name == "R3" and satisfied_critical_claims < critical_claims:
                    findings.append(f"{goal}/R3 has critical claims without independent triangulation")
                if self.policy["saturation"].get("require_raw_capture_per_attempt"):
                    for row in rows:
                        if row.attempted_queries and not row.raw_capture_refs:
                            findings.append(f"{goal}/{round_name}/{row.batch_id} has no raw capture")

        required_zero = int(self.policy["saturation"]["minimum_no_new_high_priority_batches"])
        recent = attempts[-required_zero:]
        marginal_yield = (
            sum(len(set(row.new_high_priority_ids)) for row in recent)
            / max(sum(max(row.inspected_sources, row.unique_sources) for row in recent), 1)
        )
        zero_new_batches = 0
        for row in reversed(attempts):
            if row.new_high_priority_ids:
                break
            zero_new_batches += 1
        if zero_new_batches < required_zero:
            findings.append(f"Need {required_zero} consecutive batches with no new high-priority discoveries")
        if marginal_yield > float(self.policy["saturation"]["maximum_marginal_high_priority_yield"]):
            findings.append("Marginal high-priority discovery yield remains above the saturation threshold")
        if critical_gap_ids:
            findings.append("Unresolved critical gaps: " + ", ".join(critical_gap_ids))
        if unexpanded_high_priority_ids:
            findings.append("Unexpanded high-priority discoveries: " + ", ".join(unexpanded_high_priority_ids))

        if not findings:
            status: SaturationStatus = "SATURATED"
        elif budget_exhausted and (critical_gap_ids or missing_rounds):
            status = "BLOCKED"
            findings.append("Budget exhaustion does not convert incomplete research into saturation")
        else:
            status = "PARTIAL"
        return SaturationAssessment(
            status=status,
            marginal_high_priority_yield=marginal_yield,
            missing_rounds=missing_rounds,
            findings=findings,
        )
