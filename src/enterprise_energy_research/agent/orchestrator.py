"""Research orchestrator agent (§3/§21/§29).

One single orchestrator (§66): the LLM understands, plans, judges, recovers and
synthesizes; deterministic skills execute, evidence is ingested into the
unified store, and code enforces budgets, round accounting, approval gates and
structured output. No multi-agent conversation exists.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

import threading

from pydantic import Field

from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.gateway.base import ModelGateway

from .evaluator import GoalEvaluator
from .goal_planner import GoalPlanner
from .mission_parser import MissionParser
from .mission_store import MissionStore
from .models import (
    AgentCostRecord,
    AgentStrictModel,
    ApprovalStatus,
    CrossDomainFinding,
    FailureClass,
    GoalClass,
    GoalEvaluation,
    GoalStatus,
    MissionApproval,
    MissionStatus,
    PriorityLevel,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
    RoutingDecision,
    SkillName,
    SkillRunResult,
    SubjectType,
)
from .policies import AgentPolicies
from .recovery import RecoveryLedger, RecoveryPlanner, auditable_limitation
from .router import ResearchSkillRouter
from .state import AgentPhase, AgentState
from .synthesis import CrossDomainSynthesisEngine
from .tools.base import ResearchSkillPort


class AgentOutcome(AgentStrictModel):
    mission: ResearchMission
    goals: list[ResearchGoal] = []
    routing: list[RoutingDecision] = []
    skill_results: list[SkillRunResult] = []
    evaluations: list[GoalEvaluation] = []
    recovery_ledger: dict[str, int] = {}
    auditable_limitations: list[dict[str, Any]] = []
    synthesis_findings: list[CrossDomainFinding] = []
    cost_records: list[AgentCostRecord] = []
    phase: str = AgentPhase.PREFLIGHT.value
    status: MissionStatus = MissionStatus.PARSED
    diagnostics: list[str] = []
    metrics: dict[str, Any] = Field(default_factory=dict)


class _MissionCancelled(Exception):
    """Raised at cancellation checkpoints; finalized as MissionStatus.CANCELLED."""


ApprovalCallback = Callable[[ResearchMission, list[ResearchGoal], list[RoutingDecision]], MissionApproval]


class ResearchOrchestratorAgent:
    """Governed agentic research system: dynamic reasoning, controlled execution."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        *,
        skills: dict[SkillName, ResearchSkillPort] | None = None,
        policies: AgentPolicies | None = None,
        store: MissionStore | None = None,
        evidence_store: EvidenceStore | None = None,
        approval_cb: ApprovalCallback | None = None,
    ) -> None:
        from enterprise_energy_research.automation.observability import CountingGateway

        self.gateway = CountingGateway(gateway) if gateway is not None else None
        self.policies = policies or AgentPolicies.load()
        self.store = store or MissionStore()
        self.evidence_store = evidence_store
        self.skills: dict[SkillName, ResearchSkillPort] = skills or {}
        self.approval_cb = approval_cb
        self.parser = MissionParser(self.gateway)
        self.planner = GoalPlanner(allow_dynamic_custom_goal=self.policies.allow_dynamic_custom_goal)
        self.router = ResearchSkillRouter(self.gateway)
        self.evaluator = GoalEvaluator(self.gateway)
        self.recovery_planner = RecoveryPlanner(
            self.gateway, max_rounds_per_goal=self.policies.max_recovery_rounds_per_goal
        )
        self.synthesis_engine = CrossDomainSynthesisEngine(self.gateway)
        self._ledger = RecoveryLedger()
        # Cooperative cancellation: one event per mission. Overseas subprocess
        # runs are killed immediately by request_stop; in-process enterprise
        # work stops at the next checkpoint (skill group / recovery round).
        self._cancel_events: dict[str, threading.Event] = {}

    # -- public API ------------------------------------------------------------

    # -- cancellation ----------------------------------------------------------

    def _cancel_event(self, mission_id: str) -> threading.Event:
        event = self._cancel_events.get(mission_id)
        if event is None:
            event = threading.Event()
            self._cancel_events[mission_id] = event
        return event

    def _reset_cancel_event(self, mission_id: str) -> None:
        # A fresh event per run: a stale stop request from a previous run (or
        # from the pre-start approval phase) never poisons the next one.
        self._cancel_events[mission_id] = threading.Event()

    def _check_cancelled(self, mission_id: str) -> None:
        event = self._cancel_events.get(mission_id)
        if event is not None and event.is_set():
            raise _MissionCancelled(mission_id)

    def request_stop(self, mission_id: str) -> dict[str, Any]:
        """User stop: kill overseas subprocesses now, mark CANCELLED, and arm
        the cooperative event so in-process loops exit at the next checkpoint.
        """
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        self._cancel_event(mission_id).set()
        killed_subprocesses = 0
        for skill in self.skills.values():
            stop = getattr(skill, "stop", None)
            if callable(stop):
                try:
                    killed_subprocesses += int(stop(mission_id=mission_id) or 0)
                except Exception:  # stop must never raise into the API layer
                    continue
        if mission.status not in {
            MissionStatus.COMPLETED,
            MissionStatus.PARTIAL,
            MissionStatus.EXHAUSTED,
            MissionStatus.BLOCKED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            mission.status = MissionStatus.CANCELLED
            mission.touch()
            self.store.upsert_mission(mission)
        self.store.trace(mission_id, "stop_requested", {"killed_subprocesses": killed_subprocesses})
        return {
            "mission_id": mission_id,
            "status": mission.status.value,
            "killed_subprocesses": killed_subprocesses,
        }

    def _finalize_cancelled(self, mission_id: str) -> AgentOutcome:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        mission.status = MissionStatus.CANCELLED
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(mission_id, "cancelled", {})
        return AgentOutcome(
            mission=mission,
            status=MissionStatus.CANCELLED,
            phase=AgentPhase.EXECUTE_SKILLS.value,
            diagnostics=["用户停止：任务已取消"],
        )

    def parse_and_plan(self, raw_request: str, *, mission_id: str | None = None, track: str | None = None) -> AgentOutcome:
        """PREFLIGHT -> MISSION_PARSE -> GOAL_PLAN -> ROUTING -> APPROVAL."""
        mission = ResearchMission(mission_id=mission_id or new_sortable_id("MISSION"), raw_request=raw_request)
        state = AgentState(mission_id=mission.mission_id, raw_request=raw_request)
        state.transition(AgentPhase.MISSION_PARSE)
        parsed = self.parser.parse(raw_request)
        # Deterministic mode guardrail: an enterprise subject together with
        # market goals is a HYBRID mission, whatever the LLM labeled it.
        if parsed.market_goals and parsed.mode == ResearchMode.ENTERPRISE and parsed.primary_subject:
            parsed.mode = ResearchMode.HYBRID
            parsed.notes = f"{parsed.notes} mode upgraded to HYBRID (market goals present with enterprise subject)".strip()
        # Track hint (portal tabs): warn when the parsed mode does not fit the
        # tab the request came from. The parse itself is never overridden —
        # the user sees the mismatch and decides.
        diagnostics: list[str] = []
        if track == "enterprise" and parsed.mode == ResearchMode.MARKET:
            diagnostics.append("轨道提示：当前在企业调查板块，但需求解析为市场研究；如非有意，请切换到海外市场调研板块")
        if track == "market" and parsed.mode in {ResearchMode.ENTERPRISE, ResearchMode.HYBRID}:
            diagnostics.append("轨道提示：当前在海外市场调研板块，但需求包含企业主体研究；如非有意，请切换到企业调查板块")
        mission.mode = parsed.mode
        mission.primary_subject = parsed.primary_subject
        mission.geographies = parsed.geographies
        mission.industries = parsed.industries
        mission.products = parsed.products
        mission.time_scope = parsed.time_scope
        mission.decision_question = parsed.decision_question
        mission.audience = parsed.audience
        mission.parse_mode = parsed.parse_mode
        mission.touch()

        state.transition(AgentPhase.GOAL_PLAN)
        goals = self.planner.plan(mission, parsed)
        mission.goals = goals
        state.goal_ids = [goal.goal_id for goal in goals]
        state.active_goal_ids = list(state.goal_ids)
        state.goal_status = {goal.goal_id: goal.status for goal in goals}

        state.transition(AgentPhase.ROUTING)
        routing = self.router.route(mission, goals)
        for decision in routing:
            goal = next(goal for goal in goals if goal.goal_id == decision.goal_id)
            goal.assigned_skill = decision.assigned_skill
            goal.routing_reason = decision.routing_reason
        state.skill_assignments = {d.goal_id: d.assigned_skill for d in routing}
        mission.status = MissionStatus.ROUTED
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(mission.mission_id, "routed", {"goals": len(goals), "mode": mission.mode.value})

        if self.policies.unified_mission_approval:
            state.transition(AgentPhase.APPROVAL)
            approval = self._request_approval(mission, goals, routing)
            if approval.decision == ApprovalStatus.APPROVED:
                mission.approval_status = ApprovalStatus.APPROVED
                mission.status = MissionStatus.APPROVED
            elif approval.decision == ApprovalStatus.REJECTED:
                mission.status = MissionStatus.BLOCKED
            else:
                mission.status = MissionStatus.AWAITING_APPROVAL
            self.store.record_approval(approval)
        else:
            mission.approval_status = ApprovalStatus.APPROVED
            mission.status = MissionStatus.APPROVED
        mission.touch()
        self.store.upsert_mission(mission)

        outcome = AgentOutcome(
            mission=mission,
            goals=goals,
            routing=routing,
            phase=state.phase.value,
            status=mission.status,
            diagnostics=([parsed.notes] if parsed.notes else []) + diagnostics,
        )
        self._record_costs(outcome)
        return outcome

    def run_approved(self, mission_id: str) -> AgentOutcome:
        """EXECUTE_SKILLS -> INGEST -> GOAL_EVALUATION -> (RECOVERY)* -> SYNTHESIS."""
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        if mission.approval_status != ApprovalStatus.APPROVED:
            return AgentOutcome(
                mission=mission,
                status=MissionStatus.AWAITING_APPROVAL,
                phase=AgentPhase.APPROVAL.value,
                diagnostics=["mission not approved; the agent cannot self-approve (§27)"],
            )
        if mission.status == MissionStatus.CANCELLED:
            return AgentOutcome(
                mission=mission,
                status=MissionStatus.CANCELLED,
                phase=AgentPhase.APPROVAL.value,
                diagnostics=["任务已取消；如需重新研究请新建任务"],
            )
        self._reset_cancel_event(mission_id)
        try:
            return self._execute_mission(mission)
        except _MissionCancelled:
            return self._finalize_cancelled(mission_id)

    def _execute_mission(self, mission: ResearchMission) -> AgentOutcome:
        mission_id = mission.mission_id
        goals = list(mission.goals)
        state = AgentState(
            mission_id=mission.mission_id,
            raw_request=mission.raw_request,
            research_mode=mission.mode,
            goal_ids=[goal.goal_id for goal in goals],
            skill_assignments={goal.goal_id: goal.assigned_skill for goal in goals if goal.assigned_skill},
            active_goal_ids=[goal.goal_id for goal in goals],
            goal_status={goal.goal_id: goal.status for goal in goals},
            evidence_version=mission.evidence_version,
        )
        mission.status = MissionStatus.RUNNING
        mission.touch()
        self.store.upsert_mission(mission)

        skill_results: list[SkillRunResult] = []
        evaluations: list[GoalEvaluation] = []
        limitations: list[dict[str, Any]] = []
        evidence_by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)

        # ---- execute by skill group -------------------------------------------
        for skill_name, group in self._group_by_skill(goals).items():
            self._check_cancelled(mission_id)
            skill = self.skills.get(skill_name)
            if skill is None:
                for goal in group:
                    evaluations.append(
                        GoalEvaluation(
                            goal_id=goal.goal_id,
                            status=GoalStatus.BLOCKED,
                            evaluation_reason=f"未注册 Skill：{skill_name.value}",
                            failure_class=FailureClass.ADAPTER_FAILURE,
                        )
                    )
                continue
            state.transition(AgentPhase.EXECUTE_SKILLS)
            plan = skill.plan(mission, group)
            result = skill.execute(plan)
            skill_results.append(result)
            self.store.record_skill_run(mission.mission_id, result.model_dump(mode="json"))
            self._bind_evidence(mission, group, result, evidence_by_goal)

        state.transition(AgentPhase.INGEST)
        self._ingest_market_evidence(mission, goals, skill_results)

        # ---- evaluate + recovery loop ------------------------------------------
        state.transition(AgentPhase.GOAL_EVALUATION)
        # Parallel goal recovery (§config parallel_recovery_rounds): per-goal
        # recovery is independent; only shared-state mutations serialize on a
        # lock. Searches/LLM calls (the slow part) run concurrently.
        parallel = self.policies.parallel_recovery_rounds > 1
        lock = threading.Lock() if parallel else None

        def _run_goal(goal: ResearchGoal) -> tuple[ResearchGoal, dict[str, Any]]:
            self._check_cancelled(mission_id)
            goal_result = self._recover_until_done(
                mission, goal, evidence_by_goal.get(goal.goal_id, []),
                [r for r in skill_results if goal.goal_id in r.goal_ids],
                state, lock=lock,
            )
            return goal, goal_result

        if parallel:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=self.policies.parallel_recovery_rounds) as pool:
                completed = list(pool.map(_run_goal, goals))
        else:
            completed = [_run_goal(goal) for goal in goals]
        for goal, goal_result in completed:
            skill_results.extend(goal_result["skill_results"])
            evaluations.append(goal_result["evaluation"])
            if goal_result["limitation"] is not None:
                limitations.append(goal_result["limitation"])
            goal.recovery_rounds = self._ledger.executed_rounds(goal.goal_id)
            goal.gap_refs = [f"GAP-{goal.goal_id}-{i}" for i in range(len(goal_result["evaluation"].gaps))]
            mission.goals = self._replace_goal(mission.goals, goal)
        # §20 rebind after recovery: recovery rounds produced new claim rows;
        # bind them to goals so evidence_refs and the freeze include them.
        self._rebind_evidence_after_recovery(goals, skill_results, evidence_by_goal)
        for goal in goals:
            goal.evidence_refs = [
                str(row.get("claim_id")) for row in evidence_by_goal.get(goal.goal_id, []) if row.get("claim_id")
            ]
            mission.goals = self._replace_goal(mission.goals, goal)
        state.goal_status = {goal.goal_id: goal.status for goal in goals}

        # ---- synthesis / publication / final status (shared tail) --------------
        return self._finish_mission(
            mission, goals, skill_results, evaluations, limitations, state, evidence_by_goal,
        )

    def _finish_mission(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        skill_results: list[SkillRunResult],
        evaluations: list[GoalEvaluation],
        limitations: list[dict[str, Any]],
        state: AgentState,
        evidence_by_goal: dict[str, list[dict[str, Any]]],
        *,
        event_name: str = "completed",
    ) -> AgentOutcome:
        """SYNTHESIS -> unified publication (§37) -> final mission status.

        Shared by the first run and by deep-research repair so both paths keep
        exactly one artifact owner and identical status semantics.
        """
        # ---- synthesis -----------------------------------------------------------
        state.transition(AgentPhase.SYNTHESIS)
        findings: list[CrossDomainFinding] = []
        if mission.mode != ResearchMode.ENTERPRISE:
            enterprise_pool = self._pool_for_skill(mission, evidence_by_goal, SkillName.ENTERPRISE_RESEARCH)
            market_pool = self._pool_for_skill(mission, evidence_by_goal, SkillName.OVERSEAS_MARKET_RESEARCH)
            findings = self.synthesis_engine.synthesize(mission, goals, enterprise_pool, market_pool)

        # ---- unified publication (§37) ---------------------------------------------
        # One artifact owner, after synthesis: enterprise + market evidence are
        # merged into one freeze and published; findings ride into the bundle.
        publish_payload: dict | None = None
        enterprise_runs = [
            run for run in skill_results
            if run.skill_name == SkillName.ENTERPRISE_RESEARCH
            and run.status.value == "OK"
            and run.evidence_exports and run.evidence_exports[0].get("run_id")
        ]
        if enterprise_runs:
            skill = self.skills.get(SkillName.ENTERPRISE_RESEARCH)
            if skill is not None and hasattr(skill, "publish"):
                overseas_refs = [
                    ref for run in skill_results
                    if run.skill_name == SkillName.OVERSEAS_MARKET_RESEARCH
                    for ref in run.artifact_refs
                ]
                enterprise_run_id = enterprise_runs[0].evidence_exports[0]["run_id"]
                # Recovery rounds each produced their own run; merge them all
                # into the unified freeze (§37), never losing recovery evidence.
                recovery_run_ids = sorted({
                    str(row.get("run_id"))
                    for run in skill_results
                    if run.skill_name == SkillName.ENTERPRISE_RESEARCH
                    for row in run.evidence_exports
                    if row.get("run_id") and str(row.get("run_id")) != enterprise_run_id
                })
                publish_payload = skill.publish(
                    mission,
                    enterprise_run_id=enterprise_run_id,
                    findings=findings,
                    sub_artifact_refs=overseas_refs,
                    recovery_run_ids=recovery_run_ids,
                )
                if isinstance(publish_payload, dict) and publish_payload.get("status") == "BLOCKED":
                    self.store.trace(
                        mission.mission_id, "publication_blocked",
                        {"diagnostics": publish_payload.get("diagnostics", [])},
                    )

        # A stop requested during the final publication steps wins over the
        # freshly computed terminal status.
        self._check_cancelled(mission.mission_id)
        mission.status = self._mission_status(goals, evaluations)
        if isinstance(publish_payload, dict) and publish_payload.get("status") == "BLOCKED":
            mission.status = MissionStatus.BLOCKED
        # Surface unified artifact-plane references so the portal can link
        # Word/Excel/HTML/PPT deliverables (§37 single artifact owner).
        mission.artifact_refs = sorted(
            set(publish_payload.get("artifacts", [])) if isinstance(publish_payload, dict) else {
                ref for run in skill_results for ref in run.artifact_refs if ref
            }
        )
        # Terminal-state review reasons: publication audit findings first,
        # then every blocked goal's evaluation reason, then skill-level
        # diagnostics (research-stage saturation/adapter/extraction issues
        # ride here).  Bounded so a pathological run cannot flood the store.
        review_reasons: list[str] = []
        if isinstance(publish_payload, dict):
            review_reasons.extend(
                str(reason) for reason in (publish_payload.get("review_reasons") or [])[:8]
            )
        goal_by_id = {goal.goal_id: goal for goal in goals}
        for evaluation in evaluations:
            if evaluation.status != GoalStatus.SATISFIED and evaluation.evaluation_reason:
                goal_name = goal_by_id.get(evaluation.goal_id).goal_name if goal_by_id.get(evaluation.goal_id) else evaluation.goal_id
                review_reasons.append(
                    f"[{evaluation.status.value}] {goal_name}: {evaluation.evaluation_reason}"
                )
        for run in skill_results:
            review_reasons.extend(
                f"{run.skill_name.value}: {diagnostic}" for diagnostic in (run.diagnostics or [])[:6]
            )
        mission.review_reasons = review_reasons[:40]
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(
            mission.mission_id, event_name,
            {
                "status": mission.status.value,
                "limitations": len(limitations),
                "findings": len(findings),
                "artifact_refs": mission.artifact_refs,
                "freeze_id": publish_payload.get("freeze_id") if isinstance(publish_payload, dict) else None,
            },
        )
        outcome = AgentOutcome(
            mission=mission,
            goals=goals,
            skill_results=skill_results,
            evaluations=evaluations,
            recovery_ledger=dict(self._ledger.rounds),
            auditable_limitations=limitations,
            synthesis_findings=findings,
            phase=state.phase.value,
            status=mission.status,
        )
        from .evals import compute_agent_metrics

        outcome.metrics = compute_agent_metrics(outcome)
        self.store.trace(mission.mission_id, "metrics", outcome.metrics)
        self._record_costs(outcome)
        return outcome

    def run(self, raw_request: str, *, mission_id: str | None = None, approval: MissionApproval | None = None) -> AgentOutcome:
        """One-shot convenience: parse, plan, (approve) and execute."""
        parsed = self.parse_and_plan(raw_request, mission_id=mission_id)
        if parsed.status in {MissionStatus.AWAITING_APPROVAL} and approval is None:
            return parsed
        if approval is not None:
            self.store.record_approval(approval)
            parsed.mission.approval_status = ApprovalStatus.APPROVED
            self.store.upsert_mission(parsed.mission)
        return self.run_approved(parsed.mission.mission_id)

    def continue_mission(self, mission_id: str, additional_request: str) -> AgentOutcome:
        """Continuation mode (§12): additive goals only; core is never re-run."""
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        state = AgentState(mission_id=mission.mission_id, raw_request=additional_request)
        state.transition(AgentPhase.MISSION_PARSE)
        parsed = self.parser.parse(additional_request)
        new_goals = self.planner.plan(mission, parsed)
        new_goals = [goal for goal in new_goals if goal.goal_class.value not in {"CORE_ENTERPRISE"} or mission.mode == ResearchMode.MARKET]
        if not new_goals:
            return AgentOutcome(mission=mission, status=mission.status, phase=state.phase.value)
        scope_changed = bool(
            (set(parsed.geographies) - set(mission.geographies))
            or (parsed.mode == ResearchMode.MARKET and mission.mode == ResearchMode.ENTERPRISE)
        )
        if scope_changed:
            # §28: material scope change requires one fresh approval.
            mission.approval_status = ApprovalStatus.PENDING
            mission.status = MissionStatus.AWAITING_APPROVAL
        routing = self.router.route(mission, new_goals)
        for decision in routing:
            goal = next(goal for goal in new_goals if goal.goal_id == decision.goal_id)
            goal.assigned_skill = decision.assigned_skill
            goal.routing_reason = decision.routing_reason
        mission.goals = mission.goals + new_goals
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(mission_id, "continued", {"new_goals": len(new_goals), "scope_changed": scope_changed})
        if mission.approval_status != ApprovalStatus.APPROVED:
            return AgentOutcome(mission=mission, goals=new_goals, routing=routing, status=mission.status)
        # Targeted execution for the new goals only.
        return self._execute_subset(mission, new_goals)

    # -- goal framework editing (pre-approval) ---------------------------------

    _EDITABLE_STATUSES = {
        MissionStatus.PARSED,
        MissionStatus.PLANNED,
        MissionStatus.ROUTED,
        MissionStatus.AWAITING_APPROVAL,
    }

    def update_goals(self, mission_id: str, items: list[dict[str, Any]]) -> AgentOutcome:
        """Pre-approval goal framework editing: rename / remove / add goals.

        Desired-final-state semantics: ``items`` is the complete goal list the
        user wants; goals present in the mission but absent from ``items`` are
        removed (core enterprise goals may be removed too — the removal is
        audited in the trace and surfaced as a diagnostic warning).
        """
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        if mission.status not in self._EDITABLE_STATUSES:
            raise ValueError(f"研究框架仅能在开始研究前修改；当前状态 {mission.status.value}")
        by_id = {goal.goal_id: goal for goal in mission.goals}
        kept: list[ResearchGoal] = []
        fresh: list[ResearchGoal] = []
        for item in items:
            goal_id = str(item.get("goal_id") or "")
            name = str(item.get("goal_name") or "").strip()
            if not name:
                continue
            if goal_id and goal_id in by_id:
                goal = by_id[goal_id].model_copy(deep=True)
                if name != goal.goal_name:
                    goal.goal_name = name
                description = str(item.get("goal_description") or "").strip()
                if description and description != goal.goal_description:
                    goal.goal_description = description
                kept.append(goal)
                continue
            fresh.append(
                ResearchGoal(
                    goal_id=new_sortable_id("GOAL"),
                    goal_name=name,
                    goal_description=str(item.get("goal_description") or "").strip() or name,
                    subject_id=mission.primary_subject or "custom-subject",
                    subject_name=mission.primary_subject or "研究主体",
                    subject_type=SubjectType.CUSTOM,
                    goal_class=GoalClass.CUSTOM,
                    priority=PriorityLevel.P1,
                    required_evidence=[],
                    success_criteria=["该专项问题获得了直接相关证据"],
                )
            )
        if not kept and not fresh:
            raise ValueError("研究框架至少需要保留一个目标")
        kept_ids = {goal.goal_id for goal in kept}
        removed_core = [
            goal.goal_name for goal in mission.goals
            if goal.goal_id not in kept_ids and goal.goal_class == GoalClass.CORE_ENTERPRISE
        ]
        if fresh:
            routing = self.router.route(mission, fresh)
            for decision in routing:
                goal = next(goal for goal in fresh if goal.goal_id == decision.goal_id)
                goal.assigned_skill = decision.assigned_skill
                goal.routing_reason = decision.routing_reason
        mission.goals = kept + fresh
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(
            mission_id, "goals_edited",
            {
                "kept": len(kept),
                "added": len(fresh),
                "removed": len(by_id) - len(kept_ids),
                "removed_core": removed_core,
            },
        )
        outcome = AgentOutcome(mission=mission, goals=mission.goals, status=mission.status)
        if removed_core:
            outcome.diagnostics.append("已移除企业核心目标：" + "、".join(removed_core))
        return outcome

    # -- deep research (post-completion repair) ----------------------------------

    _DEEP_RESEARCH_ELIGIBLE = {
        MissionStatus.COMPLETED,
        MissionStatus.PARTIAL,
        MissionStatus.EXHAUSTED,
        MissionStatus.BLOCKED,
    }

    def deep_research(self, mission_id: str, additional_request: str = "") -> AgentOutcome:
        """Deep research on a finished mission: add follow-up goals from a
        natural-language request and repair every goal that is not SATISFIED.

        EXHAUSTED goals get a fresh, separately capped recovery budget
        (policies.deep_recovery_rounds) so repair capability stays bounded;
        the repaired evidence merges into one unified re-publication.
        """
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise ValueError(f"unknown mission: {mission_id}")
        if mission.status not in self._DEEP_RESEARCH_ELIGIBLE:
            raise ValueError(f"深度研究仅面向已产出成果的任务；当前状态 {mission.status.value}")
        self._reset_cancel_event(mission_id)
        mission.status = MissionStatus.RUNNING
        mission.touch()
        self.store.upsert_mission(mission)
        self.store.trace(
            mission_id, "deep_research_started",
            {"additional_request": additional_request[:500]},
        )
        try:
            return self._deep_research_run(mission, additional_request)
        except _MissionCancelled:
            return self._finalize_cancelled(mission_id)

    def _deep_research_run(self, mission: ResearchMission, additional_request: str) -> AgentOutcome:
        mission_id = mission.mission_id
        # 1) Additive follow-up goals (the core plan is never re-run, §12).
        new_goals: list[ResearchGoal] = []
        if additional_request.strip():
            parsed = self.parser.parse(additional_request)
            new_goals = self.planner.plan(mission, parsed)
            new_goals = [
                goal for goal in new_goals
                if goal.goal_class.value not in {"CORE_ENTERPRISE"} or mission.mode == ResearchMode.MARKET
            ]
            existing_names = {goal.goal_name for goal in mission.goals}
            new_goals = [goal for goal in new_goals if goal.goal_name not in existing_names]
            if new_goals:
                routing = self.router.route(mission, new_goals)
                for decision in routing:
                    goal = next(goal for goal in new_goals if goal.goal_id == decision.goal_id)
                    goal.assigned_skill = decision.assigned_skill
                    goal.routing_reason = decision.routing_reason
                mission.goals = mission.goals + new_goals
                self.store.trace(mission_id, "deep_research_goals_added", {"count": len(new_goals)})
        self._check_cancelled(mission_id)

        # 2) Rebuild full history: every persisted skill run + evidence binding.
        skill_results: list[SkillRunResult] = []
        for item in self.store.skill_runs_for(mission_id):
            try:
                skill_results.append(SkillRunResult.model_validate(item["payload"]))
            except Exception:  # a malformed historical row never blocks repair
                continue
        evidence_by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run in skill_results:
            self._bind_evidence(mission, mission.goals, run, evidence_by_goal)
        self._rebind_evidence_after_recovery(mission.goals, skill_results, evidence_by_goal)
        self._ingest_market_evidence(mission, mission.goals, skill_results)

        # 3) Execute the brand-new goals first (they have no history at all).
        for skill_name, group in self._group_by_skill(new_goals).items():
            self._check_cancelled(mission_id)
            skill = self.skills.get(skill_name)
            if skill is None:
                continue
            plan = skill.plan(mission, group)
            result = skill.execute(plan)
            skill_results.append(result)
            self.store.record_skill_run(mission_id, result.model_dump(mode="json"))
            self._bind_evidence(mission, group, result, evidence_by_goal)

        # 4) Repair every goal that is not SATISFIED. EXHAUSTED goals get a
        #    fresh budget; other goals extend from their persisted rounds.
        state = AgentState(mission_id=mission_id, raw_request=additional_request or mission.raw_request)
        state.transition(AgentPhase.GOAL_EVALUATION)
        targets: list[ResearchGoal] = []
        for goal in mission.goals:
            if goal.status == GoalStatus.SATISFIED:
                continue
            if goal.status == GoalStatus.EXHAUSTED:
                self.store.trace(
                    mission_id, "deep_research_budget_reset",
                    {
                        "goal_id": goal.goal_id,
                        "previous_rounds": goal.recovery_rounds,
                        "new_budget": self.policies.deep_recovery_rounds,
                    },
                )
                goal.recovery_rounds = 0
                goal.mark(GoalStatus.PLANNED)
            targets.append(goal)
        # Seed the in-memory ledger with persisted round counts so §24
        # accounting keeps counting from the real baseline after restarts.
        for goal in mission.goals:
            self._ledger.rounds[goal.goal_id] = max(
                self._ledger.rounds.get(goal.goal_id, 0), goal.recovery_rounds
            )
        evaluations: list[GoalEvaluation] = [
            GoalEvaluation(
                goal_id=goal.goal_id,
                status=GoalStatus.SATISFIED,
                evaluation_reason="先前研究已达标，无需修复",
            )
            for goal in mission.goals if goal.status == GoalStatus.SATISFIED
        ]
        limitations: list[dict[str, Any]] = []
        for goal in targets:
            self._check_cancelled(mission_id)
            max_rounds = goal.recovery_rounds + self.policies.deep_recovery_rounds
            goal_result = self._recover_until_done(
                mission, goal, evidence_by_goal.get(goal.goal_id, []),
                [run for run in skill_results if goal.goal_id in run.goal_ids],
                state, max_rounds=max_rounds,
            )
            skill_results.extend(goal_result["skill_results"])
            evaluations.append(goal_result["evaluation"])
            if goal_result["limitation"] is not None:
                limitations.append(goal_result["limitation"])
            goal.recovery_rounds = self._ledger.executed_rounds(goal.goal_id)
            mission.goals = self._replace_goal(mission.goals, goal)
        self._rebind_evidence_after_recovery(mission.goals, skill_results, evidence_by_goal)
        for goal in targets:
            goal.evidence_refs = [
                str(row.get("claim_id")) for row in evidence_by_goal.get(goal.goal_id, []) if row.get("claim_id")
            ]
            mission.goals = self._replace_goal(mission.goals, goal)

        goals = list(mission.goals)
        return self._finish_mission(
            mission, goals, skill_results, evaluations, limitations, state, evidence_by_goal,
            event_name="deep_research_completed",
        )

    # -- internals ---------------------------------------------------------------

    def _execute_subset(self, mission: ResearchMission, goals: list[ResearchGoal]) -> AgentOutcome:
        skill_results: list[SkillRunResult] = []
        evaluations: list[GoalEvaluation] = []
        evidence_by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for skill_name, group in self._group_by_skill(goals).items():
            skill = self.skills.get(skill_name)
            if skill is None:
                continue
            plan = skill.plan(mission, group)
            result = skill.execute(plan)
            skill_results.append(result)
            self.store.record_skill_run(mission.mission_id, result.model_dump(mode="json"))
            self._bind_evidence(mission, group, result, evidence_by_goal)
        for goal in goals:
            evaluation = self.evaluator.evaluate(goal, evidence_by_goal.get(goal.goal_id, []), skill_results)
            evaluations.append(evaluation)
            goal.status = evaluation.status
        mission.touch()
        self.store.upsert_mission(mission)
        outcome = AgentOutcome(
            mission=mission, goals=goals, skill_results=skill_results, evaluations=evaluations,
            status=mission.status,
        )
        self._record_costs(outcome)
        return outcome

    def _recover_until_done(
        self,
        mission: ResearchMission,
        goal: ResearchGoal,
        evidence: list[dict[str, Any]],
        skill_results: list[SkillRunResult],
        state: AgentState,
        *,
        lock: Any | None = None,
        max_rounds: int | None = None,
    ) -> dict[str, Any]:
        """One goal through the recovery loop with hard accounting (§21-§25).

        ``lock`` serializes shared-state mutations (iteration counter,
        ledger, store writes) when goals recover in parallel; the slow
        search/LLM work runs outside the lock. ``max_rounds`` overrides the
        production per-goal ceiling for deep-research repair passes.
        """
        ceiling = max_rounds if max_rounds is not None else self.policies.max_recovery_rounds_per_goal
        extra_runs: list[SkillRunResult] = []
        previous_attempts = [
            attempt for run in skill_results for attempt in run.attempts
        ]
        evaluation = self.evaluator.evaluate(goal, evidence, skill_results)
        if evaluation.status in {GoalStatus.SATISFIED, GoalStatus.BLOCKED}:
            goal.mark(evaluation.status)
            return {"evaluation": evaluation, "skill_results": [], "limitation": None}

        failed_round = 0
        uncounted_streak = 0
        while goal.recovery_rounds < ceiling:
            self._check_cancelled(mission.mission_id)
            if lock is not None:
                lock.acquire()
            try:
                if state.agent_iteration >= self.policies.max_agent_iterations:
                    evaluation = GoalEvaluation(
                        goal_id=goal.goal_id,
                        status=GoalStatus.EXHAUSTED,
                        evaluation_reason="Agent 迭代预算耗尽",
                        failure_class=FailureClass.BUDGET_EXHAUSTED,
                    )
                    goal.mark(GoalStatus.EXHAUSTED)
                    return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": auditable_limitation(goal, evaluation)}
                state.agent_iteration += 1
                state.transition(AgentPhase.RECOVERY)
            finally:
                if lock is not None:
                    lock.release()
            recovery = self.recovery_planner.plan(
                goal, evaluation,
                failed_round=failed_round,
                previous_attempts=previous_attempts,
                evidence_sample=evidence,
                max_rounds=ceiling,
            )
            if recovery.failure_class == FailureClass.RECOVERY_EXHAUSTED:
                goal.mark(GoalStatus.EXHAUSTED)
                return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": auditable_limitation(goal, evaluation)}
            skill = self.skills.get(goal.assigned_skill)
            if skill is None:
                evaluation = GoalEvaluation(
                    goal_id=goal.goal_id,
                    status=GoalStatus.BLOCKED,
                    evaluation_reason=f"补救时 Skill 未注册：{goal.assigned_skill}",
                    failure_class=FailureClass.ADAPTER_FAILURE,
                )
                goal.mark(GoalStatus.BLOCKED)
                return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": None}
            plan = skill.plan(mission, [goal])
            run = skill.recover(plan, recovery)
            extra_runs.append(run)
            if lock is not None:
                lock.acquire()
            try:
                self.store.record_skill_run(mission.mission_id, run.model_dump(mode="json"))
                self.store.trace(mission.mission_id, "recovery_round", {
                    "goal_id": goal.goal_id,
                    "round": failed_round + 1,
                    "queries": recovery.new_queries,
                    "counted": False,
                })
            finally:
                if lock is not None:
                    lock.release()
            if lock is not None:
                lock.acquire()
            try:
                counted = self._ledger.record(goal.goal_id, run)
            finally:
                if lock is not None:
                    lock.release()
            if not counted:
                # §24: adapter failure / identical queries consume no round.
                previous_attempts.extend(run.attempts)
                uncounted_streak += 1
                if uncounted_streak >= 3:
                    # Adapter keeps failing without executing anything: stop
                    # honestly instead of spinning (§24 executed-round rule).
                    evaluation = GoalEvaluation(
                        goal_id=goal.goal_id,
                        status=GoalStatus.BLOCKED,
                        unmet_criteria=list(goal.success_criteria),
                        evidence_count=len(evidence),
                        required_evidence_missing=self.evaluator._missing_required(goal, evidence),
                        evaluation_reason="连续 3 轮补救均未实际执行（适配器失败或重复 query），停止补救",
                        failure_class=FailureClass.ADAPTER_FAILURE,
                    )
                    goal.mark(GoalStatus.BLOCKED)
                    return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": None}
                continue
            uncounted_streak = 0
            goal.recovery_rounds = self._ledger.executed_rounds(goal.goal_id)
            previous_attempts.extend(run.attempts)
            failed_round = goal.recovery_rounds
            new_evidence = [
                row for row in run.evidence_exports
                if str(row.get("goal_id")) == goal.goal_id or self._row_matches_subject(goal, row)
            ]
            evidence = evidence + new_evidence
            evaluation = self.evaluator.evaluate(goal, evidence, skill_results + extra_runs)
            if evaluation.status in {GoalStatus.SATISFIED, GoalStatus.BLOCKED}:
                goal.mark(evaluation.status)
                return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": None}

        goal.mark(GoalStatus.EXHAUSTED)
        return {"evaluation": evaluation, "skill_results": extra_runs, "limitation": auditable_limitation(goal, evaluation)}

    def _bind_evidence(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        result: SkillRunResult,
        evidence_by_goal: dict[str, list[dict[str, Any]]],
    ) -> None:
        """§20: evidence joins a goal only via explicit binding.

        Primary binding is the explicit ``goal_id``. Enterprise claims expose
        ``field_name`` from the extraction contract; when no goal_id is
        present, a row binds deterministically to every goal whose
        ``required_evidence`` contains that field (the plan's own contract),
        so the evaluator sees real evidence instead of treating it as absent.
        """
        goal_ids = {goal.goal_id for goal in goals}
        required_by_goal = {goal.goal_id: set(goal.required_evidence) for goal in goals}
        for row in result.evidence_exports:
            goal_id = str(row.get("goal_id") or "")
            if goal_id in goal_ids:
                evidence_by_goal[goal_id].append(row)
                continue
            # Contract binding: rows carry goal_families (inverse extraction
            # contract) and/or field_name; both are deterministic contracts
            # from the plan, never a fuzzy "looks relevant" judgment.
            families = [str(f) for f in (row.get("goal_families") or [])]
            field = str(row.get("field_name") or "")
            for candidate, fields in required_by_goal.items():
                if any(family in fields for family in families) or (field and field in fields):
                    evidence_by_goal[candidate].append(row)
                    break

    def _rebind_evidence_after_recovery(
        self,
        goals: list[ResearchGoal],
        skill_results: list[SkillRunResult],
        evidence_by_goal: dict[str, list[dict[str, Any]]],
    ) -> None:
        """§20: bind evidence rows produced by recovery rounds to goals.

        Recovery rounds return their own claim rows (carrying goal_families /
        field_name); without this rebind, recovery evidence would be invisible
        to goal.evidence_refs and to the unified freeze.
        """
        required_by_goal = {goal.goal_id: set(goal.required_evidence) for goal in goals}
        for run in skill_results:
            if run.skill_name != SkillName.ENTERPRISE_RESEARCH:
                continue
            for row in run.evidence_exports:
                families = [str(f) for f in (row.get("goal_families") or [])]
                field = str(row.get("field_name") or "")
                for candidate, fields in required_by_goal.items():
                    if any(family in fields for family in families) or (field and field in fields):
                        key = str(row.get("claim_id") or id(row))
                        existing = {str(r.get("claim_id") or id(r)) for r in evidence_by_goal.get(candidate, [])}
                        if key not in existing:
                            evidence_by_goal.setdefault(candidate, []).append(row)
                        break

    def _row_matches_subject(self, goal: ResearchGoal, row: dict[str, Any]) -> bool:
        # Recovery evidence lands on the recovering goal when it carries the
        # goal's subject name; market rows carry geography in scope.
        subject = str(row.get("subject_name") or row.get("geography") or "")
        return bool(subject) and (subject in goal.subject_name or subject in str(goal.scope.get("geographies") or []))

    def _ingest_market_evidence(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        skill_results: list[SkillRunResult],
    ) -> None:
        if self.evidence_store is None or not self.policies.unified_store:
            return
        from .market_evidence import MarketEvidenceImporter

        importer = MarketEvidenceImporter(self.evidence_store, self.policies)
        for run in skill_results:
            if run.skill_name != SkillName.OVERSEAS_MARKET_RESEARCH or not run.evidence_exports:
                continue
            report = importer.import_rows(
                mission=mission,
                rows=run.evidence_exports,
                goals=[goal for goal in goals if goal.goal_id in run.goal_ids],
                originating_skill=run.skill_name.value,
            )
            self.store.trace(mission.mission_id, "evidence_ingested", report.model_dump())

    def _request_approval(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        routing: list[RoutingDecision],
    ) -> MissionApproval:
        if self.approval_cb is not None:
            return self.approval_cb(mission, goals, routing)
        return MissionApproval(
            approval_id=new_sortable_id("APPROVAL"),
            mission_id=mission.mission_id,
            decision=ApprovalStatus.PENDING,
            scope_summary=f"{mission.mode.value} / {len(goals)} goals / approval pending human decision",
        )

    def _group_by_skill(self, goals: list[ResearchGoal]) -> dict[SkillName, list[ResearchGoal]]:
        groups: dict[SkillName, list[ResearchGoal]] = defaultdict(list)
        for goal in goals:
            if goal.assigned_skill is not None:
                groups[goal.assigned_skill].append(goal)
        return groups

    @staticmethod
    def _pool_for_skill(
        mission: ResearchMission,
        evidence_by_goal: dict[str, list[dict[str, Any]]],
        skill: SkillName,
    ) -> list[dict[str, Any]]:
        pool: list[dict[str, Any]] = []
        seen: set[str] = set()
        for goal in mission.goals:
            if goal.assigned_skill != skill:
                continue
            for row in evidence_by_goal.get(goal.goal_id, []):
                key = str(row.get("claim_id") or id(row))
                if key not in seen:
                    seen.add(key)
                    pool.append(row)
        return pool

    @staticmethod
    def _replace_goal(goals: list[ResearchGoal], updated: ResearchGoal) -> list[ResearchGoal]:
        return [updated if goal.goal_id == updated.goal_id else goal for goal in goals]

    @staticmethod
    def _mission_status(goals: list[ResearchGoal], evaluations: list[GoalEvaluation]) -> MissionStatus:
        by_id = {evaluation.goal_id: evaluation for evaluation in evaluations}
        planned = lambda goal_id: GoalEvaluation(goal_id=goal_id, status=GoalStatus.PLANNED, evaluation_reason="未评估")
        statuses = [by_id.get(goal.goal_id, planned(goal.goal_id)).status for goal in goals]
        if any(status == GoalStatus.BLOCKED for status in statuses):
            return MissionStatus.BLOCKED if all(s in {GoalStatus.BLOCKED, GoalStatus.PLANNED} for s in statuses) else MissionStatus.PARTIAL
        if all(status == GoalStatus.SATISFIED for status in statuses):
            return MissionStatus.COMPLETED
        if all(status in {GoalStatus.EXHAUSTED, GoalStatus.SATISFIED} for status in statuses):
            return MissionStatus.EXHAUSTED
        return MissionStatus.PARTIAL

    def _record_costs(self, outcome: AgentOutcome) -> None:
        if self.gateway is None or not hasattr(self.gateway, "usage"):
            return
        usage = self.gateway.usage.snapshot()
        outcome.cost_records.append(
            AgentCostRecord(
                stage=outcome.phase or "agent",
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
        )


__all__ = ["ResearchOrchestratorAgent", "AgentOutcome"]
