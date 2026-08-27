"""Regression tests: LLM-directed recovery queries (2026-08-26 fix).

Live run #3 showed 90 minutes of recovery rounds with zero new evidence:
the LLM's recovery plan was rejected by ``extra_forbidden`` (the model
answered with analysis/strategy/queries), every round fell back to English
field-name template queries, and those queries were re-templated by the
keyword engine instead of being searched verbatim. These tests pin all
three repairs:

1. ``_LLMRecovery`` accepts common LLM field synonyms and drops extras.
2. The deterministic fallback picks keyword LANGUAGE from the subject
   (Chinese subjects -> Chinese hints; foreign subjects / market goals ->
   English hints), never raw English field names.
3. Recovery note lines ("第N轮补采：...") are parsed and executed verbatim.
"""

import unittest

from enterprise_energy_research.agent.models import (
    GoalClass,
    GoalEvaluation,
    GoalStatus,
    ResearchGoal,
    SkillName,
    SubjectType,
)
from enterprise_energy_research.agent.recovery import RecoveryPlanner, _LLMRecovery
from enterprise_energy_research.automation.orchestration import split_recovery_notes
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.research.planner import ResearchPlanner


def _goal(
    subject: str = "苏州昀冢电子科技股份有限公司",
    *,
    skill: SkillName | None = SkillName.ENTERPRISE_RESEARCH,
    required_evidence: list[str] | None = None,
    geographies: list[str] | None = None,
) -> ResearchGoal:
    return ResearchGoal(
        goal_id=new_sortable_id("GOAL"),
        goal_name="公司概况",
        goal_description="d",
        subject_id="e",
        subject_name=subject,
        subject_type=SubjectType.ENTERPRISE,
        goal_class=GoalClass.CORE_ENTERPRISE,
        assigned_skill=skill,
        required_evidence=required_evidence or ["company_identity", "ownership_structure"],
        scope={"geographies": geographies or []},
    )


def _evaluation(goal: ResearchGoal) -> GoalEvaluation:
    return GoalEvaluation(
        goal_id=goal.goal_id,
        status=GoalStatus.PARTIAL,
        evaluation_reason="证据不足",
        required_evidence_missing=list(goal.required_evidence)[:2],
    )


class TestLLMRecoverySchemaTolerance(unittest.TestCase):
    """The strict schema must never reject a well-formed LLM answer."""

    def test_synonym_fields_are_mapped(self):
        parsed = _LLMRecovery.model_validate({
            "analysis": "上一轮未执行任何查询",
            "strategy": "改用官方工商来源",
            "queries": ["苏州昀冢电子科技股份有限公司 成立时间 注册地 工商登记"],
        })
        self.assertEqual(parsed.failure_reason, "上一轮未执行任何查询")
        self.assertEqual(parsed.new_strategy, "改用官方工商来源")
        self.assertEqual(len(parsed.new_queries), 1)

    def test_unknown_fields_are_dropped_not_rejected(self):
        parsed = _LLMRecovery.model_validate({
            "failure_reason": "x",
            "new_strategy": "s",
            "new_queries": ["q"],
            "confidence": 0.9,
            "thinking": "...",
        })
        self.assertEqual(parsed.new_queries, ["q"])

    def test_canonical_fields_win_over_synonyms(self):
        parsed = _LLMRecovery.model_validate({
            "new_queries": ["canonical"],
            "queries": ["synonym"],
        })
        self.assertEqual(parsed.new_queries, ["canonical"])

    def test_scalar_query_string_is_coerced_to_list(self):
        parsed = _LLMRecovery.model_validate({"strategy": "s", "queries": "single query"})
        self.assertEqual(parsed.new_queries, ["single query"])

    def test_missing_strategy_gets_non_empty_default(self):
        parsed = _LLMRecovery.model_validate({"queries": ["q"]})
        self.assertTrue(parsed.new_strategy.strip())


