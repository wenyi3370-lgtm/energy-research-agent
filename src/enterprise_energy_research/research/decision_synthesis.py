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
    ) -> DecisionSynthesis:
        entity = next(
            (item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id),
            bundle.entities[0] if bundle.entities else None,
        )
        if entity is None:
            raise ValueError("Frozen bundle contains no canonical enterprise")
        analysis = analysis or ResearchAnalysisEngine().analyze(bundle)
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
        blocker_count = sum(item.decision_blocker for item in due_diligence)
        priority_solutions = [item for item in bundle.solutions if item.priority in {"A", "B"} and item.claim_ids]
        concrete_energy = [claim for claim in by_domain["energy"] if claim.field_name in ENERGY_FIELDS]
        if priority_solutions and len(concrete_energy) >= 2 and blocker_count == 0:
            judgement = "推进"
            rationale = "公开事实已覆盖合作能力、目标场景与关键能源边界，可进入方案共创与项目预可研。"
        elif priority_solutions and verified:
            judgement = "有条件推进"
            rationale = "公开事实支持进入技术交流与数据获取阶段，尚不足以直接支持项目报价或收益承诺。"
        else:
            judgement = "暂缓"
            rationale = "当前公开资料尚未形成可核验的合作场景与价值链闭环，应先补齐关键事实再决定是否投入商务资源。"

        solution_names = list(dict.fromkeys(item.opportunity for item in priority_solutions))
        priority_summary = (
            "优先围绕" + "、".join(solution_names[:3]) + "开展场景核验。"
            if solution_names else "优先补齐目标场景和项目边界数据。"
        )
        key_risks = self._key_risks(bundle, due_diligence)
        decision_questions = [
            "该企业是否值得推进，以及当前可以推进到哪一阶段？",
            "哪些合作方向具备已核验事实基础，优先从什么场景切入？",
            "哪些信息缺口会阻断项目经济性和 Go / No-Go 判断？",
            "未来 90 天应完成哪些验证动作？",
        ]
        executive = self._executive_summary(
            entity.canonical_name, judgement, rationale, analysis, findings,
            priority_summary, due_diligence, key_risks, synthesis,
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
        regions = analysis.region_distribution
        region_text = "、".join(f"{region} {count} 处" for region, count in list(regions.items())[:6])
        claim_ids = [claim.claim_id for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED and claim.field_name in MANUFACTURING_FIELDS]
        source_ids = [claim.source_id for claim in bundle.claims if claim.claim_id in claim_ids]
        return DecisionFinding(
            finding_id="DF-MANUFACTURING", decision_question="生产布局如何影响合作切入顺序？",
            conclusion=f"已核验生产基地 {len(bundle.factories)} 处" + (f"，主要分布在{region_text}" if region_text else ""),
            supporting_claim_ids=claim_ids, supporting_source_ids=list(dict.fromkeys(source_ids)),
            fact_summary=f"已核验生产基地 {len(bundle.factories)} 处。",
            analysis=(f"基地地域分布为{region_text}。" if region_text else "基地名录已入附录。")
                    + "制造布局可用于筛选首批接触基地；产能口径反映制造输出，与企业自身用电规模是两类指标。",
            business_implication="首批基地应按业务相关性、数据可得性与决策链路筛选。",
            recommendation="选择一处资料完整、场景明确的基地做预可研，再决定是否复制。",
            limitations=["公开基地名录可能不是法定完整清单，完整名录见附录。"],
            confidence=min(0.9, 0.55 + 0.04 * len(bundle.factories)),
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
                conclusion=f"公开资料可识别{labels}等企业自身能源语义数据，但仍需按基地范围核验",
                supporting_claim_ids=ids, supporting_source_ids=sources,
                fact_summary=f"已核验企业自身能源语义数据 {len(own)} 项。",
                analysis=f"已识别{labels}等能源语义事实。进入测算前，仍需确认统计期间、基地范围与计费口径。",
                business_implication="自身用能数据是项目价值测算的输入；产品与项目能力是合作范围证据，两者分开评估。",
                recommendation="进入报价前完成基地级电量、负荷、电价与配电条件核验。",
                limitations=["现有能源事实的时间粒度与基地范围待现场核验。"],
                confidence=min(0.92, 0.55 + 0.04 * len(own)),
                statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
                semantic_domain="energy",
            )
        return DecisionFinding(
            finding_id="DF-ENERGY", decision_question="公开资料能否形成基地级用能画像？",
            conclusion="现有公开资料尚未形成基地级用能画像，用能测算需以现场数据为准",
            supporting_claim_ids=list(dict.fromkeys(claim.claim_id for claim in energy_claims)),
            supporting_source_ids=list(dict.fromkeys(claim.source_id for claim in energy_claims)),
            fact_summary="当前未取得可独立核验的年度用电量、峰值负荷、电价或负荷曲线。",
            analysis="公开披露中的制造产能与产品容量属于生产与产品能力，不能转换为企业自身能源消费。",
            business_implication="现阶段支持技术交流与数据获取，不支持直接进入商业报价。",
            recommendation="把基地级电量、负荷曲线、电价账单与配电容量作为预可研必备输入。",
            limitations=["缺少基地级能源事实。"],
            confidence=0.9 if energy_claims else 0.75,
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE if energy_claims else DecisionStatementType.TO_BE_CONFIRMED,
            semantic_domain="energy",
        )

    # ── due diligence / risks ──────────────────────────────────────────────
    def _due_diligence(self, gaps: list[DataGap]) -> list[DueDiligenceRequirement]:
        requirements: list[DueDiligenceRequirement] = []
        for index, gap in enumerate(gaps, start=1):
            item = field_label(gap.field_name)
            blocker = gap.importance == "critical" or gap.field_name in {
                "electricity_consumption", "load_curve", "electricity_cost", "peak_load", "transformer_capacity",
            }
            requirements.append(DueDiligenceRequirement(
                requirement_id=f"DDR-{index:03d}", item=item,
                why_it_matters=f"{reason_label(gap.reason)}。该事项决定相关方案能否建立可审计的事实和测算边界。",
                affected_decision="项目经济性与是否进入方案设计" if blocker else "合作范围与实施优先级",
                requested_materials=self._requested_materials(gap.field_name),
                timing="项目预可研阶段" if blocker else "首轮技术交流后 30 天内",
                decision_blocker=blocker, source_gap_ids=[gap.gap_id],
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
        if any(item.decision_blocker for item in requirements):
            risks.append("关键现场数据缺失可能导致容量设计、收益估算和投资边界失真。")
        if not bundle.solutions:
            risks.append("公开资料尚未形成可核验的合作场景。")
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
    ) -> list[str]:
        profile = getattr(synthesis, "company_profile", None) if synthesis is not None else None
        business = profile.core_business if profile and profile.core_business else None
        segments = profile.business_segments if profile and profile.business_segments else []
        revenue = analysis.trend("revenue")
        profit = analysis.trend("profit")

        # 1. 企业是什么（100-200字）
        business_text = business or ("、".join(segments) if segments else "以新能源业务为主的综合性企业")
        founded = profile.founded_date if profile and profile.founded_date else ""
        first = (
            f"总体判断：{entity_name}为{judgement}对象。"
            f"公司以{business_text}为核心业务"
            + (f"，成立于{founded}" if founded else "")
            + (f"，总部位于{profile.headquarters}" if profile and profile.headquarters else "")
            + ("，覆盖" + "、".join(segments) + "等板块" if segments else "")
            + f"。本报告基于公开渠道已核验事实，对公司经营、产品、制造布局与能源相关能力作客观研究，再回答与委托方的合作价值与切入方式。"
        )

        # 2. 关键经营事实（真实数据）
        facts: list[str] = []
        if revenue is not None:
            last = revenue.points[-1]
            facts.append(f"营业收入 {last.value_display}{last.unit or ''}（{last.period}）")
        if profit is not None:
            last = profit.points[-1]
            facts.append(f"归母净利润 {last.value_display}{last.unit or ''}（{last.period}）")
        position = next((item for item in analysis.kpis if item.label == "市场地位"), None)
        if position is not None:
            facts.append(f"市场地位：{position.value}")
        family_kpi = next((item for item in analysis.kpis if item.label == "已核验产品族"), None)
        factory_kpi = next((item for item in analysis.kpis if item.label == "已核验生产基地"), None)
        if family_kpi is not None:
            facts.append(f"已核验产品族 {family_kpi.value} 个")
        if factory_kpi is not None:
            facts.append(f"生产基地 {factory_kpi.value} 处")
        if analysis.own_energy_metrics:
            facts.append("企业自身能源数据" + "；".join(
                f"{item.label} {item.value_display}{item.unit or ''}" for item in analysis.own_energy_metrics[:3]
            ))
        second = (
            "核心依据：" + ("；".join(facts) if facts else "已核验公开披露覆盖企业身份、业务与产品制造能力") + "。"
            + ((revenue.statement + "。") if revenue is not None and revenue.year_count >= 3 else "")
            + "这些数据构成判断合作资源基础的客观依据，经营规模反映资源投入能力，产品与基地反映交付能力；"
            "对应证据在后续章节逐项展开并配有图表。"
        )

        # 3. 产业与技术能力（2-4点）
        capabilities: list[str] = []
        product_finding = next((item for item in findings if item.semantic_domain == "product"), None)
        manufacturing_finding = next((item for item in findings if item.semantic_domain == "manufacturing"), None)
        energy_finding = next((item for item in findings if item.semantic_domain == "energy"), None)
        rnd_insight = next((item for item in analysis.insights if item.insight_id == "INS-RND"), None)
        if product_finding is not None:
            capabilities.append(product_finding.conclusion)
        if manufacturing_finding is not None:
            capabilities.append(manufacturing_finding.conclusion)
        if energy_finding is not None:
            capabilities.append(energy_finding.conclusion)
        if rnd_insight is not None:
            capabilities.append(rnd_insight.findings[0])
        third = (
            "产业与技术能力方面，" + ("；".join(capabilities) + "。" if capabilities else "现有公开资料对产业技术能力的披露有限。")
            + f"优先切入：{priority_summary}"
        )

        # 4. 主要机会与限制
        blockers = [item.item for item in requirements if item.decision_blocker]
        limitation = (
            "限制条件：当前尚不能判断的关键事项包括" + "、".join(blockers[:6]) + "。"
            if blockers else "限制条件：关键前置资料整体可控，具体口径需在预可研中复核。"
        )
        risk_text = ("主要风险还包括" + "；".join(risks[:3]) + "。") if risks else ""
        fourth = limitation + risk_text + "缺少基地级电量和负荷时，不估算削峰或自消纳收益；缺少配电和权属条件时，不承诺可实施容量。"

        # 5. 最终建议
        fifth = (
            "行动建议：未来 30 天完成对接主体确认、资料清单发放与优先场景选择；"
            "60 天完成现场踏勘、数据清洗与技术接口验证；90 天提交预可研结论并召开 Go / No-Go 评审。"
            "只有当关键资料齐套、技术边界可控、责任主体明确且价值测算通过敏感性检验时，才进入方案设计或报价阶段，"
            "同时明确返回补数或停止投入的触发条件。"
        )
        return [first, second, third, fourth, fifth]

    @staticmethod
    def _lineage(claims: list[Claim]) -> tuple[list[str], list[str]]:
        return (
            list(dict.fromkeys(claim.claim_id for claim in claims)),
            list(dict.fromkeys(claim.source_id for claim in claims)),
        )
