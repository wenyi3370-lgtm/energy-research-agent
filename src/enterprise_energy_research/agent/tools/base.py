"""Skill port contracts (§15).

Every capability pack is reached through ResearchSkillPort and must return a
structured SkillRunResult — free text is never a valid skill return.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import RecoveryPlan, ResearchMission, ResearchGoal, SkillPlan, SkillRunResult


@runtime_checkable
class ResearchSkillPort(Protocol):
    def plan(self, mission: ResearchMission, goals: list[ResearchGoal]) -> SkillPlan: ...

    def execute(self, plan: SkillPlan) -> SkillRunResult: ...

    def recover(self, plan: SkillPlan, recovery_plan: RecoveryPlan) -> SkillRunResult: ...

    def inspect(self, run_id: str) -> SkillRunResult: ...


def blocked_result(
    skill_name: str,
    *,
    plan: SkillPlan | None = None,
    failure_class: str = "ADAPTER_FAILURE",
    diagnostics: list[str] | None = None,
) -> SkillRunResult:
    """Fail-closed result used when a skill cannot run (repo convention)."""
    from enterprise_energy_research.domain.ids import new_sortable_id

    from ..models import FailureClass, SkillName, SkillRunStatus

    return SkillRunResult(
        skill_run_id=new_sortable_id("SKILLRUN"),
        skill_name=SkillName(skill_name),
        goal_ids=list(plan.goal_ids) if plan else [],
        status=SkillRunStatus.UNAVAILABLE,
        failure_class=FailureClass(failure_class),
        diagnostics=diagnostics or ["skill unavailable; fail-closed"],
    )
