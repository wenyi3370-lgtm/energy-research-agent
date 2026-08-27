"""Enterprise research skill port.

Wraps the mature enterprise research kernel (ResearchPlanner/SearchExecutor/
evidence/validation/artifacts). The wrapper adds the port contract; it does not
re-implement any research logic (§70: extend, never duplicate).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from enterprise_energy_research.domain.ids import new_sortable_id

from ..models import (
    FailureClass,
    RecoveryPlan,
    ResearchGoal,
    ResearchMission,
    SkillAttempt,
    SkillName,
    SkillPlan,
    SkillRunResult,
    SkillRunStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EnterpriseResearchSkill:
    """ENTERPRISE_RESEARCH tool. ``executor`` is the production research callable.

    The executor receives a dict contract::

        {
          "mission_id": str,
          "canonical_subject": str,
          "requirements": [str, ...],      # additive user goals (never shrink core)
          "recovery_queries": [str, ...],  # set on recover()
          "recovery_round": int,
        }

    and returns a dict with at least ``run_id`` plus optional ``evidence_path``,
    ``counts`` and ``artifacts``. When no executor is injected the skill is
    fail-closed (UNAVAILABLE), matching the repository adapter convention.
    """

    def __init__(
        self,
        executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        publish_cb: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.executor = executor
        self.publish_cb = publish_cb

    def publish(
        self,
        mission: ResearchMission,
        *,
        enterprise_run_id: str,
        findings: list,
        sub_artifact_refs: list[str],
        recovery_run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Unified publication (§37): merge -> freeze -> artifacts -> QA.

        Called by the orchestrator after synthesis; the agent's findings and
        the overseas sub-artifacts ride into the frozen bundle/manifest.
        """
        if self.publish_cb is None:
            return {"status": "BLOCKED", "diagnostics": ["publish callback not configured"], "artifacts": []}
        try:
            return self.publish_cb({
                "mission_id": mission.mission_id,
                "enterprise_run_id": enterprise_run_id,
                "findings": findings,
                "sub_artifact_refs": list(sub_artifact_refs),
                "recovery_run_ids": list(recovery_run_ids or []),
            })
        except Exception as exc:
            return {"status": "BLOCKED", "diagnostics": [f"publish failed: {type(exc).__name__}: {exc}"[:400]], "artifacts": []}

    def plan(self, mission: ResearchMission, goals: list[ResearchGoal]) -> SkillPlan:
        custom_requirements = [
            f"{goal.goal_name}：{goal.goal_description}"
            for goal in goals
            if goal.goal_class.value in {"CUSTOM_ENTERPRISE", "CUSTOM"}
        ]
        parameters = {
            "canonical_subject": mission.primary_subject or mission.raw_request,
            "requirements": custom_requirements,
            "recovery_queries": [],
            "recovery_round": 0,
        }
        return SkillPlan(
            skill_plan_id=new_sortable_id("ENTPLAN"),
            skill_name=SkillName.ENTERPRISE_RESEARCH,
            mission_id=mission.mission_id,
            goal_ids=[goal.goal_id for goal in goals],
            parameters=parameters,
        )

    def execute(self, plan: SkillPlan) -> SkillRunResult:
        started = _utc_now()
        if self.executor is None:
            return self._unavailable(plan, started, "enterprise executor not configured")
        try:
            payload = self.executor(dict(plan.parameters, mission_id=plan.mission_id))
        except Exception as exc:  # executor boundary is normalized, never leaks
            return self._unavailable(plan, started, f"enterprise executor raised: {type(exc).__name__}: {exc}"[:500])
        attempt = SkillAttempt(
            attempt_id=new_sortable_id("ENTATT"),
            attempt_no=int(payload.get("recovery_round", 0)) + 1,
            executed=True,
            strategy_summary=f"enterprise research round {payload.get('recovery_round', 0)}",
            queries=[str(query) for query in payload.get("queries", [])],
            completed_at=_utc_now(),
        )
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=list(plan.goal_ids),
            status=SkillRunStatus(payload.get("status", "OK")),
            # §20: expose the run's claim rows (not the summary payload) so the
            # orchestrator can bind evidence to goals deterministically.
            evidence_exports=list(payload.get("evidence_rows") or []),
            source_refs=[str(ref) for ref in payload.get("source_refs", [])],
            artifact_refs=[str(ref) for ref in payload.get("artifact_refs", [])],
            coverage_metrics=payload.get("coverage_metrics", {}),
            quality_metrics=payload.get("quality_metrics", {}),
            gaps=list(payload.get("gaps", [])),
            attempts=[attempt],
            started_at=started,
            completed_at=_utc_now(),
        )

    def recover(self, plan: SkillPlan, recovery_plan: RecoveryPlan) -> SkillRunResult:
        started = _utc_now()
        if self.executor is None:
            return self._unavailable(plan, started, "enterprise executor not configured")
        try:
            payload = self.executor(
                {
                    **plan.parameters,
                    "mission_id": plan.mission_id,
                    "recovery_queries": list(recovery_plan.new_queries),
                    "recovery_round": recovery_plan.failed_round + 1,
                }
            )
        except Exception as exc:
            return self._unavailable(plan, started, f"enterprise executor raised: {type(exc).__name__}: {exc}"[:500])
        attempt = SkillAttempt(
            attempt_id=new_sortable_id("ENTATT"),
            attempt_no=recovery_plan.failed_round + 1,
            executed=True,
            strategy_summary=recovery_plan.new_strategy,
            queries=list(recovery_plan.new_queries),
            source_categories=list(recovery_plan.new_source_categories),
            completed_at=_utc_now(),
        )
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=list(recovery_plan.goal_ids),
            status=SkillRunStatus(payload.get("status", "PARTIAL")),
            evidence_exports=list(payload.get("evidence_rows") or []),
            coverage_metrics=payload.get("coverage_metrics", {}),
            quality_metrics=payload.get("quality_metrics", {}),
            gaps=list(payload.get("gaps", [])),
            attempts=[attempt],
            started_at=started,
            completed_at=_utc_now(),
        )

    def inspect(self, run_id: str) -> SkillRunResult:
        return SkillRunResult(
            skill_run_id=run_id,
            skill_name=SkillName.ENTERPRISE_RESEARCH,
            status=SkillRunStatus.UNAVAILABLE,
            failure_class=FailureClass.ADAPTER_FAILURE,
            diagnostics=["inspect requires the production runner handle; pass the run through execute()"],
        )

    @staticmethod
    def _unavailable(plan: SkillPlan, started: datetime, reason: str) -> SkillRunResult:
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=list(plan.goal_ids),
            status=SkillRunStatus.UNAVAILABLE,
            failure_class=FailureClass.ADAPTER_FAILURE,
            diagnostics=[reason],
            started_at=started,
            completed_at=_utc_now(),
        )
