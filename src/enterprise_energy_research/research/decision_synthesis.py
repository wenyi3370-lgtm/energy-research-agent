"""Evidence -> decision findings, before consulting narrative publication.

This module is intentionally not a renderer.  It converts frozen claims into
typed findings with lineage, limitations and management implications.  Word
and HTML consume the resulting narrative rather than re-reading raw fields.
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
    schema_version: str = "1.0"
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


ENERGY_FIELDS = {
    "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
    "peak_demand", "electricity_cost", "load_curve", "pv_capacity", "storage_capacity",
    "storage_power", "renewable_share", "transformer_capacity", "roof_area",
}
MANUFACTURING_FIELDS = {
    "capacity", "production_capacity", "factory_capacity", "battery_production_capacity",
    "production_lines", "output", "annual_output", "factory_name", "process", "processes",
    "factory_address", "address", "commissioning_date", "project_status",
}
FINANCIAL_FIELDS = {"revenue", "profit", "gross_margin", "rnd_expense", "rnd_expense_ratio"}
PRODUCT_FIELDS = {
    "product_family", "product_catalog_scope", "product_name", "model", "series", "category",
    "parameter_name", "technology", "technology_route", "certification", "application",
}


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
    """Deterministic evidence-bound consulting analysis."""

    def synthesize(self, bundle: FrozenResearchBundle) -> DecisionSynthesis:
        entity = next(
            (item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id),
            bundle.entities[0] if bundle.entities else None,
        )
        if entity is None:
            raise ValueError("Frozen bundle contains no canonical enterprise")
        verified = [claim for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED]
        by_domain: dict[str, list[Claim]] = defaultdict(list)
        by_field: dict[str, list[Claim]] = defaultdict(list)
        for claim in verified:
            by_domain[semantic_domain(claim.field_name)].append(claim)
            by_field[claim.field_name].append(claim)

        findings: list[DecisionFinding] = []
        if strategy := self._strategy_finding(by_domain["strategy"]):
            findings.append(strategy)
        if financial := self._financial_finding(by_domain["financial"]):
            findings.append(financial)
        if product := self._product_finding(bundle, by_domain["product"]):
            findings.append(product)
        if manufacturing := self._manufacturing_finding(bundle, by_domain["manufacturing"]):
            findings.append(manufacturing)
        findings.append(self._energy_finding(by_domain["energy"], by_domain["manufacturing"]))

        due_diligence = self._due_diligence(bundle.gaps)
        blocker_count = sum(item.decision_blocker for item in due_diligence)
        priority_solutions = [item for item in bundle.solutions if item.priority in {"A", "B"} and item.claim_ids]
        concrete_energy = [claim for claim in by_domain["energy"] if claim.field_name in ENERGY_FIELDS]
        if priority_solutions and len(concrete_energy) >= 2 and blocker_count == 0:
            judgement = "推进"
            rationale = "现有公开事实已同时覆盖合作能力、目标场景与关键能源边界，可进入方案共创与项目预可研。"
        elif priority_solutions and verified:
            judgement = "有条件推进"
            rationale = "现有公开事实能够支持进入技术交流和数据获取阶段，但尚不足以直接支持项目报价或收益承诺。"
        else:
            judgement = "暂缓"
            rationale = "当前公开资料尚未形成可核验的合作场景与价值链闭环，应先补齐关键事实，再决定是否投入商务资源。"

        solution_names = list(dict.fromkeys(item.opportunity for item in priority_solutions))
        priority_summary = (
            "优先围绕" + "、".join(solution_names[:3]) + "开展场景核验，先确认价值成立条件，再决定商业化投入。"
            if solution_names else "现阶段不宜人为制造合作机会，优先任务是补齐目标场景和项目边界。"
        )
        key_risks = self._key_risks(bundle, due_diligence)
        decision_questions = [
            "该企业是否值得推进，以及当前可以推进到哪一阶段？",
            "哪些合作方向具备已核验事实基础，优先从什么场景切入？",
            "哪些信息缺口会阻断项目经济性和 Go / No-Go 判断？",
            "未来 90 天应完成哪些验证动作？",
        ]
        executive = self._executive_summary(
            entity.canonical_name, judgement, rationale, findings, priority_summary,
            due_diligence, key_risks,
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

    def _strategy_finding(self, claims: list[Claim]) -> DecisionFinding | None:
        if not claims:
            return None
        ids, sources = self._lineage(claims)
        business_values = [
            str(claim.value).strip() for claim in claims
            if claim.field_name in {"core_business", "business_segment", "business_segments", "industry_position"}
            and str(claim.value).strip()
        ]
        business = "；".join(dict.fromkeys(business_values))
        fact = f"已核验 {len(claims)} 条企业身份、业务边界与组织定位事实。"
        analysis = (
            (f"公开披露将核心业务界定为{business}。" if business else "现有公开资料已确认企业身份与基本业务边界。")
            + "这些事实用于识别合作责任主体、能力边界和战略相关性，但不能单独证明某一具体合作场景具有技术可行性或商业回报。"
            "判断是否推进仍需把企业层能力继续映射到产品、基地和能源数据。"
        )
        return DecisionFinding(
            finding_id="DF-STRATEGY", decision_question="企业业务定位与组织基础是否支持进入合作验证？",
            conclusion="企业身份与业务边界已经可核验，合作判断应继续下沉到具体能力、场景和责任主体",
            supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=fact, analysis=analysis,
            business_implication="企业层事实能够支持确定首轮接触方向，但不能替代场景级预可研和项目经济性。",
            recommendation="围绕已核验核心业务选择责任部门和优先场景，并用场景级数据决定是否继续投入。",
            confidence=min(0.94, 0.55 + len(claims) * 0.03),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="strategy",
        )

    def _financial_finding(self, claims: list[Claim]) -> DecisionFinding | None:
        if not claims:
            return None
        periods = sorted({period for claim in claims if (period := claim_period(claim))})
        fields = sorted({field_label(claim.field_name) for claim in claims})
        if len(periods) >= 3:
            conclusion = f"最近 {len(periods)} 个可比年度已经形成经营趋势基础，但趋势方向仍需按统一口径逐项解释"
            analysis = (
                f"现有披露覆盖 {periods[0]}—{periods[-1]} 年，并包含{'、'.join(fields[:4])}等指标。"
                "这些数据足以支持同比、复合增速和利润率变化分析，但只有在合并范围、币种和会计口径一致时，变化才可被解释为经营趋势。"
            )
        else:
            conclusion = "现有经营数据只能证明当前规模，不能据此声称长期增长趋势"
            analysis = (
                f"当前可比较年度仅有 {len(periods)} 个，公开披露可确认{'、'.join(fields[:4])}等经营信息。"
                "单年或不足三年的数据能够回答企业当前资源基础，却不能区分周期波动、一次性因素与持续增长，因此不应把规模事实包装成趋势判断。"
            )
        ids, sources = self._lineage(claims)
        return DecisionFinding(
            finding_id="DF-FINANCIAL", decision_question="经营与资源基础是否支持合作推进？",
            conclusion=conclusion, supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=f"已核验 {len(claims)} 条经营披露，覆盖 {len(periods)} 个可识别年度。",
            analysis=analysis,
            business_implication="经营规模可以说明合作对象具备资源投入基础，但不能替代项目层面的经济性论证。",
            recommendation="将经营数据作为合作对象筛选依据，同时把基地级电量、负荷和投资边界作为项目决策的独立门槛。",
            limitations=[] if len(periods) >= 3 else ["可比较年度少于 3 个，禁止使用趋势、CAGR 或持续增长表述。"],
            confidence=min(0.95, 0.55 + 0.05 * len(claims)),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="financial",
        )

    def _product_finding(self, bundle: FrozenResearchBundle, claims: list[Claim]) -> DecisionFinding | None:
        verified_products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        if not verified_products or not claims:
            return None
        categories = sorted({item.category or "其他产品" for item in verified_products})
        parameterized = sum(bool(item.parameters) for item in verified_products)
        ids, sources = self._lineage(claims)
        return DecisionFinding(
            finding_id="DF-PRODUCT", decision_question="对方具备哪些可用于合作的产品与技术能力？",
            conclusion="产品能力已经形成可讨论的合作基础，但产品存在不等于能源项目价值已经成立",
            supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=f"已核验 {len(verified_products)} 项产品，覆盖 {len(categories)} 个产品族，其中 {parameterized} 项具有公开参数。",
            analysis=(
                f"现有产品记录主要分布于{'、'.join(categories[:5])}。产品目录与参数能够证明技术路线和交付能力，"
                "但是否适合某一基地仍取决于现场接口、工况、认证责任与商务边界，不能从产品页直接推导项目收益，也不能替代场景级技术核验与经济性论证。"
            ),
            business_implication="产品证据适合支撑技术交流、联合验证和供应链准入，不足以单独支持工程报价。",
            recommendation="优先选择与目标场景直接相关的产品族开展接口核验，并把型号、认证、交付责任和服务边界纳入首轮技术清单。",
            limitations=[] if parameterized else ["公开产品参数不足，技术适配仍需通过原厂资料或联合测试确认。"],
            confidence=min(0.94, 0.58 + 0.03 * len(verified_products)),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="product",
        )

    def _manufacturing_finding(self, bundle: FrozenResearchBundle, claims: list[Claim]) -> DecisionFinding | None:
        if not bundle.factories and not claims:
            return None
        ids, sources = self._lineage(claims)
        if not ids:
            return None
        locations = sorted({item.address for item in bundle.factories if item.address})
        return DecisionFinding(
            finding_id="DF-MANUFACTURING", decision_question="生产布局如何影响合作切入顺序？",
            conclusion="生产布局可用于筛选首批接触基地，但制造产能不得被解释为企业用电规模",
            supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary=f"已识别 {len(bundle.factories)} 处生产基地，公开地点覆盖 {len(locations)} 个区域。",
            analysis=(
                "基地数量、工艺与生产能力反映制造组织和项目落地复杂度，可帮助判断应从总部、业务条线还是具体工厂进入。"
                "但 GWh、产线数量和产能口径描述的是制造输出，不是年度购电量、峰值负荷或负荷曲线，两类指标必须严格分开。"
            ),
            business_implication="首批基地应按业务相关性、数据可得性和决策链路筛选，而不是简单按产能数字排序。",
            recommendation="先选择一处资料完整、场景明确且责任主体清晰的基地做预可研，再决定是否复制到其他基地。",
            limitations=["公开基地名录可能不是法定完整清单，完整名录应放入附录并保留覆盖口径。"],
            confidence=min(0.9, 0.55 + 0.04 * len(claims)),
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
            semantic_domain="manufacturing",
        )

    def _energy_finding(self, energy_claims: list[Claim], manufacturing_claims: list[Claim]) -> DecisionFinding:
        if energy_claims:
            ids, sources = self._lineage(energy_claims)
            fields = sorted({field_label(claim.field_name) for claim in energy_claims})
            return DecisionFinding(
                finding_id="DF-ENERGY", decision_question="公开资料能否形成基地级用能画像？",
                conclusion="能源相关公开事实已提供初步边界，但仍需判断是否达到基地级方案测算要求",
                supporting_claim_ids=ids, supporting_source_ids=sources,
                fact_summary=f"已核验能源语义字段 {len(energy_claims)} 条，涉及{'、'.join(fields[:6])}。",
                analysis=(
                    "只有年度用电量、峰值负荷、电价、负荷曲线、光伏和储能现状等字段，才能进入企业用能画像。"
                    "现有能源事实可用于提出假设和确定资料清单，但若缺少时间粒度、基地范围或计费口径，仍不能可靠估算削峰、需量或自消纳收益。"
                ),
                business_implication="能源能力与基地用能事实必须分别论证；前者证明会做什么，后者决定项目值不值得做。",
                recommendation="在进入报价前完成基地级电量、15 分钟或小时级负荷、电价账单和配电条件核验。",
                limitations=[], confidence=min(0.92, 0.55 + 0.04 * len(energy_claims)),
                statement_type=DecisionStatementType.ANALYTICAL_INFERENCE,
                semantic_domain="energy",
            )
        ids, sources = self._lineage(manufacturing_claims)
        return DecisionFinding(
            finding_id="DF-ENERGY", decision_question="公开资料能否形成基地级用能画像？",
            conclusion="现有公开资料只能确认制造或能源业务能力，尚不足以形成基地级用能画像",
            supporting_claim_ids=ids, supporting_source_ids=sources,
            fact_summary="当前未取得可独立核验的年度用电量、峰值负荷、电价或负荷曲线。",
            analysis=(
                "公开披露中的制造产能、产品容量或 GWh 规模属于生产与产品能力，不能转换为企业自身能源消费。"
                "在缺少基地范围、计量边界和时间序列时，任何用电 KPI、储能收益或光伏自消纳结论都会超出公开事实。"
            ),
            business_implication="现阶段只支持进入技术交流和数据获取阶段，不支持直接进入商业方案或报价阶段。",
            recommendation="把基地级电量、负荷曲线、电价账单、配电容量和可利用屋面作为预可研必备输入。",
            limitations=["缺少基地级能源事实，无法形成可靠的项目经济性判断。"],
            confidence=0.9 if ids else 0.75,
            statement_type=DecisionStatementType.ANALYTICAL_INFERENCE if ids else DecisionStatementType.TO_BE_CONFIRMED,
            semantic_domain="energy",
        )

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
            risks.append("公开资料尚未形成可核验的合作场景，过早投入商务资源可能降低转化效率。")
        return list(dict.fromkeys(risks))[:8]

    def _executive_summary(
        self,
        entity_name: str,
        judgement: str,
        rationale: str,
        findings: list[DecisionFinding],
        priority_summary: str,
        requirements: list[DueDiligenceRequirement],
        risks: list[str],
    ) -> list[str]:
        core_basis = "；".join(item.conclusion for item in findings[:4])
        blockers = [item.item for item in requirements if item.decision_blocker]
        first = (
            f"基于当前冻结的公开事实，建议将{entity_name}定义为“{judgement}”对象。{rationale}"
            "总体判断关注的是合作是否应当进入下一道决策门，而不是对企业整体价值作笼统评价。推进意味着现有证据足以启动预可研；有条件推进意味着只宜进入技术交流和资料获取；暂缓则意味着事实链尚未闭合。"
            "因此，管理层应把本报告当作资源配置边界：先明确当前可以验证什么、不能承诺什么，再决定是否配置商务、技术和投资测算资源。"
        )
        second = (
            f"核心依据可归纳为四层：{core_basis}。这些事实共同说明企业能力、制造基础和合作议题可能具备讨论价值，"
            "但经营规模、产品数量、基地数量和来源数量都不能直接替代项目价值。经营信息回答对方是否具备组织和资源基础，产品与制造信息回答能否形成技术接口，"
            "能源事实才回答具体基地是否存在可量化的成本、韧性或减碳空间。真正影响决策的是能力能否映射到明确场景、场景是否有基地级数据、数据能否支撑可审计的经济性；三层必须连续成立，不能用上一层的数量替代下一层的判断。"
        )
        third = (
            f"优先切入方面，{priority_summary}每个方向都应同时回答战略理由、目标场景、对方已验证能力、我方价值、首个责任接口和继续推进门槛。"
            "优先级不是把所有可能性并排列出，而是把有限资源集中在最容易形成书面 Go / No-Go 结论的一至三处场景。首轮接触应面向能够提供原始资料并对技术边界负责的业务、工厂运营或能源管理主体，"
            "同时明确我方交付是诊断、技术适配、预可研还是工程方案。若战略理由、场景、责任主体、数据和门槛中任何一项缺少事实依据，该方向应降级为技术交流或资料获取任务，而不是包装成成熟商业机会。"
        )
        limitation = (
            "当前尚不能判断的关键事项包括" + "、".join(blockers[:6]) + "。"
            if blockers else "当前关键前置资料已覆盖主要决策边界，但仍需在项目预可研中复核口径和时效。"
        )
        fourth = (
            limitation + ("主要风险还包括" + "；".join(risks[:3]) + "。" if risks else "")
            + "限制条件直接决定哪些结论现在不能形成：缺少基地级电量和负荷时，不能估算削峰或自消纳收益；缺少配电和权属条件时，不能承诺可实施容量；缺少责任边界时，不能确认投资与交付模式。"
            "数据缺失不是研究失败，但把缺失数据包装成确定事实会直接破坏 Go / No-Go 判断。因此所有未核实项必须在受影响结论附近披露，并转化为材料、责任人、获取时点和阻断性四项明确要求。"
        )
        fifth = (
            "行动建议按 30 / 60 / 90 天设门：未来 30 天完成对接主体确认、资料清单发放、一处优先场景选择和计量边界核验，并由双方书面确认缺口责任；"
            "60 天内完成现场踏勘、原始数据清洗、技术接口验证、基准情景与敏感性测算，同时记录不能验证的假设；90 天时提交预可研结论并召开 Go / No-Go 评审。"
            "评审材料至少应回答价值来源、技术约束、责任主体、投资边界、关键风险和退出条件。只有当关键资料齐套、技术边界可控、责任主体明确且价值测算通过敏感性检验时，才进入方案设计或报价阶段；否则应明确返回补数、调整场景或停止投入。"
        )
        return [first, second, third, fourth, fifth]

    @staticmethod
    def _lineage(claims: list[Claim]) -> tuple[list[str], list[str]]:
        return (
            list(dict.fromkeys(claim.claim_id for claim in claims)),
            list(dict.fromkeys(claim.source_id for claim in claims)),
        )
