"""Goal planning: enterprise core plan + additive user goals + market goals.

§11 invariant: an enterprise subject always keeps the fixed core plan
(概况/主营业务/产品/工厂/产能/生产线/技术/财务/客户/渠道/战略/市场证明/合作机会);
user-specific asks are ADDITIVE goals and never shrink the core budget.
Additive goals that merely RESTATE the core plan are dropped (§budget):
they duplicate work the core goals already own and burn the shared
whole-mission iteration budget without adding any evidence scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from energy_research_agent.domain.ids import new_sortable_id

from .mission_parser import MissionParseResult
from .models import (
    GoalClass,
    PriorityLevel,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
    SubjectType,
)


@dataclass(frozen=True)
class CoreGoalSpec:
    name: str
    description: str
    required_evidence: tuple[str, ...]
    priority: PriorityLevel


CORE_ENTERPRISE_GOALS: tuple[CoreGoalSpec, ...] = (
    CoreGoalSpec(
        "公司概况",
        "主体身份、成立时间、注册地、股权结构、集团归属与治理概况",
        ("company_identity", "ownership_structure"),
        PriorityLevel.P0,
    ),
    CoreGoalSpec(
        "主营业务",
        "主营业务构成、业务板块与收入结构",
        ("revenue", "profit"),
        PriorityLevel.P1,
    ),
    CoreGoalSpec(
        "产品与产品线",
        "主要产品、产品线、参数与迭代",
        ("products", "product_parameters"),
        PriorityLevel.P1,
    ),
    CoreGoalSpec(
        "工厂与生产基地",
        "工厂分布、基地数量与区域",
        ("factories",),
        PriorityLevel.P1,
    ),
    CoreGoalSpec(
        "产能与产线",
        "产能规模、利用率与生产线布局",
        ("capacity", "production_lines"),
        PriorityLevel.P1,
    ),
    CoreGoalSpec(
        "技术与研发",
        "核心技术、专利、研发体系",
        ("technology", "patents"),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "财务与经营",
        "营收、利润、增长与经营质量",
        ("financials",),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "客户与市场证明",
        "主要客户、标杆项目与市场验证",
        ("customers", "customer_market_proof"),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "渠道与销售",
        "销售渠道、经销/直销结构与区域覆盖",
        ("sales_channels",),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "战略与投资",
        "战略方向、扩产计划与投资轨迹",
        ("strategic_trajectory", "business_drivers"),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "市场证明与竞争",
        "行业地位、竞争格局与同业对比",
        ("competitive_position", "industry_position"),
        PriorityLevel.P2,
    ),
    CoreGoalSpec(
        "合作机会",
        "潜在合作方向、需求与接口",
        ("cooperation_timing", "overseas_opportunities"),
        PriorityLevel.P3,
    ),
)

# Market-side goal families the planner materializes for MARKET/HYBRID missions.
MARKET_GOAL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("市场定义与规模", "目标市场边界、TAM/SAM/SOM 与增长"),
    ("政策与准入", "政策、补贴、电价、认证与市场准入"),
    ("客户与场景", "用户需求、应用场景与负荷模型"),
    ("竞争格局与产品对标", "竞争者、exact-model benchmark 与产品价格"),
    ("渠道与服务", "销售渠道、服务网络与用户评价"),
    ("经济性与商业模式", "NPV/IRR/Payback 与商业模式"),
)


# Generic modifiers that never make a custom goal additive on their own.
_CORE_RESTATEMENT_STOP_TERMS: tuple[str, ...] = (
    "调查", "研究", "分析", "评估", "专项", "情况", "现状", "布局",
    "体系", "结构", "方向", "领域", "方面", "机会", "企业", "公司",
    "集团", "以及", "及其", "与", "和", "及", "或", "的", "了", "是", "在", "对",
)

# Topic keywords of the fixed core plan.  A custom goal whose name is fully
# covered by these keywords (plus generic modifiers) only restates work the
# core goals already own.  Longest-first matching keeps 能源合作机会 from
# being mis-split.  竞争对手 is intentionally NOT a keyword: a competitor
# deep-dive is genuine extra scope beyond 市场证明与竞争.
_CORE_TOPIC_KEYWORDS: tuple[str, ...] = (
    # 公司概况 / 主营业务
    "公司概况", "概况", "简介", "基本信息", "股权结构", "治理概况",
    "主营业务", "业务板块", "收入结构", "业务构成",
    # 产品与产品线 / 工厂与生产基地 / 产能与产线
    "产品线", "产品组合", "产品体系", "产品",
    "生产基地", "工厂", "厂区", "基地",
    "生产线", "产能", "产线",
    # 技术与研发 / 财务与经营 / 客户与市场证明 / 渠道与销售
    "核心技术", "技术", "研发", "专利",
    "财务", "营收", "利润", "经营质量",
    "标杆项目", "市场证明", "市场验证", "客户",
    "销售渠道", "渠道", "经销", "销售",
    # 战略与投资 / 市场证明与竞争 / 合作机会
    "战略", "投资", "扩产",
    "竞争格局", "竞争", "行业地位", "同业对比",
    "能源合作机会", "能源合作", "合作机会", "合作方向", "合作",
)

logger = logging.getLogger(__name__)


class GoalPlanner:
    """Builds ResearchGoal lists from a parsed mission."""

    def __init__(self, *, allow_dynamic_custom_goal: bool = True) -> None:
        self.allow_dynamic_custom_goal = allow_dynamic_custom_goal

    def plan(self, mission: ResearchMission, parsed: MissionParseResult) -> list[ResearchGoal]:
        goals: list[ResearchGoal] = []
        if mission.mode in {ResearchMode.ENTERPRISE, ResearchMode.HYBRID}:
            goals.extend(self._core_enterprise_goals(mission, parsed))
            goals.extend(self._custom_goals(mission, parsed))
        if mission.mode in {ResearchMode.MARKET, ResearchMode.HYBRID}:
            goals.extend(self._market_goals(mission, parsed))
        if mission.mode == ResearchMode.HYBRID:
            goals.append(
                self._goal(
                    mission,
                    name="企业—市场匹配与进入策略",
                    description="基于企业与市场两侧证据的跨域匹配、风险与市场进入/合作机会判断",
                    subject_id=mission.primary_subject or "hybrid-subject",
                    subject_name=mission.primary_subject or "跨域主体",
                    subject_type=SubjectType.CUSTOM,
                    goal_class=GoalClass.STRATEGY,
                    priority=PriorityLevel.P1,
                    required_evidence=("enterprise_evidence", "market_evidence"),
                    success_criteria=("两侧证据均可用且结论可追溯",),
                )
            )
        return goals

    def _core_enterprise_goals(self, mission: ResearchMission, parsed: MissionParseResult) -> list[ResearchGoal]:
        subject = parsed.primary_subject or mission.primary_subject
        return [
            self._goal(
                mission,
                name=spec.name,
                description=spec.description,
                subject_id=subject,
                subject_name=subject,
                subject_type=SubjectType.ENTERPRISE,
                goal_class=GoalClass.CORE_ENTERPRISE,
                priority=spec.priority,
                required_evidence=list(spec.required_evidence),
                success_criteria=tuple(f"{field} 存在有效证据" for field in spec.required_evidence),
            )
            for spec in CORE_ENTERPRISE_GOALS
        ]

    def _custom_goals(self, mission: ResearchMission, parsed: MissionParseResult) -> list[ResearchGoal]:
        if not self.allow_dynamic_custom_goal:
            return []
        goals: list[ResearchGoal] = []
        for spec in parsed.custom_goals:
            if self._redundant_with_core(spec, parsed.primary_subject or mission.primary_subject):
                logger.info(
                    "custom goal %r restates the core plan; dropped to protect the shared iteration budget",
                    spec.name,
                )
                continue
            subject = spec.subject_name or parsed.primary_subject or mission.primary_subject
            goal_class = self._coerce_goal_class(spec.goal_class_hint)
            goals.append(
                self._goal(
                    mission,
                    name=spec.name or "用户专项研究",
                    description=spec.description or mission.raw_request,
                    subject_id=subject,
                    subject_name=subject,
                    subject_type=SubjectType.CUSTOM if goal_class == GoalClass.CUSTOM else SubjectType.ENTERPRISE,
                    goal_class=goal_class,
                    priority=PriorityLevel.P1,
                    required_evidence=[],
                    success_criteria=("该专项问题获得了直接相关证据",),
                )
            )
        return goals

    @staticmethod
    def _redundant_with_core(spec, primary_subject: str | None) -> bool:
        """True when a custom goal only restates the fixed core plan.

        Redundant = the goal name is fully covered by core-topic keywords
        plus generic modifiers, so no novel topic remains.  Geographies only
        rescue a fully-restating goal when the goal is market-scoped by class
        (MARKET/ECONOMICS) or a geography token is part of the goal NAME
        itself (a genuine regional study); the parser echoing the subject's
        own city into geographies of a CUSTOM restatement (observed: 企业概况调查
        carrying geographies=["苏州"]) must not defeat dedup.  Names without
        any core keyword are novel by definition.
        """
        text = (spec.name or "").strip()
        if not text:
            return False
        subject = (spec.subject_name or primary_subject or "").strip()
        if subject:
            text = text.replace(subject, "")
        covered = [False] * len(text)
        for keyword in sorted(_CORE_TOPIC_KEYWORDS, key=len, reverse=True):
            start = 0
            while True:
                idx = text.find(keyword, start)
                if idx < 0:
                    break
                for i in range(idx, idx + len(keyword)):
                    covered[i] = True
                start = idx + len(keyword)
        if not any(covered):
            return False
        residue = "".join(ch for ch, ok in zip(text, covered) if not ok)
        for stop in sorted(_CORE_RESTATEMENT_STOP_TERMS, key=len, reverse=True):
            residue = residue.replace(stop, "")
        if residue:
            return False
        # Name fully restates the core plan.  Geographies rescue the goal
        # only for market-scoped classes or when a geography token is part
        # of the goal name itself (e.g. 德国渠道调研); otherwise they are
        # just the parser echoing where the subject sits.
        if spec.geographies:
            market_scoped = str(spec.goal_class_hint or "").strip().upper() in {"MARKET", "ECONOMICS"}
            name = (spec.name or "").strip()
            geographies = [str(geo).strip() for geo in spec.geographies if str(geo).strip()]
            if market_scoped or any(geo and geo in name for geo in geographies):
                return False
        return True

    def _market_goals(self, mission: ResearchMission, parsed: MissionParseResult) -> list[ResearchGoal]:
        goals: list[ResearchGoal] = []
        specs = self._dedup_market_specs(parsed.market_goals)
        for spec in specs:
            geography = spec.geography if spec else ""
            for family, description in MARKET_GOAL_FAMILIES:
                goals.append(
                    self._goal(
                        mission,
                        name=f"{geography or '目标市场'}·{family}",
                        description=f"{description}（{spec.market_object if spec else mission.raw_request}）",
                        subject_id=f"market:{geography or 'target'}",
                        subject_name=f"{geography or '目标市场'}市场",
                        subject_type=SubjectType.MARKET,
                        goal_class=GoalClass.MARKET,
                        priority=PriorityLevel.P1,
                        required_evidence=("market_evidence",),
                        success_criteria=("市场证据存在且来源可审计",),
                    )
                )
        return goals

    @staticmethod
    def _dedup_market_specs(specs: list) -> list:
        """同一 geography 的多条解析目标合并为一条（6 个目标族只展开一次）。

        LLM 解析器可能把用户的多个关注点拆成同地理的多条 market_goals，
        直接展开会把目标数翻倍（如 6 族 × 3 条 = 18 个重复目标），浪费全部
        召回预算。合并时保留各条的 market_object，关注点不丢失。
        """
        merged: dict[str, dict[str, str]] = {}
        order: list[str] = []
        for spec in specs or []:
            key = (spec.geography or "").strip()
            if key not in merged:
                merged[key] = {"geography": key, "objects": []}
                order.append(key)
            obj = (spec.market_object or "").strip()
            if obj and obj not in merged[key]["objects"]:
                merged[key]["objects"].append(obj)
        if not order:
            return [None]  # 无解析目标时保留原兜底：按“目标市场”展开一组族目标
        from .mission_parser import MarketGoalSpec

        return [
            MarketGoalSpec(
                name=f"{merged[key]['geography'] or '目标'}市场调研",
                description="；".join(merged[key]["objects"]) or "",
                geography=merged[key]["geography"],
                market_object="；".join(merged[key]["objects"]),
                goal_class_hint="MARKET",
            )
            for key in order
        ]

    @staticmethod
    def _coerce_goal_class(hint: str) -> GoalClass:
        try:
            return GoalClass(hint)
        except ValueError:
            return GoalClass.CUSTOM

    @staticmethod
    def _goal(
        mission: ResearchMission,
        *,
        name: str,
        description: str,
        subject_id: str,
        subject_name: str,
        subject_type: SubjectType,
        goal_class: GoalClass,
        priority: PriorityLevel,
        required_evidence: list[str],
        success_criteria: tuple[str, ...],
    ) -> ResearchGoal:
        return ResearchGoal(
            goal_id=new_sortable_id("GOAL"),
            goal_name=name,
            goal_description=description,
            subject_id=subject_id,
            subject_name=subject_name,
            subject_type=subject_type,
            goal_class=goal_class,
            priority=priority,
            required_evidence=required_evidence,
            success_criteria=list(success_criteria),
        )
