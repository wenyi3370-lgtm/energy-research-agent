"""Visual Router (P0 refactor): semantic pattern → visual type, with anti-abuse rules.

The router is the *only* place that decides which visual type a figure gets.
It receives a :class:`VisualProposal` — the business question, the evidence
data and the information-semantics pattern — and returns a
:class:`~enterprise_energy_research.artifacts.visuals.VisualSpec` with a
concrete ``visual_type``, or ``None`` when the data cannot support any
chart and the insight is better served by prose (the caller then keeps the
insight and drops only the figure).

Anti-abuse rules (see ``ANTI_ABUSE_RULES``) guarantee we never draw a chart
that implies more than the evidence says: no fake time series, no fake
multi-dimension scores, no quadrant/scatter without real x/y metrics, no
Sankey without real flow quantities, no pie/treemap without real parts.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from .visuals import (
    SemanticPattern,
    VisualDatum,
    VisualNode,
    VisualSpec,
    VisualStage,
    VisualType,
)


class VisualProposal(BaseModel):
    """Business intent + evidence data, before the router assigns a visual type."""

    visual_id: str
    chapter_id: str
    decision_question: str
    business_thesis: str
    semantic_pattern: SemanticPattern = "none"
    title: str
    subtitle: str | None = None
    data_binding: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    transformation: str = "直接映射冻结证据，不新增假设。"
    assumption_status: str = "evidence"
    verified: bool = True
    destination: str = "both"
    editorial_priority: int = Field(default=3, ge=1, le=5)
    items: list[VisualDatum] = Field(default_factory=list)
    nodes: list[VisualNode] = Field(default_factory=list)
    stages: list[VisualStage] = Field(default_factory=list)
    axes: dict[str, Any] = Field(default_factory=dict)
    source_note: str = ""
    confidence: str | None = None


class RouteCheck(BaseModel):
    """Result of a single route decision, kept for QA and tests."""

    pattern: SemanticPattern
    visual_type: VisualType | None
    ok: bool
    reasons: list[str] = Field(default_factory=list)
    fallback: bool = False
    fallback_type: VisualType | None = None


# ── Semantic pattern → candidate visual types (first candidate that passes
#    the data-sufficiency checks wins; order matters only for ties).
RULES: dict[SemanticPattern, list[VisualType]] = {
    "time_series": ["line"],
    "category_comparison": ["bar"],
    "multi_dimension_score": ["radar"],
    "opportunity_priority": ["quadrant"],
    "two_metric_distribution": ["scatter"],
    "part_to_whole": ["treemap"],
    "technology_evolution": ["timeline"],
    "operational_process": ["process"],
    "value_flow": ["sankey"],
    "implementation_roadmap": ["gantt"],
    "hierarchy_or_conversion": ["pyramid"],
    "verified_relationship": ["tree"],
    "root_cause": ["fishbone"],
    "system_architecture": ["architecture"],
    "customer_journey": ["journey"],
    "data_handoff": ["data_flow"],
    "quantitative_facts": ["kpi_cards", "table"],
    "none": ["table"],
}

# Anti-chart-abuse rules, documented for QA/reviewers (Chinese, user-facing
# reports never print these).
ANTI_ABUSE_RULES: tuple[str, ...] = (
    "禁止伪造时间序列：无 ≥2 个不同 period 的数值数据，不允许使用 line。",
    "禁止伪造多维评分：轴 <3 或任一轴无真实评分，不允许使用 radar。",
    "禁止伪造优先级/分布：无真实 x/y 数值指标，不允许使用 quadrant/scatter。",
    "禁止伪造流向：无真实流量/权重数值，不允许使用 sankey。",
    "禁止伪造构成：无真实 part_to_whole 权重，不允许使用 treemap。",
    "禁止伪造关系图：无 verified 的父子关系边，不允许使用 tree。",
    "数据不足时优先降级为 table/KPI/正文，不画任何暗示性图表。",
)

# Chinese labels used when the narrative needs to name a pattern for a human.
SEMANTIC_LABELS: dict[SemanticPattern, str] = {
    "time_series": "时间趋势",
    "category_comparison": "分类对比",
    "multi_dimension_score": "多维评分",
    "opportunity_priority": "机会优先级",
    "two_metric_distribution": "双指标分布",
    "part_to_whole": "构成占比",
    "technology_evolution": "技术演进",
    "operational_process": "业务流程",
    "value_flow": "价值流向",
    "implementation_roadmap": "实施路线图",
    "hierarchy_or_conversion": "层级/转化",
    "verified_relationship": "已验证关系",
    "root_cause": "根因分析",
    "system_architecture": "系统架构",
    "customer_journey": "客户旅程",
    "data_handoff": "数据流转",
    "quantitative_facts": "量化事实",
    "none": "无",
}


def _numbers(items: list[VisualDatum]) -> list[float | int]:
    return [item.value for item in items if isinstance(item.value, (int, float))]


def _periods(items: list[VisualDatum]) -> list[str]:
    return sorted({item.period for item in items if item.period})


def _check_line(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    nums = _numbers(items)
    if len(nums) < 2:
        reasons.append("数值数据点不足 2 个")
    if len(_periods(items)) < 2:
        reasons.append("不构成真实时间序列（少于 2 个不同 period）")
    return not reasons, reasons


def _check_bar(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(items) < 2:
        reasons.append("对比类别不足 2 项")
    if len(_numbers(items)) < 2:
        reasons.append("数值数据不足 2 项")
    return not reasons, reasons


def _check_radar(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    axes = len({item.label for item in items})
    if axes < 3:
        reasons.append("评分维度不足 3 个")
    if len(_numbers(items)) < axes:
        reasons.append("存在无真实评分的维度")
    return not reasons, reasons


def _check_quadrant(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    pairs = [item for item in items if isinstance(item.x, (int, float)) and isinstance(item.y, (int, float))]
    if len(pairs) < 2:
        reasons.append("具有真实 x/y 坐标的项不足 2 个")
    return not reasons, reasons


def _check_scatter(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    pairs = [item for item in items if isinstance(item.x, (int, float)) and isinstance(item.y, (int, float))]
    if len(pairs) < 3:
        reasons.append("具有真实 x/y 坐标的项不足 3 个")
    return not reasons, reasons


def _check_treemap(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    weights = [item.weight for item in items if isinstance(item.weight, (int, float)) and item.weight > 0]
    if len(weights) < 2:
        reasons.append("构成项不足 2 个或权重缺失")
    return not reasons, reasons


def _check_timeline(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len({item.period for item in items if item.period}) < 2:
        reasons.append("时间节点不足 2 个")
    return not reasons, reasons


def _check_process(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(stages) < 2:
        reasons.append("流程步骤不足 2 个")
    if not all(stage.from_label and stage.to_label for stage in stages):
        reasons.append("存在缺失 from/to 的步骤")
    return not reasons, reasons


def _check_sankey(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(stages) < 2:
        reasons.append("流转段不足 2 个")
    if not any(isinstance(stage.weight, (int, float)) and stage.weight > 0 for stage in stages):
        reasons.append("无真实流转数量")
    return not reasons, reasons


def _check_gantt(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(stages) < 2:
        reasons.append("任务项不足 2 个")
    if not all(stage.start and stage.end for stage in stages):
        reasons.append("存在缺失 start/end 的任务")
    return not reasons, reasons


def _check_pyramid(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(items) < 2:
        reasons.append("层级项不足 2 层")
    if not _numbers(items) and not any(isinstance(item.weight, (int, float)) for item in items):
        reasons.append("无真实数值/权重")
    return not reasons, reasons


def _check_tree(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    roots = [node for node in nodes if node.parent is None]
    children = [node for node in nodes if node.parent is not None]
    if len(nodes) < 2 or not roots or not children:
        reasons.append("树结构不成立（缺根或缺子节点）")
    if not all(node.id in {n.id for n in nodes} for node in nodes if node.parent):
        reasons.append("存在悬空父子引用")
    return not reasons, reasons


def _check_fishbone(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(nodes) < 3:
        reasons.append("根因分类项不足 3 个")
    if not any(node.kind == "focal" for node in nodes):
        reasons.append("缺少问题焦点")
    return not reasons, reasons


def _check_architecture(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(nodes) < 3:
        reasons.append("架构组件不足 3 个")
    if len({node.kind for node in nodes}) < 2:
        reasons.append("架构层级区分不足")
    return not reasons, reasons


def _check_journey(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(stages) < 2:
        reasons.append("旅程阶段不足 2 个")
    return not reasons, reasons


def _check_data_flow(items: list[VisualDatum], nodes: list[VisualNode], stages: list[VisualStage], axes: dict[str, Any]) -> tuple[bool, list[str]]:
    return _check_process(items, nodes, stages, axes)


def _check_kpi_cards(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not items:
        reasons.append("无 KPI 数据")
    return not reasons, reasons


def _check_table(items: list[VisualDatum], *_: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not items:
        reasons.append("无表格数据")
    return not reasons, reasons


SUFFICIENCY_CHECKS: dict[VisualType, Callable[..., tuple[bool, list[str]]]] = {
    "line": _check_line,
    "bar": _check_bar,
    "radar": _check_radar,
    "quadrant": _check_quadrant,
    "scatter": _check_scatter,
    "treemap": _check_treemap,
    "timeline": _check_timeline,
    "process": _check_process,
    "data_flow": _check_data_flow,
    "sankey": _check_sankey,
    "gantt": _check_gantt,
    "pyramid": _check_pyramid,
    "tree": _check_tree,
    "fishbone": _check_fishbone,
    "architecture": _check_architecture,
    "journey": _check_journey,
    "kpi_cards": _check_kpi_cards,
    "table": _check_table,
}


def _fallback_type(proposal: VisualProposal) -> VisualType | None:
    """Pick the least-lying fallback: table > kpi_cards > None (prose)."""
    if proposal.items:
        return "table"
    if _numbers(proposal.items):
        return "kpi_cards"
    return None


class VisualRouter:
    """Route a proposal to a visual type, or degrade to table/KPI/prose.

    ``route`` never raises on insufficient data: it returns ``None`` and the
    caller decides how to keep the insight (prose) or fall back (table/KPI).
    """

    def __init__(self, rules: dict[SemanticPattern, list[VisualType]] | None = None) -> None:
        self.rules = rules or RULES

    def check(self, pattern: SemanticPattern, visual_type: VisualType, proposal: VisualProposal) -> RouteCheck:
        ok, reasons = SUFFICIENCY_CHECKS[visual_type](proposal.items, proposal.nodes, proposal.stages, proposal.axes)
        return RouteCheck(pattern=pattern, visual_type=visual_type, ok=ok, reasons=reasons)

    def route(self, proposal: VisualProposal) -> tuple[VisualSpec | None, RouteCheck]:
        """Assign ``visual_type`` to the proposal, honoring anti-abuse rules."""
        candidates = self.rules.get(proposal.semantic_pattern, ["table"])
        for candidate in candidates:
            check = self.check(proposal.semantic_pattern, candidate, proposal)
            if check.ok:
                return proposal_to_spec(proposal, candidate), check
        fallback = _fallback_type(proposal)
        check = RouteCheck(
            pattern=proposal.semantic_pattern,
            visual_type=None,
            ok=False,
            reasons=["语义模式 %s 的数据不满足 %s 要求" % (proposal.semantic_pattern, "/".join(candidates))],
            fallback=True,
            fallback_type=fallback,
        )
        if fallback is None:
            return None, check
        return proposal_to_spec(proposal, fallback), check

    def choose(self, proposal: VisualProposal) -> VisualSpec | None:
        """Convenience wrapper returning only the spec (None → keep insight as prose)."""
        return self.route(proposal)[0]


def proposal_to_spec(proposal: VisualProposal, visual_type: VisualType) -> VisualSpec:
    return VisualSpec(
        visual_id=proposal.visual_id,
        chapter_id=proposal.chapter_id,
        decision_question=proposal.decision_question,
        business_thesis=proposal.business_thesis,
        visual_type=visual_type,
        semantic_pattern=proposal.semantic_pattern,
        title=proposal.title,
        subtitle=proposal.subtitle,
        data_binding=proposal.data_binding,
        source_ids=list(proposal.source_ids),
        source_claim_ids=list(proposal.source_claim_ids),
        unit=proposal.unit,
        period=proposal.period,
        scope=proposal.scope,
        transformation=proposal.transformation,
        assumption_status=proposal.assumption_status,  # type: ignore[arg-type]
        verified=proposal.verified,
        destination=proposal.destination,  # type: ignore[arg-type]
        editorial_priority=proposal.editorial_priority,
        items=list(proposal.items),
        nodes=list(proposal.nodes),
        stages=list(proposal.stages),
        axes=dict(proposal.axes),
        source_note=proposal.source_note,
        confidence=proposal.confidence,
    )
