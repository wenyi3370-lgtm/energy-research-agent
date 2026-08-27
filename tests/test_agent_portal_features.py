"""Agent portal features: stop, goal editing, mission lookup, deep research.

TEST-AGENT-16~19: cooperative cancellation (CANCELLED), pre-approval goal
framework editing, natural-language mission lookup, and post-completion
deep-research repair (fresh budget for EXHAUSTED goals). All offline, reusing
the fakes from test_agent_orchestration.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from test_agent_orchestration import FakeGateway, FakeSkill, make_orchestrator

from energy_research_agent.agent.mission_parser import CustomGoalSpec, MissionParseResult
from energy_research_agent.agent.models import (
    ApprovalStatus,
    GoalClass,
    GoalStatus,
    MissionApproval,
    MissionStatus,
    ResearchMode,
    SkillName,
)
from energy_research_agent.domain.ids import new_sortable_id


def pending_approval_cb(mission, goals, routing):
    """Manual-approval stub: the mission stays AWAITING_APPROVAL after parse
    (the portal flow edits the goal framework before approving)."""
    return MissionApproval(
        approval_id=new_sortable_id("APPROVAL"),
        mission_id=mission.mission_id,
        decision=ApprovalStatus.PENDING,
        scope_summary="awaiting user approval",
    )


# ------------------------------------------------------ TEST-AGENT-16 stop ----

class TestStopMechanism(unittest.TestCase):
    """TEST-AGENT-16: user stop -> CANCELLED + cooperative checkpoints."""

    def test_stop_marks_pending_mission_cancelled(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        mid = outcome.mission.mission_id
        result = orchestrator.request_stop(mid)
        self.assertEqual(result["status"], "CANCELLED")
        mission = orchestrator.store.get_mission(mid)
        self.assertEqual(mission.status, MissionStatus.CANCELLED)
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("stop_requested", events)

    def test_stop_calls_skill_stop_hook(self):
        orchestrator, ent, _ = make_orchestrator()
        stop_calls: list[dict] = []
        ent.stop = lambda **kwargs: stop_calls.append(kwargs) or 1  # type: ignore[method-assign]
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        result = orchestrator.request_stop(outcome.mission.mission_id)
        self.assertEqual(result["killed_subprocesses"], 1)
        self.assertEqual(stop_calls, [{"mission_id": outcome.mission.mission_id}])

    def test_cooperative_cancel_during_run(self):
        """A stop issued while a skill executes must cancel the mission at the
        next checkpoint instead of letting it complete."""
        orchestrator, ent, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        mid = outcome.mission.mission_id
        original_execute = ent.execute

        def execute_then_stop(plan):
            result = original_execute(plan)
            orchestrator.request_stop(mid)
            return result

        ent.execute = execute_then_stop  # type: ignore[method-assign]
        run = orchestrator.run_approved(mid)
        self.assertEqual(run.status, MissionStatus.CANCELLED)
        self.assertEqual(run.mission.status, MissionStatus.CANCELLED)
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("cancelled", events)

    def test_run_approved_rejects_cancelled_mission(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        mid = outcome.mission.mission_id
        orchestrator.request_stop(mid)
        run = orchestrator.run_approved(mid)
        self.assertEqual(run.status, MissionStatus.CANCELLED)
        self.assertTrue(any("已取消" in item for item in run.diagnostics))

    def test_stale_stop_does_not_poison_next_run(self):
        """Stop before start, then a fresh run must not see the old event."""
        orchestrator, ent, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        mid = outcome.mission.mission_id
        ent.bind(outcome)
        orchestrator.request_stop(mid)
        # The user re-approves through the API layer (fresh approval record)
        # and restarts; run_approved resets the event and completes normally.
        mission = orchestrator.store.get_mission(mid)
        mission.status = MissionStatus.APPROVED
        orchestrator.store.upsert_mission(mission)
        run = orchestrator.run_approved(mid)
        self.assertEqual(run.status, MissionStatus.COMPLETED)


# ------------------------------------------------ TEST-AGENT-17 goal editing --

class TestGoalEditing(unittest.TestCase):
    """TEST-AGENT-17: pre-approval goal framework editing."""

    def test_rename_remove_add(self):
        orchestrator, _, _ = make_orchestrator(approval_cb=pending_approval_cb)
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        self.assertEqual(outcome.status, MissionStatus.AWAITING_APPROVAL)
        mid = outcome.mission.mission_id
        goals = outcome.mission.goals
        self.assertGreaterEqual(len(goals), 2, "core enterprise plan must be complete before editing")
        items = (
            [{"goal_id": goals[0].goal_id, "goal_name": "公司背景概况"}]
            + [{"goal_id": "", "goal_name": "矿业储能合作机会", "goal_description": "矿山场景储能合作"}]
            + [{"goal_id": goal.goal_id, "goal_name": goal.goal_name} for goal in goals[2:]]
        )
        edited = orchestrator.update_goals(mid, items)
        names = [goal.goal_name for goal in edited.mission.goals]
        self.assertIn("公司背景概况", names)
        self.assertNotIn(goals[1].goal_name, names, "dropped goal must disappear")
        custom = [goal for goal in edited.mission.goals if goal.goal_name == "矿业储能合作机会"]
        self.assertEqual(len(custom), 1)
        self.assertIsNotNone(custom[0].assigned_skill, "new custom goal must be routed")
        self.assertTrue(any("已移除企业核心目标" in item for item in edited.diagnostics))
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("goals_edited", events)
        # The edited framework survives persistence.
        reloaded = orchestrator.store.get_mission(mid)
        self.assertEqual(len(reloaded.goals), len(items))

    def test_edit_rejected_after_run(self):
        orchestrator, ent, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        ent.bind(outcome)
        orchestrator.run_approved(outcome.mission.mission_id)
        with self.assertRaises(ValueError):
            orchestrator.update_goals(outcome.mission.mission_id, [
                {"goal_id": outcome.mission.goals[0].goal_id, "goal_name": "改名"}
            ])

    def test_edit_requires_at_least_one_goal(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        with self.assertRaises(ValueError):
            orchestrator.update_goals(outcome.mission.mission_id, [])


# ------------------------------------------------ TEST-AGENT-18 track hint ----

class TestTrackHint(unittest.TestCase):
    """TEST-AGENT-18a: portal tab track hints never override the parse."""

    def test_enterprise_track_warns_on_market_parse(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研西班牙户用储能市场", track="enterprise")
        self.assertEqual(outcome.mission.mode, ResearchMode.MARKET, "parse is never overridden")
        self.assertTrue(any("轨道提示" in item for item in outcome.diagnostics))

    def test_market_track_warns_on_enterprise_parse(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团", track="market")
        self.assertEqual(outcome.mission.mode, ResearchMode.ENTERPRISE)
        self.assertTrue(any("轨道提示" in item for item in outcome.diagnostics))

    def test_matching_track_adds_no_warning(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团", track="enterprise")
        self.assertFalse(any("轨道提示" in item for item in outcome.diagnostics))


# ------------------------------------------------ TEST-AGENT-19 deep research -

class TestDeepResearch(unittest.TestCase):
    """TEST-AGENT-19: post-completion repair with fresh budget for EXHAUSTED."""

    def _completed_mission(self, orchestrator, ent):
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        ent.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        assert run.status == MissionStatus.COMPLETED
        return outcome.mission.mission_id

    def test_repair_resets_exhausted_budget_and_completes(self):
        orchestrator, ent, _ = make_orchestrator()
        mid = self._completed_mission(orchestrator, ent)
        mission = orchestrator.store.get_mission(mid)
        goal = mission.goals[0]
        goal.status = GoalStatus.EXHAUSTED
        goal.recovery_rounds = 10
        goal.required_evidence = list(goal.required_evidence) + ["deep_gap_field"]
        goal.success_criteria = list(goal.success_criteria) + ["deep_gap_field 存在有效证据"]
        mission.status = MissionStatus.EXHAUSTED
        orchestrator.store.upsert_mission(mission)

        # The recovery round delivers the missing field's evidence.
        ent.recover_payloads = [{
            "evidence_rows": [{
                "goal_id": goal.goal_id,
                "claim_id": new_sortable_id("CLAIM"),
                "field_name": "deep_gap_field",
                "raw_value": "value",
                "verification_status": "VERIFIED",
                "subject_role": "SUBJECT",
            }],
        }]
        outcome = orchestrator.deep_research(mid)
        self.assertEqual(outcome.status, MissionStatus.COMPLETED)
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("deep_research_started", events)
        self.assertIn("deep_research_budget_reset", events)
        self.assertIn("deep_research_completed", events)
        repaired = orchestrator.store.get_mission(mid)
        repaired_goal = next(g for g in repaired.goals if g.goal_id == goal.goal_id)
        self.assertEqual(repaired_goal.status, GoalStatus.SATISFIED)
        # Fresh budget: the round counter restarted instead of staying at 10.
        self.assertLessEqual(repaired_goal.recovery_rounds, 5)

    def test_deep_research_adds_followup_goals(self):
        def handler(request):
            if request.purpose != "agent.mission_parse":
                return None
            text = "".join(str(m.get("content", "")) for m in request.messages)
            if "南非" not in text:
                # Setup parse falls back to the offline heuristic; only the
                # deep-research request gets the scripted follow-up goal.
                return None
            return MissionParseResult(
                    mode=ResearchMode.ENTERPRISE,
                    primary_subject="宁波鄞开集团",
                    custom_goals=[CustomGoalSpec(
                        name="南非市场机会",
                        description="南非市场储能合作机会",
                        subject_name="宁波鄞开集团",
                        goal_class_hint="CUSTOM",
                    )],
                    parse_mode="llm",
                )
            return None

        orchestrator, ent, ovs = make_orchestrator(gateway=FakeGateway(handler))
        mid = self._completed_mission(orchestrator, ent)
        executed_before = set(ent.record["execute_goal_ids"]) | set(ovs.record["execute_goal_ids"])
        outcome = orchestrator.deep_research(mid, "补充调研南非市场储能合作机会")
        names = [goal.goal_name for goal in outcome.mission.goals]
        self.assertIn("南非市场机会", names, "follow-up custom goal must be added")
        # The follow-up goal is market-flavoured, so the router legitimately
        # sends it to either skill; assert it executed on one of them.
        executed_after = set(ent.record["execute_goal_ids"]) | set(ovs.record["execute_goal_ids"])
        new_executed = executed_after - executed_before
        self.assertTrue(new_executed, "the follow-up goal must actually execute")
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("deep_research_goals_added", events)

    def test_deep_research_rejects_unfinished(self):
        orchestrator, _, _ = make_orchestrator()
        outcome = orchestrator.parse_and_plan("调研宁波鄞开集团")
        with self.assertRaises(ValueError):
            orchestrator.deep_research(outcome.mission.mission_id, "补充")

    def test_deep_research_can_be_cancelled(self):
        def handler(request):
            if request.purpose != "agent.mission_parse":
                return None
            text = "".join(str(m.get("content", "")) for m in request.messages)
            if "海外产能" not in text:
                return None
            return MissionParseResult(
                mode=ResearchMode.ENTERPRISE,
                primary_subject="宁波鄞开集团",
                custom_goals=[CustomGoalSpec(
                    name="海外产能布局专项",
                    description="海外储能产能布局",
                    subject_name="宁波鄞开集团",
                    goal_class_hint="CUSTOM",
                )],
                parse_mode="llm",
            )

        orchestrator, ent, ovs = make_orchestrator(gateway=FakeGateway(handler))
        mid = self._completed_mission(orchestrator, ent)

        def wrap_stop_after(skill):
            original_execute = skill.execute

            def execute_then_stop(plan):
                result = original_execute(plan)
                orchestrator.request_stop(mid)
                return result

            skill.execute = execute_then_stop  # type: ignore[method-assign]

        wrap_stop_after(ent)
        wrap_stop_after(ovs)
        # A follow-up goal triggers execution, which stops the mission.
        outcome = orchestrator.deep_research(mid, "补充调研该企业的海外产能布局")
        self.assertEqual(outcome.status, MissionStatus.CANCELLED)
        self.assertEqual(orchestrator.store.get_mission(mid).status, MissionStatus.CANCELLED)


class TestDeepResearchMarketMode(unittest.TestCase):
    """Deep research (portal tab 3) must also work for MARKET-mode missions:
    a locked market task is repaired through the overseas market skill."""

    def _completed_market_mission(self, orchestrator, ovs):
        outcome = orchestrator.parse_and_plan("调研西班牙户用储能市场")
        assert outcome.mission.mode == ResearchMode.MARKET
        ovs.bind(outcome)
        run = orchestrator.run_approved(outcome.mission.mission_id)
        assert run.status == MissionStatus.COMPLETED
        return outcome.mission.mission_id

    def test_market_mission_repair_runs_through_market_skill(self):
        orchestrator, ent, ovs = make_orchestrator()
        mid = self._completed_market_mission(orchestrator, ovs)
        mission = orchestrator.store.get_mission(mid)
        goal = mission.goals[0]
        goal.status = GoalStatus.EXHAUSTED
        goal.recovery_rounds = 10
        goal.required_evidence = list(goal.required_evidence) + ["deep_gap_field"]
        goal.success_criteria = list(goal.success_criteria) + ["deep_gap_field 存在有效证据"]
        mission.status = MissionStatus.EXHAUSTED
        orchestrator.store.upsert_mission(mission)

        # The recovery round delivers the missing field's evidence.
        ovs.recover_payloads = [{
            "evidence_rows": [{
                "goal_id": goal.goal_id,
                "claim_id": new_sortable_id("CLAIM"),
                "field_name": "deep_gap_field",
                "raw_value": "value",
                "verification_status": "VERIFIED",
                "subject_role": "SUBJECT",
            }],
        }]
        outcome = orchestrator.deep_research(mid)
        self.assertEqual(outcome.status, MissionStatus.COMPLETED)
        events = [t["event"] for t in orchestrator.store.trace_for(mid)]
        self.assertIn("deep_research_started", events)
        self.assertIn("deep_research_budget_reset", events)
        self.assertIn("deep_research_completed", events)
        # Repair traffic goes through the overseas market skill, not enterprise.
        self.assertTrue(ovs.record["recover_calls"], "market goal repair must use the market skill")
        self.assertFalse(ent.record["recover_calls"], "enterprise skill must not be invoked")
        repaired = orchestrator.store.get_mission(mid)
        repaired_goal = next(g for g in repaired.goals if g.goal_id == goal.goal_id)
        self.assertEqual(repaired_goal.status, GoalStatus.SATISFIED)
        self.assertLessEqual(repaired_goal.recovery_rounds, 5)


# ------------------------------------------------------ API surface ----------

class TestAgentPortalApi(unittest.TestCase):
    """API endpoints: stop / goals / deep-research guards / missions filters."""

    def _client(self):
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from energy_research_agent.automation.api.app import create_app
        from energy_research_agent.automation.executor import SyntheticKernelExecutor

        tmp = Path(tempfile.mkdtemp(prefix="agent-portal-api-"))
        with patch.dict(os.environ, {"ERA_DEEPSEEK_API_KEY": "", "ERA_OPENAI_API_KEY": ""}, clear=False):
            app = create_app(executor=SyntheticKernelExecutor(), workdir=tmp)
        self.assertTrue(app.state.agent_enabled)
        return TestClient(app), app.state.agent_orchestrator

    def test_missions_filter_by_query_and_status(self):
        client, _ = self._client()
        a = client.post("/api/agent/parse", json={"raw_request": "调研宁波鄞开集团", "track": "enterprise"}).json()
        client.post("/api/agent/parse", json={"raw_request": "调研西班牙户用储能市场", "track": "market"})
        found = client.get("/api/agent/missions", params={"query": "鄞开"}).json()["missions"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["mission_id"], a["mission_id"])
        pending = client.get("/api/agent/missions", params={"status": "AWAITING_APPROVAL"}).json()["missions"]
        self.assertEqual(len(pending), 2)
        self.assertIn("goal_summary", pending[0])
        self.assertIn("updated_at", pending[0])

    def test_stop_and_approve_guard(self):
        client, _ = self._client()
        parsed = client.post("/api/agent/parse", json={"raw_request": "调研宁波鄞开集团"}).json()
        mid = parsed["mission_id"]
        stopped = client.post(f"/api/agent/mission/{mid}/stop")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["status"], "CANCELLED")
        approve = client.post(f"/api/agent/mission/{mid}/approve", json={"approve": True, "message": ""})
        self.assertEqual(approve.status_code, 409, "a cancelled mission must not be approvable")
        missing = client.post("/api/agent/mission/MISSION-NOPE/stop")
        self.assertEqual(missing.status_code, 404)

    def test_goals_endpoint_edit(self):
        client, _ = self._client()
        parsed = client.post("/api/agent/parse", json={"raw_request": "调研宁波鄞开集团"}).json()
        mid = parsed["mission_id"]
        detail = client.get(f"/api/agent/mission/{mid}").json()
        goals = detail["mission"]["goals"]
        payload = {"goals": (
            [{"goal_id": goals[0]["goal_id"], "goal_name": "公司背景概况"},
             {"goal_id": "", "goal_name": "新增专项"}]
            + [{"goal_id": goal["goal_id"], "goal_name": goal["goal_name"]} for goal in goals[1:]]
        )}
        edited = client.post(f"/api/agent/mission/{mid}/goals", json=payload)
        self.assertEqual(edited.status_code, 200)
        self.assertIn("公司背景概况", str(edited.json()["goal_groups"]))
        missing = client.post("/api/agent/mission/MISSION-NOPE/goals", json=payload)
        self.assertEqual(missing.status_code, 404)

    def test_deep_research_endpoint_guards(self):
        client, _ = self._client()
        parsed = client.post("/api/agent/parse", json={"raw_request": "调研宁波鄞开集团"}).json()
        mid = parsed["mission_id"]
        resp = client.post(f"/api/agent/mission/{mid}/deep-research", json={"raw_request": ""})
        self.assertEqual(resp.status_code, 409, "unfinished missions must be rejected")
        missing = client.post("/api/agent/mission/MISSION-NOPE/deep-research", json={"raw_request": ""})
        self.assertEqual(missing.status_code, 404)

    def test_track_hint_in_parse_response(self):
        client, _ = self._client()
        parsed = client.post(
            "/api/agent/parse",
            json={"raw_request": "调研西班牙户用储能市场", "track": "enterprise"},
        ).json()
        self.assertTrue(any("轨道提示" in item for item in parsed.get("diagnostics", [])))


if __name__ == "__main__":
    unittest.main()
