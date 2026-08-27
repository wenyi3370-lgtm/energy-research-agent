"""Recovery planning and executed-round accounting (§22-§25).

A recovery round counts only when a genuinely different strategy actually ran
(§24): different queries, a real search execution, no adapter-level total
failure. The per-goal round cap comes from AgentPolicies (config), never from
a prompt. Reaching the cap produces an Auditable Evidence Limitation — the
first missing-data round is never allowed to degrade immediately (§25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import model_validator

from energy_research_agent.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .models import (
    AgentStrictModel,
    FailureClass,
    GoalEvaluation,
    GoalStatus,
    RecoveryPlan,
    ResearchGoal,
    SkillAttempt,
    SkillName,
    SkillRunResult,
)
from .policies import NON_EXECUTED_FAILURES


class _LLMRecovery(AgentStrictModel):
    failure_reason: str = ""
    new_strategy: str = ""
    new_source_categories: list[str] = []
    new_queries: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _accept_common_llm_synonyms(cls, data: Any) -> Any:
        """Models answer with natural field names (analysis/strategy/queries).

        Map those onto the strict schema and drop anything unknown, so a
        well-formed recovery answer is never rejected by extra-forbidden
        (observed: every live recovery round fell back to the template
        engine because the model's ``analysis``/``strategy``/``queries``
        keys tripped ``extra_forbidden``).
        """
        if not isinstance(data, dict):
            return data
        aliases = {
            "analysis": "failure_reason",
            "reason": "failure_reason",
            "strategy": "new_strategy",
            "queries": "new_queries",
            "source_categories": "new_source_categories",
            "sources": "new_source_categories",
        }
        known = {"failure_reason", "new_strategy", "new_source_categories", "new_queries"}
        mapped: dict[str, Any] = {}
        for key, value in data.items():
            target = aliases.get(key, key)
            if target in known and target not in mapped:
                mapped[target] = value
        for list_field in ("new_queries", "new_source_categories"):
            if isinstance(mapped.get(list_field), str):
                mapped[list_field] = [mapped[list_field]]
        if not str(mapped.get("new_strategy") or "").strip():
            mapped["new_strategy"] = str(
                mapped.get("failure_reason") or "更换来源类别与查询表述重新检索"
            )
        return mapped


@dataclass
class RecoveryLedger:
    """Code-owned accounting of executed recovery rounds per goal."""

    rounds: dict[str, int] = field(default_factory=dict)
    previous_queries: dict[str, set[str]] = field(default_factory=dict)

    def executed_rounds(self, goal_id: str) -> int:
        return self.rounds.get(goal_id, 0)

    def record(self, goal_id: str, result: SkillRunResult) -> bool:
        """Return True when this result counts as one executed round."""
        executed_attempts = [
            a for a in result.executed_attempts
            if a.failure_class is None or a.failure_class.value not in NON_EXECUTED_FAILURES
        ]
        if not executed_attempts:
            return False
        seen = self.previous_queries.setdefault(goal_id, set())
        new_queries = {
            query for attempt in executed_attempts for query in attempt.queries if query
        }
        if not new_queries or new_queries <= seen:
            # §24: repeating the exact same queries is not a recovery round.
            return False
        seen.update(new_queries)
        self.rounds[goal_id] = self.rounds.get(goal_id, 0) + 1
        return True


class RecoveryPlanner:
    """Plans the NEXT round from the previous round's failure (§22)."""

    def __init__(self, gateway: ModelGateway | None = None, *, max_rounds_per_goal: int = 10) -> None:
        self.gateway = gateway
        self.max_rounds_per_goal = max_rounds_per_goal

    def plan(
        self,
        goal: ResearchGoal,
        evaluation: GoalEvaluation,
        *,
        failed_round: int,
        previous_attempts: list[SkillAttempt],
        evidence_sample: list[dict[str, Any]],
        max_rounds: int | None = None,
    ) -> RecoveryPlan:
        # ``max_rounds`` lets the deep-research repair pass grant EXHAUSTED
        # goals a fresh, separately capped budget without touching the
        # production per-goal ceiling.
        ceiling = max_rounds if max_rounds is not None else self.max_rounds_per_goal
        if goal.recovery_rounds >= ceiling:
            return RecoveryPlan(
                recovery_plan_id=f"RECOVERY-EXHAUSTED-{goal.goal_id}",
                goal_ids=[goal.goal_id],
                failed_round=failed_round,
                failure_reason=f"已达单目标有效补救上限 {ceiling} 轮",
                failure_class=FailureClass.RECOVERY_EXHAUSTED,
                new_strategy="停止补救，生成 Auditable Evidence Limitation",
                new_source_categories=[],
                new_queries=[],
            )

        llm: _LLMRecovery | None = None
        if self.gateway is not None:
            try:
                llm = self._llm_plan(goal, evaluation, previous_attempts, evidence_sample)
            except (GatewayError, ValueError):
                llm = None
        if llm is None or not llm.new_queries:
            llm = self._deterministic_plan(goal, failed_round)
        return RecoveryPlan(
            recovery_plan_id=f"RECOVERY-{goal.goal_id}-{failed_round + 1}",
            goal_ids=[goal.goal_id],
            failed_round=failed_round,
            failure_reason=evaluation.evaluation_reason,
            failure_class=evaluation.failure_class,
            new_strategy=llm.new_strategy,
            new_source_categories=llm.new_source_categories,
            new_queries=llm.new_queries,
            expected_evidence_delta="新来源类别证据进入统一证据层",
        )

    def _llm_plan(
        self,
        goal: ResearchGoal,
        evaluation: GoalEvaluation,
        previous_attempts: list[SkillAttempt],
        evidence_sample: list[dict[str, Any]],
    ) -> _LLMRecovery:
        from .evaluator import jsonable

        request = StructuredRequest[_LLMRecovery](
            purpose="agent.recovery_plan",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是研究补救规划器。上一轮搜索未满足目标，请制定【不同】的下一轮策略。"
                        "只输出 JSON，字段严格为 failure_reason / new_strategy / "
                        "new_source_categories / new_queries 四个，禁止输出任何其他字段。"
                        "规则：1) 禁止重复 previous_queries 中已出现的 query；"
                        "2) 分析失败原因后更换来源类别与搜索表述"
                        "（如环评/建设项目/投产公告/政府项目/招标/年报/子公司/地方工信/能源评价/"
                        "行业数据库/平台评论等）；"
                        "3) 每个 query 必须显式包含研究主体名称与缺失证据的语义；"
                        "4) query 语言跟随信息来源地：中国主体或中国市场用中文；海外主体用英文或"
                        "其所在国语言；海外市场目标按 geographies 用市场所在国语言或英文；"
                        "中国主体的海外布局目标可中文为主并酌情追加外语 query；"
                        "5) new_queries 给 3-6 条自然语言查询，面向真实可搜到的公开来源，"
                        "不要堆砌无关关键词；市场目标 query 必须包含 geography + 品类 + 市场对象。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"goal_name={goal.goal_name}\ngoal_description={goal.goal_description}\n"
                        f"subject={goal.subject_name}\n"
                        f"assigned_skill={goal.assigned_skill}\n"
                        f"geographies={goal.scope.get('geographies') or []}\n"
                        f"evaluation_reason={evaluation.evaluation_reason}\n"
                        f"unmet={evaluation.unmet_criteria}\n"
                        f"previous_queries={[q for a in previous_attempts for q in a.queries]}\n"
                        f"evidence_sample={jsonable(evidence_sample[:20])}"
                    ),
                },
            ],
            response_model=_LLMRecovery,
        )
        return self.gateway.structured(request)

    # English hint table for non-Chinese subjects / overseas market goals:
    # the deterministic fallback must never inject raw English FIELD NAMES
    # (company_identity...) nor Chinese keywords into foreign searches.
    _ENGLISH_FAMILY_HINTS = {
        "company_identity": "company profile registered entity official website",
        "ownership_structure": "ownership structure parent company shareholder annual report",
        "organization": "organization management board of directors",
        "subsidiaries": "subsidiaries affiliates group structure",
        "factories": "factory production base plant location address",
        "locations": "headquarters location site address",
        "financials": "revenue net profit annual report financial statements",
        "revenue": "revenue segment revenue annual report",
        "profit": "net profit gross margin R&D spending annual report",
        "employees": "number of employees headcount workforce",
        "capacity": "production capacity annual output expansion project",
        "production_lines": "production line process equipment",
        "products": "product center product catalog product list",
        "product_series": "product series product family",
        "product_models": "product model SKU",
        "product_parameters": "technical parameters specifications datasheet manual PDF",
        "customers": "key customers contracts orders application cases",
        "sales_channels": "sales channel distributor dealer network",
        "suppliers": "suppliers procurement supply chain",
        "certifications": "certification certificate test report",
        "technology": "core technology R&D platform technology roadmap",
        "patents": "patent invention intellectual property",
        "industry_position": "market share ranking industry position",
        "energy_consumption": "energy consumption electricity usage sustainability report",
        "energy_projects": "energy project solar storage charging station",
        "overseas_opportunities": "overseas export subsidiary distributor certification",
        "risks": "operational risk compliance risk litigation",
    }

    @classmethod
    def _fallback_hint(cls, field: str, *, chinese_subject: bool, overseas_market: bool) -> str:
        """Pick the fallback keyword language from the SUBJECT, not the round.

        Chinese subjects search Chinese sources; foreign subjects and market
        goals search English/local-language sources. The enterprise track may
        investigate overseas companies, so the subject text decides.
        """
        from energy_research_agent.research.planner import GOAL_FAMILIES

        if overseas_market or not chinese_subject:
            return cls._ENGLISH_FAMILY_HINTS.get(field.lower(), field)
        chinese_hints = dict(GOAL_FAMILIES)
        return chinese_hints.get(field, field)

    @staticmethod
    def _deterministic_plan(goal: ResearchGoal, failed_round: int) -> _LLMRecovery:
        """Degraded planner: the repo's own R4 coverage engine.

        Uses ResearchPlanner.coverage_queries, which rotates the skill's
        RECOVERY_STRATEGIES (10 distinct source strategies) and anchors every
        query on the canonical subject — never a hand-rolled lane list
        (SKILL.md Search Recall and Coverage contract). Hint keywords follow
        the subject's language: Chinese subjects get the Chinese GOAL_FAMILIES
        keywords, foreign subjects / market goals get English hints.
        """
        from energy_research_agent.research.planner import RECOVERY_STRATEGIES, ResearchPlanner

        subject = goal.subject_name or "主体"
        missing = list(goal.required_evidence) or ["公开事实"]
        chinese_subject = any("\u4e00" <= char <= "\u9fff" for char in subject)
        overseas_market = goal.assigned_skill == SkillName.OVERSEAS_MARKET_RESEARCH
        geographies = [str(geo).strip() for geo in (goal.scope.get("geographies") or []) if str(geo).strip()]
        # Synthesize coverage-gap records so the repo engine can target them.
        class _Gap:
            def __init__(self, field: str) -> None:
                self.searchable = True
                self.gap_code = f"coverage-{field}"
                self.field_name = field
                hint = RecoveryPlanner._fallback_hint(
                    field, chinese_subject=chinese_subject, overseas_market=overseas_market,
                )
                if overseas_market and geographies:
                    hint = f"{hint} {' '.join(geographies)}"
                self.retry_hint = hint
                self.description = f"缺少 {field} 有效证据"
                self.found = ""
                self.severity = "high"

        queries = ResearchPlanner().coverage_queries(
            subject, [_Gap(field) for field in missing[:3]], retry_round=max(1, failed_round + 1)
        )
        strategy = RECOVERY_STRATEGIES[failed_round % len(RECOVERY_STRATEGIES)]
        return _LLMRecovery(
            failure_reason="LLM 补救规划不可用，使用仓库 R4 覆盖引擎（RECOVERY_STRATEGIES 轮换）",
            new_strategy=f"来源策略[{failed_round + 1}/{len(RECOVERY_STRATEGIES)}]：{strategy}",
            new_source_categories=[strategy],
            new_queries=[query.query for query in queries],
        )


def auditable_limitation(goal: ResearchGoal, evaluation: GoalEvaluation) -> dict[str, Any]:
    """The only acceptable end-state for an exhausted goal (§25)."""
    return {
        "goal_id": goal.goal_id,
        "goal_name": goal.goal_name,
        "type": "AUDITABLE_EVIDENCE_LIMITATION",
        "recovery_rounds_executed": goal.recovery_rounds,
        "missing": evaluation.required_evidence_missing,
        "reason": evaluation.evaluation_reason,
    }