class TestFallbackLanguageFollowsSubject(unittest.TestCase):
    """Deterministic fallback keyword language is decided by the subject,
    never by a hardcoded Chinese/English choice."""

    def test_chinese_subject_gets_chinese_hints(self):
        plan = RecoveryPlanner._deterministic_plan(_goal(), failed_round=0)
        joined = " ".join(plan.new_queries)
        self.assertIn("官网", joined)
        self.assertNotIn("company_identity", joined)
        self.assertNotIn("ownership_structure", joined)

    def test_foreign_subject_gets_english_hints(self):
        plan = RecoveryPlanner._deterministic_plan(
            _goal(subject="Siemens AG", required_evidence=["financials", "factories"]),
            failed_round=0,
        )
        joined = " ".join(plan.new_queries)
        self.assertIn("annual report", joined)
        self.assertIn("factory", joined)
        self.assertNotIn("年报", joined)

    def test_market_goal_gets_english_hints_with_geography(self):
        plan = RecoveryPlanner._deterministic_plan(
            _goal(
                subject="德国户用储能市场",
                skill=SkillName.OVERSEAS_MARKET_RESEARCH,
                required_evidence=["financials"],
                geographies=["德国"],
            ),
            failed_round=0,
        )
        joined = " ".join(plan.new_queries)
        self.assertIn("annual report", joined)
        self.assertIn("德国", joined)


class TestDirectRecoveryQueriesVerbatim(unittest.TestCase):
    """Agent-planned recovery queries must be searched as planned."""

    def test_query_text_is_kept_verbatim(self):
        planner = ResearchPlanner()
        queries = planner.direct_recovery_queries(
            "苏州昀冢电子科技股份有限公司",
            ['"苏州昀冢电子科技股份有限公司" 成立年份 注册资本 工商登记信息 国家企业信用信息公示系统'],
        )
        self.assertEqual(len(queries), 1)
        self.assertEqual(
            queries[0].query,
            '"苏州昀冢电子科技股份有限公司" 成立年份 注册资本 工商登记信息 国家企业信用信息公示系统',
        )
        self.assertEqual(queries[0].collection_round, "R4")

    def test_subject_anchored_when_missing(self):
        queries = ResearchPlanner().direct_recovery_queries(
            "苏州昀冢电子科技股份有限公司", ["股权结构 实际控制人 年报"],
        )
        self.assertTrue(queries[0].query.startswith('"苏州昀冢电子科技股份有限公司"'))
        self.assertEqual(queries[0].topic, "ownership_structure")

    def test_unknown_topic_routes_to_custom_requirement(self):
        queries = ResearchPlanner().direct_recovery_queries(
            "苏州昀冢电子科技股份有限公司", ["高管薪酬 股权激励计划 限售股解禁"],
        )
        self.assertEqual(queries[0].topic, "custom_requirement")

    def test_empty_texts_are_skipped(self):
        queries = ResearchPlanner().direct_recovery_queries("主体", ["", "   "])
        self.assertEqual(queries, [])


class TestRecoveryNotesParsing(unittest.TestCase):
    """recovery_only runs execute 第N轮补采 lines and nothing else."""

    def test_recovery_lines_extracted_with_round(self):
        notes = (
            "调查企业概况与工厂布局\n"
            "第2轮补采：示例公司 环评 建设项目\n"
            "第2轮补采：示例公司 投产 公告"
        )
        texts, round_no = split_recovery_notes(notes)
        self.assertEqual(texts, ["示例公司 环评 建设项目", "示例公司 投产 公告"])
        self.assertEqual(round_no, 2)

    def test_max_round_wins_when_lines_mix(self):
        texts, round_no = split_recovery_notes("第1轮补采：a\n第3轮补采：b")
        self.assertEqual((len(texts), round_no), (2, 3))

    def test_no_recovery_lines_returns_empty(self):
        texts, round_no = split_recovery_notes("普通需求文本")
        self.assertEqual((texts, round_no), ([], 0))

    def test_targeted_plan_carries_direct_queries_only(self):
        plan = ResearchPlanner().targeted_plan(
            "RUN", "示例公司", "",
            direct_recovery_texts=["示例公司 环评 建设项目"],
            recovery_round=2,
        )
        self.assertEqual(len(plan.queries), 1)
        self.assertIn("环评", plan.queries[0].query)
        self.assertEqual(plan.queries[0].trigger, "coverage")


if __name__ == "__main__":
    unittest.main()
