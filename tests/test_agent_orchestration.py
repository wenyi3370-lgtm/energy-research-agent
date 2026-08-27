"""Agent-layer tests: TEST-AGENT-01 through TEST-AGENT-15 + hybrid golden (§57/§58).

All offline. Fakes follow the repository convention (no network, no live
credentials): a scripted gateway returns structured outputs, fake skills
record their calls and return scripted evidence. Live capability is proven by
scripts/run_live_acceptance.py, never by mocks pretending to be live (§78-25).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from enterprise_energy_research.agent.evaluator import _LLMEvaluation
from enterprise_energy_research.agent.mission_parser import CustomGoalSpec, MarketGoalSpec, MissionParseResult
from enterprise_energy_research.agent.models import (
    ApprovalStatus,
    CrossDomainFinding,
    FailureClass,
    GoalClass,
    GoalEvaluation,
    GoalStatus,
    MissionApproval,
    MissionStatus,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
    RoutingDecision,
    SkillAttempt,
    SkillName,
    SkillPlan,
    SkillRunResult,
    SkillRunStatus,
    SubjectType,
)
from enterprise_energy_research.agent.policies import AgentPolicies
from enterprise_energy_research.agent.recovery import RecoveryLedger
from enterprise_energy_research.agent.router import RoutingBatch
from enterprise_energy_research.agent.synthesis import _LLMSynthesis
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.gateway.base import GatewayError

_SENTINEL = object()


def _goal(goal_id: str, subject_id: str) -> ResearchGoal:
    return ResearchGoal(
        goal_id=goal_id,
        goal_name="竞争格局",
        goal_description="竞争分析",
        subject_id=subject_id,
        subject_name=subject_id,
        subject_type=SubjectType.CUSTOM,
        goal_class=GoalClass.COMPETITION,
        required_evidence=[],
        success_criteria=[],
    )


# ---------------------------------------------------------------- fakes ------

class FakeGateway:
    """Scripted structured-output gateway. `handler(request) -> model|None`."""

    def __init__(self, handler=None):
        self.handler = handler or (lambda request: None)
        self.calls: list[Any] = []

    def complete(self, request):
        raise GatewayError("not used")

    def structured(self, request):
        self.calls.append(request)
        result = self.handler(request)
        if result is None:
            raise GatewayError("no scripted result")
        return result

    def health(self):
        return {"ok": True}


def satisfied_rows(goal: ResearchGoal, *, verified: bool = True) -> list[dict[str, Any]]:
    """Evidence rows covering every required field of one goal."""
    rows = []
    for field in goal.required_evidence or ["evidence"]:
        rows.append({
            "goal_id": goal.goal_id,
            "claim_id": new_sortable_id("CLAIM"),
            "field_name": field,
            "raw_value": "value",
            "verification_status": "VERIFIED" if verified else "UNVERIFIED",
            "subject_role": "SUBJECT",
        })
    return rows


class FakeSkill:
    """Records calls; auto-generates satisfying evidence from a goal registry."""

    def __init__(
        self,
        name: SkillName,
        *,
        execute_payloads: list[dict[str, Any]] | None = None,
        recover_payloads: list[dict[str, Any]] | None = None,
        record: dict[str, Any] | None = None,
    ):
        self.name = name
        self.execute_payloads = execute_payloads if execute_payloads is not None else [{}]
        self.recover_payloads = recover_payloads if recover_payloads is not None else [{}]
        self.record = record if record is not None else {"execute_goal_ids": [], "recover_calls": []}
        self.goal_objects: dict[str, ResearchGoal] = {}

    def bind(self, outcome) -> None:
        self.goal_objects = {goal.goal_id: goal for goal in outcome.goals}

    def _rows_for(self, payload: dict[str, Any], goal_ids: list[str]) -> list[dict[str, Any]]:
        if "evidence_rows" in payload:
            return list(payload["evidence_rows"] or [])
        goals = payload.get("goals")
        if goals is not None:
            return [row for goal in goals for row in satisfied_rows(goal)]
        skip_marker = str(payload.get("skip_goal_name_contains", ""))
        rows: list[dict[str, Any]] = []
        for goal_id in goal_ids:
            goal = self.goal_objects.get(goal_id)
            if goal is None:
                continue
            if skip_marker and skip_marker in goal.goal_name:
                continue
            rows.extend(satisfied_rows(goal))
        return rows

    def plan(self, mission: ResearchMission, goals: list[ResearchGoal]) -> SkillPlan:
        return SkillPlan(
            skill_plan_id=new_sortable_id("PLAN"),
            skill_name=self.name,
            mission_id=mission.mission_id,
            goal_ids=[goal.goal_id for goal in goals],
            parameters={"project_dir": str(Path(tempfile.gettempdir()) / mission.mission_id)},
        )

    def execute(self, plan: SkillPlan) -> SkillRunResult:
        self.record["execute_goal_ids"].extend(plan.goal_ids)
        payload = self.execute_payloads.pop(0) if len(self.execute_payloads) > 1 else dict(self.execute_payloads[0])
        rows = self._rows_for(payload, plan.goal_ids)
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=self.name,
            goal_ids=list(plan.goal_ids),
            status=SkillRunStatus(payload.get("status", "OK")),
            evidence_exports=rows,
            attempts=[SkillAttempt(
                attempt_id=new_sortable_id("ATT"), attempt_no=1, executed=True,
                queries=list(payload.get("queries", ["initial-query"])),
            )],
            failure_class=FailureClass(payload["failure_class"]) if payload.get("failure_class") else None,
            diagnostics=list(payload.get("diagnostics", [])),
        )

    def recover(self, plan: SkillPlan, recovery_plan) -> SkillRunResult:
        self.record["recover_calls"].append(list(recovery_plan.new_queries))
        payload = self.recover_payloads.pop(0) if len(self.recover_payloads) > 1 else dict(self.recover_payloads[0])
        rows = self._rows_for(payload, plan.goal_ids)
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=self.name,
            goal_ids=list(recovery_plan.goal_ids),
            status=SkillRunStatus(payload.get("status", "OK")),
            evidence_exports=rows,
            attempts=[SkillAttempt(
                attempt_id=new_sortable_id("ATT"),
                attempt_no=recovery_plan.failed_round + 1,
                executed=payload.get("executed", True),
                queries=list(recovery_plan.new_queries) if payload.get("use_new_queries", True) else [],
                failure_class=FailureClass(payload["failure_class"]) if payload.get("failure_class") else None,
            )],
            failure_class=FailureClass(payload["failure_class"]) if payload.get("failure_class") else None,
        )

    def inspect(self, run_id: str) -> SkillRunResult:
        return SkillRunResult(skill_run_id=run_id, skill_name=self.name, status=SkillRunStatus.UNAVAILABLE)


def make_orchestrator(
    *,
    gateway=None,
    enterprise: FakeSkill | None = None,
    overseas: FakeSkill | None = None,
    policies: AgentPolicies | None = None,
    approval_cb=None,
    evidence_store: EvidenceStore | None = None,
):
    from enterprise_energy_research.agent.mission_store import MissionStore
    from enterprise_energy_research.agent.orchestrator import ResearchOrchestratorAgent

    tmp = Path(tempfile.mkdtemp(prefix="agent-test-"))
    ent = enterprise if enterprise is not None else FakeSkill(SkillName.ENTERPRISE_RESEARCH)
    ovs = overseas if overseas is not None else FakeSkill(SkillName.OVERSEAS_MARKET_RESEARCH)
    store = MissionStore(tmp / "store.sqlite3")
    if evidence_store is None:
        evidence_store = EvidenceStore(tmp / "evidence.sqlite3")
    return ResearchOrchestratorAgent(
        gateway=gateway,
        skills={SkillName.ENTERPRISE_RESEARCH: ent, SkillName.OVERSEAS_MARKET_RESEARCH: ovs},
        policies=policies or AgentPolicies.load(),
        store=store,
        evidence_store=evidence_store,
        approval_cb=approval_cb or (
            lambda mission, goals, routing: MissionApproval(
                approval_id=new_sortable_id("APPROVAL"),
                mission_id=mission.mission_id,
                decision=ApprovalStatus.APPROVED,
                scope_summary="test approval",
            )
        ),
    ), ent, ovs


# ------------------------------------------------------------- TEST-AGENT -----

class TestAgentRouting(unittest.TestCase):
    """TEST-AGENT-01/02/03: mode detection and skill routing."""

    def test_agent01_enterprise_only(self):
        orchestrator, ent, ovs = make_orchestrator(gateway=None)
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        self.assertEqual(outcome.mission.mode, ResearchMode.ENTERPRISE)
        self.assertTrue(any(goal.goal_class == GoalClass.CORE_ENTERPRISE for goal in outcome.goals))
        ent.bind(outcome)
        ovs.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        self.assertEqual(run.status, MissionStatus.COMPLETED)
        self.assertTrue(ent.record["execute_goal_ids"], "enterprise skill must be invoked")
        self.assertFalse(ovs.record["execute_goal_ids"], "market skill must NOT be invoked")

    def test_agent02_market_only(self):
        orchestrator, ent, ovs = make_orchestrator(gateway=None)
        outcome = orchestrator.parse_and_plan("调研西班牙户用储能市场")
        self.assertEqual(outcome.mission.mode, ResearchMode.MARKET)
        ent.bind(outcome)
        ovs.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        self.assertTrue(ovs.record["execute_goal_ids"], "market skill must be invoked")
        self.assertFalse(ent.record["execute_goal_ids"], "enterprise skill must NOT be invoked")

    def test_agent03_hybrid(self):
        orchestrator, ent, ovs = make_orchestrator(gateway=None)
        outcome = orchestrator.parse_and_plan("调研阳光电源在西班牙户储市场的发展机会")
        self.assertEqual(outcome.mission.mode, ResearchMode.HYBRID)
        enterprise_goals = [g for g in outcome.goals if g.assigned_skill == SkillName.ENTERPRISE_RESEARCH]
        market_goals = [g for g in outcome.goals if g.assigned_skill == SkillName.OVERSEAS_MARKET_RESEARCH]
        self.assertTrue(enterprise_goals)
        self.assertTrue(market_goals)
        self.assertTrue(any(g.goal_class == GoalClass.STRATEGY for g in outcome.goals))
        ent.bind(outcome)
        ovs.bind(outcome)
        orchestrator.run_approved(outcome.mission.mission_id)
        self.assertTrue(ent.record["execute_goal_ids"])
        self.assertTrue(ovs.record["execute_goal_ids"])

    def test_agent05_dynamic_custom_goal(self):
        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(
                    mode=ResearchMode.ENTERPRISE,
                    primary_subject="企业A",
                    custom_goals=[CustomGoalSpec(
                        name="Mining Energy Storage Application",
                        description="调查企业A是否有针对矿山场景的储能产品",
                        subject_name="企业A",
                        goal_class_hint="CUSTOM",
                    )],
                    parse_mode="llm",
                )
            return None  # routing falls back deterministically

        orchestrator, ent, _ = make_orchestrator(gateway=FakeGateway(handler))
        outcome = orchestrator.parse_and_plan("调查企业A是否适合矿山备用电源市场")
        custom = [g for g in outcome.goals if g.goal_class == GoalClass.CUSTOM]
        self.assertTrue(custom, "dynamic custom goal must be first-class")
        self.assertIn("Mining", custom[0].goal_name)
        self.assertIsNotNone(custom[0].assigned_skill, "custom goal must be routed")
        self.assertEqual(custom[0].assigned_skill, SkillName.ENTERPRISE_RESEARCH)

    def test_agent06_no_separator_full_intents(self):
        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(
                    mode=ResearchMode.HYBRID,
                    primary_subject="企业A",
                    geographies=["欧洲"],
                    custom_goals=[
                        CustomGoalSpec(name="欧洲政策风险", description="欧洲政策与准入风险", subject_name="企业A", goal_class_hint="POLICY", geographies=["欧洲"]),
                        CustomGoalSpec(name="竞争对手分析", description="竞争对手与竞争格局", subject_name="企业A", goal_class_hint="COMPETITION", geographies=["欧洲"]),
                    ],
                    market_goals=[MarketGoalSpec(name="欧洲市场", description="欧洲市场研究", geography="欧洲", market_object="储能")],
                    parse_mode="llm",
                )
            return None

        orchestrator, _, _ = make_orchestrator(gateway=FakeGateway(handler))
        outcome = orchestrator.parse_and_plan("查主营业务生产基地产品线客户渠道欧洲政策风险竞争对手")
        core = [g for g in outcome.goals if g.goal_class == GoalClass.CORE_ENTERPRISE]
        self.assertEqual(len(core), 12, "core enterprise plan must never shrink")
        names = " ".join(g.goal_name for g in outcome.goals)
        self.assertIn("政策", names)
        self.assertIn("竞争", names)
        assigned = {g.assigned_skill for g in outcome.goals}
        self.assertEqual(assigned, {SkillName.ENTERPRISE_RESEARCH, SkillName.OVERSEAS_MARKET_RESEARCH})

    def test_mode_upgrade_guardrail(self):
        """LLM labeled ENTERPRISE but produced market goals -> HYBRID upgrade."""
        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(
                    mode=ResearchMode.ENTERPRISE,
                    primary_subject="阳光电源",
                    geographies=["西班牙"],
                    market_goals=[MarketGoalSpec(name="西班牙户储市场概况", description="市场规模", geography="西班牙", market_object="户用储能")],
                    custom_goals=[CustomGoalSpec(name="市场机会评估", description="进入机会", subject_name="阳光电源", goal_class_hint="STRATEGY", geographies=["西班牙"])],
                    parse_mode="llm",
                )
            return None

        orchestrator, _, _ = make_orchestrator(gateway=FakeGateway(handler))
        outcome = orchestrator.parse_and_plan("调研阳光电源在西班牙户储市场的发展机会")
        self.assertEqual(outcome.mission.mode, ResearchMode.HYBRID)
        self.assertTrue(any(g.assigned_skill == SkillName.OVERSEAS_MARKET_RESEARCH for g in outcome.goals))
        self.assertTrue(any(g.goal_class == GoalClass.CORE_ENTERPRISE for g in outcome.goals))


class TestRecoveryUsesRepoStrategies(unittest.TestCase):
    """Recovery must use the repo's RECOVERY_STRATEGIES engine (SKILL.md
    Search Recall contract), not a hand-rolled lane list."""

    def test_deterministic_recovery_rotates_repo_strategies(self):
        from enterprise_energy_research.agent.recovery import RecoveryPlanner
        from enterprise_energy_research.research.planner import RECOVERY_STRATEGIES

        goal = ResearchGoal(
            goal_id=new_sortable_id("GOAL"), goal_name="产能与产线", goal_description="d",
            subject_id="e", subject_name="示例公司", subject_type=SubjectType.ENTERPRISE,
            goal_class=GoalClass.CORE_ENTERPRISE,
            required_evidence=["capacity", "production_lines"],
        )
        evaluation = GoalEvaluation(
            goal_id=goal.goal_id, status=GoalStatus.PARTIAL,
            evaluation_reason="缺产能证据", required_evidence_missing=["capacity"],
        )
        planner = RecoveryPlanner(None, max_rounds_per_goal=10)
        plan = planner.plan(goal, evaluation, failed_round=0, previous_attempts=[], evidence_sample=[])
        self.assertIsNone(plan.failure_class)
        self.assertTrue(plan.new_queries, "recovery must produce queries")
        self.assertIn("示例公司", plan.new_queries[0], "canonical subject must anchor every query")
        self.assertEqual(
            plan.new_source_categories[0],
            RECOVERY_STRATEGIES[0],
            "strategy must come from the repo rotation, not a hardcoded lane",
        )
        plan2 = planner.plan(goal, evaluation, failed_round=1, previous_attempts=[], evidence_sample=[])
        self.assertEqual(plan2.new_source_categories[0], RECOVERY_STRATEGIES[1], "rounds rotate strategies")


class TestAgentEvidenceBoundaries(unittest.TestCase):
    """TEST-AGENT-04/13: subject isolation and conflict preservation."""

    def test_agent04_competitor_evidence_never_pollutes_target(self):
        from enterprise_energy_research.agent.market_evidence import MarketEvidenceImporter

        tmp = Path(tempfile.mkdtemp(prefix="agent-ev-"))
        store = EvidenceStore(tmp / "ev.sqlite3")
        importer = MarketEvidenceImporter(store, AgentPolicies.load())
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="调研企业A并分析竞争对手")
        target_goal = _goal(new_sortable_id("GOAL"), subject_id="enterprise:企业A")
        report = importer.import_rows(
            mission=mission,
            goals=[target_goal],
            originating_skill=SkillName.OVERSEAS_MARKET_RESEARCH.value,
            rows=[
                {
                    "goal_id": target_goal.goal_id,
                    "source_id": "S1", "source_url": "https://example.com/a",
                    "evidence_item": "market_share", "raw_value": "10%",
                    "value_class": "observed", "reliability_tier": "B",
                    "subject_role": "SUBJECT",
                },
                {
                    "goal_id": target_goal.goal_id,
                    "source_id": "S2", "source_url": "https://example.com/b",
                    "evidence_item": "market_share", "raw_value": "25%",
                    "value_class": "observed", "reliability_tier": "B",
                    "subject_role": "COMPETITOR", "subject_name": "LG Energy Solution",
                },
            ],
        )
        self.assertEqual(report.claims_created, 2)
        claims = store.list(f"agent-{mission.mission_id}", "claim")
        competitor = [c for c in claims if c.subject_role == "COMPETITOR"]
        self.assertEqual(len(competitor), 1)
        self.assertNotEqual(competitor[0].entity_id, target_goal.subject_id)
        self.assertIn("LG", competitor[0].entity_id)
        target = [c for c in claims if c.subject_role == "SUBJECT"]
        self.assertEqual(target[0].entity_id, target_goal.subject_id)

    def test_agent13_conflicts_preserved_no_auto_overwrite(self):
        from enterprise_energy_research.agent.market_evidence import MarketEvidenceImporter
        from enterprise_energy_research.domain.enums import VerificationStatus
        from enterprise_energy_research.domain.models import Claim, utc_now

        tmp = Path(tempfile.mkdtemp(prefix="agent-conflict-"))
        store = EvidenceStore(tmp / "ev.sqlite3")
        importer = MarketEvidenceImporter(store, AgentPolicies.load())
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="冲突测试")
        goal = _goal(new_sortable_id("GOAL"), subject_id="market:spain")
        importer.import_rows(
            mission=mission,
            goals=[goal],
            originating_skill=SkillName.OVERSEAS_MARKET_RESEARCH.value,
            rows=[{
                "goal_id": goal.goal_id, "source_id": "S1", "source_url": "https://example.com/a",
                "evidence_item": "tariff", "raw_value": "0.12", "value_class": "observed",
            }],
        )
        run_id = f"agent-{mission.mission_id}"
        store.add(run_id, 1, "claim", Claim(
            claim_id=new_sortable_id("CLAIM"),
            entity_id="market:spain",
            field_name="tariff",
            value="0.20",
            value_type="market",
            source_id="S1",
            raw_text="enterprise-side observed tariff",
            context_text="enterprise evidence",
            retrieved_at=utc_now(),
            confidence=0.8,
            conflict_group_id="CONFLICT-1",
            verification_status=VerificationStatus.CONFLICTING,
        ))
        claims = store.list(run_id, "claim")
        values = sorted(str(c.value) for c in claims)
        self.assertEqual(len(claims), 2, "both conflicting claims must coexist")
        self.assertIn("0.12", values)
        self.assertIn("0.20", values)


class TestEvidenceFieldBinding(unittest.TestCase):
    """§20: enterprise claims bind to goals via field_name -> required_evidence."""

    def test_field_binding_feeds_evaluator(self):
        # Enterprise rows carry field_name but no goal_id; the orchestrator
        # must bind them to the goals whose required_evidence lists the field,
        # otherwise evaluation would treat real evidence as absent.
        class FieldSkill(FakeSkill):
            def __init__(self):
                super().__init__(SkillName.ENTERPRISE_RESEARCH)
                self.rows = []

            def execute(self, plan):
                self.record["execute_goal_ids"].extend(plan.goal_ids)
                return SkillRunResult(
                    skill_run_id=new_sortable_id("SKILLRUN"),
                    skill_name=self.name,
                    goal_ids=list(plan.goal_ids),
                    status=SkillRunStatus.OK,
                    evidence_exports=self.rows,
                )

        skill = FieldSkill()
        skill.rows = [
            {"field_name": "factories", "claim_id": new_sortable_id("CLAIM"), "verification_status": "VERIFIED", "raw_value": "x"},
            {"field_name": "financials", "claim_id": new_sortable_id("CLAIM"), "verification_status": "VERIFIED", "raw_value": "y"},
            {"field_name": "unrelated_thing", "claim_id": new_sortable_id("CLAIM"), "verification_status": "VERIFIED", "raw_value": "z"},
        ]
        orchestrator, _, _ = make_orchestrator(gateway=None, enterprise=skill)
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        ent = [g for g in outcome.goals if g.goal_name == "工厂与生产基地"][0]
        fin = [g for g in outcome.goals if g.goal_name == "财务与经营"][0]
        self.assertIn("factories", ent.required_evidence)
        self.assertIn("financials", fin.required_evidence)
        orchestrator.run_approved(outcome.mission.mission_id)
        mission = orchestrator.store.get_mission(outcome.mission.mission_id)
        bound = {g.goal_id: g for g in mission.goals}
        self.assertTrue(bound[ent.goal_id].evidence_refs, "factory goal must receive field-bound evidence")
        self.assertTrue(bound[fin.goal_id].evidence_refs, "financial goal must receive field-bound evidence")
        unrelated = [g for g in mission.goals if g.goal_name == "技术与研发"][0]
        self.assertFalse(bound[unrelated.goal_id].evidence_refs, "unrelated rows must not bind")


class TestEnterpriseToolEvidenceRows(unittest.TestCase):
    """§20: the enterprise tool must expose claim ROWS (not the summary
    payload) as evidence_exports, or goal binding sees nothing."""

    def test_execute_exposes_claim_rows(self):
        from enterprise_energy_research.agent.tools.enterprise_research import EnterpriseResearchSkill

        def fake_executor(spec):
            return {
                "status": "OK",
                "run_id": "RUN-X",
                "evidence_rows": [
                    {"claim_id": "C1", "field_name": "factories", "goal_families": ["factories"]},
                    {"claim_id": "C2", "field_name": "financials", "goal_families": ["financials"]},
                ],
                "coverage_metrics": {"evidence_count": 2, "verified_claim_count": 1},
            }

        skill = EnterpriseResearchSkill(fake_executor)
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="调研宁波鄞开集团")
        goal = _goal(new_sortable_id("GOAL"), subject_id="enterprise:x")
        result = skill.execute(skill.plan(mission, [goal]))
        self.assertEqual(result.status, SkillRunStatus.OK)
        self.assertEqual(len(result.evidence_exports), 2, "claim rows must be exposed, not the payload")
        self.assertEqual(result.evidence_exports[0]["claim_id"], "C1")
        self.assertEqual(result.coverage_metrics["evidence_count"], 2)


class TestAgentApproval(unittest.TestCase):
    """TEST-AGENT-08: the agent cannot self-approve market research."""

    def test_agent08_unapproved_overseas_blocks(self):
        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-approval-"))
        calls: dict[str, Any] = {"runner": 0}

        def runner(spec):
            calls["runner"] += 1
            return {"status": "OK"}

        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"), runner=runner)
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="调研泰国户储市场", mode=ResearchMode.MARKET)
        goal = _goal(new_sortable_id("GOAL"), subject_id="market:thailand")
        plan = SkillPlan(
            skill_plan_id=new_sortable_id("PLAN"),
            skill_name=SkillName.OVERSEAS_MARKET_RESEARCH,
            mission_id=mission.mission_id,
            goal_ids=[goal.goal_id],
            parameters={"project_dir": str(tmp / "market")},
        )
        result = adapter.execute(plan)
        self.assertEqual(result.status, SkillRunStatus.BLOCKED)
        self.assertEqual(result.failure_class, FailureClass.AUTH_REQUIRED)
        self.assertEqual(calls["runner"], 0, "runner must not run without human approval")

    def test_agent08b_unified_approval_opens_both_gates(self):
        """§27: one human mission approval materializes the skill's own
        Stage-0 record, so no second approval step is needed."""
        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-approval-"))
        calls: dict[str, Any] = {"runner": 0}

        def runner(spec):
            calls["runner"] += 1
            return {"status": "OK", "strategy": "default"}

        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"), runner=runner)
        mission = ResearchMission(
            mission_id=new_sortable_id("MISSION"),
            raw_request="调研泰国户储市场",
            mode=ResearchMode.MARKET,
            approval_status=ApprovalStatus.APPROVED,
        )
        goal = _goal(new_sortable_id("GOAL"), subject_id="market:thailand")
        plan = adapter.plan(mission, [goal])
        # The unified approval already opened the skill's Stage-0 gate.
        self.assertTrue(adapter.check_approval(Path(plan.parameters["project_dir"]))["approved"])
        result = adapter.execute(plan)
        self.assertEqual(result.status, SkillRunStatus.OK)
        self.assertEqual(calls["runner"], 1)

    def test_agent08_approved_overseas_runs(self):
        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-approval-"))
        project_dir = tmp / "market"
        project_dir.mkdir(parents=True)
        (project_dir / "00_Research_Approval.csv").write_text(
            "approval_id,outline_version,outline_path,scope_summary,reviewer,approval_status,approval_date,approval_message,scope_change_requires_reapproval,notes\n"
            "A1,v1,outline.md,泰国户储市场,human,approved,2026-08-25,ok,yes,\n",
            encoding="utf-8-sig",
        )
        calls: dict[str, Any] = {"runner": 0}

        def runner(spec):
            calls["runner"] += 1
            return {"status": "OK", "strategy": "default"}

        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"), runner=runner)
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="调研泰国户储市场", mode=ResearchMode.MARKET)
        goal = _goal(new_sortable_id("GOAL"), subject_id="market:thailand")
        plan = SkillPlan(
            skill_plan_id=new_sortable_id("PLAN"),
            skill_name=SkillName.OVERSEAS_MARKET_RESEARCH,
            mission_id=mission.mission_id,
            goal_ids=[goal.goal_id],
            parameters={"project_dir": str(project_dir)},
        )
        result = adapter.execute(plan)
        self.assertEqual(result.status, SkillRunStatus.OK)
        self.assertEqual(calls["runner"], 1)


class TestMarketTaskFloors(unittest.TestCase):
    """Overseas strategy adoption: collection tasks must carry the skill's
    policy floors, not hardcoded 2/3."""

    def test_task_rows_use_policy_floors(self):
        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-floors-"))
        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"), runner=lambda spec: {"status": "OK"})
        floors = adapter._policy_floors()
        self.assertTrue(floors, "policy floors must load from the vendored pack")
        project = tmp / "market"
        project.mkdir(parents=True)
        adapter._write_tasks({
            "goal_specs": [
                {"goal_id": "G1", "name": "西班牙市场定义与规模", "description": "TAM"},
                {"goal_id": "G2", "name": "政策与准入", "description": "tariff"},
            ],
            "region": "西班牙",
            "category": "户用储能",
        }, project)
        import csv
        rows = list(csv.DictReader((project / "02_Web_Collection_Tasks.csv").open(encoding="utf-8-sig")))
        self.assertTrue(rows)
        size_rows = [r for r in rows if r["collection_goal"].startswith("西班牙市场定义与规模")]
        floor = floors["market_size_and_demand"]["rounds"]["1"]["min_unique_sources"]
        self.assertEqual(int(size_rows[0]["target_unique_sources"]), floor, "floors must come from the policy")
        self.assertGreater(int(size_rows[0]["target_unique_sources"]), 2, "policy floors exceed the old hardcode")
        self.assertEqual(size_rows[0]["goal_family"], "market_size_and_demand")


class TestMarketRunnerCommand(unittest.TestCase):
    """回归：采集子进程命令必须合法。--json-log 裸传（无路径值）会让
    run_workflow.py 直接 argparse 报错退出，整轮采集 0.3 秒失败、零证据。"""

    def test_json_log_flag_carries_path_value(self):
        from unittest import mock

        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-runner-"))
        project = tmp / "market"
        project.mkdir(parents=True)
        (project / "00_Research_Approval.csv").write_text(
            "approval_id,outline_version,outline_path,scope_summary,reviewer,approval_status,approval_date,approval_message,scope_change_requires_reapproval,notes\n"
            "A1,v1,outline.md,德国家庭储能市场,human,approved,2026-08-25,ok,yes,\n",
            encoding="utf-8-sig",
        )
        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"))
        captured: dict[str, Any] = {}

        class FakeProc:
            returncode = 0

            def communicate(self):
                return ("", "")

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            return FakeProc()

        def fake_run(cmd, **kwargs):
            # init 子进程走 subprocess.run；同样 mock，避免触发真实 init 脚本
            # （其内部 with Popen 会撞上被 mock 的 FakeProc 无 __enter__）。
            captured.setdefault("run_cmds", []).append(list(cmd))

            class R:
                returncode = 0

            return R()

        with mock.patch("subprocess.Popen", side_effect=fake_popen), mock.patch("subprocess.run", side_effect=fake_run):
            payload = adapter._default_runner({
                "project_dir": str(project),
                "region": "德国",
                "category": "家庭储能",
                "goal_specs": [{"goal_id": "G1", "name": "市场规模", "description": "TAM"}],
            })
        cmd = captured["cmd"]
        self.assertIn("--json-log", cmd)
        index = cmd.index("--json-log")
        self.assertLess(index + 1, len(cmd), "--json-log requires a path value, not a bare flag")
        self.assertTrue(cmd[index + 1].endswith("workflow_run.json"))
        self.assertEqual(payload["status"], "OK")

    def test_init_not_skipped_when_approval_already_materialized(self):
        """回归：ensure_approved 先落盘审批后，init 不得被跳过（旧条件看审批文件，
        导致项目模板永远未初始化 → ledger 0 行 → 目标全部 EXHAUSTED 零交付）。"""
        from unittest import mock

        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        tmp = Path(tempfile.mkdtemp(prefix="agent-runner-init-"))
        project = tmp / "market"
        project.mkdir(parents=True)
        (project / "00_Research_Approval.csv").write_text(
            "approval_id,outline_version,outline_path,scope_summary,reviewer,approval_status,approval_date,approval_message,scope_change_requires_reapproval,notes\n"
            "A1,v1,outline.md,德国家庭储能市场,human,approved,2026-08-25,ok,yes,\n",
            encoding="utf-8-sig",
        )
        adapter = OverseasMarketResearchAdapter(skill_root=Path("unused"))
        calls: list[list[str]] = []

        class FakeProc:
            returncode = 0

            def communicate(self):
                return ("", "")

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            return FakeProc()

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))

            class R:
                returncode = 0

            return R()

        with mock.patch("subprocess.Popen", side_effect=fake_popen), mock.patch("subprocess.run", side_effect=fake_run):
            adapter._default_runner({
                "project_dir": str(project),
                "region": "德国",
                "category": "家庭储能",
                "goal_specs": [{"goal_id": "G1", "name": "市场规模", "description": "TAM"}],
            })
        init_cmds = [c for c in calls if any("init_research_project.py" in str(part) for part in c)]
        self.assertTrue(init_cmds, "审批已落盘但台账骨架缺失时，init 必须执行")
        self.assertIn("--region", init_cmds[0])

    def test_successful_captures_are_registered_into_ledger_with_dedup(self):
        """回归：采集成功记录必须登记进 00_Source_Ledger.csv（按 URL 去重），
        否则编排层判零证据、证据进不了 unified store、整任务零交付物。"""
        import csv as _csv

        from enterprise_energy_research.agent.tools.overseas_market_research import register_sources_from_captures

        tmp = Path(tempfile.mkdtemp(prefix="agent-ledger-"))
        project = tmp / "market"
        project.mkdir(parents=True)
        (project / "00_Source_Ledger.csv").write_text(
            "source_id,stage,evidence_item,value_class,source_type,source_title,source_url,"
            "root_domain,local_file_path,access_date,verification_status\n",
            encoding="utf-8",
        )
        (project / "13_Collection_Attempt_Journal.csv").write_text(
            "attempt_id,task_id,round,round_goal,tool,action,query_or_url,status,error_class,"
            "failure_reason,result_count,candidates_found,raw_capture_path,session,timestamp\n"
            "T1-1,T001,1,coverage 广度,anysearch,search,德国 家庭储能,success,none,,,2,raw_capture/T001.md,s1,2026-08-25T11:00:00+00:00\n"
            "T1-2,T001,1,coverage 广度,anysearch,search,德国 家庭储能 2,success,none,,,1,raw_capture/T001b.md,s1,2026-08-25T11:01:00+00:00\n"
            "T1-3,T002,1,coverage 广度,anysearch,search,失败样本,success,none,,,,,s1,2026-08-25T11:02:00+00:00\n",
            encoding="utf-8",
        )
        capture_dir = project / "raw_capture"
        capture_dir.mkdir()
        (capture_dir / "T001.md").write_text(
            "## Search Results (2 results)\n\n"
            "### 1. 标题 A\n- **URL**: https://a.example.com/x\n- 摘要\n\n"
            "### 2. 标题 B\n- **URL**: https://b.example.com/y\n- 摘要\n",
            encoding="utf-8",
        )
        # 第二个 capture 含重复 URL（必须去重）与一个新 URL。
        (capture_dir / "T001b.md").write_text(
            "## Search Results (2 results)\n\n"
            "### 1. 标题 A 再现\n- **URL**: https://a.example.com/x\n- 摘要\n\n"
            "### 2. 标题 C\n- **URL**: https://c.example.com/z\n- 摘要\n",
            encoding="utf-8",
        )

        added = register_sources_from_captures(project)
        self.assertEqual(added, 3)
        with (project / "00_Source_Ledger.csv").open(encoding="utf-8") as handle:
            rows = list(_csv.DictReader(handle))
        urls = {row["source_url"] for row in rows}
        self.assertEqual(
            urls, {"https://a.example.com/x", "https://b.example.com/y", "https://c.example.com/z"}
        )
        for row in rows:
            self.assertTrue(row["source_id"])
            self.assertEqual(row["root_domain"], row["source_url"].split("/")[2])
            self.assertEqual(row["verification_status"], "unverified")
        # 重复登记不新增。
        self.assertEqual(register_sources_from_captures(project), 0)


class TestMarketGoalDedup(unittest.TestCase):
    """回归：解析器对同一地理输出多条 market_goals（每个关注点一条）时，
    规划器不得按条数 × 目标族展开，否则单市场出现重复目标组（18 而非 6）。"""

    def test_same_geography_specs_are_merged(self):
        from enterprise_energy_research.agent.goal_planner import MARKET_GOAL_FAMILIES, GoalPlanner

        planner = GoalPlanner()
        mission = ResearchMission(
            mission_id=new_sortable_id("MISSION"),
            raw_request="调研德国家庭储能市场，重点分析市场规模、竞争格局和政策环境",
            mode=ResearchMode.MARKET,
        )
        parsed = MissionParseResult(
            mode=ResearchMode.MARKET,
            geographies=["德国"],
            market_goals=[
                MarketGoalSpec(name="市场规模", description="规模", geography="德国", market_object="家庭储能市场规模"),
                MarketGoalSpec(name="竞争格局", description="竞争", geography="德国", market_object="竞争格局"),
                MarketGoalSpec(name="政策环境", description="政策", geography="德国", market_object="政策环境"),
            ],
            parse_mode="llm",
        )
        goals = planner.plan(mission, parsed)
        self.assertEqual(len(goals), len(MARKET_GOAL_FAMILIES), "每个地理只展开一组目标族")
        descriptions = " ".join(goal.goal_description for goal in goals)
        for focus in ("市场规模", "竞争格局", "政策环境"):
            self.assertIn(focus, descriptions, "合并时不得丢失用户关注点")


class TestCustomGoalCoreDedup(unittest.TestCase):
    """回归：LLM 解析常把固定核心计划复述成用户专项目标（如“企业概况调查”
    “产品与工厂布局调查”“能源合作机会调查”），重复目标会烧光全任务共享的
    迭代预算，导致后面的核心目标零修复轮。规划器必须丢弃复述类专项，
    同时保留真正新增范围的目标（新主题、带地理限定、竞对深挖）。"""

    def _planned(self, custom_goals):
        from enterprise_energy_research.agent.goal_planner import GoalPlanner

        planner = GoalPlanner()
        mission = ResearchMission(
            mission_id=new_sortable_id("MISSION"),
            raw_request="调查苏州昀冢电子科技股份有限公司的企业概况、产品与工厂布局及能源合作机会",
            mode=ResearchMode.ENTERPRISE,
        )
        parsed = MissionParseResult(
            mode=ResearchMode.ENTERPRISE,
            primary_subject="苏州昀冢电子科技股份有限公司",
            custom_goals=custom_goals,
            parse_mode="llm",
        )
        return planner.plan(mission, parsed)

    def test_core_restatements_are_dropped(self):
        goals = self._planned([
            CustomGoalSpec(name="企业概况调查", description="企业概况", subject_name="苏州昀冢电子科技股份有限公司"),
            CustomGoalSpec(name="产品与工厂布局调查", description="产品与工厂布局", subject_name="苏州昀冢电子科技股份有限公司"),
            CustomGoalSpec(name="能源合作机会调查", description="能源合作机会", subject_name="苏州昀冢电子科技股份有限公司"),
        ])
        core = [g for g in goals if g.goal_class == GoalClass.CORE_ENTERPRISE]
        self.assertEqual(len(core), 12, "core enterprise plan must never shrink")
        self.assertEqual(len(goals), 12, "复述类专项必须被丢弃，不得重复消耗预算")

    def test_novel_and_scoped_goals_survive(self):
        goals = self._planned([
            CustomGoalSpec(name="Mining Energy Storage Application", description="矿山场景储能产品", subject_name="苏州昀冢电子科技股份有限公司"),
            CustomGoalSpec(name="竞争对手分析", description="主要竞争对手深挖", subject_name="苏州昀冢电子科技股份有限公司"),
            # 真区域专项：地理词必须进入目标名本身才是区域研究的信号；
            # 只给复述类名称挂地理（观测：企业概况调查+苏州）曾让复述专项逃出去重。
            CustomGoalSpec(name="德国市场调研", description="德国市场专项", subject_name="苏州昀冢电子科技股份有限公司", geographies=["德国"]),
            CustomGoalSpec(name="海外产能布局专项", description="海外储能产能布局", subject_name="苏州昀冢电子科技股份有限公司"),
        ])
        names = [g.goal_name for g in goals]
        for expected in ("Mining Energy Storage Application", "竞争对手分析", "德国市场调研", "海外产能布局专项"):
            self.assertIn(expected, names, f"真正新增范围的目标必须保留：{expected}")

    def test_geo_echo_on_restatements_is_still_dropped(self):
        """观测回归：MISSION-01M0YD91629V0ZHP2MC4Z0PH8G 的三个复述专项带着
        geographies=[主体所在城市] 逃过去重，误入海外轨空烧预算。"""
        goals = self._planned([
            CustomGoalSpec(name="企业概况调查", description="企业概况", subject_name="苏州昀冢电子科技股份有限公司", geographies=["苏州"]),
            CustomGoalSpec(name="产品与工厂布局调查", description="产品与工厂布局", subject_name="苏州昀冢电子科技股份有限公司", geographies=["苏州"]),
            CustomGoalSpec(name="能源合作机会分析", description="能源合作机会", subject_name="苏州昀冢电子科技股份有限公司", geographies=["苏州"]),
        ])
        self.assertEqual(len(goals), 12, "带主体城市地理的复述专项也必须被丢弃")


class TestAgentRecovery(unittest.TestCase):
    """TEST-AGENT-09/10/11/12: recovery loop semantics and accounting."""

    def _policy(self, rounds: int) -> AgentPolicies:
        return AgentPolicies(
            enabled=True,
            max_agent_iterations=30,
            max_recovery_rounds_per_goal=rounds,
            require_structured_output=True,
            allow_dynamic_custom_goal=True,
            allow_multi_skill_goal=True,
            unified_mission_approval=True,
            unified_store=True,
            single_artifact_owner=True,
            value_class_mapping={"observed": "OBSERVED"},
        )

    def test_agent09_insufficient_evidence_recovers_then_satisfies(self):
        evals: dict[str, int] = {}

        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(mode=ResearchMode.ENTERPRISE, primary_subject="企业A", parse_mode="llm")
            if request.purpose == "agent.goal_evaluation":
                content = str(request.messages[-1]["content"])
                goal_name = content.split("goal_name=", 1)[1].split("\n", 1)[0]
                if "产能" not in goal_name:
                    return _LLMEvaluation(satisfied=True, reason="ok")
                count = evals.get(goal_name, 0)
                evals[goal_name] = count + 1
                return _LLMEvaluation(satisfied=count >= 1, reason="scripted")
            if request.purpose == "agent.recovery_plan":
                from enterprise_energy_research.agent.recovery import _LLMRecovery
                return _LLMRecovery(
                    failure_reason="上一轮产能证据缺失",
                    new_strategy="环评与投产公告",
                    new_source_categories=["环评", "投产公告"],
                    new_queries=["企业A 环评 建设项目", "企业A 投产 公告"],
                )
            if request.purpose == "agent.cross_domain_synthesis":
                return _LLMSynthesis(findings=[])
            return None

        enterprise = FakeSkill(
            SkillName.ENTERPRISE_RESEARCH,
            execute_payloads=[{"skip_goal_name_contains": "产能"}],
            recover_payloads=[{}],
        )
        orchestrator, ent, _ = make_orchestrator(gateway=FakeGateway(handler), enterprise=enterprise, policies=self._policy(3))
        outcome = orchestrator.parse_and_plan("调研企业A")
        ent.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        recovered = [g for g in run.goals if g.status == GoalStatus.SATISFIED and g.recovery_rounds > 0]
        self.assertTrue(recovered, "at least one goal must recover and then satisfy")
        self.assertTrue(ent.record["recover_calls"], "recovery must be invoked with new queries")
        self.assertEqual(len(ent.record["recover_calls"][0]), 2)

    def test_agent10_identical_queries_do_not_count(self):
        ledger = RecoveryLedger()
        result = SkillRunResult(
            skill_run_id=new_sortable_id("RUN"), skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=["G1"], status=SkillRunStatus.PARTIAL,
            attempts=[SkillAttempt(attempt_id="A1", attempt_no=1, executed=True, queries=["q1", "q2"])],
        )
        self.assertTrue(ledger.record("G1", result))
        self.assertEqual(ledger.executed_rounds("G1"), 1)
        duplicate = SkillRunResult(
            skill_run_id=new_sortable_id("RUN"), skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=["G1"], status=SkillRunStatus.PARTIAL,
            attempts=[SkillAttempt(attempt_id="A2", attempt_no=2, executed=True, queries=["q1", "q2"])],
        )
        self.assertFalse(ledger.record("G1", duplicate), "repeated identical queries consume no round")
        self.assertEqual(ledger.executed_rounds("G1"), 1)

    def test_agent11_adapter_failure_consumes_no_round(self):
        ledger = RecoveryLedger()
        result = SkillRunResult(
            skill_run_id=new_sortable_id("RUN"), skill_name=SkillName.ENTERPRISE_RESEARCH,
            goal_ids=["G1"], status=SkillRunStatus.UNAVAILABLE,
            failure_class=FailureClass.ADAPTER_FAILURE,
            attempts=[SkillAttempt(attempt_id="A1", attempt_no=1, executed=True, queries=["q1"], failure_class=FailureClass.ADAPTER_FAILURE)],
        )
        self.assertFalse(ledger.record("G1", result))
        self.assertEqual(ledger.executed_rounds("G1"), 0)

    def test_agent11b_three_uncounted_rounds_block(self):
        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(mode=ResearchMode.ENTERPRISE, primary_subject="企业A", parse_mode="llm")
            if request.purpose == "agent.goal_evaluation":
                return _LLMEvaluation(satisfied=False, reason="scripted failure")
            if request.purpose == "agent.recovery_plan":
                from enterprise_energy_research.agent.recovery import _LLMRecovery
                return _LLMRecovery(failure_reason="x", new_strategy="y", new_queries=["new-query"])
            if request.purpose == "agent.cross_domain_synthesis":
                return _LLMSynthesis(findings=[])
            return None

        enterprise = FakeSkill(
            SkillName.ENTERPRISE_RESEARCH,
            execute_payloads=[{"evidence_rows": []}],
            recover_payloads=[{"status": "UNAVAILABLE", "failure_class": "ADAPTER_FAILURE", "evidence_rows": []}],
        )
        orchestrator, ent, _ = make_orchestrator(gateway=FakeGateway(handler), enterprise=enterprise, policies=self._policy(10))
        outcome = orchestrator.parse_and_plan("调研企业A")
        ent.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        self.assertTrue(any(g.status == GoalStatus.BLOCKED for g in run.goals))
        for goal in run.goals:
            self.assertEqual(goal.recovery_rounds, 0, "adapter failures must never count as rounds")

    def test_agent12_round_cap_produces_auditable_limitation(self):
        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(mode=ResearchMode.ENTERPRISE, primary_subject="企业A", parse_mode="llm")
            if request.purpose == "agent.goal_evaluation":
                return _LLMEvaluation(satisfied=False, reason="scripted insufficiency")
            if request.purpose == "agent.recovery_plan":
                from enterprise_energy_research.agent.recovery import _LLMRecovery
                return _LLMRecovery(failure_reason="x", new_strategy="y", new_queries=[new_sortable_id("Q")])
            if request.purpose == "agent.cross_domain_synthesis":
                return _LLMSynthesis(findings=[])
            return None

        enterprise = FakeSkill(
            SkillName.ENTERPRISE_RESEARCH,
            execute_payloads=[{"evidence_rows": []}],
            recover_payloads=[{"evidence_rows": []}],
        )
        orchestrator, ent, _ = make_orchestrator(gateway=FakeGateway(handler), enterprise=enterprise, policies=self._policy(2))
        outcome = orchestrator.parse_and_plan("调研企业A")
        ent.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        exhausted = [g for g in run.goals if g.status == GoalStatus.EXHAUSTED]
        self.assertTrue(exhausted)
        self.assertEqual(exhausted[0].recovery_rounds, 2, "cap is a configuration value (2 here, 10 in config)")
        self.assertTrue(run.auditable_limitations)
        self.assertEqual(run.auditable_limitations[0]["type"], "AUDITABLE_EVIDENCE_LIMITATION")
        # Default config still carries the §23 value of 10.
        self.assertEqual(AgentPolicies.load().max_recovery_rounds_per_goal, 10)


class TestAgentSynthesisAndPublisher(unittest.TestCase):
    """TEST-AGENT-14: final publication never fetches; synthesis is traceable."""

    def test_agent14_synthesis_requires_traceable_refs(self):
        from enterprise_energy_research.agent.synthesis import CrossDomainSynthesisEngine

        evidence = [{"claim_id": "CLAIM-1", "verification_status": "VERIFIED", "raw_value": "x"}]
        engine = CrossDomainSynthesisEngine(FakeGateway(lambda request: _LLMSynthesis(findings=[
            CrossDomainFinding(
                finding_id="F1", finding_type="MARKET_FIT",
                statement="适配度高",
                enterprise_evidence_refs=["CLAIM-1"],
                confidence=0.7,
            ),
            CrossDomainFinding(
                finding_id="F2", finding_type="RISK",
                statement="无法追溯的结论",
                enterprise_evidence_refs=["CLAIM-NOT-IN-INPUT"],
                confidence=0.9,
            ),
        ])))
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="x", mode=ResearchMode.HYBRID)
        findings = engine.synthesize(mission, [], evidence, [])
        self.assertEqual(len(findings), 1, "untraceable finding must be dropped")
        self.assertEqual(findings[0].finding_id, "F1")

    def test_agent14b_engine_has_no_network_surface(self):
        import inspect
        from enterprise_energy_research.agent.synthesis import CrossDomainSynthesisEngine

        source = inspect.getsource(CrossDomainSynthesisEngine)
        for banned in ("requests.get", "urlopen", "httpx", "urllib.request", "socket"):
            self.assertNotIn(banned, source, f"synthesis engine must not fetch: {banned}")

    def test_agent15_daily_intelligence_untouched(self):
        # The agent layer must not import the intelligence workflow (§47), and
        # its public entry point stays intact.
        import inspect
        from enterprise_energy_research.automation.intelligence.service import IntelligenceService
        from enterprise_energy_research.agent.orchestrator import ResearchOrchestratorAgent
        from enterprise_energy_research.agent.api import build_agent_orchestrator

        self.assertTrue(hasattr(IntelligenceService, "run_daily"), "run_daily must remain intact")
        for module in (ResearchOrchestratorAgent, build_agent_orchestrator):
            source = inspect.getsource(module)
            self.assertNotIn("intelligence", source, "agent layer must not touch the daily intelligence workflow")


class TestHybridGolden(unittest.TestCase):
    """§58 golden case: company + market + cross-domain synthesis, offline."""

    def test_hybrid_golden_three_layers(self):
        import json as _json
        import re as _re

        def handler(request):
            if request.purpose == "agent.mission_parse":
                return MissionParseResult(
                    mode=ResearchMode.HYBRID,
                    primary_subject="阳光电源",
                    geographies=["德国", "西班牙"],
                    market_goals=[MarketGoalSpec(name="德国户储市场", description="德国户储市场规模与政策", geography="德国", market_object="户用储能")],
                    custom_goals=[CustomGoalSpec(name="竞争与渠道", description="竞争、政策、渠道专项", subject_name="阳光电源", goal_class_hint="CUSTOM", geographies=["德国", "西班牙"])],
                    parse_mode="llm",
                )
            if request.purpose == "agent.skill_routing":
                decisions = []
                lines = [line for line in str(request.messages[-1]["content"]).splitlines() if line.startswith("[")]
                for line in lines:
                    item = _json.loads(line[line.index("{"):])
                    skill = SkillName.OVERSEAS_MARKET_RESEARCH if item.get("subject_type") == "market" else SkillName.ENTERPRISE_RESEARCH
                    decisions.append(RoutingDecision(
                        goal_id=item["goal_id"], assigned_skill=skill,
                        routing_reason="脚本化路由", confidence=0.9, mode=ResearchMode.HYBRID,
                    ))
                return RoutingBatch(decisions=decisions)
            if request.purpose == "agent.goal_evaluation":
                return _LLMEvaluation(satisfied=True, reason="golden satisfied")
            if request.purpose == "agent.cross_domain_synthesis":
                content = str(request.messages[-1]["content"])
                ids = _re.findall(r"'claim_id': '([^']+)'", content)
                return _LLMSynthesis(findings=[
                    CrossDomainFinding(
                        finding_id="F-GOLDEN", finding_type="ENTRY_STRATEGY",
                        statement="阳光电源在德国家用储能市场具有中等偏高适配度",
                        enterprise_evidence_refs=ids[:1],
                        market_evidence_refs=ids[1:2],
                        assumptions=["电价与补贴政策延续"],
                        confidence=0.7,
                    ),
                ])
            return None

        orchestrator, ent, ovs = make_orchestrator(gateway=FakeGateway(handler))
        outcome = orchestrator.parse_and_plan("调研阳光电源在德国/西班牙户储市场的业务、产品、竞争、政策、渠道、市场机会。")
        self.assertEqual(outcome.mission.mode, ResearchMode.HYBRID)
        ent.bind(outcome)
        ovs.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        self.assertEqual(run.status, MissionStatus.COMPLETED)
        self.assertTrue(ent.record["execute_goal_ids"], "company research layer")
        self.assertTrue(ovs.record["execute_goal_ids"], "market research layer")
        self.assertTrue(run.synthesis_findings, "cross-domain synthesis layer")
        for finding in run.synthesis_findings:
            self.assertTrue(finding.enterprise_evidence_refs or finding.market_evidence_refs)


class TestAgentApiSurface(unittest.TestCase):
    """API smoke: agent router registers and answers health."""

    def test_agent_api_health_and_parse(self):
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from enterprise_energy_research.automation.api.app import create_app
        from enterprise_energy_research.automation.executor import SyntheticKernelExecutor

        tmp = Path(tempfile.mkdtemp(prefix="agent-api-"))
        with patch.dict(os.environ, {"EER_DEEPSEEK_API_KEY": "", "EER_OPENAI_API_KEY": ""}, clear=False):
            app = create_app(executor=SyntheticKernelExecutor(), workdir=tmp)
        self.assertTrue(app.state.agent_enabled)
        client = TestClient(app)
        health = client.get("/api/agent/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("ENTERPRISE_RESEARCH", health.json()["skills"])
        parsed = client.post("/api/agent/parse", json={"raw_request": "调研宁波鄞开集团"})
        self.assertEqual(parsed.status_code, 200)
        body = parsed.json()
        self.assertEqual(body["research_mode"], "ENTERPRISE")
        self.assertEqual(body["approval_status"], "PENDING", "parse must not self-approve")


class TestMarketHarvestAndProduction(unittest.TestCase):
    """回归：模板骨架绝不进交付清单（曾被推送到飞书）；生产管线幂等可跳过。"""

    def _adapter(self):
        from enterprise_energy_research.agent.tools.overseas_market_research import OverseasMarketResearchAdapter

        return OverseasMarketResearchAdapter(skill_root=Path("unused"), runner=lambda spec: {"status": "OK"})

    def test_harvest_excludes_draft_insight_template(self) -> None:
        adapter = self._adapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "deliverables").mkdir()
            insight = project / "intermediate" / "market-insight" / "market_insight_report.md"
            insight.parent.mkdir(parents=True)
            insight.write_text("---\nstatus: draft\n---\n[[填写看宏观]]\n", encoding="utf-8")
            refs = adapter.harvest(project)["artifact_refs"]
            self.assertNotIn(str(insight), refs)
            insight.write_text("---\nstatus: final\n---\n## 决策问题与证据边界\n正文\n", encoding="utf-8")
            refs = adapter.harvest(project)["artifact_refs"]
            self.assertIn(str(insight), refs)

    def test_produce_deliverables_skips_without_registered_sources(self) -> None:
        adapter = self._adapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "00_Source_Ledger.csv").write_text("source_id,source_url\n", encoding="utf-8")
            result = adapter.produce_deliverables(project)
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("0 registered sources", result["diagnostics"][0])

    def test_produce_deliverables_skips_when_already_produced(self) -> None:
        adapter = self._adapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            deliverables = project / "deliverables"
            deliverables.mkdir()
            (deliverables / "市场深度调研与商业机会报告.docx").write_bytes(b"PK")
            result = adapter.produce_deliverables(project)
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("already produced", result["diagnostics"][0])


if __name__ == "__main__":
    unittest.main()
