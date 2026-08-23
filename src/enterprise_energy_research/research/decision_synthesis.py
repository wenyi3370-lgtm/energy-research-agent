"""Decision synthesis (P0 third round): slim decision layer.

Architecture: ResearchAnalysisEngine answers "what is the enterprise
like" (objective research); this engine answers ONLY the delegation
question that remains afterwards — "what does that mean for cooperating
with us, and what should we do next".  It no longer writes business
chapters, no longer re-explains evidence methodology, and no longer
pads every finding with domain boilerplate.

The executive summary is data-first (enterprise facts, then consulting
judgement) and stays within 800–1500 Chinese characters.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from enterprise_energy_research.artifacts.publication_terminology import field_label, reason_label
from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, DataGap, FrozenResearchBundle
from enterprise_energy_research.research.publication_relevance import (
    ENERGY_FIELDS,
    MANUFACTURING_FIELDS,
)
from enterprise_energy_research.research.research_analysis import (
    ResearchAnalysis,
    ResearchAnalysisEngine,
)
from enterprise_energy_research.research.client_profile import ClientProfile, client_profile_from_manifest
from enterprise_energy_research.research.cooperation_hypothesis import (
    CooperationHypothesis, CooperationHypothesisEngine, CooperationHypothesisStatus,
)
from enterprise_energy_research.research.strategic_interpretation import (
    StrategicInterpretation, StrategicInterpretationEngine,
)

FINANCIAL_FIELDS = {"revenue", "profit", "gross_margin", "rnd_expense", "rnd_expense_ratio"}
PRODUCT_FIELDS = {
    "product_family", "product_catalog_scope", "product_name", "model", "series", "category",
    "parameter_name", "technology", "technology_route", "certification", "application",
}


class DecisionStatementType(str, Enum):
    FACT = "FACT"
    CALCULATION = "CALCULATION"
    ANALYTICAL_INFERENCE = "ANALYTICAL_INFERENCE"
    RECOMMENDATION = "RECOMMENDATION"
    TO_BE_CONFIRMED = "TO_BE_CONFIRMED"


class CalculationLineage(BaseModel):
    formula: str
    input_values: dict[str, Any]
    input_claim_ids: list[str]
    period: str
    unit: str | None = None


class DecisionFinding(BaseModel):
    finding_id: str
    decision_question: str
    conclusion: str
    supporting_claim_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)
    fact_summary: str
    analysis: str
    business_implication: str
    recommendation: str
    counter_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    statement_type: DecisionStatementType
    semantic_domain: str
    calculation: CalculationLineage | None = None

    @model_validator(mode="after")
    def validate_lineage(self) -> "DecisionFinding":
        if self.statement_type == DecisionStatementType.FACT and (
            not self.supporting_claim_ids or not self.supporting_source_ids
        ):
            raise ValueError("FACT requires claim and source lineage")
        if self.statement_type == DecisionStatementType.CALCULATION and self.calculation is None:
            raise ValueError("CALCULATION requires formula and input lineage")
        if self.statement_type in {
            DecisionStatementType.ANALYTICAL_INFERENCE,
            DecisionStatementType.RECOMMENDATION,
        } and not self.supporting_claim_ids:
            raise ValueError(f"{self.statement_type.value} requires supporting facts")
        return self


class DueDiligenceRequirement(BaseModel):
    requirement_id: str
    item: str
    why_it_matters: str
    affected_decision: str
    requested_materials: list[str]
    timing: str
    decision_blocker: bool
    source_gap_ids: list[str] = Field(default_factory=list)


class DecisionSynthesis(BaseModel):
    schema_version: str = "1.1"
    run_id: str
    entity_name: str
    overall_judgement: str
    judgement_rationale: str
    priority_direction_summary: str
    decision_questions: list[str]
    findings: list[DecisionFinding]
    due_diligence: list[DueDiligenceRequirement]
    key_risks: list[str]
    executive_summary_paragraphs: list[str]

    @property
    def executive_summary_text(self) -> str:
        return "\n".join(self.executive_summary_paragraphs)


def semantic_domain(field_name: str) -> str:
    if field_name in ENERGY_FIELDS:
        return "energy"
    if field_name in MANUFACTURING_FIELDS:
        return "manufacturing"
    if field_name in FINANCIAL_FIELDS:
        return "financial"
    if field_name in PRODUCT_FIELDS:
        return "product"
    if "risk" in field_name:
        return "risk"
    return "strategy"


def claim_period(claim: Claim) -> str | None:
    if claim.period_end:
        return str(claim.period_end.year)
    if claim.as_of_date:
        return str(claim.as_of_date.year)
    if claim.period_start:
        return str(claim.period_start.year)
    match = re.search(r"(?:19|20)\d{2}", f"{claim.scope or ''} {claim.raw_text or ''}")
    return match.group(0) if match else None


class DecisionSynthesisEngine:
    """Decision layer only: cooperation value, risks and next actions."""

    def synthesize(
        self,
        bundle: FrozenResearchBundle,
        analysis: ResearchAnalysis | None = None,
        synthesis: Any | None = None,
        strategic: StrategicInterpretation | None = None,
        hypotheses: list[CooperationHypothesis] | None = None,
        client: ClientProfile | None = None,
    ) -> DecisionSynthesis:
        entity = next(
            (item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id),
            bundle.entities[0] if bundle.entities else None,
        )
        if entity is None:
            raise ValueError("Frozen bundle contains no canonical enterprise")
        analysis = analysis or ResearchAnalysisEngine().analyze(bundle)
        strategic = strategic or StrategicInterpretationEngine().interpret(bundle, analysis)
        client = client or client_profile_from_manifest(bundle.run_manifest)
        hypotheses = hypotheses if hypotheses is not None else CooperationHypothesisEngine().build(bundle, strategic, client)
        verified = [claim for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED]
        by_domain: dict[str, list[Claim]] = defaultdict(list)
        for claim in verified:
            by_domain[semantic_domain(claim.field_name)].append(claim)

        findings: list[DecisionFinding] = []
        if strategy := self._strategy_finding(by_domain["strategy"], synthesis):
            findings.append(strategy)
        if financial := self._financial_finding(analysis, by_domain["financial"]):
            findings.append(financial)
        if product := self._product_finding(bundle, analysis):
            findings.append(product)
        if manufacturing := self._manufacturing_finding(bundle, analysis):
            findings.append(manufacturing)
        findings.append(self._energy_finding(analysis, by_domain))

        due_diligence = self._due_diligence(bundle.gaps)
        priority_hypotheses = [item for item in hypotheses if item.status == CooperationHypothesisStatus.PRIORITY_OPPORTUNITY]
        potential_hypotheses = [item for item in hypotheses if item.status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS]
        if priority_hypotheses:
            judgement = "建议接洽"
            top = priority_hypotheses[0]
            rationale = (
                f"可先讨论“{top.opportunity_name}”，但不宜直接立项。"
                f"由{top.target_department}确认具体需求和合作范围后，再决定是否设计课题。"
            )
        elif potential_hypotheses:
            judgement = "保留接洽"
            rationale = "现有资料只显示可能的合作方向，尚未确认对方需求、负责人和项目条件。"
        else:
            judgement = "暂缓"
            rationale = "现有资料不足以支持主动接洽；待出现明确需求或新的合作条件后再评估。"

        ranked: list[CooperationHypothesis] = []
        seen_directions: set[str] = set()
        for item in [*priority_hypotheses, *potential_hypotheses]:
            if item.opportunity_name in seen_directions:
                continue
            seen_directions.add(item.opportunity_name)
            ranked.append(item)
        solution_names = list(dict.fromkeys(item.opportunity_name for item in ranked))
        priority_summary = (
            "优先联系相关业务部门，讨论" + "、".join(solution_names[:3]) + "中的一个具体课题。"
            if solution_names else "当前没有足够依据支持主动接洽。"
        )
        key_risks = list(dict.fromkeys(item.risk for item in strategic.enterprise_risks))[:8]
        decision_questions = [
            "该企业是否值得推进，以及当前可以推进到哪一阶段？",
            "哪些合作方向具备已核验事实基础，优先从什么场景切入？",
            "企业正在发生什么战略变化，哪些驱动和风险会改变合作窗口？",
            "创新中心能够提供哪些资源，双方合作还需确认哪些条件？",
            "未来 90 天应完成哪些接洽和验证工作，何时决定是否立项？",
        ]
        executive = self._executive_summary(
            entity.canonical_name, judgement, rationale, analysis, findings,
            priority_summary, due_diligence, key_risks, synthesis,
            strategic=strategic, hypotheses=hypotheses, client=client,
        )
        return DecisionSynthesis(
            run_id=bundle.run_manifest.run_id,
            entity_name=entity.canonical_name,
            overall_judgement=judgement,
            judgement_rationale=rationale,
            priority_direction_summary=priority_summary,
            decision_questions=decision_questions,
            findings=findings,
            due_diligence=due_diligence,
            key_risks=key_risks,
            executive_summary_paragraphs=executive,
        )

    # ── findings: data-derived, concise ────────────────────────────────────
    def _strategy_finding(self, claims: list[Claim], synthesis: Any) -> DecisionFinding | None:
        profile = getattr(synthesis, "company_profile", None) if synthesis is not None else None
        business_values = [
            str(claim.value).strip() for claim in claims
            if claim.field_name in {"core_business", "business_segment", "business_segments", "industry_position"}
            and str(claim.value).strip()
        ]
        if not claims and not (profile and (profile.core_business or profile.business_segments)):
            return None
        if profile and (profile.core_business or profile.business_segments):
            business_text = "；".join(filter(None, [profile.core_business, "、".join(profile.business_segments or [])]))
        else:
            business_text = "；".join(dict.fromkeys(business_values))
        ids, sources = self._lineage(claims)
        return DecisionFinding(
            finding_id="DF-STRATEGY", decision_question="企业业务定位与组织基础是什么？",
            conclusion=f"公司已形成以{business_text or '多元业务'}为核心的业务结构",
            supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=f"已核验企业身份、业务边界与组织定位事实 {len(claims)} 条。",
            analysis=f"公开披露显示公司以{business_text or '多元业务'}为核心业务。这一业务结构决定了首轮合作的责任主体与议题范围；"
                     "主营业务与产业板块的公开表述构成后续经营、产品与制造分析的框架，身份与业务事实已在研究前期完成核验。",
            business_implication="首轮沟通应围绕核心业务的责任部门展开，而不是停留在集团层的泛化交流。",
            recommendation="依据业务结构选择责任部门和优先场景。",
            confidence=min(0.94, 0.55 + len(claims) * 0.03),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="strategy",
        )

    def _financial_finding(self, analysis: ResearchAnalysis, claims: list[Claim]) -> DecisionFinding | None:
        revenue = analysis.trend("revenue")
        profit = analysis.trend("profit")
        if revenue is None and profit is None and not claims:
            return None
        ids = list(dict.fromkeys(claim_id for claim in claims for claim_id in [claim.claim_id]))
        sources = list(dict.fromkeys(claim.source_id for claim in claims))
        if revenue is not None and revenue.year_count >= 3:
            conclusion = "近三年经营形成经营趋势基础，可支持趋势与增速分析"
            analysis_text = f"{revenue.statement}" + (f"利润端：{profit.statement}" if profit is not None else "")
        elif revenue is not None:
            conclusion = "现有经营数据只能证明当前规模，不能据此声称长期增长趋势"
            analysis_text = f"{revenue.statement}公开可比较年度不足三年，规模事实不应被包装为长期趋势判断。"
        else:
            conclusion = "公开经营数据以单年口径为主，仅能支持当前规模判断"
            analysis_text = "当前经营披露以单年口径为主，可回答企业资源基础，不足以形成趋势结论。"
        return DecisionFinding(
            finding_id="DF-FINANCIAL", decision_question="经营与资源基础是否支持合作推进？",
            conclusion=conclusion, supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=f"已核验经营披露 {len(claims)} 条。" + (f"营业收入覆盖 {revenue.year_count} 个年度。" if revenue else ""),
            analysis=analysis_text,
            business_implication="经营规模说明合作对象具备资源投入基础，具体项目仍需按基地条件单独测算。",
            recommendation="以经营数据作为合作对象筛选依据，项目经济性以基地级数据独立测算。",
            limitations=[] if (revenue and revenue.year_count >= 3) else ["可比较年度不足 3 个，不使用趋势或复合增速表述。"],
            confidence=min(0.95, 0.55 + 0.05 * len(claims)),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="financial",
        )

    def _product_finding(self, bundle: FrozenResearchBundle, analysis: ResearchAnalysis) -> DecisionFinding | None:
        verified_products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        if not verified_products:
            return None
        families = next((item for item in analysis.comparisons if item.comparison_id == "CMP-FAMILIES"), None)
        parameterized = sum(bool(item.parameters) for item in verified_products)
        claim_ids: list[str] = []
        source_ids: list[str] = []
        for product in verified_products:
            source_ids.extend(product.source_ids)
        return DecisionFinding(
            finding_id="DF-PRODUCT", decision_question="对方具备哪些可用于合作的产品与技术能力？",
            conclusion=f"已核验 {len(verified_products)} 项产品、{len({item.category or '其他' for item in verified_products})} 个产品族，其中 {parameterized} 项具有公开参数",
            supporting_claim_ids=claim_ids, supporting_source_ids=list(dict.fromkeys(source_ids)),
            fact_summary=f"产品记录覆盖 {len(verified_products)} 项产品，其中 {parameterized} 项具有公开参数。",
            analysis=(families.statement if families else "") + "产品目录与参数可用于技术交流与接口核验的起点。",
            business_implication="产品证据适合支撑技术交流、联合验证与供应链准入。",
            recommendation="优先选择与目标场景直接相关的产品族开展接口核验。",
            limitations=[] if parameterized else ["公开产品参数不足，技术适配仍需原厂资料或联合测试确认。"],
            confidence=min(0.94, 0.58 + 0.03 * len(verified_products)),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE if claim_ids else DecisionStatementType.TO_BE_CONFIRMED,
            semantic_domain="product",
        )

    def _manufacturing_finding(self, bundle: FrozenResearchBundle, analysis: ResearchAnalysis) -> DecisionFinding | None:
        if not bundle.factories:
            return None
        site_count = analysis.factory_site_count or len(bundle.factories)
        regions = analysis.region_distribution
        region_text = "、".join(f"{region} {count} 处" for region, count in list(regions.items())[:6])
        claim_ids = [claim.claim_id for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED and claim.field_name in MANUFACTURING_FIELDS]
        source_ids = [claim.source_id for claim in bundle.claims if claim.claim_id in claim_ids]
        return DecisionFinding(
            finding_id="DF-MANUFACTURING", decision_question="生产布局如何影响合作切入顺序？",
            conclusion=f"公开资料收录基地记录 {site_count} 条" + (f"，按披露地址归类为{region_text}" if region_text else ""),
            supporting_claim_ids=claim_ids, supporting_source_ids=list(dict.fromkeys(source_ids)),
            fact_summary=f"公开资料收录基地记录 {site_count} 条；地址不完整的记录单列待核验。",
            analysis=(f"基地记录按披露地址归类为{region_text}。" if region_text else "基地名录已入附录。")
                    + "制造布局可用于筛选首批接触基地；产能口径反映制造输出，与企业自身用电规模是两类指标。",
            business_implication="首批基地应按业务相关性、数据可得性与决策链路筛选。",
            recommendation="选择一处资料完整、场景明确的基地做预可研，再决定是否复制。",
            limitations=["公开基地名录可能不是法定完整清单，完整名录见附录。"],
            confidence=min(0.9, 0.55 + 0.04 * site_count),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE if claim_ids else DecisionStatementType.TO_BE_CONFIRMED,
            semantic_domain="manufacturing",
        )

    def _energy_finding(self, analysis: ResearchAnalysis, by_domain: dict[str, list[Claim]]) -> DecisionFinding:
        own = analysis.own_energy_metrics
        energy_claims = by_domain.get("energy", [])
        ids = list(dict.fromkeys(claim_id for item in own for claim_id in item.claim_ids))
        sources = list(dict.fromkeys(source_id for item in own for source_id in item.source_ids))
        if own:
            labels = "、".join(item.label for item in own)
            return DecisionFinding(
                finding_id="DF-ENERGY", decision_question="公开资料能否形成基地级用能画像？",
                conclusion=f"公开资料披露了{labels}等量化数据，可用于场景初筛但不能替代基地测算",
                supporting_claim_ids=ids, supporting_source_ids=sources,
                fact_summary=f"已核验企业自身能源语义数据 {len(own)} 项。",
                analysis=f"已识别{labels}等量化事实，但公开口径通常不能同时覆盖单基地电量、负荷、电价、屋顶和配电约束。",
                business_implication="现有数据只能帮助判断是否值得进入基地预可研，不能据此确定装机规模、储能时长或项目收益。",
                recommendation="选择一处责任部门明确的基地，取得连续电量、负荷、电价、配电和屋顶数据后再决定是否报价。",
                limitations=["单基地统计边界和计费口径尚未形成完整、可比的数据组。"],
                confidence=min(0.92, 0.55 + 0.04 * len(own)),
                statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
                semantic_domain="energy",
            )
        report_titles = list(dict.fromkeys(
            str(claim.value).strip() for claim in energy_claims
            if "碳排放核算报告" in str(claim.value) and str(claim.value).strip()
        ))
        disclosure_fact = (
            f"公开页面列示{'、'.join(report_titles[:3])}，但报告标题没有给出可用于项目测算的能耗数值。"
            if report_titles else
            "当前未取得可独立核验的年度用电量、峰值负荷、电价、配电容量或负荷曲线。"
        )
        return DecisionFinding(
            finding_id="DF-ENERGY", decision_question="公开资料能否形成基地级用能画像？",
            conclusion="公开资料尚不足以判断单个基地的光伏或储能项目经济性",
            supporting_claim_ids=list(dict.fromkeys(claim.claim_id for claim in energy_claims)),
            supporting_source_ids=list(dict.fromkeys(claim.source_id for claim in energy_claims)),
            fact_summary=disclosure_fact,
            analysis="年度碳核算报告入口说明企业有相关披露，但报告名称不是综合能源消费量。没有基地级数据，就不能比较基地优先级、配置设备容量或估算收益。",
            business_implication="当前只能决定是否启动一处基地的数据核验，不能据此进入容量设计或商业报价。",
            recommendation="由基地能源管理或设施部门提供近12至24个月电量账单、分时负荷、电价、配电容量、屋顶条件及既有光储设施资料。",
            limitations=["缺少能够落到单一基地和统一期间的完整测算输入。"],
            confidence=0.9 if energy_claims else 0.75,
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE if energy_claims else DecisionStatementType.TO_BE_CONFIRMED,
            semantic_domain="energy",
        )

    # ── due diligence / risks ──────────────────────────────────────────────
    def _due_diligence(self, gaps: list[DataGap]) -> list[DueDiligenceRequirement]:
        requirements: list[DueDiligenceRequirement] = []
        grouped: dict[tuple[str | None, str, str], list[DataGap]] = defaultdict(list)
        for gap in gaps:
            affected = "项目经济性与是否进入方案设计" if gap.importance == "critical" else "合作范围与实施优先级"
            # Several internal field names can intentionally share one public
            # label (for example miscellaneous disclosure gaps).  Group on
            # that publication label so the appendix does not repeat the same
            # heading and boilerplate under different schema keys.
            grouped[(gap.entity_id, field_label(gap.field_name), affected)].append(gap)
        for index, ((_, public_item, affected), duplicates) in enumerate(grouped.items(), start=1):
            gap = sorted(duplicates, key=lambda item: {"critical": 3, "major": 2, "minor": 1}[item.importance], reverse=True)[0]
            blocker = gap.importance == "critical" or gap.field_name in {
                "electricity_consumption", "load_curve", "electricity_cost", "peak_load", "transformer_capacity",
            }
            requirements.append(DueDiligenceRequirement(
                requirement_id=f"DDR-{index:03d}", item=public_item,
                why_it_matters=f"{reason_label(gap.reason)}。该事项决定相关方案能否建立可审计的事实和测算边界。",
                affected_decision=affected,
                requested_materials=self._requested_materials(gap.field_name),
                timing="项目预可研阶段" if blocker else "首轮技术交流后 30 天内",
                decision_blocker=blocker, source_gap_ids=[item.gap_id for item in duplicates],
            ))
        return requirements

    @staticmethod
    def _requested_materials(field_name: str) -> list[str]:
        mapping = {
            "load_curve": ["最近 12 个月 15 分钟或小时级负荷曲线", "最大需量及峰谷时段记录"],
            "electricity_consumption": ["最近 12 个月分月电量", "对应基地和计量边界说明"],
            "electricity_cost": ["最近 12 个月电费账单", "电价、基本电费和功率因数条款"],
            "transformer_capacity": ["一次系统图", "变压器容量、负载率和并网余量"],
            "roof_area": ["屋面图纸", "权属、结构荷载、遮挡和可利用面积说明"],
            "operating_schedule": ["生产班次", "停产检修计划和主要设备运行时段"],
        }
        return mapping.get(field_name, [f"{field_label(field_name)}的最新原始资料", "责任部门确认记录"])

    @staticmethod
    def _key_risks(bundle: FrozenResearchBundle, requirements: list[DueDiligenceRequirement]) -> list[str]:
        risks = [str(claim.value) for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED and "risk" in claim.field_name]
        return list(dict.fromkeys(risks))[:8]

    # ── executive summary: data-first, 800-1500 chars ──────────────────────
    def _executive_summary(
        self,
        entity_name: str,
        judgement: str,
        rationale: str,
        analysis: ResearchAnalysis,
        findings: list[DecisionFinding],
        priority_summary: str,
        requirements: list[DueDiligenceRequirement],
        risks: list[str],
        synthesis: Any,
        *,
        strategic: StrategicInterpretation | None = None,
        hypotheses: list[CooperationHypothesis] | None = None,
        client: ClientProfile | None = None,
    ) -> list[str]:
        profile = getattr(synthesis, "company_profile", None) if synthesis is not None else None
        business = profile.core_business if profile and profile.core_business else None
        segments = profile.business_segments if profile and profile.business_segments else []
        revenue = analysis.trend("revenue")
        profit = analysis.trend("profit")

        strategic = strategic or StrategicInterpretationEngine().interpret
        hypotheses = hypotheses or []
        client_name = client.client_name if client else "委托方"
        business_text = business or ("、".join(segments) if segments else "已核验主营业务")
        trajectory_text = "；".join(
            f"{item.title}已收录{'、'.join(item.periods)}年度数据，可用于观察这些年份的变化"
            for item in strategic.trajectories[:2]
        ) if isinstance(strategic, StrategicInterpretation) and strategic.trajectories else "现有年度数据不足以判断长期变化"
        turning_text = "；".join(f"{item.period}年{item.event}" for item in strategic.turning_points[:2]) if isinstance(strategic, StrategicInterpretation) and strategic.turning_points else "尚未识别足以改变业务边界的具名战略转折"
        priority_items = [item for item in hypotheses if item.status == CooperationHypothesisStatus.PRIORITY_OPPORTUNITY]
        potential_items = [item for item in hypotheses if item.status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS]
        ranked = [*priority_items, *potential_items]
        opportunity_text = "；".join(
            f"{item.opportunity_name}：{item.recommended_action.rstrip('。；;')}"
            for item in ranked[:3]
        ) or "暂无建议主动接洽的方向"
        risks_text = "；".join(risks[:3]) if risks else "未从已核验披露中识别需要单列的企业特定风险"
        unknowns = [item.item for item in requirements if item.decision_blocker][:4]
        operating_fact_items = [
            item.conclusion for item in findings
            if item.semantic_domain in {"financial", "product", "manufacturing"}
        ]
        operating_facts = "；".join(operating_fact_items)
        strength_labels = {"strong": "强", "medium": "中", "weak": "弱"}
        customer_text = "；".join(
            f"{item.customer_or_market}（资料支持程度：{strength_labels.get(item.strength, '待确认')}）"
            for item in strategic.customer_market_proofs[:3]
        ) if isinstance(strategic, StrategicInterpretation) else ""
        capability_text = "、".join(item.name for item in (client.capabilities if client else []) if item.supports_formal_recommendation)
        top = ranked[0] if ranked else None
        contact_department = top.target_department if top else "相关业务部门"
        top_direction = top.opportunity_name if top else "候选合作方向"
        return [
            f"企业定位：{entity_name}以{business_text}为核心业务。{operating_facts or '公开资料已覆盖公司的主要经营、产品和制造情况'}。这些信息反映了公司的主营方向和现有交付基础，首轮沟通宜聚焦具体产品或工艺课题。据现有资料，{rationale}",
            f"经营与战略：{trajectory_text}；{turning_text}。{('已披露的客户与市场信息包括' + customer_text + '。') if customer_text else '公开资料尚未充分说明持续订单、排他关系或稳定收入。'}",
            f"合作建议：{opportunity_text}。{client_name}可投入的相关能力包括{capability_text or '尚无已确认的专项能力'}。当前建议先聚焦{top_direction}，与{contact_department}确认一项具体课题，不同时铺开多个方向。",
            f"主要限制：{risks_text}。" + (f"立项前还需取得{'、'.join(unknowns)}。" if unknowns else "当前没有发现会立即推翻上述判断的重大信息缺口。") + "如对方没有明确需求、双方技术路线或交付范围无法对齐，建议停止接洽。",
            f"下一步：30 天内与{contact_department}确认需求和负责人；60 天内由{client_name}与对方选定一个课题，明确指标、分工、数据和知识产权边界；90 天根据验证结果决定立项、缩小范围或结束接洽。",
        ]

    @staticmethod
    def _lineage(claims: list[Claim]) -> tuple[list[str], list[str]]:
        return (
            list(dict.fromkeys(claim.claim_id for claim in claims)),
            list(dict.fromkeys(claim.source_id for claim in claims)),
        )
