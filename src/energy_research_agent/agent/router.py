"""Skill router (§13/§33/§34).

Routing is LLM semantic classification validated by code. The code never
decides semantics from keywords; it only enforces what is verifiable:
skill existence, goal existence, subject-boundary legality and budget
presence. Every decision carries a routing_reason for audit.
"""

from __future__ import annotations

from typing import Any

from energy_research_agent.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .models import (
    AgentStrictModel,
    GoalClass,
    PriorityLevel,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
    RoutingDecision,
    SkillName,
    SubjectType,
)


class RoutingBatch(AgentStrictModel):
    """LLM contract: one decision per goal, in goal order."""

    decisions: list[RoutingDecision]


class _RoutingItem(AgentStrictModel):
    goal_id: str
    goal_name: str
    goal_class: str
    subject_type: str
    subject_name: str
    geographies: list[str]
    description: str


# Deterministic subject-boundary rules that override an illegal LLM decision
# (§43/§79: enterprise entity boundary rules win).
def _boundary_override(item: _RoutingItem) -> SkillName | None:
    if item.subject_type == "enterprise":
        return SkillName.ENTERPRISE_RESEARCH
    if item.subject_type == "market":
        return SkillName.OVERSEAS_MARKET_RESEARCH
    return None


class ResearchSkillRouter:
    """Routes goals to skills. Open-set custom goals are first-class."""

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        self.gateway = gateway

    def route(self, mission: ResearchMission, goals: list[ResearchGoal]) -> list[RoutingDecision]:
        items = [self._item(mission, goal) for goal in goals]
        decisions: list[RoutingDecision] = []
        if self.gateway is not None:
            try:
                decisions = self._route_llm(mission, items)
            except (GatewayError, ValueError):
                decisions = []
        if not decisions:
            decisions = [self._route_fallback(mission, item) for item in items]
        return [self._enforce_boundaries(item, decision) for item, decision in zip(items, decisions)]

    def _route_llm(self, mission: ResearchMission, items: list[_RoutingItem]) -> list[RoutingDecision]:
        request = StructuredRequest[RoutingBatch](
            purpose="agent.skill_routing",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是研究 Skill 路由器。为每个目标选择执行 Skill："
                        "ENTERPRISE_RESEARCH 适合企业主体事实（主营业务/产品/工厂/产能/生产线/技术/财务/"
                        "企业客户/项目/招标/企业战略/企业风险/企业合作机会）；"
                        "OVERSEAS_MARKET_RESEARCH 适合国家或区域市场（市场规模/政策/电价/认证/用户/竞争格局/"
                        "产品对标/市场价格/渠道/售后/评论/痛点/经济性/商业模式/市场进入/产品定义）。"
                        "企业进入某市场的机会类目标是 HYBRID，应拆分到两侧而非只交给一方。"
                        "每个决策必须给出 routing_reason（审计用，中文），说明该目标为何属于该 Skill。"
                        "CUSTOM 目标依据语义路由，不得一律归入某一方。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"mission_mode={mission.mode.value}\n"
                        + "\n".join(
                            f"[{i}] {item.model_dump_json()}" for i, item in enumerate(items)
                        )
                    ),
                },
            ],
            response_model=RoutingBatch,
        )
        result = self.gateway.structured(request)
        known = {item.goal_id for item in items}
        decisions = [decision for decision in result.decisions if decision.goal_id in known]
        missing = known - {decision.goal_id for decision in decisions}
        if missing:
            # Never leave a goal unrouted; deterministic completion for stragglers.
            decisions.extend(
                self._route_fallback(
                    mission, next(item for item in items if item.goal_id == goal_id)
                )
                for goal_id in sorted(missing)
            )
        return decisions

    def _route_fallback(self, mission: ResearchMission, item: _RoutingItem) -> RoutingDecision:
        """Deterministic degraded routing. Explicit, conservative, auditable."""
        if item.subject_type == "enterprise":
            skill = SkillName.ENTERPRISE_RESEARCH
            reason = "确定性兜底：企业主体事实核验归企业研究 Skill"
        elif item.subject_type == "market":
            skill = SkillName.OVERSEAS_MARKET_RESEARCH
            reason = "确定性兜底：区域市场研究归海外市场 Skill"
        elif item.geographies or item.goal_class in {"MARKET", "POLICY", "ECONOMICS"}:
            skill = SkillName.OVERSEAS_MARKET_RESEARCH
            reason = "确定性兜底：目标携带地理/市场类语义，归海外市场 Skill"
        else:
            skill = SkillName.ENTERPRISE_RESEARCH
            reason = "确定性兜底：无明确市场信号，保守归企业研究 Skill"
        return RoutingDecision(
            goal_id=item.goal_id,
            assigned_skill=skill,
            routing_reason=reason,
            confidence=0.5,
            mode=mission.mode,
        )

    def _enforce_boundaries(self, item: _RoutingItem, decision: RoutingDecision) -> RoutingDecision:
        override = _boundary_override(item)
        if override is not None and decision.assigned_skill != override:
            # Subject integrity beats semantic routing (§43): competitor or
            # market facts must never pollute the target enterprise's evidence.
            return RoutingDecision(
                goal_id=decision.goal_id,
                assigned_skill=override,
                routing_reason=(
                    f"主体边界修正：subject_type={item.subject_type} 的目标必须由 {override.value} "
                    f"执行（原决策 {decision.assigned_skill.value} 被覆盖：{decision.routing_reason}）"
                ),
                confidence=decision.confidence,
                mode=decision.mode,
            )
        return decision

    @staticmethod
    def _item(mission: ResearchMission, goal: ResearchGoal) -> _RoutingItem:
        return _RoutingItem(
            goal_id=goal.goal_id,
            goal_name=goal.goal_name,
            goal_class=goal.goal_class.value,
            subject_type=goal.subject_type.value,
            subject_name=goal.subject_name,
            # Only the goal's OWN scope geography counts.  Falling back to
            # mission.geographies poisoned scope-less CUSTOM enterprise goals
            # (observed: 企业概况调查 routed to the overseas skill because the
            # mission carried a city), burning budget on the wrong lane.
            geographies=[str(geo) for geo in (goal.scope.get("geographies") or [])],
            description=goal.goal_description,
        )


# Re-exported for tests / callers that prefer a functional interface.
def route_goals(
    gateway: ModelGateway | None,
    mission: ResearchMission,
    goals: list[ResearchGoal],
) -> list[RoutingDecision]:
    return ResearchSkillRouter(gateway).route(mission, goals)


__all__ = [
    "ResearchSkillRouter",
    "RoutingBatch",
    "route_goals",
    "SkillName",
    "GoalClass",
    "PriorityLevel",
    "SubjectType",
]
