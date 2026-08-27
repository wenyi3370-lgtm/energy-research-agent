"""Agent evaluation metrics (§59).

Computed at mission completion from the outcome; persisted in the mission
store trace and aggregated by scripts/run_agent_metrics.py. Valid Evidence
Yield counts verified claims, never raw search result counts (§61).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import GoalClass, GoalStatus, ResearchMode, SkillName

if TYPE_CHECKING:
    from .orchestrator import AgentOutcome


def compute_agent_metrics(outcome: "AgentOutcome") -> dict[str, Any]:
    goals = outcome.goals
    total = len(goals) or 1
    satisfied = sum(1 for goal in goals if goal.status == GoalStatus.SATISFIED)
    core = [goal for goal in goals if goal.goal_class == GoalClass.CORE_ENTERPRISE]
    custom = [goal for goal in goals if goal.goal_class in {GoalClass.CUSTOM, GoalClass.CUSTOM_ENTERPRISE}]
    recovered = [goal for goal in goals if goal.recovery_rounds > 0]
    recovered_ok = [goal for goal in recovered if goal.status == GoalStatus.SATISFIED]

    total_claims = 0
    verified_claims = 0
    for run in outcome.skill_results:
        coverage = run.coverage_metrics or {}
        total_claims += int(coverage.get("evidence_count") or 0)
        verified_claims += int(coverage.get("verified_claim_count") or 0)

    claim_ids = {
        ref for goal in goals for ref in goal.evidence_refs
    }
    findings = outcome.synthesis_findings
    traceable = sum(
        1 for finding in findings
        if all(
            ref in claim_ids
            for ref in (
                list(finding.enterprise_evidence_refs)
                + list(finding.market_evidence_refs)
                + list(finding.counter_evidence_refs)
            )
        )
    ) if findings else 0

    tokens = sum(
        record.input_tokens + record.output_tokens for record in outcome.cost_records
    )
    cost = sum(
        record.input_tokens * 0.0 for record in outcome.cost_records
    )  # USD table lives in the gateway; token totals are recorded here.

    metrics: dict[str, Any] = {
        "goal_total": len(goals),
        "goal_completion_rate": round(satisfied / total, 4),
        "core_goal_count": len(core),
        "core_goal_coverage": round(
            sum(1 for goal in core if goal.status == GoalStatus.SATISFIED) / len(core), 4
        ) if core else None,
        "dynamic_goal_count": len(custom),
        "dynamic_goal_completion_rate": round(
            sum(1 for goal in custom if goal.status == GoalStatus.SATISFIED) / len(custom), 4
        ) if custom else None,
        "recovery_goal_count": len(recovered),
        "recovery_success_rate": round(len(recovered_ok) / len(recovered), 4) if recovered else None,
        "valid_evidence_yield": round(verified_claims / total_claims, 4) if total_claims else 0.0,
        "evidence_total": total_claims,
        "evidence_verified": verified_claims,
        "synthesis_finding_count": len(findings),
        "citation_traceability": round(traceable / len(findings), 4) if findings else None,
        "routing_llm_rate": 1.0 if outcome.mission.parse_mode == "llm" else 0.0,
        "agent_token_usage": tokens,
        "mode": outcome.mission.mode.value,
        "status": outcome.status.value,
    }
    if outcome.mission.mode == ResearchMode.HYBRID:
        metrics["cross_skill_conflict_rate"] = round(
            len(outcome.auditable_limitations) / max(1, len(outcome.goals)), 4
        )
    return metrics
