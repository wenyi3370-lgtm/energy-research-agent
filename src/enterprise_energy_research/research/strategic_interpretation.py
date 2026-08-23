"""Evidence-bound strategic interpretation above normalized enterprise facts."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, FrozenResearchBundle
from enterprise_energy_research.research.research_analysis import ResearchAnalysis, ResearchAnalysisEngine


class InterpretationLineage(BaseModel):
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    reasoning: str
    counterevidence_claim_ids: list[str] = Field(default_factory=list)


class StrategicTrajectory(BaseModel):
    trajectory_id: str
    title: str
    direction: str
    periods: list[str]
    lineage: InterpretationLineage


class StrategicTurningPoint(BaseModel):
    turning_point_id: str
    period: str
    event: str
    implication: str
    lineage: InterpretationLineage


class BusinessDriver(BaseModel):
    driver_id: str
    name: str
    mechanism: str
    lineage: InterpretationLineage


class StrategicPriority(BaseModel):
    priority_id: str
    name: str
    rationale: str
    lineage: InterpretationLineage


class CompetitivePosition(BaseModel):
    position_id: str
    conclusion: str
    comparison_basis: str
    named_comparables: list[str] = Field(default_factory=list)
    lineage: InterpretationLineage


class CustomerMarketProof(BaseModel):
    proof_id: str
    customer_or_market: str
    proof_type: str
    strength: str
    conclusion: str
    lineage: InterpretationLineage


class Dependency(BaseModel):
    dependency_id: str
    name: str
    consequence: str
    lineage: InterpretationLineage


class EnterpriseRisk(BaseModel):
    risk_id: str
    risk: str
    mechanism: str
    lineage: InterpretationLineage


class FutureScenario(BaseModel):
    scenario_id: str
    scenario: str
    condition: str
    implication: str
    lineage: InterpretationLineage


class DecisionSaturationStatus(str, Enum):
    SATURATED = "SATURATED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class DecisionSaturationAssessment(BaseModel):
    status: DecisionSaturationStatus
    covered_questions: list[str] = Field(default_factory=list)
    decision_changing_unknowns: list[str] = Field(default_factory=list)
    rationale: str


class StrategicInterpretation(BaseModel):
    schema_version: str = "1.0"
    trajectories: list[StrategicTrajectory] = Field(default_factory=list)
    turning_points: list[StrategicTurningPoint] = Field(default_factory=list)
    drivers: list[BusinessDriver] = Field(default_factory=list)
    priorities: list[StrategicPriority] = Field(default_factory=list)
    competitive_positions: list[CompetitivePosition] = Field(default_factory=list)
    customer_market_proofs: list[CustomerMarketProof] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    enterprise_risks: list[EnterpriseRisk] = Field(default_factory=list)
    scenarios: list[FutureScenario] = Field(default_factory=list)
    saturation: DecisionSaturationAssessment


class StrategicInterpretationEngine:
    """Interpret only verified, comparable evidence; absence creates no story."""

    STRATEGY_FIELDS = {
        "strategy", "strategic_priority", "business_segment", "core_business",
        "investment", "capacity", "technology_route", "overseas_expansion",
    }
    CUSTOMER_FIELDS = {"customer", "customer_name", "customer_segment", "order", "contract", "market_share"}
    COMPETITION_FIELDS = {"competitor", "market_share", "industry_rank", "industry_position", "comparison"}
    DEPENDENCY_FIELDS = {"supplier", "raw_material", "dependency", "customer_concentration", "supply_chain"}

    def interpret(
        self, bundle: FrozenResearchBundle, analysis: ResearchAnalysis | None = None,
    ) -> StrategicInterpretation:
        analysis = analysis or ResearchAnalysisEngine().analyze(bundle)
        verified = [c for c in bundle.claims if c.verification_status == VerificationStatus.VERIFIED]
        by_field: dict[str, list[Claim]] = defaultdict(list)
        for claim in verified:
            by_field[claim.field_name].append(claim)

        trajectories = self._trajectories(analysis, by_field)
        turning_points = self._turning_points(verified)
        drivers = self._drivers(trajectories, verified)
        priorities = self._priorities(verified)
        competitive = self._competitive_positions(verified)
        customer_proofs = self._customer_proofs(verified)
        dependencies = self._dependencies(verified)
        risks = self._risks(verified)
        scenarios = self._scenarios(drivers, risks)
        saturation = self._saturation(bundle, trajectories, priorities, customer_proofs, risks)
        return StrategicInterpretation(
            trajectories=trajectories, turning_points=turning_points, drivers=drivers,
            priorities=priorities, competitive_positions=competitive,
            customer_market_proofs=customer_proofs, dependencies=dependencies,
            enterprise_risks=risks, scenarios=scenarios, saturation=saturation,
        )

    def _trajectories(self, analysis: ResearchAnalysis, by_field: dict[str, list[Claim]]) -> list[StrategicTrajectory]:
        result: list[StrategicTrajectory] = []
        for metric in ("revenue", "profit", "rnd_expense", "capacity", "battery_sales_volume"):
            trend = analysis.trend(metric)
            if trend is None or trend.year_count < 3:
                continue
            result.append(StrategicTrajectory(
                trajectory_id=f"ST-{metric.upper()}", title=trend.label,
                direction=trend.statement, periods=[point.period or "" for point in trend.points],
                lineage=InterpretationLineage(
                    claim_ids=trend.claim_ids, source_ids=trend.source_ids,
                    reasoning="至少三个完整可比年度形成可验证轨迹；未用单期数据外推长期趋势。",
                ),
            ))
        return result

    def _turning_points(self, claims: list[Claim]) -> list[StrategicTurningPoint]:
        candidates = [c for c in claims if c.field_name in {"strategy_event", "major_investment", "acquisition", "new_factory", "overseas_expansion"}]
        result: list[StrategicTurningPoint] = []
        for index, claim in enumerate(sorted(candidates, key=self._period), start=1):
            period = self._period(claim)
            if not period:
                continue
            result.append(StrategicTurningPoint(
                turning_point_id=f"TP-{index:03d}", period=period, event=str(claim.value),
                implication="该事件改变了业务范围、产能组织或市场进入方式，后续表现需由经营结果验证。",
                lineage=self._lineage([claim], "按已披露事件日期识别战略转折，不推断未披露动机。"),
            ))
        return result[:8]

    def _drivers(self, trajectories: list[StrategicTrajectory], claims: list[Claim]) -> list[BusinessDriver]:
        result: list[BusinessDriver] = []
        for index, trajectory in enumerate(trajectories[:4], start=1):
            result.append(BusinessDriver(
                driver_id=f"BD-{index:03d}", name=f"{trajectory.title}变化",
                mechanism=f"{trajectory.direction}该变化影响企业的资源投向、组织能力和合作窗口。",
                lineage=trajectory.lineage,
            ))
        return result

    def _priorities(self, claims: list[Claim]) -> list[StrategicPriority]:
        candidates = [c for c in claims if c.field_name in {"strategic_priority", "strategy", "technology_route", "overseas_expansion"}]
        return [StrategicPriority(
            priority_id=f"SP-{i:03d}", name=str(c.value),
            rationale="企业公开披露将该事项列为战略、技术路线或市场拓展方向。",
            lineage=self._lineage([c], "直接采用企业披露，不把分析者假设写成企业战略。"),
        ) for i, c in enumerate(candidates[:8], start=1)]

    def _competitive_positions(self, claims: list[Claim]) -> list[CompetitivePosition]:
        candidates = [c for c in claims if c.field_name in self.COMPETITION_FIELDS]
        named = [c for c in candidates if c.field_name in {"competitor", "comparison"}]
        quantified = [c for c in candidates if c.field_name in {"market_share", "industry_rank"}]
        if not quantified and len(named) < 2:
            return []
        selected = [*quantified, *named][:8]
        names = list(dict.fromkeys(str(c.value) for c in named))
        return [CompetitivePosition(
            position_id="CP-001",
            conclusion="现有可比披露支持形成有限竞争位置判断；比较仅限同一指标、期间和市场范围。",
            comparison_basis="；".join(str(c.value) for c in quantified[:4]) or "已披露可比对象",
            named_comparables=names,
            lineage=self._lineage(selected, "只有具名可比对象或量化份额/排名才打开竞争分析。"),
        )]

    def _customer_proofs(self, claims: list[Claim]) -> list[CustomerMarketProof]:
        result: list[CustomerMarketProof] = []
        for index, claim in enumerate([c for c in claims if c.field_name in self.CUSTOMER_FIELDS][:10], start=1):
            strength = "strong" if claim.field_name in {"order", "contract"} else "medium" if claim.field_name in {"customer", "customer_name", "market_share"} else "weak"
            result.append(CustomerMarketProof(
                proof_id=f"CMP-{index:03d}", customer_or_market=str(claim.value), proof_type=claim.field_name,
                strength=strength, conclusion="该披露证明市场/客户触达程度；不自动等同于持续收入或排他关系。",
                lineage=self._lineage([claim], "按合同/订单、具名客户、客群描述分级，不夸大关系强度。"),
            ))
        return result

    def _dependencies(self, claims: list[Claim]) -> list[Dependency]:
        candidates = [c for c in claims if c.field_name in self.DEPENDENCY_FIELDS]
        return [Dependency(
            dependency_id=f"DEP-{i:03d}", name=str(c.value),
            consequence="该依赖可能影响交付、成本、技术路线或市场进入，影响程度需由进一步经营数据验证。",
            lineage=self._lineage([c], "仅把公开披露的供应链或集中度事项识别为依赖。"),
        ) for i, c in enumerate(candidates[:8], start=1)]

    def _risks(self, claims: list[Claim]) -> list[EnterpriseRisk]:
        # DataGap and missing-energy fields are deliberately excluded.
        candidates = [
            c for c in claims
            if ("risk" in c.field_name.casefold() or c.field_name in {"litigation", "regulatory_risk", "impairment", "customer_concentration"})
            and self._is_substantive_risk_text(str(c.value))
        ]
        return [EnterpriseRisk(
            risk_id=f"ER-{i:03d}", risk=str(c.value),
            mechanism="该企业特定风险可能改变经营结果、合作时点或资源投入边界。",
            lineage=self._lineage([c], "风险来自企业披露或可核验事件，不把研究数据缺口冒充企业风险。"),
        ) for i, c in enumerate(candidates[:10], start=1)]

    @staticmethod
    def _is_substantive_risk_text(value: str) -> bool:
        text = "".join(value.split())
        non_risk_disclosures = (
            "未发生重大诉讼", "不存在重大诉讼", "不存在重大差异", "未发现重大风险",
            "不存在重大风险", "以控制风险", "风控小组", "风险可控",
        )
        return (
            bool(text)
            and "不存在" not in text
            and not text.startswith(("未发生", "无重大"))
            and not any(token in text for token in non_risk_disclosures)
        )

    def _scenarios(self, drivers: list[BusinessDriver], risks: list[EnterpriseRisk]) -> list[FutureScenario]:
        if not drivers and not risks:
            return []
        lineage_claims = [claim for item in [*drivers, *risks] for claim in item.lineage.claim_ids]
        lineage_sources = [source for item in [*drivers, *risks] for source in item.lineage.source_ids]
        lineage = InterpretationLineage(claim_ids=list(dict.fromkeys(lineage_claims)), source_ids=list(dict.fromkeys(lineage_sources)), reasoning="情景是条件推演，不是事实预测。")
        result = [FutureScenario(scenario_id="FS-BASE", scenario="基准情景", condition="已识别经营驱动延续且主要风险未显著恶化", implication="按当前业务重点安排接洽和课题确认。", lineage=lineage)]
        if risks:
            result.append(FutureScenario(scenario_id="FS-DOWN", scenario="下行情景", condition=f"{risks[0].risk}显著恶化", implication="缩小投入范围，并在风险影响明确前暂缓立项。", lineage=lineage))
        if drivers:
            result.append(FutureScenario(scenario_id="FS-UP", scenario="上行情景", condition=f"{drivers[0].name}得到后续经营结果确认", implication="先完成一个具体课题，再评估是否扩展到相邻业务场景。", lineage=lineage))
        return result

    def _saturation(self, bundle: FrozenResearchBundle, trajectories: list[Any], priorities: list[Any], proofs: list[Any], risks: list[Any]) -> DecisionSaturationAssessment:
        covered = []
        if trajectories: covered.append("企业如何变化")
        if priorities: covered.append("战略优先级")
        if proofs: covered.append("客户与市场证明")
        if risks: covered.append("企业特定风险")
        critical = list(dict.fromkeys(g.field_name for g in bundle.gaps if g.importance == "critical"))[:5]
        status = DecisionSaturationStatus.SATURATED if len(covered) >= 3 and not critical else DecisionSaturationStatus.PARTIAL if covered else DecisionSaturationStatus.INSUFFICIENT
        return DecisionSaturationAssessment(status=status, covered_questions=covered, decision_changing_unknowns=critical, rationale=f"已覆盖 {len(covered)} 类管理问题；仅保留 {len(critical)} 项可能改变决策的关键不确定性。")

    @staticmethod
    def _period(claim: Claim) -> str:
        point = claim.period_end or claim.as_of_date or claim.period_start
        return str(point.year) if point else ""

    @staticmethod
    def _lineage(claims: list[Claim], reasoning: str) -> InterpretationLineage:
        return InterpretationLineage(claim_ids=[c.claim_id for c in claims], source_ids=list(dict.fromkeys(c.source_id for c in claims)), reasoning=reasoning)
