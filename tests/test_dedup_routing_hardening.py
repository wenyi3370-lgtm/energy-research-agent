"""Regression: restatement custom goals must neither escape dedup nor reach the overseas lane.

Live incident (MISSION-01M0YD91629V0ZHP2MC4Z0PH8G): three pure restatements
(企业概况调查 / 产品与工厂布局调查 / 能源合作机会分析) carried
geographies=["苏州"] (the subject's own city), escaped _redundant_with_core
through the geography escape hatch, then inherited mission geographies inside
the routing item and burned the shared budget on OVERSEAS_MARKET_RESEARCH,
which exported dozens of valueless source-ledger shells.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.agent.goal_planner import GoalPlanner
from enterprise_energy_research.agent.market_evidence import MarketEvidenceImporter
from enterprise_energy_research.agent.mission_parser import CustomGoalSpec
from enterprise_energy_research.agent.models import (
    GoalClass,
    PriorityLevel,
    ResearchGoal,
    ResearchMission,
    SkillName,
    SubjectType,
)
from enterprise_energy_research.agent.policies import AgentPolicies
from enterprise_energy_research.agent.router import ResearchSkillRouter
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.evidence.store import EvidenceStore

SUBJECT = "苏州昀冢电子科技股份有限公司"


def _spec(name: str, hint: str = "CUSTOM", geographies: list[str] | None = None) -> CustomGoalSpec:
    return CustomGoalSpec(
        name=name,
        description=f"调查{SUBJECT}的{name}",
        subject_name=SUBJECT,
        goal_class_hint=hint,
        geographies=geographies or [],
    )


def _goal(name: str, scope: dict | None = None) -> ResearchGoal:
    return ResearchGoal(
        goal_id=new_sortable_id("GOAL"),
        goal_name=name,
        goal_description=name,
        subject_id=SUBJECT,
        subject_name=SUBJECT,
        subject_type=SubjectType.CUSTOM,
        goal_class=GoalClass.CUSTOM,
        scope=scope or {},
        priority=PriorityLevel.P1,
        success_criteria=["该专项问题获得了直接相关证据"],
    )


class TestRestatementDedupHardening(unittest.TestCase):
    """City-echo geographies must no longer defeat the dedup gate."""

    def test_city_echo_geographies_no_longer_defeat_dedup(self):
        for name in ("企业概况调查", "产品与工厂布局调查", "能源合作机会分析"):
            spec = _spec(name, geographies=["苏州"])
            self.assertTrue(
                GoalPlanner._redundant_with_core(spec, SUBJECT),
                f"{name} must be dropped as a core-plan restatement",
            )

    def test_plain_restatements_still_dropped(self):
        self.assertTrue(GoalPlanner._redundant_with_core(_spec("企业概况调查"), SUBJECT))

    def test_genuine_regional_study_survives(self):
        spec = _spec("德国渠道调研", hint="CHANNEL", geographies=["德国"])
        self.assertFalse(GoalPlanner._redundant_with_core(spec, SUBJECT))

    def test_market_scoped_class_survives(self):
        spec = _spec("公司概况", hint="MARKET", geographies=["西班牙"])
        self.assertFalse(GoalPlanner._redundant_with_core(spec, SUBJECT))

    def test_novel_topic_survives(self):
        self.assertFalse(GoalPlanner._redundant_with_core(_spec("矿山储能应用场景"), SUBJECT))


class TestRoutingNoMissionGeoInheritance(unittest.TestCase):
    """Scope-less CUSTOM goals must not inherit mission geographies into routing."""

    def test_scope_less_custom_goal_stays_enterprise(self):
        mission = ResearchMission(
            mission_id=new_sortable_id("MISSION"),
            raw_request=f"调查{SUBJECT}",
            primary_subject=SUBJECT,
            geographies=["苏州"],
        )
        decisions = ResearchSkillRouter(gateway=None).route(mission, [_goal("企业概况调查")])
        self.assertEqual(decisions[0].assigned_skill, SkillName.ENTERPRISE_RESEARCH)

    def test_scope_geographies_still_route_overseas(self):
        mission = ResearchMission(
            mission_id=new_sortable_id("MISSION"),
            raw_request="西班牙渠道专项",
        )
        goal = _goal("西班牙渠道调研", scope={"geographies": ["西班牙"]})
        decisions = ResearchSkillRouter(gateway=None).route(mission, [goal])
        self.assertEqual(decisions[0].assigned_skill, SkillName.OVERSEAS_MARKET_RESEARCH)


class TestImporterRejectsValuelessRows(unittest.TestCase):
    """Source-only ledger shells must never become claims."""

    def test_empty_raw_value_rows_are_skipped(self):
        tmp = Path(tempfile.mkdtemp(prefix="agent-valueless-"))
        store = EvidenceStore(tmp / "ev.sqlite3")
        importer = MarketEvidenceImporter(store, AgentPolicies.load())
        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="空壳行回归")
        goal = _goal("企业概况调查")
        report = importer.import_rows(
            mission=mission,
            goals=[goal],
            originating_skill=SkillName.OVERSEAS_MARKET_RESEARCH.value,
            rows=[
                {"goal_id": goal.goal_id, "source_id": "S1", "source_url": "https://example.com/a",
                 "evidence_item": "company_overview", "raw_value": "", "value_class": "observed"},
                {"goal_id": goal.goal_id, "source_id": "S2", "source_url": "https://example.com/b",
                 "evidence_item": "company_overview", "raw_value": "2013年成立", "value_class": "observed"},
            ],
        )
        self.assertEqual(report.claims_created, 1, "only the row with a real value becomes a claim")
        self.assertEqual(report.skipped_unsupported, 1)


class TestAnySearchRegistrationNotice(unittest.TestCase):
    """Anonymous-mode auto-registration notices must be infrastructure blocks, not hits."""

    def test_notice_is_provider_blocked(self):
        from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter

        notice = (
            "Your account and API key have been automatically generated. "
            "Use the API key below to continue.\n"
            "username=as_auto_probe\npassword=probe\napi_key=as_sk_probe"
        )
        self.assertTrue(AnySearchCliAdapter._provider_error_message(notice))

    def test_normal_content_not_flagged(self):
        from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter

        self.assertIsNone(
            AnySearchCliAdapter._provider_error_message(
                "苏州昀冢电子科技股份有限公司成立于2013年，主营MLCC等电子元件。"
            )
        )


if __name__ == "__main__":
    unittest.main()
