"""Review Gate policy engine (Phase 5).

The human-in-the-loop gate is a deterministic rules engine, not an agent
judgment: ten declarative trigger rules (``RV-01`` .. ``RV-10``) decide
whether an executed run needs human review before the freeze is allowed.
Rules live in ``config/review_policy.yaml``; each rule can be enabled or
tuned per deployment without code changes. The service combines the
executor's own flag (e.g. validation passed with warnings) with the
policy's enforced reasons, so the gate is always visible and auditable.

Design notes:

- rules consume only the structured ``ExecutionOutcome`` + the original
  ``ResearchRequest``; they never read natural-language state.
- the freeze is not reachable while the gate is open: the service only
  calls ``freeze_and_publish`` after REVIEW_REQUIRED -> APPROVED.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from ..domain.enums import ValidationStatus
from ..domain.models import StrictModel
from ..settings import load_yaml
from .contracts import ResearchRequest
from .enums import Priority, ResearchType, RiskLevel
from .executor import ExecutionOutcome

REVIEW_RULE_CODES = ("RV-01", "RV-02", "RV-03", "RV-04", "RV-05",
                     "RV-06", "RV-07", "RV-08", "RV-09", "RV-10")


class ReviewGateResult(StrictModel):
    """Outcome of applying the review policy to one executed run."""

    review_required: bool = False
    reasons: list[str] = Field(default_factory=list)

    def with_reason(self, code: str, message: str) -> None:
        self.review_required = True
        self.reasons.append(f"{code}: {message}")


class ReviewPolicy:
    """Declarative ten-rule engine; only ``enabled`` rules are enforced.

    Defaults mirror the V1 gate (RV-01: warnings -> review) so enabling
    the engine never loosens the baseline contract.
    """

    DEFAULTS: dict[str, dict[str, Any]] = {
        "RV-01_pass_with_warnings": {
            "enabled": True,
            "reason": "validation passed with warnings; a human must confirm",
        },
        "RV-02_low_confidence": {
            "enabled": False,
            "min_confidence": 0.70,
            "reason": "model confidence {confidence} is below {min_confidence}",
        },
        "RV-03_high_risk": {
            "enabled": False,
            "min_risk": "HIGH",
            "reason": "risk level is {risk_level}",
        },
        "RV-04_conflicts": {
            "enabled": False,
            "reason": "{conflict_count} conflicting claims need adjudication",
        },
        "RV-05_gaps": {
            "enabled": False,
            "reason": "{gap_count} open evidence gaps need acceptance",
        },
        "RV-06_low_evidence": {
            "enabled": False,
            "min_evidence": 10,
            "reason": "only {evidence_count} evidence records; below {min_evidence}",
        },
        "RV-07_executor_reasons": {
            "enabled": False,
            "reason": "executor reported: {first_reason}",
        },
        "RV-08_market_scope": {
            "enabled": False,
            "reason": "market-level scope without a named company",
        },
        "RV-09_sensitive_types": {
            "enabled": False,
            "research_types": ["policy_regulation", "channel_research"],
            "reason": "research type {research_type} is policy-sensitive",
        },
        "RV-10_urgent_priority": {
            "enabled": False,
            "reason": "priority {priority} requires senior sign-off",
        },
    }

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None) -> None:
        merged = {code: dict(self.DEFAULTS[code]) for code in self.DEFAULTS}
        for code, config in (rules or {}).items():
            if code in merged:
                merged[code].update(config)
            else:
                merged[code] = dict(config)
        self.rules = merged

    def evaluate(
        self, outcome: ExecutionOutcome, request: ResearchRequest
    ) -> ReviewGateResult:
        """Apply the enabled rules; order matters for stable reason output."""
        result = ReviewGateResult()
        rv = self.rules

        if rv.get("RV-01_pass_with_warnings", {}).get("enabled") and (
            outcome.validation_status == ValidationStatus.PASS_WITH_WARNINGS
        ):
            result.with_reason("RV-01", rv["RV-01_pass_with_warnings"]["reason"])

        if rv.get("RV-02_low_confidence", {}).get("enabled") and outcome.confidence is not None:
            floor = float(rv["RV-02_low_confidence"].get("min_confidence", 0.70))
            if outcome.confidence < floor:
                result.with_reason(
                    "RV-02",
                    rv["RV-02_low_confidence"]["reason"].format(
                        confidence=outcome.confidence, min_confidence=floor
                    ),
                )

        if rv.get("RV-03_high_risk", {}).get("enabled") and outcome.risk_level is not None:
            floor = RiskLevel(rv["RV-03_high_risk"].get("min_risk", "HIGH"))
            if _severity_rank(outcome.risk_level) >= _severity_rank(floor):
                result.with_reason(
                    "RV-03",
                    rv["RV-03_high_risk"]["reason"].format(risk_level=outcome.risk_level.value),
                )

        if rv.get("RV-04_conflicts", {}).get("enabled") and outcome.conflict_count > 0:
            result.with_reason(
                "RV-04",
                rv["RV-04_conflicts"]["reason"].format(conflict_count=outcome.conflict_count),
            )

        if rv.get("RV-05_gaps", {}).get("enabled") and outcome.gap_count > 0:
            result.with_reason(
                "RV-05", rv["RV-05_gaps"]["reason"].format(gap_count=outcome.gap_count)
            )

        if rv.get("RV-06_low_evidence", {}).get("enabled"):
            floor = int(rv["RV-06_low_evidence"].get("min_evidence", 10))
            if outcome.evidence_count < floor:
                result.with_reason(
                    "RV-06",
                    rv["RV-06_low_evidence"]["reason"].format(
                        evidence_count=outcome.evidence_count, min_evidence=floor
                    ),
                )

        if rv.get("RV-07_executor_reasons", {}).get("enabled") and outcome.review_reasons:
            result.with_reason(
                "RV-07",
                rv["RV-07_executor_reasons"]["reason"].format(
                    first_reason=outcome.review_reasons[0]
                ),
            )

        if rv.get("RV-08_market_scope", {}).get("enabled") and not request.company:
            result.with_reason("RV-08", rv["RV-08_market_scope"]["reason"])

        if rv.get("RV-09_sensitive_types", {}).get("enabled"):
            sensitive = rv["RV-09_sensitive_types"].get("research_types", [])
            if str(request.research_type) in sensitive:
                result.with_reason(
                    "RV-09",
                    rv["RV-09_sensitive_types"]["reason"].format(
                        research_type=request.research_type.value
                    ),
                )

        if rv.get("RV-10_urgent_priority", {}).get("enabled") and (
            request.priority in (Priority.HIGH, Priority.URGENT)
        ):
            result.with_reason(
                "RV-10",
                rv["RV-10_urgent_priority"]["reason"].format(priority=request.priority.value),
            )
        return result

    @staticmethod
    def load(path: Path) -> "ReviewPolicy":
        """Load rules from ``config/review_policy.yaml`` (missing file -> defaults)."""
        try:
            payload = load_yaml(path)
        except FileNotFoundError:
            return ReviewPolicy()
        return ReviewPolicy(payload.get("rules", {}))


def _severity_rank(level: RiskLevel) -> int:
    return {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}[level]
