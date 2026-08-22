"""ResearchNarrative + StoryModule (P0 third round): research-first narrative.

HTML and Word renderers consume the SAME ResearchNarrative.  The pipeline
is now:

    Evidence -> PublicationRelevanceFilter -> ResearchAnalysis
        -> DecisionSynthesis -> PublicationNarrative -> Word/HTML

The narrative's first half answers objective research questions (business
performance, products, manufacturing layout, energy) with real data and
real visuals; the second half carries the consulting judgement
(opportunities, action plan, risks).  Removed in this round:

  * ``_domain_analysis()`` — the fixed 3-4 paragraph consulting template
    per domain (the main source of "AI-flavoured" boilerplate);
  * ``_evidence_interpretations()`` — the field->paragraph expansion that
    turned every claim into a 100-character disclaimer paragraph.

Chapters now aggregate the ResearchAnalysis dataset into paragraph / table
/ visual; a claim is never automatically one paragraph.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from enterprise_energy_research.analysis.financials import AnalysisResult, FinancialAnalyst
from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import (
    Claim,
    FrozenResearchBundle,
    ImageEvidence,
    Product,
)
from enterprise_energy_research.research.synthesis import ResearchSynthesis
from enterprise_energy_research.research.decision_synthesis import (
    DecisionFinding,
    DecisionSynthesis,
    DecisionSynthesisEngine,
    DueDiligenceRequirement,
    ENERGY_FIELDS,
)
from enterprise_energy_research.research.opportunity_assessment import (
    OpportunityAssessment,
    OpportunityAssessmentEngine,
)
from enterprise_energy_research.research.product_images import ProductImageResolver
from enterprise_energy_research.research.research_analysis import (
    ResearchAnalysis,
    ResearchAnalysisEngine,
)
from enterprise_energy_research.artifacts.publication_terminology import (
    PublicationNumberFormatter,
    field_label,
    source_type_label,
    translate_table_row,
)
from enterprise_energy_research.artifacts.visual_opportunity import VisualOpportunityPlanner

from .visual_router import VisualProposal, VisualRouter
from .visuals import VisualDatum, VisualManifest, VisualNode, VisualSpec

# Per-chapter photograph budgets (P0 image count control).
IMAGE_BUDGETS: dict[str, int] = {
    "executive_summary": 2,
    "factories": 6,
    "products": 8,
    "default": 4,
}

# Structured (ownership/partnership) relations that may appear in an
# organization diagram — and ONLY when VERIFIED.  UNKNOWN never qualifies.
STRUCTURED_RELATIONS = {
    "SUBSIDIARY", "CONTROLLED_BY", "OWNED_BY", "JOINT_VENTURE",
    "PARTNER", "SUPPLIER", "CUSTOMER", "LICENSEE",
    "Subsidiary", "ParentCompany", "Owns",
}

# Chapter kinds that count as "analysis chapters" for image budgets.
ANALYSIS_CHAPTERS = {"operations", "energy_profile", "opportunities"}


class VisualEvent(BaseModel):
    """QA-visible routing outcome. User reports never render this."""

    visual_id: str
    chapter_id: str
    pattern: str
    outcome: Literal["routed", "fallback_table", "dropped_to_prose"]
    visual_type: str | None = None
    reason: str | None = None


class StoryModule(BaseModel):
    """One consulting module with assertion, analysis and action semantics."""

    module_id: str
    chapter_id: str
    kind: Literal[
        "executive_summary", "entity_profile", "group_structure", "partnerships",
        "operations", "factories", "products", "energy_profile", "opportunities",
        "action_plan", "risks_evidence",
    ]
    title: str
    assertion_title: str
    decision_question: str
    executive_takeaway: str
    context_paragraphs: list[str] = Field(default_factory=list)
    analysis_paragraphs: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    visual_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    table_rows: list[dict[str, Any]] = Field(default_factory=list)
    order: int = 0

    @property
    def thesis(self) -> str:
        """Compatibility accessor; publication uses ``executive_takeaway``."""
        return self.executive_takeaway

    @property
    def content(self) -> list[str]:
        """Compatibility accessor for tests; the serialized schema is structured."""
        return [
            *self.context_paragraphs, *self.analysis_paragraphs, *self.implications,
            *self.recommendations, *self.counter_evidence, *self.limitations, *self.action_items,
        ]


class NarrativeAppendices(BaseModel):
    source_ledger: list[dict[str, Any]] = Field(default_factory=list)
    image_ledger: list[dict[str, Any]] = Field(default_factory=list)
    due_diligence: list[DueDiligenceRequirement] = Field(default_factory=list)
    factory_ledger: list[dict[str, Any]] = Field(default_factory=list)
    product_ledger: list[dict[str, Any]] = Field(default_factory=list)


class ResearchNarrative(BaseModel):
    schema_version: str = "3.1"
    run_id: str
    freeze_id: str
    entity_name: str
    entity_id: str | None = None
    decision_questions: list[str] = Field(default_factory=list)
    overall_judgement: str = ""
    judgement_rationale: str = ""
    executive_summary: list[str] = Field(default_factory=list)
    decision_findings: list[DecisionFinding] = Field(default_factory=list)
    opportunity_assessments: list[OpportunityAssessment] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    chapters: list[StoryModule] = Field(default_factory=list)
    visuals: list[VisualSpec] = Field(default_factory=list)
    visual_events: list[VisualEvent] = Field(default_factory=list)
    kpis: list[dict[str, Any]] = Field(default_factory=list)
    product_images: dict[str, str] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    appendices: NarrativeAppendices = Field(default_factory=NarrativeAppendices)
    generated_at: str = ""

    def visual_manifest(self) -> VisualManifest:
        return VisualManifest(
            freeze_id=self.freeze_id,
            visuals=self.visuals,
        )

    def chapter(self, chapter_id: str) -> StoryModule | None:
        return next((item for item in self.chapters if item.chapter_id == chapter_id), None)

    def visuals_for(self, chapter_id: str) -> list[VisualSpec]:
        ids = next(
            (item.visual_ids for item in self.chapters if item.chapter_id == chapter_id),
            [],
        )
        wanted = set(ids)
        return [visual for visual in self.visuals if visual.visual_id in wanted]


def publishable_images(bundle: FrozenResearchBundle) -> list[ImageEvidence]:
    """Images that may appear as verified illustrations.

    P0 rule: a published image needs a bound target entity AND pixel-level
    visual verification — except editorial images (covers, maps) which carry
    no entity claim.  Context-only images never publish as entity photos.
    """
    return [
        image for image in bundle.images
        if image.target_entity_type == "editorial"
        or (image.target_entity_id is not None and image.visual_verified)
    ]


class NarrativeBuilder:
    """Builds ResearchNarrative from one FrozenResearchBundle."""

    def __init__(self, router: VisualRouter | None = None, analyst: FinancialAnalyst | None = None) -> None:
        self.router = router or VisualRouter()
        self.analyst = analyst or FinancialAnalyst()
        self.decision_engine = DecisionSynthesisEngine()
        self.opportunity_engine = OpportunityAssessmentEngine()

    # ── entry ──
    def build(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis | None = None) -> ResearchNarrative:
        entity = self._canonical_entity(bundle)
        if entity is None:
            raise ValueError("Frozen bundle contains no enterprise entity")
        synthesis = synthesis or self._default_synthesis(bundle, entity)
        analysis = ResearchAnalysisEngine().analyze(bundle)
        decision = self.decision_engine.synthesize(bundle, analysis, synthesis)
        opportunities = self.opportunity_engine.assess(bundle)
        product_images = ProductImageResolver().resolve(bundle)

        narrative = ResearchNarrative(
            run_id=bundle.run_manifest.run_id,
            freeze_id=bundle.freeze.freeze_id,
            entity_name=entity.canonical_name,
            entity_id=entity.entity_id,
            overall_judgement=decision.overall_judgement,
            judgement_rationale=decision.judgement_rationale,
            decision_findings=decision.findings,
            opportunity_assessments=opportunities,
            key_risks=decision.key_risks,
            kpis=[item.model_dump(mode="json") for item in analysis.kpis],
            product_images=product_images,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        order = 0
        used_images: set[str] = set()

        def add(chapter: StoryModule) -> None:
            nonlocal order
            chapter.order = order
            order += 1
            narrative.chapters.append(chapter)
            used_images.update(chapter.image_ids)

        def images_for(*, chapter: str, entity_id: str | None, product_ids: set[str] | None = None, factory_ids: set[str] | None = None) -> list[str]:
            return self._images_for(
                bundle, chapter=chapter, entity_id=entity_id,
                product_ids=product_ids, factory_ids=factory_ids, exclude=used_images,
            )

        narrative.decision_questions = decision.decision_questions
        narrative.executive_summary = list(decision.executive_summary_paragraphs)
        add(self._decision_executive(bundle, decision, analysis, opportunities, images_for, narrative))

        structure = self._chapter_group_structure(bundle, narrative)
        if structure is not None:
            add(structure)

        finding_by_domain = {item.semantic_domain: item for item in decision.findings}
        add(self._operations_module(bundle, analysis, finding_by_domain, narrative, synthesis))
        if any(product.verification_status == VerificationStatus.VERIFIED for product in bundle.products):
            add(self._products_module(bundle, analysis, finding_by_domain.get("product"), narrative, images_for))
        if bundle.factories:
            add(self._factories_module(bundle, analysis, finding_by_domain.get("manufacturing"), narrative, images_for))
        add(self._energy_module(bundle, analysis, finding_by_domain.get("energy"), narrative))
        if opportunities:
            add(self._opportunity_module(opportunities, narrative))
            add(self._action_module(opportunities, narrative))
        add(self._risk_module(decision))

        narrative.appendices = NarrativeAppendices(
            source_ledger=[{
                "来源名称": source.source_title or source.source_domain,
                "来源类型": source_type_label(source.source_level),
                "发布日期": source.publication_date.isoformat() if source.publication_date else "",
                "网址": str(source.canonical_url),
            } for source in bundle.sources],
            image_ledger=[{
                "图片说明": image.source_title or image.image_type,
                "原始页面": str(image.source_page_url),
            } for image in bundle.images],
            due_diligence=decision.due_diligence,
            factory_ledger=[translate_table_row({
                "name": factory.name or "未命名基地", "address": factory.address or "",
                "processes": "、".join(factory.processes), "status": factory.operating_status or "",
            }) for factory in bundle.factories],
            product_ledger=[translate_table_row({
                "name": product.name, "brand": product.brand or "", "model": product.model or "",
                "category": product.category or "未分类", "series": product.series or "",
                "parameters": "；".join(
                    f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                    for parameter in product.parameters
                ),
            }) for product in bundle.products if product.verification_status == VerificationStatus.VERIFIED],
        )

        narrative.counts = self._counts(bundle, narrative)
        return narrative

    # ── executive summary (data-first) ─────────────────────────────────────
    def _decision_executive(self, bundle, decision: DecisionSynthesis, analysis: ResearchAnalysis, opportunities: list[OpportunityAssessment], images_for, narrative: ResearchNarrative) -> StoryModule:
        entity = self._canonical_entity(bundle)
        paragraphs = decision.executive_summary_paragraphs
        kpi_items = [
            VisualDatum(label=item.label, value=item.value, unit=item.unit, period=item.period, note=item.scope)
            for item in analysis.kpis
        ]
        module = StoryModule(
            module_id="mod-exec", chapter_id="executive_summary", kind="executive_summary",
            title="执行摘要与决策建议",
            assertion_title=f"{decision.overall_judgement}：{decision.judgement_rationale}",
            decision_question=decision.decision_questions[0],
            executive_takeaway=decision.judgement_rationale,
            context_paragraphs=paragraphs[:1],
            analysis_paragraphs=paragraphs[1:],
            source_ids=list(dict.fromkeys(source_id for finding in decision.findings for source_id in finding.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(claim_id for finding in decision.findings for claim_id in finding.supporting_claim_ids)),
        )
        if kpi_items:
            proposal = VisualProposal(
                visual_id="v-exec-kpis", chapter_id="executive_summary",
                decision_question=decision.decision_questions[0],
                business_thesis="关键经营指标一栏总览（全部来自已核验公开披露）。",
                semantic_pattern="quantitative_facts", title="关键经营指标",
                data_binding="research:kpis",
                source_ids=list(dict.fromkeys(source_id for item in analysis.kpis for source_id in item.source_ids)),
                source_claim_ids=list(dict.fromkeys(claim_id for item in analysis.kpis for claim_id in item.claim_ids)),
                items=kpi_items,
                source_note=self._source_note(bundle, list(dict.fromkeys(source_id for item in analysis.kpis for source_id in item.source_ids))),
                semantic_domain="strategy",
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(chapter="executive_summary", entity_id=entity.entity_id)
        return module

    # ── 2. operations: data-centric business chapter ───────────────────────
    def _operations_module(self, bundle, analysis: ResearchAnalysis, finding_by_domain: dict[str, DecisionFinding], narrative: ResearchNarrative, synthesis: ResearchSynthesis | None = None) -> StoryModule:
        entity = self._canonical_entity(bundle)
        financial = finding_by_domain.get("financial")
        strategy = finding_by_domain.get("strategy")
        findings = [item for item in (strategy, financial) if item is not None]
        revenue = analysis.trend("revenue")
        profit = analysis.trend("profit")
        revenue_claims = [claim for claim in self._verified_claims(bundle) if claim.field_name == "revenue"]
        if revenue is not None and revenue.year_count >= 3:
            assertion = "近三年经营形成经营趋势基础，可支持趋势与增速分析"
        elif revenue is not None or revenue_claims:
            assertion = "现有经营数据只能证明当前规模，不能据此声称长期增长趋势"
        else:
            assertion = "公开经营数据的年度可比口径有限，本章以已核验事实呈现企业业务结构"

        context: list[str] = []
        business_insight = next((item for item in analysis.insights if item.insight_id == "INS-BUSINESS"), None)
        if business_insight is not None:
            context.append(
                f"{business_insight.findings[0] if business_insight.findings else ''}"
                "公开披露显示公司业务围绕上述板块展开，该结构决定首轮合作的责任主体与议题范围；"
                "主营业务与产业板块的公开表述构成后续经营、产品与制造分析的框架。"
            )
        if financial is not None:
            context.append(financial.fact_summary)
        if strategy is not None and strategy.analysis:
            context.append(strategy.analysis)

        analysis_paragraphs: list[str] = []
        profile_text = self._profile_paragraph(bundle)
        if profile_text:
            analysis_paragraphs.append(profile_text)
        if synthesis is not None and synthesis.business_summary:
            analysis_paragraphs.append(
                f"{synthesis.business_summary.strip('。')}。"
                "该表述来自公开披露的综合归纳，用于定位企业的业务底盘与合作议题；具体业务占比以分业务披露数据为准。"
            )
        financial_paragraphs: list[str] = []
        for trend in analysis.trends:
            if trend.field_name in {"revenue", "profit", "rnd_expense", "capacity"} or trend.year_count >= 2:
                financial_paragraphs.append(trend.statement)
                if trend.consulting_note:
                    financial_paragraphs.append(trend.consulting_note)
        for insight in analysis.insights:
            if insight.topic == "financial":
                financial_paragraphs.extend(insight.findings)
                if insight.consulting_note:
                    financial_paragraphs.append(insight.consulting_note)
        comparison = next((item for item in analysis.comparisons if item.comparison_id == "CMP-SEGMENTS"), None)
        if comparison is not None:
            financial_paragraphs.append(comparison.statement)
        if not financial_paragraphs:
            financial_paragraphs.append(
                "公开披露的经营数据以单年口径为主：目前可确认企业当前经营规模，但年度可比序列不足，"
                "暂不外推长期增长趋势；后续将通过年报与交易所披露补齐可比年度数据，用于增速与盈利质量分析。"
            )
        analysis_paragraphs.extend(dict.fromkeys(financial_paragraphs))
        has_position = any(claim.field_name in {"market_share", "industry_position"} for claim in self._verified_claims(bundle))
        if not has_position:
            analysis_paragraphs.append(
                "公开资料暂未披露可独立核验的市场份额、装机量排名或行业地位数据；"
                "产业地位判断需以行业机构统计或官方披露为准，本章不作推测；该缺口不影响经营规模判断，但影响行业地位结论，后续以权威行业数据为准。"
            )
        consulting = "；".join(dict.fromkeys(item.business_implication for item in findings))
        if consulting:
            analysis_paragraphs.append(
                consulting + "经营数据用于合作对象筛选与资源基础判断，项目层面的经济性仍以基地级数据独立测算；"
                "经营规模与项目收益分账管理，避免把企业层数字重复包装为项目层价值。"
            )
        analysis_paragraphs.append(
            "从合作基础看，现有公开事实支持以产品与基地为切入点的合作讨论；"
            "多年收入与利润序列等高价值数据补齐后，可进一步评估经营趋势与盈利质量，并形成跨期可比图表，该补齐工作由定向检索完成。"
        )
        analysis_paragraphs.append(
            "本章回答的经营问题是：公司多大、经营如何变化、收入来自哪里、盈利与研发投入如何；"
            "针对公开数据可支撑的维度逐项给出结论，未披露的维度如实记录为数据缺口，该口径同样适用于表格与图表数据。"
        )
        analysis_paragraphs.append(
            "经营章节的数据基础为公开披露口径：收入、利润等指标以原始披露的时间、范围与单位为准，不进行行业均值替代；"
            "数据缺口在文末附录中列示，并转化为待补资料清单，每项缺口标注责任部门与承诺日期。"
        )

        module = StoryModule(
            module_id="mod-operations", chapter_id="operations", kind="operations",
            title="企业经营与战略位置", assertion_title=assertion,
            decision_question="公司经营规模、趋势与业务结构如何？",
            executive_takeaway="；".join(dict.fromkeys(item.conclusion for item in findings)),
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=list(dict.fromkeys(item.business_implication for item in findings)),
            recommendations=list(dict.fromkeys(item.recommendation for item in findings)),
            limitations=list(dict.fromkeys(limitation for item in findings for limitation in item.limitations))[:1],
            source_ids=list(dict.fromkeys(value for item in findings for value in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(value for item in findings for value in item.supporting_claim_ids)),
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).financial_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    # ── 3. products: key products + parameters + images ────────────────────
    def _products_module(self, bundle, analysis: ResearchAnalysis, finding: DecisionFinding | None, narrative: ResearchNarrative, images_for) -> StoryModule:
        entity = self._canonical_entity(bundle)
        verified_products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        key_ids = analysis.key_product_ids or [item.product_id for item in verified_products[:6]]
        key_products = [item for item in verified_products if item.product_id in key_ids]
        families = next((item for item in analysis.comparisons if item.comparison_id == "CMP-FAMILIES"), None)

        context: list[str] = []
        if families is not None:
            context.append(families.statement + "产品族结构反映产品线重心与公开披露深度，该结构是技术适配讨论的起点，并与目标场景匹配，减少重复确认工作。")
        else:
            context.append(f"已核验产品合计 {len(verified_products)} 项。")
        if finding is not None:
            context.append(finding.fact_summary + "产品记录以公开产品中心与规格资料为口径。")

        analysis_paragraphs: list[str] = []
        for product in key_products[:8]:
            params = "；".join(
                f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                for parameter in product.parameters[:4]
            )
            application = "、".join(product.applications[:3])
            sentence = f"{product.name}" + (f"（{product.series}）" if product.series else "") + (f"（型号 {product.model}）" if product.model else "")
            if product.description:
                sentence += f"，{product.description.strip('。')}"
            if params:
                sentence += f"：{params}"
            sentence += "。" if not application else f"；主要应用于{application}。"
            sentence += "该产品构成双方产品接口核验与技术适配讨论的起点，参数完整性直接影响适配判断效率，并列出应用场景便于与目标场景匹配，减少重复确认。"
            analysis_paragraphs.append(sentence)
        parameterized = sum(bool(item.parameters) for item in verified_products)
        if parameterized:
            analysis_paragraphs.append(
                f"已核验产品中 {parameterized} 项具有公开参数，参数覆盖{'、'.join(dict.fromkeys(parameter.name for product in verified_products for parameter in product.parameters))[:8]}等指标；"
                "其余指标需结合原厂规格书与认证文件在技术交流阶段确认，参数口径以产品页与规格书为准，必要时向原厂索取正式规格书，并核对认证与检测报告。"
            )
        else:
            analysis_paragraphs.append(
                "已核验产品目前以名录与系列信息为主，公开参数有限；"
                "技术适配所需的能量密度、循环寿命、充电倍率等关键指标需随技术交流向原厂索取规格书确认，完整产品矩阵见附录产品清单。"
            )
        families_text = "、".join(sorted({product.category or "未分类" for product in verified_products}))
        analysis_paragraphs.append(
            f"从产品组合看，公司当前公开产品集中在{families_text}等产品族；"
            "产品路线与技术差异需结合系列、型号与参数信息进一步核验，本节只呈现公开披露可支撑的结论，技术路线时间轴需以发布时间等数据支撑。"
        )
        analysis_paragraphs.append(
            "产品分析章节回答“有哪些核心产品族、参数有何差异”；正文聚焦重点产品，完整矩阵与参数明细放附录，"
            "避免以数据库打印件代替研究报告，同时保留 HTML 端的搜索与对比能力，以提升可交互性并降低读者查找成本。"
        )
        if len(verified_products) > len(key_products):
            analysis_paragraphs.append(
                f"其余 {len(verified_products) - len(key_products)} 项产品明细见附录产品清单；"
                "HTML 版本支持按产品族筛选与最多 4 项参数对比，便于快速定位与目标场景相关的产品族。"
            )
        analysis_paragraphs.append(
            "产品实景与图片证据遵循“来源可追溯、产品可绑定、视觉已核验”的发布规则；"
            "无合格图片的产品以文本卡片呈现，不放置占位图，也不使用搜索结果缩略图；"
            "图片缺失在质量检查中以覆盖缺口记录，并触发定向补采流程。"
        )

        rows = [translate_table_row({
            "name": product.name, "brand": product.brand or "", "model": product.model or "",
            "category": product.category or "未分类", "series": product.series or "",
            "parameters": "；".join(
                f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                for parameter in product.parameters
            ),
        }) for product in verified_products]

        assertion = finding.conclusion if finding is not None else f"已核验产品 {len(verified_products)} 项，覆盖 {len({item.category or '未分类' for item in verified_products})} 个产品族"
        product_claim_ids = [
            claim.claim_id for claim in self._verified_claims(bundle)
            if claim.field_name in {"product_family", "product_catalog_scope", "product_name", "model", "series", "parameter_name", "product_parameter"}
        ]
        module = StoryModule(
            module_id="mod-products", chapter_id="products", kind="products",
            title="核心产品与技术能力", assertion_title=assertion,
            decision_question="有哪些核心产品族，关键技术参数有何差异？",
            executive_takeaway=finding.business_implication if finding is not None else "产品与参数构成技术交流的事实基础。",
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=[finding.business_implication] if finding is not None else [],
            recommendations=[finding.recommendation] if finding is not None else [],
            limitations=list(finding.limitations or [])[:1] if finding is not None else [],
            source_ids=list(dict.fromkeys(source_id for product in verified_products for source_id in product.source_ids)),
            claim_ids=list(dict.fromkeys([*(finding.supporting_claim_ids if finding is not None else []), *product_claim_ids])),
            table_rows=rows,
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).product_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(
            chapter="products", entity_id=entity.entity_id,
            product_ids={product.product_id for product in verified_products},
        )
        return module

    # ── 4. factories: geo distribution + core bases ────────────────────────
    def _factories_module(self, bundle, analysis: ResearchAnalysis, finding: DecisionFinding | None, narrative: ResearchNarrative, images_for) -> StoryModule:
        entity = self._canonical_entity(bundle)
        region_insight = next((item for item in analysis.insights if item.insight_id == "INS-REGIONS"), None)
        context: list[str] = []
        if region_insight is not None:
            context.append(
                f"{region_insight.findings[0] if region_insight.findings else ''}"
                "基地名录（含地址与工艺）完整保留在附录，供选址与切入顺序判断。"
            )
        if finding is not None:
            context.append(finding.fact_summary + "基地清单为公开渠道可核验口径，可能并非法定完整名录。")
        if not context:
            context.append(f"已核验生产基地 {len(bundle.factories)} 处，完整名录见附录基地清单。")

        analysis_paragraphs: list[str] = []
        distribution = analysis.region_distribution
        if distribution:
            regions = "、".join(f"{region} {count} 处" for region, count in list(distribution.items())[:8])
            analysis_paragraphs.append(
                f"从地域结构看，生产基地分布在{regions}。"
                "区域集中度反映产能组织重心，也影响跨区域复制试点时的审批、物流与运维条件；"
                "首批切入应优先选择与目标场景直接相关、资料可得性高的基地，避免以产能排名代替选择。"
            )
            if analysis.overseas_factory_count:
                analysis_paragraphs.append(
                    f"国内基地 {analysis.domestic_factory_count} 处、海外基地 {analysis.overseas_factory_count} 处，"
                    "海外布局反映交付与供应链的境外延伸，合作切入需分别确认境内外的责任主体与标准适用。"
                )
        else:
            analysis_paragraphs.append("基地地址公开披露有限，地域归类将在附录基地清单中随地址原文保留。")
        analysis_paragraphs.append(
            "地址信息不完整或未标注地区的基地保留原文待核验，不强行归类；"
            "基地清单随新增公开披露滚动更新，区位判断以最新披露为准。"
        )
        for index, factory in enumerate(bundle.factories[:6]):
            location = f"，位于{factory.address}" if factory.address else ""
            process = f"，主要工艺为{'、'.join(factory.processes)}" if factory.processes else ""
            status = f"，状态：{factory.operating_status}" if factory.operating_status else ""
            if index == 0:
                analysis_paragraphs.append(
                    f"{factory.name or '未命名基地'}{location}{process}{status}。"
                    "基地工艺与产线信息用于评估项目落地的工程条件与责任接口，也用于判断试点复制的可行性，基地之间复制需单独评估。"
                )
            else:
                analysis_paragraphs.append(f"{factory.name or '未命名基地'}{location}{process}{status}。")
        if region_insight is not None and region_insight.consulting_note:
            analysis_paragraphs.append(
                region_insight.consulting_note + "基地选择不以产能数字为唯一依据，而应结合业务相关性、数据可得性与决策链路综合判断，完整名录见附录 E。"
            )
        capacity_trend = analysis.trend("capacity")
        if capacity_trend is not None and capacity_trend.year_count >= 2:
            analysis_paragraphs.append(capacity_trend.statement)
        else:
            analysis_paragraphs.append(
                "公开资料暂未形成多年度可比产能序列；产能口径描述制造输出，与企业自身用电规模是两类指标，"
                "项目测算不使用产能数字替代负荷与电量数据，用电与负荷须以现场计量为准，测算边界须双方书面确认。"
            )

        # Body shows only the most informative bases; full ledger is an appendix.
        core_rows: list[dict[str, Any]] = []
        for factory in bundle.factories[:10]:
            core_rows.append(translate_table_row({
                "name": factory.name or "未命名基地", "address": factory.address or "",
                "processes": "、".join(factory.processes), "status": factory.operating_status or "",
            }))
        if len(bundle.factories) > len(core_rows):
            analysis_paragraphs.append(f"完整 {len(bundle.factories)} 处基地名录见附录基地清单。")

        assertion = finding.conclusion if finding is not None else f"已核验生产基地 {len(bundle.factories)} 处"
        module = StoryModule(
            module_id="mod-factories", chapter_id="factories", kind="factories",
            title="生产布局与产能组织", assertion_title=assertion,
            decision_question="生产基地集中在哪里，产能如何组织？",
            executive_takeaway=finding.business_implication if finding is not None else "基地分布用于筛选首批接触基地。",
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=[finding.business_implication] if finding is not None else [],
            recommendations=[finding.recommendation] if finding is not None else [],
            limitations=list(finding.limitations or [])[:1] if finding is not None else [],
            source_ids=list(finding.supporting_source_ids) if finding is not None else [],
            claim_ids=list(finding.supporting_claim_ids) if finding is not None else [],
            table_rows=core_rows,
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).factory_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(
            chapter="factories", entity_id=entity.entity_id,
            factory_ids={factory.factory_id for factory in bundle.factories},
        )
        return module

    # ── 5. energy & zero-carbon ────────────────────────────────────────────
    def _energy_module(self, bundle, analysis: ResearchAnalysis, finding: DecisionFinding | None, narrative: ResearchNarrative) -> StoryModule:
        context: list[str] = []
        if analysis.own_energy_metrics:
            context.append(
                "企业自身能源数据：" + "；".join(
                    f"{item.label} {item.value_display}{item.unit or ''}"
                    + (f"（{item.period}）" if item.period else "")
                    for item in analysis.own_energy_metrics
                ) + "。这些数据描述企业自身的用能条件，是分布式光伏与储能场景测算的输入，与能源产品能力是两类信息；"
                "屋顶面积规模支持分布式光伏场景的初步讨论，具体装机与收益需结合屋面荷载、遮挡与并网条件测算。"
            )
        elif finding is not None:
            context.append(finding.fact_summary + "基地级用电量、负荷曲线与电价账单需在预可研阶段由现场数据补齐。")
        else:
            context.append(
                "公开渠道暂未披露可独立核验的企业自身能源数据；"
                "基地级用电量、负荷曲线与电价账单需在预可研阶段由现场数据补齐，测算不得以制造产能或产品容量替代。"
            )

        analysis_paragraphs: list[str] = []
        for insight in analysis.insights:
            if insight.topic == "energy":
                analysis_paragraphs.append(
                    f"{insight.findings[0] if insight.findings else ''}"
                    "进入测算前，仍需确认统计期间、基地范围与计费口径，并把制造产能与产品容量排除在用能画像之外，原始披露值保留备查，相关边界以现场数据为准。"
                )
                if insight.consulting_note:
                    analysis_paragraphs.append(insight.consulting_note)
        if analysis.energy_product_metrics:
            analysis_paragraphs.append(
                "能源产品/项目能力：" + "；".join(
                    f"{item.label} {item.value_display}{item.unit or ''}"
                    for item in analysis.energy_product_metrics
                ) + "。产品能力说明企业会做什么，与企业自身用能规模是两类信息，分别用于合作范围判断与项目价值测算。"
            )
        else:
            analysis_paragraphs.append(
                "公开资料中暂未识别出独立可核验的能源产品/项目指标；"
                "储能、光伏、零碳等能力需以企业官方产品页或项目披露为准，本章不作推断；"
                "项目级证据（并网规模、投运时间）暂缺时，不推导项目收益结论。"
            )
        if not analysis_paragraphs:
            analysis_paragraphs.append(
                "能源章节区分两类事实：企业自身用能数据（决定项目值不值得做）与能源产品/项目能力"
                "（说明双方会做什么）。现有公开资料以产品与项目能力为主，基地级用能数据需在预可研阶段获取。"
            )
        analysis_paragraphs.append(
            "零碳方面，公开资料暂未披露企业级碳盘查、零碳工厂或绿电采购的项目级信息；"
            "零碳项目时间轴与减排数据需以官方可持续发展报告或项目披露为准，本节不作推断，其披露以官方口径为准，最新口径以企业披露为准。"
        )
        if finding is not None and finding.business_implication:
            analysis_paragraphs.append(
                finding.business_implication + "屋顶资源与配电条件是分布式方案可行性的直接边界，需与电量、电价一并纳入资料清单，"
                "并在预可研阶段按基地逐项核验。"
            )

        assertion = finding.conclusion if finding is not None else "现有公开资料以能源产品与项目能力为主"
        module = StoryModule(
            module_id="mod-energy", chapter_id="energy_profile", kind="energy_profile",
            title="能源与零碳能力", assertion_title=assertion,
            decision_question="企业有哪些能源数据与零碳能力？",
            executive_takeaway=finding.business_implication if finding is not None else "自身用能数据与能源产品能力分开评估。",
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=[finding.business_implication] if finding is not None else [],
            recommendations=[finding.recommendation] if finding is not None else [],
            limitations=list(finding.limitations or [])[:1] if finding is not None else [],
            source_ids=list(finding.supporting_source_ids) if finding is not None else [],
            claim_ids=list(finding.supporting_claim_ids) if finding is not None else [],
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).energy_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    # ── opportunities / action / risks (consulting layer) ──────────────────
    def _opportunity_module(self, opportunities: list[OpportunityAssessment], narrative: ResearchNarrative) -> StoryModule:
        paragraphs: list[str] = []
        rows: list[dict[str, Any]] = []
        for rank, item in enumerate(opportunities, start=1):
            paragraphs.extend([
                f"优先方向 {rank} 为{item.opportunity_name}（优先级 {item.priority}）。{item.strategic_rationale}"
                f"战略匹配、实施可行性、证据强度与商业潜力评分分别为 {item.strategic_fit}、{item.implementation_feasibility}、"
                f"{item.evidence_strength} 和 {item.commercial_potential}，评分用于安排验证顺序。",
                f"切入场景为{item.target_scenario}：对方需要解决{item.target_need}，我方价值在于{item.our_value_proposition}。"
                f"首个责任接口为{item.entry_point}，由{item.owner}推动；推进前需取得{'、'.join(item.key_prerequisites)}。",
                f"行动节奏：前 30 天{item.first_30_day_action}；第 60 天{item.day_60_action}；第 90 天里程碑为{item.day_90_milestone}。"
                f"成功标准为{item.success_kpi}，最终门槛：{item.go_no_go_gate}。",
            ])
            rows.append(translate_table_row({
                "opportunity": item.opportunity_name, "priority": item.priority,
                "target_scenario": item.target_scenario, "entry_point": item.entry_point,
                "go_no_go_gate": item.go_no_go_gate,
            }))
        top = opportunities[0]
        module = StoryModule(
            module_id="mod-opportunities", chapter_id="opportunities", kind="opportunities",
            title="合作机会评估与优先级",
            assertion_title=f"{top.opportunity_name}排名首位，须先通过数据与场景门槛再进入商业化",
            decision_question="哪些合作机会最值得推进，从哪里切入？",
            executive_takeaway=f"优先级由战略匹配、实施可行性、事实强度与商业潜力共同决定，当前首位为{top.opportunity_name}。",
            analysis_paragraphs=paragraphs,
            limitations=["未达到事实与可行性门槛的方向不进入优先机会清单。"],
            source_ids=list(dict.fromkeys(s for item in opportunities for s in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(c for item in opportunities for c in item.supporting_claim_ids)),
            table_rows=rows,
        )
        proposal = VisualOpportunityPlanner.opportunity_proposal(opportunities)
        if proposal is not None:
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    def _action_module(self, opportunities: list[OpportunityAssessment], narrative: ResearchNarrative) -> StoryModule:
        actions = []
        for item in opportunities[:3]:
            actions.extend([
                f"30 天｜{item.opportunity_name}：{item.first_30_day_action}",
                f"60 天｜{item.opportunity_name}：{item.day_60_action}",
                f"90 天｜{item.opportunity_name}：{item.day_90_milestone}",
            ])
        module = StoryModule(
            module_id="mod-action", chapter_id="action_plan", kind="action_plan",
            title="优先切入方案与 90 天行动",
            assertion_title="90 天行动以一处场景的 Go / No-Go 结论为终点",
            decision_question="未来 90 天应完成什么，谁负责，如何判断成功？",
            executive_takeaway="行动链按资料、现场、测算、评审四个门槛推进，任一门槛不满足即返回补数或暂停。",
            analysis_paragraphs=[
                "30 天阶段解决责任主体和数据边界，60 天阶段解决技术适配和价值测算，90 天阶段形成书面决策。"
                "每个阶段以可核查输入和书面产出为完成标志，容量、收益或工期数字必须回溯到已核验输入；"
                "前一道门未通过时，后一道工作不得以假设替代。",
                "各阶段完成标志为书面产出：资料清单双方签认、数据清洗记录归档、基准情景与敏感性测算成文、"
                "Go / No-Go 评审结论落表，确保每个里程碑可以审计和追溯，并同步更新单一问题台账，台账口径由双方共用。",
            ], action_items=actions,
            source_ids=list(dict.fromkeys(s for item in opportunities for s in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(c for item in opportunities for c in item.supporting_claim_ids)),
        )
        proposal = VisualOpportunityPlanner.action_proposal(opportunities)
        if proposal is not None:
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    @staticmethod
    def _risk_module(decision: DecisionSynthesis) -> StoryModule:
        due_rows = [{
            "当前尚不能判断的关键事项": item.item,
            "为什么重要": item.why_it_matters,
            "影响判断": item.affected_decision,
            "建议获取资料": "；".join(item.requested_materials),
            "获取时点": item.timing,
            "是否阻断决策": "是" if item.decision_blocker else "否",
        } for item in decision.due_diligence]
        return StoryModule(
            module_id="mod-risks", chapter_id="risks_evidence", kind="risks_evidence",
            title="风险、前置条件与 Go / No-Go 判断",
            assertion_title="关键现场数据未齐套前，Go / No-Go 应停留在技术交流层而非报价层",
            decision_question="主要风险、前置条件和停止条件是什么？",
            executive_takeaway="缺口必须转化为责任明确、时点明确、影响明确的决策前置条件。",
            context_paragraphs=[
                "本章集中呈现合作推进的主要风险、前置条件与停止条件，并把每条缺口转化为责任、时点与影响明确的行动要求；"
                "风险清单来自公开资料识别与现场数据缺口分析，不构成对企业的投资评级，新发现的缺口在问题台账中补充。"
            ],
            analysis_paragraphs=[
                *(decision.key_risks or ["当前未发现需要单列的外部风险，仍应在预可研阶段复核数据口径、责任边界与项目时效，确保测算输入可追溯、结论可复核。"]),
                "Go 条件覆盖事实、技术、组织和商业四个维度：原始数据口径一致且可复核，关键接口与工程条件可行，"
                "责任主体和审批路径明确，价值测算在不利情景下仍满足双方门槛。任一维度不满足，不得仅凭其他维度优势越级推进。",
                "No-Go 不等于永久否定合作：缺口在明确期限内关闭可返回补数；核心价值来源无法验证、责任主体长期缺位"
                "或技术边界不可控时，应停止当前方向，把团队资源转向证据更强的机会，避免以会议热度替代决策质量。",
            ],
            recommendations=[
                "在决策评审会上逐项核对阻断性资料；未取得原始数据或责任部门书面确认的事项不得以假设替代。"
            ], table_rows=due_rows,
            source_ids=list(dict.fromkeys(source_id for finding in decision.findings for source_id in finding.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(claim_id for finding in decision.findings for claim_id in finding.supporting_claim_ids)),
        )

    # ── group structure (unchanged ownership tree) ─────────────────────────
    def _chapter_group_structure(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative) -> StoryModule | None:
        entity = self._canonical_entity(bundle)
        verified_edges = [
            edge for edge in bundle.edges
            if edge.verification_status == VerificationStatus.VERIFIED
            and edge.relation in STRUCTURED_RELATIONS
        ]
        ownership_edges = [
            edge for edge in verified_edges
            if edge.relation in {"SUBSIDIARY", "CONTROLLED_BY", "OWNED_BY", "JOINT_VENTURE", "Subsidiary", "ParentCompany", "Owns"}
        ]
        if not ownership_edges:
            return None
        entity_names = {item.entity_id: item.canonical_name for item in bundle.entities}
        children_ids = {edge.to_id for edge in ownership_edges}
        roots = {edge.from_id for edge in ownership_edges if edge.from_id not in children_ids} or {entity.entity_id}
        nodes: list[VisualNode] = []
        node_ids: set[str] = set()
        for root in roots:
            if root in node_ids:
                continue
            node_ids.add(root)
            nodes.append(VisualNode(
                id=root, label=entity_names.get(root, root), kind="focal",
                sublabel="研究主体" if root == entity.entity_id else "控股主体",
            ))
        for edge in ownership_edges:
            child = edge.to_id
            parent = edge.from_id
            if child in node_ids:
                continue
            node_ids.add(child)
            nodes.append(VisualNode(
                id=child, label=entity_names.get(child, child), kind="backend",
                sublabel={"SUBSIDIARY": "子公司", "Subsidiary": "子公司", "CONTROLLED_BY": "受控企业",
                          "OWNED_BY": "持股企业", "JOINT_VENTURE": "合营企业", "Owns": "持股企业", "ParentCompany": "集团"} .get(edge.relation, "关联企业"),
                parent=parent,
            ))
        content = [
            f"已核验股权关系 {len(ownership_edges)} 条，涉及主体 {len(nodes)} 个。",
            "图中仅展示经核验的股权/控制关系；未核验或来源冲突的关系不呈现。",
        ]
        module = StoryModule(
            module_id="mod-structure", chapter_id="group_structure", kind="group_structure",
            title="企业治理与组织边界",
            assertion_title=f"经核验的股权关系涉及 {len(nodes)} 个主体，首轮沟通应沿已确认控制链定位责任主体",
            decision_question="集团边界与成员关系是什么，与谁谈？",
            executive_takeaway=f"经核验的股权关系涉及 {len(nodes)} 个主体。",
            analysis_paragraphs=content,
            source_ids=[claim.source_id for edge in verified_edges for claim in bundle.claims if claim.claim_id in edge.claim_ids],
            claim_ids=[claim_id for edge in verified_edges for claim_id in edge.claim_ids],
        )
        proposal = VisualProposal(
            visual_id="v-structure-tree", chapter_id="group_structure",
            decision_question="集团边界与成员关系是什么？",
            business_thesis=f"经核验的股权关系共 {len(ownership_edges)} 条。",
            semantic_pattern="verified_relationship", title="股权关系结构",
            data_binding="verified_edges",
            source_ids=module.source_ids, source_claim_ids=module.claim_ids,
            nodes=nodes,
            source_note=self._source_note(bundle, module.source_ids),
            semantic_domain="strategy",
        )
        spec = self._route(proposal, narrative)
        if spec is not None:
            module.visual_ids.append(spec.visual_id)
        return module

    # ── helpers ──
    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        canonical_id = bundle.run_manifest.canonical_entity_id
        return next(
            (item for item in bundle.entities if item.entity_id == canonical_id),
            bundle.entities[0] if bundle.entities else None,
        )

    def _profile_paragraph(self, bundle: FrozenResearchBundle) -> str:
        """Objective company-profile paragraph from verified identity facts."""
        entity = self._canonical_entity(bundle)
        if entity is None:
            return ""
        facts: list[str] = []
        verified = {claim.field_name: claim for claim in self._verified_claims(bundle)}
        for field_name, label in (
            ("headquarters", "总部"), ("registration_region", "注册地"),
            ("founded_date", "成立时间"), ("stock_code", "股票代码"),
        ):
            claim = verified.get(field_name)
            if claim is not None and str(claim.value).strip():
                facts.append(f"{label}{str(claim.value).strip()}")
        employee = verified.get("employee_count")
        if employee is not None and str(employee.value).strip():
            facts.append(f"员工人数 {str(employee.value).strip()}{employee.unit or ''}")
        prefix = f"{entity.canonical_name}：{'；'.join(facts)}"
        return prefix + "。上述信息用于识别研究主体与合作责任边界，构成经营分析的组织背景；"
        "相关登记与工商信息以公开页面为准，如后续发现登记信息变化，以最新官方公示为准。"

    @staticmethod
    def _verified_claims(bundle: FrozenResearchBundle) -> list[Claim]:
        return [claim for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED]

    def _default_synthesis(self, bundle: FrozenResearchBundle, entity) -> ResearchSynthesis:
        from enterprise_energy_research.research.synthesis import ResearchSynthesizer
        return ResearchSynthesizer().synthesize(
            run_id=bundle.run_manifest.run_id,
            entity=entity,
            entities=bundle.entities,
            claims=bundle.claims,
            sources=bundle.sources,
            edges=bundle.edges,
            factories=bundle.factories,
            products=bundle.products,
            energy_profiles=bundle.energy_profiles,
            gaps=bundle.gaps,
            solutions=bundle.solutions,
        )

    def _images_for(
        self,
        bundle: FrozenResearchBundle,
        *,
        chapter: str,
        entity_id: str | None,
        product_ids: set[str] | None = None,
        factory_ids: set[str] | None = None,
        exclude: set[str] | None = None,
    ) -> list[str]:
        budget = IMAGE_BUDGETS.get(chapter, IMAGE_BUDGETS["default"])
        candidates = [image for image in publishable_images(bundle) if image.image_id not in (exclude or set())]
        if chapter == "products":
            candidates = [image for image in candidates if image.product_id and image.product_id in (product_ids or set())]
        elif chapter == "factories":
            candidates = [image for image in candidates if image.factory_id and image.factory_id in (factory_ids or set())]
        elif chapter in {"executive_summary", "entity_profile"}:
            candidates = [
                image for image in candidates
                if image.target_entity_type in {"logo", "headquarters", "office", "editorial"}
                or (image.entity_id == entity_id and not image.product_id and not image.factory_id)
            ]
        scored: list[tuple[int, ImageEvidence]] = []
        for image in candidates:
            score = image.publication_priority
            if product_ids and image.product_id in product_ids:
                score += 4
            if factory_ids and image.factory_id in factory_ids:
                score += 4
            if entity_id and image.target_entity_id == entity_id:
                score += 2
            scored.append((score, image))
        scored.sort(key=lambda pair: (-pair[0], pair[1].image_id))
        return [image.image_id for _, image in scored[:budget]]

    def _route(self, proposal: VisualProposal, narrative: ResearchNarrative) -> VisualSpec | None:
        spec, check = self.router.route(proposal)
        if spec is not None:
            narrative.visuals.append(spec)
            narrative.visual_events.append(VisualEvent(
                visual_id=spec.visual_id, chapter_id=spec.chapter_id,
                pattern=spec.semantic_pattern,
                outcome="fallback_table" if check.fallback else "routed",
                visual_type=spec.visual_type,
                reason="；".join(check.reasons) if check.fallback else None,
            ))
            return spec
        narrative.visual_events.append(VisualEvent(
            visual_id=proposal.visual_id, chapter_id=proposal.chapter_id,
            pattern=proposal.semantic_pattern, outcome="dropped_to_prose",
            reason="；".join(check.reasons),
        ))
        return None

    @staticmethod
    def _source_note(bundle: FrozenResearchBundle, source_ids: list[str]) -> str:
        names = {
            source.source_id: source.source_title or source.source_domain
            for source in bundle.sources
        }
        cited = [names[source_id] for source_id in source_ids if source_id in names]
        return "数据来源：" + "、".join(cited[:5]) if cited else ""

    def _counts(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative) -> dict[str, int]:
        verified_products = [product for product in bundle.products if product.verification_status == VerificationStatus.VERIFIED]
        chapter_counts = {
            chapter.chapter_id: len(re.findall(
                r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]",
                "".join([
                    chapter.assertion_title, chapter.executive_takeaway,
                    *chapter.context_paragraphs, *chapter.analysis_paragraphs,
                    *chapter.implications, *chapter.recommendations,
                    *chapter.counter_evidence, *chapter.limitations, *chapter.action_items,
                ]),
            ))
            for chapter in narrative.chapters
        }
        meaningful = 0
        for visual in narrative.visuals:
            numeric = [item for item in visual.items if isinstance(item.value, (int, float))]
            if len(numeric) >= 2 or len(visual.stages) >= 2 or len(visual.nodes) >= 2:
                meaningful += 1
        product_image_count = sum(
            len(chapter.image_ids) for chapter in narrative.chapters if chapter.chapter_id == "products"
        )
        return {
            "chapters": len(narrative.chapters),
            "visuals": len(narrative.visuals),
            "meaningful_visual_count": meaningful,
            "verified_claims": len(self._verified_claims(bundle)),
            "sources": len(bundle.sources),
            "factories": len(bundle.factories),
            "verified_products": len(verified_products),
            "images_publishable": len(publishable_images(bundle)),
            "product_image_count": product_image_count,
            "kpis": len(narrative.kpis),
            "main_body_cjk_char_count": sum(chapter_counts.values()),
            "executive_summary_cjk_char_count": chapter_counts.get("executive_summary", 0),
            **{f"chapter_cjk_{key}": value for key, value in chapter_counts.items()},
        }


def write_narrative(narrative: ResearchNarrative, path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(narrative.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
