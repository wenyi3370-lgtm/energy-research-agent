"""ResearchNarrative + StoryModule (P0 refactor): the single middle layer.

HTML and Word renderers consume the SAME ResearchNarrative: report structure
is driven by research conclusions and decision questions, never by a fixed
database-chapter list.  A chapter only appears when its evidence gate passes
(dynamic chapters).  Visuals are routed here via the Visual Router and carry
the same business thesis in both outputs.

Nothing in this module may fabricate enterprise facts: every sentence in a
StoryModule is derived from verified claims, entity records, or synthesis
output; every VisualSpec comes from the router's evidence-backed data.
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
from enterprise_energy_research.artifacts.publication_terminology import (
    PublicationNumberFormatter,
    field_label,
    source_type_label,
    translate_table_row,
)

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


class ResearchNarrative(BaseModel):
    schema_version: str = "3.0"
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
        decision = self.decision_engine.synthesize(bundle)
        opportunities = self.opportunity_engine.assess(bundle)
        verified = self._verified_claims(bundle)
        by_field: dict[str, list[Claim]] = {}
        for claim in verified:
            by_field.setdefault(claim.field_name, []).append(claim)

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

        # Decision findings — not raw database tables — own the publication.
        narrative.decision_questions = decision.decision_questions
        narrative.executive_summary = list(decision.executive_summary_paragraphs)
        add(self._decision_executive(bundle, decision, opportunities, images_for))

        structure = self._chapter_group_structure(bundle, narrative)
        if structure is not None:
            add(structure)

        finding_by_domain = {item.semantic_domain: item for item in decision.findings}
        strategy = finding_by_domain.get("strategy")
        financial = finding_by_domain.get("financial")
        if strategy or financial:
            add(self._enterprise_position_module(bundle, strategy, financial, narrative))
        if product := finding_by_domain.get("product"):
            add(self._product_decision_module(bundle, product, narrative, images_for))
        if manufacturing := finding_by_domain.get("manufacturing"):
            add(self._factory_decision_module(bundle, manufacturing, images_for))
        if energy := finding_by_domain.get("energy"):
            add(self._energy_decision_module(bundle, energy, by_field, narrative))
        if opportunities:
            add(self._opportunity_module(opportunities))
            add(self._action_module(opportunities))
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
        )

        narrative.counts = self._counts(bundle, narrative)
        return narrative

    # ── decision-grade publication modules ──
    def _decision_executive(self, bundle, decision: DecisionSynthesis, opportunities: list[OpportunityAssessment], images_for) -> StoryModule:
        entity = self._canonical_entity(bundle)
        direction = opportunities[0].opportunity_name if opportunities else "关键事实补齐"
        module = StoryModule(
            module_id="mod-exec", chapter_id="executive_summary", kind="executive_summary",
            title="执行摘要与决策建议",
            assertion_title=f"{decision.overall_judgement}：当前应优先推进{direction}的验证，而不是跳过前置条件直接报价",
            decision_question=decision.decision_questions[0],
            executive_takeaway=decision.judgement_rationale,
            context_paragraphs=decision.executive_summary_paragraphs[:1],
            analysis_paragraphs=decision.executive_summary_paragraphs[1:3],
            limitations=decision.executive_summary_paragraphs[3:4],
            action_items=decision.executive_summary_paragraphs[4:],
            source_ids=list(dict.fromkeys(source_id for finding in decision.findings for source_id in finding.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(claim_id for finding in decision.findings for claim_id in finding.supporting_claim_ids)),
        )
        module.image_ids = images_for(chapter="executive_summary", entity_id=entity.entity_id)
        return module

    def _finding_module(self, bundle, finding: DecisionFinding, chapter_id: str, title: str, narrative: ResearchNarrative) -> StoryModule:
        module = StoryModule(
            module_id=f"mod-{chapter_id}", chapter_id=chapter_id, kind="operations",
            title=title, assertion_title=finding.conclusion,
            decision_question=finding.decision_question,
            executive_takeaway=finding.business_implication,
            context_paragraphs=[finding.fact_summary],
            analysis_paragraphs=[finding.analysis, *self._domain_analysis(finding), *self._evidence_interpretations(bundle, finding)],
            implications=[finding.business_implication],
            recommendations=[finding.recommendation],
            counter_evidence=finding.counter_evidence,
            limitations=finding.limitations,
            source_ids=finding.supporting_source_ids,
            claim_ids=finding.supporting_claim_ids,
        )
        if chapter_id == "operations" and finding.supporting_claim_ids:
            module.visual_ids.extend(self._analysis_visuals(bundle, self._canonical_entity(bundle).entity_id, narrative, chapter_id))
        return module

    def _enterprise_position_module(
        self, bundle: FrozenResearchBundle, strategy: DecisionFinding | None,
        financial: DecisionFinding | None, narrative: ResearchNarrative,
    ) -> StoryModule:
        primary = financial or strategy
        assert primary is not None
        findings = [item for item in (strategy, financial) if item is not None]
        assertion = financial.conclusion if financial else strategy.conclusion  # type: ignore[union-attr]
        module = StoryModule(
            module_id="mod-operations", chapter_id="operations", kind="operations",
            title="企业经营与战略位置", assertion_title=assertion,
            decision_question="企业业务定位与经营资源是否支持进入合作验证？",
            executive_takeaway="；".join(dict.fromkeys(item.business_implication for item in findings)),
            context_paragraphs=[item.fact_summary for item in findings],
            analysis_paragraphs=[paragraph for item in findings for paragraph in [
                item.analysis, *self._domain_analysis(item), *self._evidence_interpretations(bundle, item),
            ]],
            implications=list(dict.fromkeys(item.business_implication for item in findings)),
            recommendations=list(dict.fromkeys(item.recommendation for item in findings)),
            counter_evidence=[value for item in findings for value in item.counter_evidence],
            limitations=[value for item in findings for value in item.limitations],
            source_ids=list(dict.fromkeys(value for item in findings for value in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(value for item in findings for value in item.supporting_claim_ids)),
        )
        if financial is not None:
            module.visual_ids.extend(self._analysis_visuals(bundle, self._canonical_entity(bundle).entity_id, narrative, "operations"))
        return module

    def _product_decision_module(self, bundle, finding: DecisionFinding, narrative: ResearchNarrative, images_for) -> StoryModule:
        products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        rows = [translate_table_row({
            "name": product.name, "brand": product.brand or "", "model": product.model or "",
            "category": product.category or "未分类", "series": product.series or "",
            "parameters": "；".join(
                f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                for parameter in product.parameters
            ),
        }) for product in products]
        module = StoryModule(
            module_id="mod-products", chapter_id="products", kind="products",
            title="核心产品与技术能力", assertion_title=finding.conclusion,
            decision_question=finding.decision_question, executive_takeaway=finding.business_implication,
            context_paragraphs=[finding.fact_summary], analysis_paragraphs=[finding.analysis, *self._domain_analysis(finding), *self._evidence_interpretations(bundle, finding)],
            implications=[finding.business_implication], recommendations=[finding.recommendation],
            limitations=finding.limitations, source_ids=finding.supporting_source_ids,
            claim_ids=finding.supporting_claim_ids, table_rows=rows,
        )
        categories: dict[str, int] = {}
        for product in products:
            key = product.category or "未分类"
            categories[key] = categories.get(key, 0) + 1
        if len(categories) >= 2:
            proposal = VisualProposal(
                visual_id="v-products-categories", chapter_id="products",
                decision_question=finding.decision_question, business_thesis=finding.business_implication,
                semantic_pattern="category_comparison", title="产品族分布",
                data_binding="verified_products", source_ids=finding.supporting_source_ids,
                source_claim_ids=finding.supporting_claim_ids,
                items=[VisualDatum(label=key, value=value, unit="项") for key, value in categories.items()],
                source_note=self._source_note(bundle, finding.supporting_source_ids), semantic_domain="product",
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(
            chapter="products", entity_id=self._canonical_entity(bundle).entity_id,
            product_ids={product.product_id for product in products},
        )
        return module

    def _factory_decision_module(self, bundle, finding: DecisionFinding, images_for) -> StoryModule:
        rows = [translate_table_row({
            "name": factory.name or "未命名基地", "address": factory.address or "",
            "processes": "、".join(factory.processes), "status": factory.operating_status or "",
        }) for factory in bundle.factories]
        module = StoryModule(
            module_id="mod-factories", chapter_id="factories", kind="factories",
            title="生产布局与产能组织", assertion_title=finding.conclusion,
            decision_question=finding.decision_question, executive_takeaway=finding.business_implication,
            context_paragraphs=[finding.fact_summary], analysis_paragraphs=[finding.analysis, *self._domain_analysis(finding), *self._evidence_interpretations(bundle, finding)],
            implications=[finding.business_implication], recommendations=[finding.recommendation],
            limitations=finding.limitations, source_ids=finding.supporting_source_ids,
            claim_ids=finding.supporting_claim_ids, table_rows=rows,
        )
        module.image_ids = images_for(
            chapter="factories", entity_id=self._canonical_entity(bundle).entity_id,
            factory_ids={factory.factory_id for factory in bundle.factories},
        )
        return module

    def _energy_decision_module(self, bundle, finding: DecisionFinding, by_field: dict[str, list[Claim]], narrative: ResearchNarrative) -> StoryModule:
        module = StoryModule(
            module_id="mod-energy", chapter_id="energy_profile", kind="energy_profile",
            title="能源与零碳能力", assertion_title=finding.conclusion,
            decision_question=finding.decision_question, executive_takeaway=finding.business_implication,
            context_paragraphs=[finding.fact_summary], analysis_paragraphs=[finding.analysis, *self._domain_analysis(finding), *self._evidence_interpretations(bundle, finding)],
            implications=[finding.business_implication], recommendations=[finding.recommendation],
            limitations=finding.limitations, source_ids=finding.supporting_source_ids,
            claim_ids=finding.supporting_claim_ids,
        )
        items: list[VisualDatum] = []
        for field in sorted(ENERGY_FIELDS):
            rows = by_field.get(field, [])
            if not rows:
                continue
            best = max(rows, key=lambda item: item.confidence)
            items.append(VisualDatum(
                label=field_label(field), value=best.value, unit=best.unit,
                period=str(best.as_of_date.year) if best.as_of_date else None,
                note=best.scope or "",
            ))
        if items:
            proposal = VisualProposal(
                visual_id="v-energy-kpis", chapter_id="energy_profile",
                decision_question=finding.decision_question, business_thesis=finding.business_implication,
                semantic_pattern="quantitative_facts", title="基地级能源事实",
                data_binding="verified_energy_claims", source_ids=finding.supporting_source_ids,
                source_claim_ids=finding.supporting_claim_ids, items=items,
                source_note=self._source_note(bundle, finding.supporting_source_ids), semantic_domain="energy",
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    @staticmethod
    def _opportunity_module(opportunities: list[OpportunityAssessment]) -> StoryModule:
        paragraphs: list[str] = []
        rows: list[dict[str, Any]] = []
        for rank, item in enumerate(opportunities, start=1):
            paragraphs.extend([
                f"优先方向 {rank} 为{item.opportunity_name}。{item.strategic_rationale}该判断并非因为方向名称本身热门，而是因为现有事实能够指向一组可验证能力。"
                f"其优先级为 {item.priority}，战略匹配、实施可行性、证据强度和商业潜力评分分别为 {item.strategic_fit}、{item.implementation_feasibility}、{item.evidence_strength} 和 {item.commercial_potential}；评分用于安排验证顺序，不替代最终经济性。",
                f"建议把{item.target_scenario}作为首个切入场景。对方需要解决的是{item.target_need}；我方的价值不是直接承诺收益，而是{item.our_value_proposition}。"
                f"这一组合把对方已核验能力、具体业务问题和我方可交付工作连接起来，使首轮沟通能够围绕可验证场景展开，而不是停留在泛化战略合作。",
                f"首个责任接口应为{item.entry_point}，由{item.owner}负责推动。推进前必须取得{'、'.join(item.key_prerequisites)}，并把{'、'.join(item.key_risks)}纳入问题台账。"
                f"若资料不能对应到明确基地、计量边界或产品接口，应先收窄场景；若责任主体不能确认，应暂停商务承诺，避免在组织边界不清时进入技术报价。",
                f"行动上，前 30 天应完成：{item.first_30_day_action}；第 60 天应完成：{item.day_60_action}；第 90 天里程碑为：{item.day_90_milestone}。"
                f"成功标准是{item.success_kpi}。最终门槛为：{item.go_no_go_gate}该门槛把继续、补数与停止三种状态写清，防止项目仅凭会议热度滚动投入。",
            ])
            rows.append(translate_table_row({
                "opportunity": item.opportunity_name, "priority": item.priority,
                "target_scenario": item.target_scenario, "entry_point": item.entry_point,
                "go_no_go_gate": item.go_no_go_gate,
            }))
        top = opportunities[0]
        return StoryModule(
            module_id="mod-opportunities", chapter_id="opportunities", kind="opportunities",
            title="合作机会评估与优先级",
            assertion_title=f"{top.opportunity_name}排名首位，但必须先通过数据和场景门槛再进入商业化",
            decision_question="哪些合作机会最值得推进，从哪里切入？",
            executive_takeaway=f"优先级由战略匹配、实施可行性、事实强度和商业潜力共同决定，当前首位为{top.opportunity_name}。",
            analysis_paragraphs=paragraphs, limitations=[
                "未达到事实与可行性门槛的方向不进入优先机会清单，可保留为后续观察项。"
            ],
            source_ids=list(dict.fromkeys(s for item in opportunities for s in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(c for item in opportunities for c in item.supporting_claim_ids)),
            table_rows=rows,
        )

    @staticmethod
    def _action_module(opportunities: list[OpportunityAssessment]) -> StoryModule:
        actions = []
        for item in opportunities[:3]:
            actions.extend([
                f"30 天｜{item.opportunity_name}：{item.first_30_day_action}",
                f"60 天｜{item.opportunity_name}：{item.day_60_action}",
                f"90 天｜{item.opportunity_name}：{item.day_90_milestone}",
            ])
        return StoryModule(
            module_id="mod-action", chapter_id="action_plan", kind="action_plan",
            title="优先切入方案与 90 天行动",
            assertion_title="90 天行动应以一处场景的 Go / No-Go 结论为终点，而不是以输出方案数量为终点",
            decision_question="未来 90 天应完成什么，谁负责，如何判断成功？",
            executive_takeaway="行动链按资料、现场、测算、评审四个门槛推进，任一门槛不满足即返回补数或暂停。",
            analysis_paragraphs=[
                "30 天阶段解决责任主体和数据边界，60 天阶段解决技术适配和价值测算，90 天阶段形成书面决策。"
                "这种节奏把商务热度转化为可审计的项目进展，避免在关键事实缺失时过早承诺容量、收益或工期。每个阶段均以可核查输入和书面产出为完成标志，而不是以会议次数作为进度。",
                "项目治理应采用单一问题台账：每项缺口记录资料名称、口径范围、责任部门、承诺日期、核验状态和受影响结论。技术、商务与财务团队使用同一版本，任何容量、收益或工期数字都必须回溯到已核验输入；发生口径变化时，应同步更新测算和 Go / No-Go 结论。",
                "30 天评审关注场景是否真实和资料是否可得；60 天评审关注技术接口、工程约束和价值来源是否成立；90 天评审关注基准情景、敏感性、责任边界和退出条件。若前一道门未通过，后一道工作不得以假设代替，确保资源投入随证据成熟度逐步增加。",
                "管理层应要求最终评审只有三种明确输出：进入方案设计、返回补数并设定期限、停止当前方向。模糊的“继续保持沟通”不构成决策结果。通过给每个机会配置责任人、成功指标和停止条件，可以把战略合作意向转化为可管理的项目组合。",
            ], action_items=actions,
            source_ids=list(dict.fromkeys(s for item in opportunities for s in item.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(c for item in opportunities for c in item.supporting_claim_ids)),
        )

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
            analysis_paragraphs=[
                *(decision.key_risks or ["当前未发现需要单列的外部风险，但仍应在预可研中复核数据口径、责任边界和项目时效。"]),
                "风险管理的重点不是罗列所有不确定性，而是识别哪些缺口会改变容量、收益、投资或责任判断。阻断性事项未关闭前，只能批准资料获取和技术验证；非阻断性事项可以并行补齐，但必须记录其对优先级、范围和实施节奏的影响。",
                "Go 条件应同时覆盖事实、技术、组织和商业四个维度：原始数据口径一致且可复核，关键接口与工程条件可行，责任主体和审批路径明确，价值测算在不利情景下仍满足双方门槛。任何一维不满足，都不能仅凭其他维度的优势越级推进。",
                "No-Go 并不等于永久否定合作，而是对当前场景和当前证据状态作资源纪律约束。若缺口能够在明确期限内关闭，可返回补数；若核心价值来源无法验证、责任主体长期缺位或技术边界不可控，应停止当前方向，把团队资源转向证据更强的机会。",
            ],
            recommendations=[
                "在决策评审会上逐项核对阻断性资料；未取得原始数据或责任部门书面确认的事项不得以假设替代。"
            ], table_rows=due_rows,
            source_ids=list(dict.fromkeys(source_id for finding in decision.findings for source_id in finding.supporting_source_ids)),
            claim_ids=list(dict.fromkeys(claim_id for finding in decision.findings for claim_id in finding.supporting_claim_ids)),
        )

    @staticmethod
    def _domain_analysis(finding: DecisionFinding) -> list[str]:
        common = (
            f"围绕“{finding.conclusion}”，本节判断由 {len(finding.supporting_claim_ids)} 条事实和 {len(finding.supporting_source_ids)} 个来源支撑，"
            "证据强度用于界定可推进阶段，不用于制造确定性。资料能够证明的范围必须与结论范围一致；来源只覆盖集团时，不下推到单一基地；来源只覆盖产品能力时，不外推为客户需求或项目收益。"
        )
        mapping = {
            "strategy": [
                common,
                "企业身份、核心业务和组织边界决定首轮合作应与谁谈、围绕什么议题谈。它们能够排除主体混淆和泛化合作叙事，却不能替代产品接口、基地条件或项目经济性的验证；因此战略位置分析的作用是缩小搜索和沟通范围，而不是提前给出项目收益结论。",
                "管理层应优先寻找同时掌握业务目标、原始数据和实施责任的接口人。若只有集团层战略口径而没有业务条线或基地责任主体，合作可停留在框架交流，但不宜投入详细设计；责任链路一旦确认，再将研究问题拆解到产品、制造和能源三个证据域。",
                "下一步应把已核验业务边界转化为一页责任地图，明确决策发起人、数据提供方、技术评审方、投资审批方和最终使用方。任何合作方向只有在这五类角色及其权限得到确认后，才具备进入 30 / 60 / 90 天行动计划的组织基础。",
            ],
            "financial": [
                common,
                "经营指标应被解释为合作对象的资源基础、业务韧性和投入能力，而不是项目收益的代理变量。只有连续三个以上可比年度且合并范围、币种和会计口径一致时，才可讨论增长、盈利趋势或复合增速；否则更稳妥的表述是当前经营规模，并在后续尽调中补齐可比较时间序列。",
                "对于合作决策，经营分析的 So What 是判断对方是否有能力组织跨部门验证、承担联合投入并把试点复制到更多场景。即便经营规模较大，若具体基地缺少数据、责任接口或投资边界，也不应跳过预可研；反之，经营规模有限也不自动否定范围清晰的小型试点。",
                "下一步应把经营数据与合作场景分开建账：经营口径用于合作对象筛选，基地级技术与财务输入用于项目决策。评审时同时展示公开披露口径、可比性限制和受影响结论，避免把企业层数字重复包装为项目层价值。",
            ],
            "product": [
                common,
                "产品目录、型号、参数和认证能够证明对方具备何种技术路线与交付能力，但它们只回答“能提供什么”，不能单独回答“客户为什么购买”或“能源项目为什么盈利”。产品分析必须进一步映射目标工况、系统接口、合规要求、运维责任和交付边界，才能成为合作机会的事实基础。",
                "优先级应放在与目标场景直接相关、参数可核验、责任主体清晰的产品族，而不是完整 SKU 数量。对参数缺失或仅有营销描述的产品，应保留记录但不进入技术适配结论；正文讨论产品族重心和接口问题，完整目录交由交互式附件承载。",
                "下一步技术交流应形成逐项接口矩阵，至少覆盖目标场景、关键参数、适用标准、认证状态、数据协议、安装运维、质保和责任分工，同时明确复核责任人与材料有效期。只有接口矩阵与一处真实场景完成匹配，产品能力才可上升为可评审的联合方案。",
            ],
            "manufacturing": [
                common,
                "制造布局用于判断组织复杂度、基地进入顺序和复制潜力。基地数量、产线和生产能力反映制造输出与资源组织，并不等于企业自身年度用电量、峰值负荷或可调节负荷；任何 GWh 产能数字都必须留在制造语义域，不能进入用能画像或项目收益测算。",
                "正文应关注哪些基地与目标业务直接相关、哪些基地资料更完整、哪些基地责任链路更清晰，以及国内外布局对审批、标准和交付的影响。完整基地名录本身不会提高决策质量，因此只将影响切入判断的结构性信息放入分析，长名单留在附录或数据附件。",
                "首批验证基地宜满足三项条件：场景与优先机会直接相关，原始数据能够在明确期限内取得，工厂运营或能源责任人愿意参与联合评审。若只因产能大而选择基地，却无法确认计量边界和决策主体，试点很容易停留在概念方案。",
            ],
            "energy": [
                common,
                "能源画像只能使用年度或分月电量、峰值负荷、电价账单、负荷曲线、配电容量、屋面条件以及现有光伏和储能等能源语义事实。制造产能、产品容量、零碳业务收入或能源产品数量可以证明能力，却不能推导企业自身的消费规模，两者必须在分析、图表和结论中持续隔离。",
                "即使取得单个能源数字，也要确认对应基地、统计期间、计量边界、单位和是否含自备电源。缺少这些限定条件时，数字最多用于提出核验假设，不能直接计算削峰、需量管理、光伏自消纳或储能套利收益。真正可用于预可研的输入应能重构典型日和全年运行边界。",
                "因此本节的管理含义是把能源能力判断和基地项目判断分成两道门：第一道门确认双方具备技术与组织合作基础；第二道门以原始负荷、电价、配电和场地资料验证具体价值。只有第二道门通过，才讨论容量、投资、收益和工程进度。",
            ],
        }
        return mapping.get(finding.semantic_domain, [common])

    @staticmethod
    def _evidence_interpretations(bundle: FrozenResearchBundle, finding: DecisionFinding) -> list[str]:
        """Contextualize selected facts; never copy a raw field/value ledger."""
        wanted = set(finding.supporting_claim_ids)
        groups: dict[str, list[Claim]] = {}
        for claim in bundle.claims:
            if claim.claim_id in wanted:
                groups.setdefault(claim.field_name, []).append(claim)
        formatter = PublicationNumberFormatter()
        paragraphs: list[str] = []
        meanings = {
            "financial": "该信息用于判断经营资源基础及跨期可比性；它不能替代具体项目的现金流、投资边界和敏感性分析。",
            "product": "该信息用于确认技术路线与接口讨论的起点；是否适配目标场景仍需原厂参数、认证与实际工况共同验证。",
            "manufacturing": "该信息用于识别制造组织、基地进入顺序和复制条件；它描述的是生产活动，不代表企业自身能源消费。",
            "energy": "该信息只有在基地、期间、计量边界和单位均明确时才能进入用能判断；缺少任一限定条件时只作为待复核输入。",
        }
        for field, claims in list(groups.items())[:8]:
            observations: list[str] = []
            for claim in sorted(claims, key=lambda item: str(item.as_of_date or item.period_end or ""))[-3:]:
                formatted = formatter.format(claim.value, claim.unit)
                period = str((claim.period_end or claim.as_of_date or claim.period_start).year) if (claim.period_end or claim.as_of_date or claim.period_start) else "披露期"
                scope = claim.scope or "公开披露口径"
                observations.append(f"{period} 年{scope}为 {formatted.display_value}{formatted.display_unit}")
            paragraphs.append(
                f"就{field_label(field)}而言，现有证据可归纳为{'；'.join(observations)}。"
                f"{meanings.get(finding.semantic_domain, '该记录用于限定本节结论范围，任何超出来源范围的外推都应作为待确认事项。')}"
                "后续评审应保留原始值、来源、期间和范围，若新资料改变口径，应同步重算并更新受影响的管理结论。"
            )
        return paragraphs

    # ── helpers ──
    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        canonical_id = bundle.run_manifest.canonical_entity_id
        return next(
            (item for item in bundle.entities if item.entity_id == canonical_id),
            bundle.entities[0] if bundle.entities else None,
        )

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

    def _decision_questions(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, by_field: dict[str, list[Claim]]) -> list[str]:
        questions: list[str] = []
        if synthesis.cooperation_opportunities:
            questions.append("哪些合作机会最值得推进，从哪里切入？")
        if synthesis.risks:
            questions.append("合作面临的主要风险与不确定性是什么？")
        if any(field in by_field for field in ("revenue", "profit", "gross_margin", "market_share")):
            questions.append("经营趋势是否支持合作判断？")
        if bundle.gaps:
            questions.append("推进合作前需要补齐哪些关键数据？")
        if bundle.factories:
            questions.append("从哪个生产基地切入最可行？")
        return questions or ["该企业是否值得合作，应从哪里切入？", "如何用公开证据验证合作方案？"]

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
        # chapter relevance: product photos belong to products, site photos to
        # factories, entity-level photos (logo/headquarters/editorial) to the
        # executive/profile chapters
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

    def _analysis_visuals(self, bundle: FrozenResearchBundle, entity_id: str, narrative: ResearchNarrative, chapter_id: str) -> list[str]:
        results = self.analyst.analyze(entity_id, bundle.claims)
        created: list[str] = []
        for result in results:
            proposal = VisualProposal(
                visual_id=f"v-{chapter_id}-{result.metric}",
                chapter_id=chapter_id,
                decision_question=f"{result.metric_label}趋势说明了什么？",
                business_thesis=f"{result.metric_label}{result.value_display}（{len(result.period)} 个真实期间）。",
                semantic_pattern="time_series",
                title=f"{result.metric_label}趋势",
                subtitle=f"{result.value_display}；期间：{'、'.join(result.period)}。",
                data_binding=f"analysis:{result.result_id}",
                source_ids=list(result.source_ids),
                source_claim_ids=list(result.source_claim_ids),
                unit=result.unit,
                period="、".join(result.period),
                transformation=result.transformation,
                assumption_status=result.assumption_status,
                verified=result.verified,
                items=[VisualDatum(**row) for row in result.items()],
                source_note=self._source_note(bundle, result.source_ids),
                confidence="high", semantic_domain="financial",
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                created.append(spec.visual_id)
        return created

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
        return {
            "chapters": len(narrative.chapters),
            "visuals": len(narrative.visuals),
            "verified_claims": len(self._verified_claims(bundle)),
            "sources": len(bundle.sources),
            "factories": len(bundle.factories),
            "verified_products": len(verified_products),
            "images_publishable": len(publishable_images(bundle)),
            "main_body_cjk_char_count": sum(chapter_counts.values()),
            "executive_summary_cjk_char_count": chapter_counts.get("executive_summary", 0),
            **{f"chapter_cjk_{key}": value for key, value in chapter_counts.items()},
        }

    # ── chapters (dynamic: return None → chapter omitted) ──
    def _chapter_executive(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, by_field: dict[str, list[Claim]], narrative: ResearchNarrative, images_for) -> StoryModule:
        entity = self._canonical_entity(bundle)
        content = list(synthesis.executive_summary)
        if not content:
            content = [
                f"本报告研究对象为{entity.canonical_name}，围绕合作可行性展开分析。",
                f"已核验公开披露数据 {len(self._verified_claims(bundle))} 项，来源 {len(bundle.sources)} 个。",
            ]
        module = StoryModule(
            module_id="mod-exec", chapter_id="executive_summary", kind="executive_summary",
            title="决策结论", decision_question=narrative.decision_questions[0],
            thesis="从哪里切入合作，依据是什么",
            content=content,
            source_ids=[source.source_id for source in bundle.sources],
            claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
        )
        kpi_items: list[VisualDatum] = []
        for field, label in (("revenue", "营业收入"), ("profit", "净利润"), ("employee_count", "员工人数")):
            rows = by_field.get(field)
            if not rows:
                continue
            best = max(rows, key=lambda item: item.confidence)
            kpi_items.append(VisualDatum(
                label=label, value=best.value, unit=best.unit,
                period=best.as_of_date.strftime("%Y-%m") if best.as_of_date else None,
                note=best.raw_text,
            ))
        if len(kpi_items) >= 1:
            proposal = VisualProposal(
                visual_id="v-exec-kpis", chapter_id="executive_summary",
                decision_question=narrative.decision_questions[0],
                business_thesis="关键经营指标一栏总览。",
                semantic_pattern="quantitative_facts", title="关键经营指标",
                data_binding="verified_claims",
                source_ids=[claim.source_id for claim in self._verified_claims(bundle)],
                source_claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
                items=kpi_items,
                source_note=self._source_note(bundle, [claim.source_id for claim in self._verified_claims(bundle)]),
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(chapter="executive_summary", entity_id=entity.entity_id)
        return module

    def _chapter_entity_profile(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, by_field: dict[str, list[Claim]], narrative: ResearchNarrative, images_for) -> StoryModule:
        entity = self._canonical_entity(bundle)
        profile = synthesis.company_profile
        content: list[str] = []
        rows: dict[str, Any] = {}
        if entity.registered_name and entity.registered_name != entity.canonical_name:
            rows["注册名称"] = entity.registered_name
        if entity.registration_region:
            rows["注册地"] = entity.registration_region
        if profile and profile.founded_date:
            rows["成立时间"] = profile.founded_date
        if profile and profile.headquarters:
            rows["总部"] = profile.headquarters
        if profile and profile.official_website:
            rows["官方网站"] = str(profile.official_website)
        if profile and profile.actual_controller:
            rows["实际控制人"] = profile.actual_controller
        if profile and profile.parent_company:
            rows["母公司"] = profile.parent_company
        if profile and profile.core_business:
            rows["主营业务"] = profile.core_business
        if profile and profile.business_segments:
            rows["产业板块"] = "、".join(profile.business_segments)
        if profile and profile.employee_count:
            rows["员工人数"] = profile.employee_count
        if synthesis.business_summary:
            content.append(synthesis.business_summary + "。")
        if synthesis.subsidiary_summary:
            content.append(synthesis.subsidiary_summary + "。")
        module = StoryModule(
            module_id="mod-profile", chapter_id="entity_profile", kind="entity_profile",
            title="企业概况",
            decision_question="这是一家什么样的企业，业务底盘是什么？",
            thesis=profile.core_business if profile and profile.core_business else entity.canonical_name,
            content=content,
            source_ids=[claim.source_id for claim in self._verified_claims(bundle)],
            claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
            table_rows=[{"field": key, "value": value} for key, value in rows.items()],
        )
        module.image_ids = images_for(chapter="entity_profile", entity_id=entity.entity_id)
        return module

    def _chapter_group_structure(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative) -> StoryModule | None:
        entity = self._canonical_entity(bundle)
        verified_edges = [
            edge for edge in bundle.edges
            if edge.verification_status == VerificationStatus.VERIFIED
            and edge.relation in STRUCTURED_RELATIONS
        ]
        # Only ownership-family relations build the org tree.
        ownership_edges = [
            edge for edge in verified_edges
            if edge.relation in {"SUBSIDIARY", "CONTROLLED_BY", "OWNED_BY", "JOINT_VENTURE", "Subsidiary", "ParentCompany", "Owns"}
        ]
        if not ownership_edges:
            return None
        entity_names = {item.entity_id: item.canonical_name for item in bundle.entities}
        children_ids = {edge.to_id for edge in ownership_edges}
        roots = {edge.from_id for edge in ownership_edges if edge.from_id not in children_ids} or {entity.entity_id}
        if not roots:
            roots = {entity.entity_id}
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

    def _chapter_partnerships(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative) -> StoryModule | None:
        entity = self._canonical_entity(bundle)
        verified_edges = [
            edge for edge in bundle.edges
            if edge.verification_status == VerificationStatus.VERIFIED
            and edge.relation in {"PARTNER", "SUPPLIER", "CUSTOMER", "LICENSEE"}
        ]
        if not verified_edges:
            return None
        entity_names = {item.entity_id: item.canonical_name for item in bundle.entities}
        names = {name for edge in verified_edges for name in (edge.from_id, edge.to_id)}
        content = []
        for edge in verified_edges:
            left = entity_names.get(edge.from_id, edge.from_id)
            right = entity_names.get(edge.to_id, edge.to_id)
            relation_label = {"PARTNER": "合作伙伴", "SUPPLIER": "供应商", "CUSTOMER": "客户", "LICENSEE": "被许可方"}.get(edge.relation, edge.relation)
            content.append(f"{left} 与 {right} 为{relation_label}关系。")
        module = StoryModule(
            module_id="mod-partners", chapter_id="partnerships", kind="partnerships",
            title="商业合作关系",
            decision_question="已核验的商业合作关系有哪些？",
            thesis=f"已核验商业合作关系 {len(verified_edges)} 条。",
            content=content,
            source_ids=[claim.source_id for edge in verified_edges for claim in bundle.claims if claim.claim_id in edge.claim_ids],
            claim_ids=[claim_id for edge in verified_edges for claim_id in edge.claim_ids],
            table_rows=[
                {"relation": {"PARTNER": "合作伙伴", "SUPPLIER": "供应商", "CUSTOMER": "客户", "LICENSEE": "被许可方"}.get(edge.relation, edge.relation),
                 "from": entity_names.get(edge.from_id, edge.from_id),
                 "to": entity_names.get(edge.to_id, edge.to_id)}
                for edge in verified_edges
            ],
        )
        return module

    def _chapter_operations(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, by_field: dict[str, list[Claim]], narrative: ResearchNarrative) -> StoryModule | None:
        entity = self._canonical_entity(bundle)
        content: list[str] = []
        if synthesis.business_summary:
            content.append(synthesis.business_summary + "。")
        if synthesis.financial_summary:
            content.append("经营情况（公开披露口径）" + synthesis.financial_summary + "。")
        if not content and not any(field in by_field for field in ("revenue", "profit", "gross_margin", "market_share", "capacity")):
            return None
        module = StoryModule(
            module_id="mod-operations", chapter_id="operations", kind="operations",
            title="经营与产业分析",
            decision_question="经营趋势是否支持合作判断？",
            thesis="经营指标变化趋势与产业能力评估。",
            content=content,
            source_ids=[claim.source_id for claim in self._verified_claims(bundle)],
            claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
        )
        results = self._analysis_visuals(bundle, entity.entity_id, narrative, "operations")
        module.visual_ids.extend(results)
        return module

    def _chapter_factories(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative, images_for) -> StoryModule | None:
        if not bundle.factories:
            return None
        entity = self._canonical_entity(bundle)
        content: list[str] = [f"已核验生产基地 {len(bundle.factories)} 处。"]
        rows: list[dict[str, Any]] = []
        for factory in bundle.factories:
            rows.append({
                "name": factory.name or "未命名基地",
                "address": factory.address or "",
                "processes": "、".join(factory.processes),
                "status": factory.operating_status or "",
            })
            if factory.name:
                location = f"，地址：{factory.address}" if factory.address else ""
                process = f"，工艺：{'、'.join(factory.processes)}" if factory.processes else ""
                content.append(f"{factory.name}{location}{process}。")
        module = StoryModule(
            module_id="mod-factories", chapter_id="factories", kind="factories",
            title="生产基地布局",
            decision_question="从哪个生产基地切入最可行？",
            thesis=f"已核验生产基地 {len(bundle.factories)} 处。",
            content=content,
            source_ids=[claim.source_id for claim in bundle.claims],
            claim_ids=[claim.claim_id for claim in bundle.claims if claim.field_name in {"capacity", "factory_name", "process"}],
            table_rows=rows,
        )
        module.image_ids = images_for(
            chapter="factories", entity_id=entity.entity_id,
            factory_ids={factory.factory_id for factory in bundle.factories},
        )
        return module

    def _chapter_products(self, bundle: FrozenResearchBundle, narrative: ResearchNarrative, images_for) -> StoryModule | None:
        verified_products = [product for product in bundle.products if product.verification_status == VerificationStatus.VERIFIED]
        if not verified_products:
            return None
        entity = self._canonical_entity(bundle)
        categories: dict[str, list[Product]] = {}
        for product in verified_products:
            categories.setdefault(product.category or "未分类", []).append(product)
        content: list[str] = []
        if len(categories) > 1:
            content.append(
                "产品族分布：" + "、".join(f"{category} {len(items)} 项" for category, items in categories.items()) + "。"
            )
        content.append(f"已核验产品合计 {len(verified_products)} 项，覆盖产品族 {len(categories)} 个。")
        rows: list[dict[str, Any]] = []
        for product in verified_products:
            rows.append({
                "name": product.name,
                "brand": product.brand or "",
                "model": product.model or "",
                "category": product.category or "未分类",
                "series": product.series or "",
                "description": product.description or "",
                "parameters": "；".join(
                    f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                    for parameter in product.parameters
                ),
            })
        module = StoryModule(
            module_id="mod-products", chapter_id="products", kind="products",
            title="产品矩阵",
            decision_question="核心产品与可合作的产品方向是什么？",
            thesis=f"已核验产品 {len(verified_products)} 项、产品族 {len(categories)} 个。",
            content=content,
            source_ids=[source_id for product in verified_products for source_id in product.source_ids],
            claim_ids=[],
            table_rows=rows,
        )
        if len(categories) >= 2:
            proposal = VisualProposal(
                visual_id="v-products-categories", chapter_id="products",
                decision_question="产品组合的重心在哪几个产品族？",
                business_thesis=f"产品分布：{len(verified_products)} 项产品、{len(categories)} 个产品族。",
                semantic_pattern="category_comparison", title="产品族分布",
                data_binding="verified_products",
                source_ids=module.source_ids,
                items=[
                    VisualDatum(label=category, value=len(items), unit="项")
                    for category, items in categories.items()
                ],
                source_note=self._source_note(bundle, module.source_ids),
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(
            chapter="products", entity_id=entity.entity_id,
            product_ids={product.product_id for product in verified_products},
        )
        return module

    def _chapter_energy(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, by_field: dict[str, list[Claim]], narrative: ResearchNarrative) -> StoryModule | None:
        entity = self._canonical_entity(bundle)
        content: list[str] = []
        if synthesis.energy_summary:
            content.append(synthesis.energy_summary + "。")
        if synthesis.existing_energy_projects:
            content.append("已有能源项目：" + "；".join(synthesis.existing_energy_projects[:6]) + "。")
        has_energy = bundle.energy_profiles or content
        if not has_energy:
            return None
        module = StoryModule(
            module_id="mod-energy", chapter_id="energy_profile", kind="energy_profile",
            title="能源画像与用能特征",
            decision_question="用能结构与节能空间是什么？",
            thesis=synthesis.energy_summary or f"已形成 {len(bundle.energy_profiles)} 份能源画像。",
            content=content,
            source_ids=[claim.source_id for claim in self._verified_claims(bundle)],
            claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
        )
        energy_items: list[VisualDatum] = []
        for field, label in (("electricity_consumption", "年度用电量"), ("roof_area", "可用屋面面积"), ("capacity", "产能")):
            rows = by_field.get(field)
            if not rows:
                continue
            best = max(rows, key=lambda item: item.confidence)
            energy_items.append(VisualDatum(label=label, value=best.value, unit=best.unit, note=best.raw_text))
        if energy_items:
            proposal = VisualProposal(
                visual_id="v-energy-kpis", chapter_id="energy_profile",
                decision_question="用能规模与节能空间是多少？",
                business_thesis=synthesis.energy_summary or "能源关键指标。",
                semantic_pattern="quantitative_facts", title="能源关键指标",
                data_binding="verified_claims",
                source_ids=module.source_ids, source_claim_ids=module.claim_ids,
                items=energy_items,
                source_note=self._source_note(bundle, module.source_ids),
            )
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    def _chapter_opportunities(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, narrative: ResearchNarrative) -> StoryModule | None:
        solutions = [
            solution for solution in bundle.solutions
            if solution.priority in {"A", "B"}
        ]
        if not solutions:
            return None
        content: list[str] = []
        rows: list[dict[str, Any]] = []
        for solution in solutions:
            content.append(
                f"{solution.opportunity}：{solution.proposed_solution}"
                + (f"（下一步：{solution.next_step}）" if solution.next_step else "")
            )
            rows.append({
                "opportunity": solution.opportunity,
                "solution": solution.proposed_solution,
                "priority": solution.priority,
                "next_step": solution.next_step,
            })
        module = StoryModule(
            module_id="mod-opportunities", chapter_id="opportunities", kind="opportunities",
            title="合作机会与切入路径",
            decision_question="哪些合作机会最值得推进，从哪里切入？",
            thesis=f"已识别可推进机会 {len(solutions)} 项。",
            content=content,
            source_ids=[claim.source_id for solution in solutions for claim in bundle.claims if claim.claim_id in solution.claim_ids],
            claim_ids=[claim_id for solution in solutions for claim_id in solution.claim_ids],
            table_rows=rows,
        )
        return module

    def _chapter_risks(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis, narrative: ResearchNarrative) -> StoryModule | None:
        content: list[str] = list(synthesis.risks)
        unknowns = synthesis.key_unknowns[:8]
        if unknowns:
            content.append("待核实事项：" + "；".join(unknowns) + "。")
        if not content:
            return None
        return StoryModule(
            module_id="mod-risks", chapter_id="risks_evidence", kind="risks_evidence",
            title="风险与待核实事项",
            decision_question="主要风险与不确定性是什么？",
            thesis=f"已识别风险 {len(synthesis.risks)} 项、待核实事项 {len(unknowns)} 项。",
            content=content,
            source_ids=[claim.source_id for claim in self._verified_claims(bundle)],
            claim_ids=[claim.claim_id for claim in self._verified_claims(bundle)],
        )

    def _chapter_sources(self, bundle: FrozenResearchBundle) -> StoryModule:
        rows = [
            {
                "title": source.source_title or source.source_domain,
                "domain": source.source_domain,
                "level": source.source_level.value if hasattr(source.source_level, "value") else str(source.source_level),
                "date": source.publication_date.isoformat() if source.publication_date else "",
                "url": str(source.canonical_url),
            }
            for source in bundle.sources
        ]
        return StoryModule(
            module_id="mod-sources", chapter_id="sources", kind="sources",
            title="数据来源",
            decision_question="结论建立在哪些公开来源之上？",
            thesis=f"共引用公开来源 {len(bundle.sources)} 个。",
            content=[f"本报告结论基于 {len(bundle.sources)} 个公开来源。"],
            source_ids=[source.source_id for source in bundle.sources],
            table_rows=rows,
        )


def write_narrative(narrative: ResearchNarrative, path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(narrative.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
