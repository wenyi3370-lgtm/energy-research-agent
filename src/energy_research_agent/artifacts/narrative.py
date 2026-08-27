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
import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from energy_research_agent.analysis.financials import AnalysisResult, FinancialAnalyst
from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import (
    Claim,
    CrossDomainFinding,
    FrozenResearchBundle,
    ImageEvidence,
    Product,
)
from energy_research_agent.research.synthesis import ResearchSynthesis
from energy_research_agent.research.decision_synthesis import (
    DecisionFinding,
    DecisionSynthesis,
    DecisionSynthesisEngine,
    DueDiligenceRequirement,
    ENERGY_FIELDS,
)
from energy_research_agent.research.opportunity_assessment import (
    OpportunityAssessment,
    OpportunityAssessmentEngine,
)
from energy_research_agent.research.client_profile import ClientProfile, client_profile_from_manifest
from energy_research_agent.research.cooperation_hypothesis import (
    CooperationHypothesis, CooperationHypothesisEngine,
)
from energy_research_agent.research.strategic_interpretation import (
    StrategicInterpretation, StrategicInterpretationEngine,
)
from energy_research_agent.research.product_images import ProductImageResolver
from energy_research_agent.research.research_analysis import (
    ResearchAnalysis,
    ResearchAnalysisEngine,
)
from energy_research_agent.research.entity_scope import (
    canonical_entity,
    scoped_factories,
    scoped_products,
    target_claims,
)
from energy_research_agent.artifacts.publication_terminology import (
    PublicationNumberFormatter,
    field_label,
    source_type_label,
    translate_table_row,
)
from energy_research_agent.artifacts.visual_opportunity import VisualOpportunityPlanner

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
        "strategic_interpretation",
        "custom_research",
        "cross_domain",
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
    schema_version: str = "4.0"
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
    supplemental_requirements: list[dict[str, Any]] = Field(default_factory=list)
    appendices: NarrativeAppendices = Field(default_factory=NarrativeAppendices)
    client_profile: ClientProfile | None = None
    strategic_interpretation: StrategicInterpretation | None = None
    cooperation_hypotheses: list[CooperationHypothesis] = Field(default_factory=list)
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
    def build(
        self,
        bundle: FrozenResearchBundle,
        synthesis: ResearchSynthesis | None = None,
        cross_domain: list[CrossDomainFinding] | None = None,
    ) -> ResearchNarrative:
        if cross_domain is None:
            cross_domain = list(bundle.cross_domain_findings or [])
        full_bundle = bundle
        entity = canonical_entity(full_bundle)
        if entity is None:
            raise ValueError("Frozen bundle contains no enterprise entity")
        # Publication always operates on the resolved enterprise boundary.
        # Adjacent new-energy companies remain in the evidence store for
        # comparison, but cannot leak into the target's claims, products or
        # factories through renderer iteration.
        bundle = full_bundle.model_copy(update={
            "claims": target_claims(full_bundle),
            "products": scoped_products(full_bundle),
            "factories": scoped_factories(full_bundle),
        })
        synthesis = synthesis or self._default_synthesis(bundle, entity)
        analysis = ResearchAnalysisEngine().analyze(bundle)
        client = client_profile_from_manifest(bundle.run_manifest)
        strategic = StrategicInterpretationEngine().interpret(bundle, analysis)
        hypotheses = CooperationHypothesisEngine().build(bundle, strategic, client)
        decision = self.decision_engine.synthesize(
            bundle, analysis, synthesis, strategic=strategic,
            hypotheses=hypotheses, client=client,
        )
        all_opportunities = self.opportunity_engine.assess(bundle, strategic)
        opportunities = [item for item in all_opportunities if item.hypothesis_status != "REJECTED"]
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
            client_profile=client,
            strategic_interpretation=strategic,
            cooperation_hypotheses=hypotheses,
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

        add(self._strategic_module(strategic, bundle, analysis))

        finding_by_domain = {item.semantic_domain: item for item in decision.findings}
        add(self._operations_module(bundle, analysis, finding_by_domain, narrative, synthesis))
        if any(product.verification_status == VerificationStatus.VERIFIED for product in bundle.products):
            add(self._products_module(bundle, analysis, finding_by_domain.get("product"), narrative, images_for))
        if bundle.factories:
            add(self._factories_module(bundle, analysis, finding_by_domain.get("manufacturing"), narrative, images_for))
        add(self._energy_module(bundle, analysis, finding_by_domain.get("energy"), narrative))
        for supplemental in self._supplemental_modules(full_bundle, narrative):
            add(supplemental)
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

        # A fact can legitimately support more than one analytical module,
        # but repeating its paragraph verbatim makes the publication read as
        # stitched output.  Keep the first editorial occurrence and remove
        # later exact copies across every visible paragraph collection.
        self._deduplicate_chapter_paragraphs(narrative)
        if cross_domain:
            narrative.chapters.append(self._cross_domain_module(bundle, cross_domain))
        narrative.counts = self._counts(bundle, narrative)
        return narrative

    def _cross_domain_module(
        self,
        bundle: FrozenResearchBundle,
        findings: list[CrossDomainFinding],
    ) -> StoryModule:
        """§38 chapters 16-19: enterprise-market fit, risks, entry, actions.

        Every paragraph is derived from traceable findings carrying evidence
        refs; nothing here invents facts beyond the frozen evidence.
        """
        all_refs = sorted({
            ref for finding in findings
            for ref in (
                list(finding.enterprise_evidence_refs)
                + list(finding.market_evidence_refs)
                + list(finding.counter_evidence_refs)
            )
        })
        fit = [f for f in findings if f.finding_type in {"MARKET_FIT", "PRODUCT_FIT", "CHANNEL_FIT"}]
        risks = [f for f in findings if f.finding_type == "RISK"]
        entry = [f for f in findings if f.finding_type in {"ENTRY_STRATEGY", "TIMING", "OPPORTUNITY", "COOPERATION_POTENTIAL"}]
        analysis = [
            f"{f.statement}（{f.finding_type}，置信度 {f.confidence:.0%}"
            + (f"，条件：{'；'.join(f.conditions)}" if f.conditions else "")
            + "）"
            for f in fit + entry
        ]
        counter = [f.statement for f in findings if f.counter_evidence_refs] + [
            f"反证：{finding.statement}" for finding in risks
        ]
        assumptions = sorted({a for f in findings for a in f.assumptions})
        return StoryModule(
            module_id="mod-cross-domain",
            chapter_id="cross_domain",
            kind="cross_domain",
            title="企业—市场匹配与进入策略",
            assertion_title=(
                f"基于 {len(fit)} 项适配判断与 {len(entry)} 项进入建议形成结论"
                if fit or entry else "跨域综合结论保持审慎"
            ),
            decision_question="目标市场对目标企业而言，适配度、风险与进入路径如何？",
            executive_takeaway=(
                "; ".join(f.statement for f in fit[:2])
                if fit else "企业侧与市场侧证据均不足以形成适配结论，按 Auditable Limitation 处理。"
            ),
            analysis_paragraphs=analysis,
            implications=[f.statement for f in entry],
            recommendations=[f.statement for f in entry if f.finding_type == "ENTRY_STRATEGY"],
            counter_evidence=counter,
            limitations=assumptions or ["未获得反证之外的独立假设验证。"],
            source_ids=all_refs,
            claim_ids=all_refs,
        )

    def _supplemental_modules(
        self,
        bundle: FrozenResearchBundle,
        narrative: ResearchNarrative,
    ) -> list[StoryModule]:
        """Build one auditable chapter for every portal/deep requirement route."""
        scope = bundle.run_manifest.research_scope or {}
        requirement = str(scope.get("requirements") or "").strip()
        routes = scope.get("requirement_routes") or []
        if not requirement or not routes:
            return []
        attempts = int(scope.get("supplemental_attempts") or 0)
        requirement_key = str(scope.get("supplemental_requirement_key") or hashlib.sha256(
            " ".join(requirement.split()).encode("utf-8")
        ).hexdigest())
        attempt_history = [
            item for item in (scope.get("supplemental_attempt_history") or [])
            if item.get("requirement_key") == requirement_key
        ]
        source_by_id = {source.source_id: source for source in bundle.sources}
        entity_by_id = {entity.entity_id: entity for entity in bundle.entities}
        topic_labels = {
            "sales_channels": "销售渠道",
            "policy_regulation": "政策与监管",
            "competitive_position": "竞争分析",
            "customers": "客户与市场",
            "suppliers": "供应链",
            "factories": "生产基地",
            "locations": "地理布局",
            "financials": "财务经营",
            "products": "产品体系",
            "product_parameters": "产品参数",
            "custom_requirement": "原始专项问题",
        }
        modules: list[StoryModule] = []
        seen_topics: set[str] = set()
        for route in routes:
            topic = str(route.get("topic") or "custom_requirement")
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            direct = [
                claim for claim in bundle.claims
                if claim.verification_status == VerificationStatus.VERIFIED
                and isinstance(claim.locator, dict)
                and (claim.locator.get("_routing") or {}).get("topic") == topic
                and " ".join(str(
                    (claim.locator.get("_routing") or {}).get("requirement_text") or ""
                ).split()) == " ".join(requirement.split())
            ]
            source_ids = list(dict.fromkeys(
                claim.source_id for claim in direct if claim.source_id in source_by_id
            ))
            satisfied = bool(direct and source_ids)
            completed_topic_rounds = {
                int(item.get("round") or 0)
                for item in attempt_history
                if item.get("execution_status") == "completed"
                and topic in (item.get("queried_topics") or [])
                and topic in (item.get("active_topics") or [])
            }
            # Failed/blocked infrastructure calls do not prove a public-data
            # gap.  Exhaustion is per topic and requires ten actually executed
            # recovery rounds for this same exact requirement.
            exhausted = attempts >= 10 and len(completed_topic_rounds) >= 10
            status = "satisfied" if satisfied else "exhausted_gap" if exhausted else "pending_retry"
            title_label = topic_labels.get(topic, field_label(topic))
            chapter_id = f"supplement-{len(modules) + 1}-{re.sub(r'[^a-z0-9]+', '-', topic.casefold()).strip('-') or 'custom'}"
            rows: list[dict[str, Any]] = []
            fact_sentences: list[str] = []
            formatter = PublicationNumberFormatter()
            for claim in direct[:30]:
                subject = entity_by_id.get(claim.entity_id)
                formatted = formatter.format(claim.value, claim.unit)
                period = (
                    claim.period_end.isoformat() if claim.period_end else
                    claim.as_of_date.isoformat() if claim.as_of_date else ""
                )
                rows.append({
                    "主体": subject.canonical_name if subject else claim.entity_id,
                    "指标": field_label(claim.field_name),
                    "事实": f"{formatted.display_value}{formatted.display_unit}",
                    "期间": period,
                    "口径": claim.scope or "",
                    "来源": source_by_id[claim.source_id].source_title or source_by_id[claim.source_id].source_domain,
                })
                fact_sentences.append(
                    f"{subject.canonical_name if subject else '相关主体'}的{field_label(claim.field_name)}"
                    f"为{formatted.display_value}{formatted.display_unit}"
                    + (f"（{period}，口径：{claim.scope}）" if period and claim.scope else f"（{period}）" if period else "")
                )
            paragraphs: list[str] = []
            if fact_sentences:
                for start in range(0, min(len(fact_sentences), 12), 4):
                    facts = "；".join(fact_sentences[start:start + 4]) + "。"
                    paragraphs.append(
                        facts
                        + "上述事实均按实际所属主体保留，目标企业、集团成员、竞品、渠道伙伴与政策机构未相互合并；"
                        "比较或影响判断仅在指标、期间、地区和业务口径一致时成立。"
                    )
            limitation = []
            if not satisfied:
                limitation.append(
                    (
                        f"初始 R1/R2/R3 检索后又完成 10 轮专项原文补采，仍未取得可核验事实；本章仅记录公开证据缺口，不以其他主体或其他需求的数据替代。"
                        if exhausted else
                        f"专项证据尚未达到发布条件，已完成初始检索及 {attempts} 次补采；发布前必须继续内部补采。"
                    )
                )
            narrative.supplemental_requirements.append({
                "topic": topic,
                "title": title_label,
                "requirement": requirement,
                "goal_domain": route.get("goal_domain"),
                "subject_role": route.get("subject_role"),
                "evidence_lane": route.get("evidence_lane"),
                "evidence_use": route.get("evidence_use"),
                "verified_claim_count": len(direct),
                "source_count": len(source_ids),
                "attempts": attempts + 1,
                "completed_recovery_rounds": len(completed_topic_rounds),
                "status": status,
            })
            modules.append(StoryModule(
                module_id=f"mod-{chapter_id}",
                chapter_id=chapter_id,
                kind="custom_research",
                title=f"专项补充：{title_label}",
                assertion_title=(
                    f"专项要求已形成 {len(direct)} 条可追溯事实"
                    if satisfied else "专项公开证据不足，结论保持空缺"
                ),
                decision_question=requirement,
                executive_takeaway=(
                    f"专项检索覆盖 {len(source_ids)} 个来源，所有事实按主体和用途隔离。"
                    if satisfied else limitation[0]
                ),
                analysis_paragraphs=paragraphs,
                limitations=limitation,
                source_ids=source_ids,
                claim_ids=[claim.claim_id for claim in direct],
                table_rows=rows,
            ))
        return modules

    @staticmethod
    def _deduplicate_chapter_paragraphs(narrative: ResearchNarrative) -> None:
        seen: set[str] = set()
        fields = (
            "context_paragraphs", "analysis_paragraphs", "implications",
            "recommendations", "counter_evidence", "limitations", "action_items",
        )
        for chapter in narrative.chapters:
            for field in fields:
                unique: list[str] = []
                for paragraph in getattr(chapter, field):
                    key = paragraph.strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    unique.append(paragraph)
                setattr(chapter, field, unique)

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

    def _strategic_module(
        self,
        strategic: StrategicInterpretation,
        bundle: FrozenResearchBundle,
        analysis: ResearchAnalysis,
    ) -> StoryModule:
        trajectories = ([
            "跨期轨迹覆盖" + "；".join(
                f"{item.title}（{'—'.join(item.periods)}）" for item in strategic.trajectories
            ) + "。各指标只有在同口径变化方向一致时，才用于判断资源投向、能力建设或合作窗口的变化。"
        ] if strategic.trajectories else [])
        turning_points = [f"{item.period}｜{item.event}：{item.implication}" for item in strategic.turning_points]
        priorities = [f"{item.name}：{item.rationale}" for item in strategic.priorities]
        competition = [item.conclusion for item in strategic.competitive_positions]
        strength_labels = {"strong": "强", "medium": "中", "weak": "弱"}
        customer = [f"{item.customer_or_market}（资料支持程度：{strength_labels.get(item.strength, '待确认')}）：{item.conclusion}" for item in strategic.customer_market_proofs]
        body = [*trajectories[:4], *turning_points[:4], *priorities[:4], *competition[:2], *customer[:4]]
        if not body:
            entity = self._canonical_entity(bundle)
            product_families = sorted({item.category or "未分类" for item in bundle.products})
            factory_regions = list(analysis.region_distribution)[:5]
            current_footprint = []
            if product_families:
                current_footprint.append(f"产品覆盖{'、'.join(product_families)}")
            if factory_regions:
                current_footprint.append(f"生产记录分布于{'、'.join(factory_regions)}")
            body = [
                "目前没有覆盖多个期间的同口径证据，无法判断企业的资源投向、能力建设或合作窗口是否发生变化。",
                (
                    f"{entity.canonical_name if entity else '目标企业'}当前可确认的经营截面为"
                    + "；".join(current_footprint)
                    + "。这些信息能说明现有业务载体和制造落点，但不能单独证明企业正在扩张、收缩或转换技术路线。"
                    if current_footprint else
                    f"{entity.canonical_name if entity else '目标企业'}当前披露只能确认静态经营轮廓，尚不足以识别资源配置方向的变化。"
                ),
                "战略变化判断需要带明确时点的产品发布、资本开支、产线投产、客户定点或组织调整相互印证；在这些时序事实缺失时，合作策略应按现有业务轮廓设定小范围验证，不将单次披露解读为战略拐点。",
            ]
        claim_ids = list(dict.fromkeys(
            claim_id for collection in (
                strategic.trajectories, strategic.turning_points, strategic.priorities,
                strategic.competitive_positions, strategic.customer_market_proofs,
            ) for item in collection for claim_id in item.lineage.claim_ids
        ))
        source_ids = list(dict.fromkeys(
            source_id for collection in (
                strategic.trajectories, strategic.turning_points, strategic.priorities,
                strategic.competitive_positions, strategic.customer_market_proofs,
            ) for item in collection for source_id in item.lineage.source_ids
        ))
        return StoryModule(
            module_id="mod-strategy", chapter_id="strategic_interpretation", kind="strategic_interpretation",
            title="战略轨迹、市场证明与未来情景",
            assertion_title=(strategic.trajectories[0].direction if strategic.trajectories else "跨期战略轨迹尚未达到可验证门槛"),
            decision_question="企业如何变化，哪些驱动、市场证明和风险会改变未来选择？",
            executive_takeaway=strategic.saturation.rationale,
            analysis_paragraphs=body,
            counter_evidence=[item.risk for item in strategic.enterprise_risks[:4]],
            limitations=[] if strategic.competitive_positions else ["缺少同口径、同期间和同市场范围的可比证据，因此不生成具名竞争格局。"],
            claim_ids=claim_ids, source_ids=source_ids,
            table_rows=[{
                "情景": item.scenario, "成立条件": item.condition, "管理含义": item.implication,
            } for item in strategic.scenarios],
        )

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
            assertion = "公开经营数据的年度可比口径有限，目前只能确认企业已披露的业务结构"

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
        analysis_paragraphs.extend(self._operating_disclosure_paragraphs(bundle))
        if synthesis is not None and synthesis.business_summary:
            analysis_paragraphs.append(
                f"{synthesis.business_summary.strip('。')}。"
                "该业务边界决定企业内部的责任部门和可讨论的合作议题；具体业务占比仅在企业提供分业务收入或分部资产口径时计算。"
            )
        financial_paragraphs: list[str] = []
        for trend in analysis.trends:
            if trend.field_name in {"capacity", "production_capacity", "battery_production_capacity", "storage_capacity", "pv_capacity"}:
                continue  # capacity is presented in the factories chapter
            if trend.field_name in {"revenue", "profit", "rnd_expense"} or trend.year_count >= 2:
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
                "当前仅有单期经营披露，无法计算收入、利润或研发投入的同比变化和复合增长率，"
                "也无法判断盈利变化来自售价、销量还是成本，因此暂不形成跨期经营趋势结论。"
            )
        analysis_paragraphs.extend(dict.fromkeys(financial_paragraphs))
        # Scale & structure facts beyond the core income statement.
        sales = analysis.trend("battery_sales_volume")
        if sales is not None and sales.year_count >= 2:
            analysis_paragraphs.append(
                sales.statement + "销量增速反映下游需求与公司交付能力，是与产能、收入相互印证的结构性指标。"
            )
        assets = analysis.trend("total_assets")
        if assets is not None and assets.year_count >= 2:
            analysis_paragraphs.append(
                assets.statement + "资产规模反映投资沉淀与再投入能力，资产效率的变化需结合收入与回报率进一步分析。"
            )
        investment_rows = [claim for claim in self._verified_claims(bundle) if claim.field_name == "investment"]
        if investment_rows:
            best = max(investment_rows, key=lambda item: item.confidence)
            analysis_paragraphs.append(
                f"对外投资方面，公开披露显示公司{str(best.value).strip()}（{best.unit or '待核验口径'}）；"
                "投资布局指向产能扩张与产业链配套，可用于判断合作窗口是否与企业资本开支节奏同步。"
            )
        # Enterprise-level risk disclosures feed the risk chapter, but the
        # operations chapter states their business context once.
        business_risks = [str(claim.value).strip() for claim in self._verified_claims(bundle) if claim.field_name in {"business_risk", "compliance_risk"} and str(claim.value).strip()]
        if business_risks:
            analysis_paragraphs.append(
                "经营层面，公司公开披露提示" + "；".join(list(dict.fromkeys(business_risks))[:3]) + "等事项；"
                "这些事项只有在能够改变技术边界、交付能力或对方合作意愿时，才计入项目风险判断。"
            )
        # Profitability & market position: latest disclosed facts, per metric.
        gross_margin_rows = [claim for claim in self._verified_claims(bundle) if claim.field_name == "gross_margin"]
        if gross_margin_rows:
            best = max(gross_margin_rows, key=lambda item: item.confidence)
            period = f"{best.period_end.year} 年" if best.period_end else "最新披露"
            analysis_paragraphs.append(
                f"盈利能力方面，{period}毛利率为 {best.value}{best.unit or ''}；"
                "毛利率水平反映产品定价与成本结构，是盈利质量判断的基础指标。"
            )
        rnd_ratio_rows = [claim for claim in self._verified_claims(bundle) if claim.field_name == "rnd_expense_ratio"]
        if rnd_ratio_rows:
            best = max(rnd_ratio_rows, key=lambda item: item.confidence)
            period = f"{best.period_end.year} 年" if best.period_end else "最新披露"
            analysis_paragraphs.append(
                f"研发投入方面，{period}研发费用率为 {best.value}{best.unit or ''}；"
                "研发费用率结合研发投入绝对额，反映技术路线跟进与联合开发投入的持续性。"
            )
        has_position = any(claim.field_name in {"market_share", "industry_position"} for claim in self._verified_claims(bundle))
        if has_position:
            position_claims = [claim for claim in self._verified_claims(bundle) if claim.field_name in {"market_share", "industry_position"}]
            best = max(position_claims, key=lambda item: item.confidence)
            period = f"（{best.period_end.year}）" if best.period_end else ""
            analysis_paragraphs.append(
                f"市场地位方面，公开披露显示公司{str(best.value)}{period}；"
                "产业地位数据用于判断公司在产业链中的议价与合作层级，其统计期间、地理范围和产品范围必须与原始披露一致。"
            )
            share_claims = {
                claim.field_name: claim for claim in self._verified_claims(bundle)
                if claim.field_name in {"global_market_share_power_battery", "global_market_share_energy_storage_battery", "global_market_share"}
            }
            if share_claims:
                parts = "；".join(
                    f"{field_label(field)} {claim.value}{claim.unit or ''}"
                    for field, claim in sorted(share_claims.items())
                )
                analysis_paragraphs.append(
                    f"分市场看，{parts}。动力与储能双主业的份额结构决定双方合作既覆盖汽车客户链，也覆盖储能与电网侧场景。"
                )
        else:
            analysis_paragraphs.append(
                "尚未取得可独立核验的市场份额、装机量排名或行业地位数据，无法把企业规模转换为行业位置判断；"
                "在披露口径、统计期间和地理范围统一前，不输出市场地位或同业排名结论。"
            )
        consulting = "；".join(dict.fromkeys(item.business_implication for item in findings))
        if consulting:
            analysis_paragraphs.append(
                consulting + "经营数据用于合作对象筛选与资源基础判断，项目层面的经济性仍以基地级数据独立测算；"
                "经营规模与项目收益分账管理，避免把企业层数字重复包装为项目层价值。"
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
            context.append(families.statement + "产品族结构显示企业对外供给的重点方向，也决定技术适配时需要对照的型号、接口和应用边界。")
        else:
            context.append(f"已核验产品合计 {len(verified_products)} 项。")
        if finding is not None:
            context.append(finding.fact_summary + "产品记录以公开产品中心与规格资料为口径。")

        analysis_paragraphs: list[str] = []
        for index, product in enumerate(key_products[:8]):
            params = "；".join(
                f"{parameter.name} {parameter.value} {parameter.unit or ''}".strip()
                for parameter in product.parameters[:6]
            )
            application = "、".join(product.applications[:3])
            sentence = f"{product.name}" + (f"（{product.series}）" if product.series else "") + (f"（型号 {product.model}）" if product.model else "")
            if product.description:
                sentence += f"，{product.description.strip('。')}"
            if params:
                sentence += f"：{params}"
            if product.commercial_status:
                sentence += f"；商业状态：{product.commercial_status}"
            sentence += "。" if not application else f"；主要应用于{application}。"
            if index == 0:
                sentence += "该产品是当前公开参数最完整的对照样本；技术适配应围绕其已披露指标设定边界，对未披露的环境条件、安全认证和接口要求不作默认假设。"
            else:
                sentence += "该型号是公司公开产品目录中的重点产品，其公开参数完整清单见附录产品清单，可作为对比选型的基础记录。"
            analysis_paragraphs.append(sentence)
        # Family-level analysis: what each key family covers and answers.
        # Families share ONE paragraph so the section stays research prose
        # instead of a repeated per-family template.
        family_groups: dict[str, list[Product]] = {}
        for product in verified_products:
            family_groups.setdefault(product.category or "未分类", []).append(product)
        family_clauses: list[str] = []
        for family, items in sorted(family_groups.items(), key=lambda pair: -len(pair[1]))[:5]:
            names = "、".join(item.name for item in items[:3])
            param_names = list(dict.fromkeys(
                parameter.name for item in items for parameter in item.parameters
            ))[:4]
            clause = f"{family}（{len(items)} 项，代表产品 {names}"
            clause += f"；参数维度：{'、'.join(param_names)}" if param_names else "；公开参数有限"
            clause += "）"
            family_clauses.append(clause)
        if family_clauses:
            analysis_paragraphs.append(
                "产品族结构上，" + "；".join(family_clauses)
                + "。产品族之间的可比性取决于系列、型号和参数口径；对不同应用场景不使用单一额定指标直接排名。"
            )
        # Technology routes & application landscape across the catalog.
        routes = list(dict.fromkeys(
            str(parameter.value).strip() for product in verified_products for parameter in product.parameters
            if parameter.name in {"技术路线", "technology", "technology_route", "电池类型", "材料体系"}
        ))
        if routes:
            analysis_paragraphs.append(
                f"技术路线方面，公开参数显示公司产品覆盖{'、'.join(routes[:6])}等路线；"
                "多路线布局使公司能够同时服务乘用车、商用车、储能与工程机械等差异化需求。"
            )
        applications_all = list(dict.fromkeys(
            application for product in verified_products for application in product.applications
        ))[:8]
        if applications_all:
            analysis_paragraphs.append(
                f"从应用场景看，已核验产品覆盖{'、'.join(applications_all)}等方向；"
                "场景广度决定双方可联合验证的领域不止于单一车型或单一储能项目，也为联合试点提供了可选择的场景池。"
            )
        # Product iteration evidence: launches and commercial status.
        launches = [str(claim.value).strip() for claim in self._verified_claims(bundle) if claim.field_name == "product_launch" and str(claim.value).strip()]
        if launches:
            analysis_paragraphs.append(
                "产品迭代方面，公开披露显示" + "；".join(list(dict.fromkeys(launches))[:3]) + "；"
                "产品发布节奏反映技术路线推进速度，可作为联合开发时间表的参照。"
            )
        segments_all = list(dict.fromkeys(
            str(product.customer_segment).strip() for product in verified_products if product.customer_segment
        ))[:6]
        if segments_all:
            analysis_paragraphs.append(
                f"从客户与市场结构看，产品覆盖{'、'.join(segments_all)}等客户层级；"
                "客户结构决定合作切入时的商务与技术支持方式，需按层级分别设计对接路径与验证节奏。"
            )
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
            "产品路线与技术差异必须落到同一系列、同一型号和同一测试条件下比较；缺少发布时间时，不将产品名录顺序解读为技术演进路线。"
        )
        if len(verified_products) > len(key_products):
            analysis_paragraphs.append(
                f"其余 {len(verified_products) - len(key_products)} 项产品明细见附录产品清单；"
                "HTML 版本支持按产品族筛选与最多 4 项参数对比，便于快速定位与目标场景相关的产品族。"
            )
        parameter_names = list(dict.fromkeys(
            parameter.name for product in verified_products for parameter in product.parameters
        ))
        product_ids = {product.product_id for product in verified_products}
        verified_image_count = sum(
            image.visual_verified and image.product_id in product_ids
            for image in bundle.images
        )
        analysis_paragraphs.append(
            f"资料完整度方面，{len(verified_products)} 项产品中有 {parameterized} 项披露可结构化参数，"
            f"已出现的参数维度为{'、'.join(parameter_names[:8]) or '暂无'}，可绑定至具体产品的已核验图片为 {verified_image_count} 张。"
            "该完整度足以支持产品族级初筛，但型号级选型还需同时核对认证版本、测试条件、工作温度、循环寿命和系统接口，不将产品展示图或单一额定参数作为采购结论。"
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
        factories = list(bundle.factories)
        region_insight = next((item for item in analysis.insights if item.insight_id == "INS-REGIONS"), None)
        context: list[str] = []
        if region_insight is not None:
            context.append(
                f"{region_insight.findings[0] if region_insight.findings else ''}"
                "地域分布可用于识别制造重心和候选切入区域，但具体基地仍需结合工艺、运行状态和责任主体评估。"
            )
        if finding is not None:
            context.append(finding.fact_summary + "当前可确认的基地范围以企业具名披露为准，不将未具名项目或合作方厂区计入目标企业生产布局。")
        if not context:
            context.append(f"公开资料可确认生产基地 {analysis.factory_site_count or len(factories)} 处，地址、工艺和运行状态分别按具体基地核对。")

        analysis_paragraphs: list[str] = []
        distribution = analysis.region_distribution
        if distribution:
            regions = "、".join(f"{region} {count} 处" for region, count in list(distribution.items())[:8])
            analysis_paragraphs.append(
                f"从地域结构看，基地记录按公开地址归类为{regions}。"
                "区域集中度反映产能组织重心，也影响跨区域复制试点时的审批、物流与运维条件；"
                "首批切入应优先选择与目标场景直接相关、资料可得性高的基地，避免以产能排名代替选择。"
            )
            classified_count = analysis.domestic_factory_count + analysis.overseas_factory_count
            if analysis.overseas_factory_count and classified_count == analysis.factory_site_count:
                analysis_paragraphs.append(
                    f"国内基地 {analysis.domestic_factory_count} 处、海外基地 {analysis.overseas_factory_count} 处，"
                    "海外布局反映交付与供应链的境外延伸，合作切入需分别确认境内外的责任主体与标准适用。"
                )
        else:
            analysis_paragraphs.append("基地地址公开披露有限，地域归类将在附录基地清单中随地址原文保留。")
        # Regional role analysis: which regions host what processes.  The
        # first regions get structurally distinct sentences so the chapter
        # does not repeat one template per region.
        region_factories: dict[str, list[Any]] = {}
        region_re = re.compile(r"([\u4e00-\u9fff]{2,10}?(?:省|自治区))")
        overseas_re = re.compile(r"(德国|匈牙利|印尼|印度尼西亚|泰国|越南|美国|西班牙|墨西哥|日本|韩国|波兰|荷兰|比利时)")
        for factory in factories:
            address = factory.address or ""
            overseas = overseas_re.search(address)
            if overseas:
                region_factories.setdefault(overseas.group(1), []).append(factory)
                continue
            match = region_re.search(address)
            if match:
                region_factories.setdefault(match.group(1), []).append(factory)
        ranked_regions = sorted(region_factories.items(), key=lambda pair: -len(pair[1]))[:5]
        templates = (
            lambda region, factories: f"{region}是基地记录最集中的区域，共 {len(factories)} 处：{'、'.join(list(dict.fromkeys(f.name for f in factories if f.name))[:3])}。",
            lambda region, factories: f"{region}布局 {len(factories)} 处基地记录，工艺覆盖{'、'.join(list(dict.fromkeys(p for f in factories for p in f.processes))[:4]) or '待核验'}，是产能组织的重点区域之一。",
            lambda region, factories: f"此外，{region}有 {len(factories)} 处基地记录，反映公司在多个省份的产能纵深布局。",
            lambda region, factories: f"{region}的 {len(factories)} 处基地记录与配套材料、回收业务相关，构成区域产业链协同的支点。",
            lambda region, factories: f"从区域职能看，{region}的 {len(factories)} 处基地记录补充了公司在产能梯次上的布局弹性。",
        )
        for index, (region, factories) in enumerate(ranked_regions):
            if index < len(templates):
                analysis_paragraphs.append(templates[index](region, factories))
        if analysis.overseas_factory_count:
            overseas_names = list(dict.fromkeys(
                factory.name for factory in factories
                if overseas_re.search(factory.address or "") and factory.name
            ))[:4]
            analysis_paragraphs.append(
                f"海外基地方面，{'、'.join(overseas_names) or '公开基地名录'}等记录显示公司在欧洲布局产能；"
                "海外基地的并网、标准与供应链条件与国内不同，合作项目需按所在国法规单独评估。"
            )
        analysis_paragraphs.append(
            "地址信息不完整或未标注地区的基地不强行归类；"
            "在无法确认运营主体、投产状态或具体工艺时，该基地不进入产能加总和首批试点排序。"
        )
        for index, factory in enumerate(factories[:6]):
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
            analysis_paragraphs.append(
                "产能规模与销量、收入的联动关系构成产能组织效率的观察窗口；产能口径描述制造输出，"
                "与基地用电负荷是两类指标，测算中严格分开。"
            )
        else:
            analysis_paragraphs.append(
                "公开资料暂未形成多年度可比产能序列；产能口径描述制造输出，与企业自身用电规模是两类指标，"
                "项目测算不使用产能数字替代负荷与电量数据，用电与负荷须以现场计量为准，测算边界须双方书面确认。"
            )
        address_count = sum(bool(factory.address) for factory in factories)
        process_count = sum(bool(factory.processes) for factory in factories)
        status_count = sum(bool(factory.operating_status) for factory in factories)
        analysis_paragraphs.append(
            f"基地资料完整度方面，{len(factories)} 处基地中有 {address_count} 处具备明确地址、"
            f"{process_count} 处具备工艺信息、{status_count} 处具备运行状态。"
            "首批候选基地应同时满足业务场景相关、运营主体明确、工程边界可核对和能源数据可提供四项条件；"
            "仅有地址或仅有产能名称的基地，只能作为调研对象，不直接进入方案设计和投资测算。"
        )

        # Body shows only the most informative bases; full ledger is an appendix.
        core_rows: list[dict[str, Any]] = []
        for factory in factories[:10]:
            core_rows.append(translate_table_row({
                "name": factory.name or "未命名基地", "address": factory.address or "",
                "processes": "、".join(factory.processes), "status": factory.operating_status or "",
            }))
        if len(factories) > len(core_rows):
            analysis_paragraphs.append(
                f"共确认 {analysis.factory_site_count or len(factories)} 处基地；其中优先展开工程条件分析的是地址、工艺和运行主体信息相对完整的基地。"
            )

        assertion = finding.conclusion if finding is not None else f"公开资料识别生产基地 {analysis.factory_site_count or len(factories)} 处"
        # Lineage: this chapter's facts come from the factory records and the
        # claims stating their address/name facts.  Finding-level claims are
        # inherited first; record-level lineage restores the real provenance
        # when the finding carries none (nothing is invented here).
        lineage_claim_ids = list(finding.supporting_claim_ids) if finding is not None else []
        if not lineage_claim_ids:
            lineage_claim_ids = list(dict.fromkeys(
                claim_id for factory in factories
                for claim_id in factory.supporting_claim_ids
            ))
        if not lineage_claim_ids:
            factory_fields = {"address", "factory_city", "factory_province", "factory_name"}
            factory_addresses = {factory.address.strip() for factory in factories if factory.address and factory.address.strip()}
            lineage_claim_ids = [
                claim.claim_id for claim in bundle.claims
                if claim.field_name in factory_fields and claim.entity_id == entity.entity_id
                and isinstance(claim.value, (str, int, float)) and str(claim.value).strip()
                and (
                    str(claim.value).strip() in factory_addresses
                    or any(str(claim.value).strip() in address for address in factory_addresses)
                )
            ]
        lineage_source_ids = list(finding.supporting_source_ids) if finding is not None else []
        if not lineage_source_ids:
            claims_by_id = {claim.claim_id: claim for claim in bundle.claims}
            lineage_source_ids = list(dict.fromkeys(
                claims_by_id[claim_id].source_id
                for claim_id in lineage_claim_ids if claim_id in claims_by_id
            ))
        module = StoryModule(
            module_id="mod-factories", chapter_id="factories", kind="factories",
            title="生产布局与产能组织", assertion_title=assertion,
            decision_question="生产基地集中在哪里，产能如何组织？",
            executive_takeaway=finding.business_implication if finding is not None else "基地分布用于筛选首批接触基地。",
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=[finding.business_implication] if finding is not None else [],
            # A recommendation without any attached evidence lineage is never
            # published (fail-closed); the gate checks exactly this.
            recommendations=[finding.recommendation] if finding is not None and lineage_claim_ids else [],
            limitations=list(finding.limitations or [])[:1] if finding is not None else [],
            source_ids=lineage_source_ids,
            claim_ids=lineage_claim_ids,
            table_rows=core_rows,
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).factory_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        module.image_ids = images_for(
            chapter="factories", entity_id=entity.entity_id,
            factory_ids={factory.factory_id for factory in factories},
        )
        return module

    # ── 5. energy & zero-carbon ────────────────────────────────────────────
    def _energy_module(self, bundle, analysis: ResearchAnalysis, finding: DecisionFinding | None, narrative: ResearchNarrative) -> StoryModule:
        context: list[str] = []
        verified_energy_claims = [
            claim for claim in bundle.claims
            if claim.verification_status == VerificationStatus.VERIFIED
            and claim.field_name in {
                "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
                "peak_demand", "electricity_cost", "load_curve", "transformer_capacity",
                "roof_area", "carbon_intensity", "pv_capacity", "storage_capacity", "storage_power",
            }
        ]
        report_titles = list(dict.fromkeys(
            str(claim.value).strip() for claim in verified_energy_claims
            if "碳排放核算报告" in str(claim.value) and str(claim.value).strip()
        ))
        present_fields = {item.field_name for item in analysis.own_energy_metrics}
        screening_fields = {"electricity_consumption", "load_curve", "electricity_cost", "transformer_capacity"}
        missing_screening = screening_fields - present_fields
        if analysis.own_energy_metrics:
            context.append(
                "公开披露中可用于能源判断的量化数据包括：" + "；".join(
                    f"{item.label} {item.value_display}{item.unit or ''}"
                    + (f"（{item.period}）" if item.period else "")
                    for item in analysis.own_energy_metrics
                ) + "。这些数值只按原披露期间、单位和范围使用，不从公司产品容量或制造产能补算企业用能。"
            )
        elif report_titles:
            context.append(
                f"公开页面列示{'、'.join(report_titles[:3])}。该页面条目只能确认年度碳核算披露的存在；"
                "标题本身没有给出综合能源消费量的数值、单位和基地范围，因此不能作为企业能耗指标。"
            )
        elif finding is not None:
            context.append(finding.fact_summary)
        else:
            context.append(
                "当前公开资料未提供可以落到单一基地的电量、负荷、电价、配电容量或屋顶数据。"
            )

        analysis_paragraphs: list[str] = []
        if analysis.own_energy_metrics and not missing_screening:
            analysis_paragraphs.append(
                "现有量化信息可用于选择进入预可研的候选基地，但装机规模、储能时长和收益仍取决于同一基地、同一期间的完整账单与运行数据。"
            )
        else:
            analysis_paragraphs.append(
                "现有证据不能比较各基地的用能成本、峰谷差或可接入容量，也不能确定光伏装机、储能功率与时长。"
                "因此当前不提供项目规模、投资额或收益估算。"
            )
        zero_carbon_insight = next((item for item in analysis.insights if item.insight_id == "INS-ZERO-CARBON"), None)
        if zero_carbon_insight and zero_carbon_insight.findings:
            analysis_paragraphs.append(zero_carbon_insight.findings[0])
        if analysis.energy_product_metrics:
            analysis_paragraphs.append(
                "公司公开披露的储能或光伏产品参数可以用于讨论技术接口，但不能替代目标基地的负荷和电价数据。"
            )
        analysis_paragraphs.append(
            "下一步只需做一项明确判断：能否由一处基地的能源管理或设施部门提供近12至24个月电量账单、"
            "分时负荷、电价、配电容量、屋顶条件和既有光储设施资料。资料齐备后再做预可研；"
            "若没有明确基地、责任部门或完整数据，则不进入容量设计和商业报价。"
        )

        if analysis.own_energy_metrics and not missing_screening:
            assertion = "公开量化能源数据可支持基地初筛，项目方案仍需按基地复核"
        elif analysis.own_energy_metrics:
            assertion = "现有量化能源数据不完整，暂不能确定项目容量或收益"
        else:
            assertion = "公开资料尚不足以判断单个基地的光伏或储能项目经济性"
        energy_claim_ids = list(dict.fromkeys(
            [claim_id for item in analysis.own_energy_metrics for claim_id in item.claim_ids]
            + [claim.claim_id for claim in verified_energy_claims]
        ))
        energy_source_ids = list(dict.fromkeys(
            [source_id for item in analysis.own_energy_metrics for source_id in item.source_ids]
            + [claim.source_id for claim in verified_energy_claims]
        ))
        recommendation = (
            "选择一处基地，由能源管理或设施部门提供同一期间的电量、负荷、电价、配电和屋顶数据。"
        )
        module = StoryModule(
            module_id="mod-energy", chapter_id="energy_profile", kind="energy_profile",
            title="能源与零碳能力", assertion_title=assertion,
            decision_question="现有公开数据能否支持基地能源项目决策？",
            executive_takeaway="当前公开信息最多支持启动一处基地的数据核验，不支持直接进行容量设计或商业报价。",
            context_paragraphs=context,
            analysis_paragraphs=analysis_paragraphs,
            implications=[],
            # An evidence-empty fixture may still state that project sizing is
            # unsupported, but must not promote an action as an evidence-backed
            # recommendation.  Real disclosures (including a report listing)
            # supply the lineage for the one-base data-verification step.
            recommendations=[recommendation] if energy_claim_ids else [],
            limitations=["缺少能够落到单一基地和统一期间的完整测算输入。"],
            source_ids=energy_source_ids,
            claim_ids=energy_claim_ids,
        )
        for proposal in VisualOpportunityPlanner(bundle, analysis).energy_proposals():
            spec = self._route(proposal, narrative)
            if spec is not None:
                module.visual_ids.append(spec.visual_id)
        return module

    # ── opportunities / action / risks (consulting layer) ──────────────────
    def _opportunity_module(self, opportunities: list[OpportunityAssessment], narrative: ResearchNarrative) -> StoryModule:
        status_labels = {
            "PRIORITY_OPPORTUNITY": "优先接洽",
            "POTENTIAL_HYPOTHESIS": "备选方向",
            "REJECTED": "暂不考虑",
        }
        paragraphs: list[str] = []
        seen_paragraphs: set[str] = set()
        rows: list[dict[str, Any]] = []
        for rank, item in enumerate(opportunities, start=1):
            status = status_labels.get(item.hypothesis_status, "待确认")
            if item.hypothesis_status == "PRIORITY_OPPORTUNITY":
                paragraph = (
                    f"{rank}. {item.opportunity_name}（{status}）。现有研发、产品或业务资料支持将其列为首个接洽方向。"
                    f"{item.why_now}仅凭公开资料仍无法判断对方是否准备启动项目。"
                    f"建议联系{item.target_department}，先确定一个具体课题、技术指标和双方分工。"
                    f"{item.client_name}可参与{'、'.join(item.client_capability_match) or '相关工作的组织'}。"
                )
            else:
                paragraph = (
                    f"{rank}. {item.opportunity_name}（{status}）。现有资料能说明相关产品、产能或客户基础，"
                    f"但未显示对方提出具体合作需求。先由{item.target_department}确认需求；未获确认前不讨论立项。"
                )
            if paragraph not in seen_paragraphs:
                seen_paragraphs.add(paragraph)
                paragraphs.append(paragraph)
            rows.append(translate_table_row({
                "opportunity": item.opportunity_name, "priority": item.priority,
                "target_scenario": item.target_problem, "entry_point": item.target_department,
                "go_no_go_gate": item.go_no_go_gate,
            }))
        top = opportunities[0]
        paragraphs.append(
            f"排序优先考虑对方需求是否明确、{top.client_name}能否投入相应资源，以及是否能在一个具体课题上形成可量化结果。"
            "未获得业务部门确认的方向仅作为备选，不进入立项。"
        )
        module = StoryModule(
            module_id="mod-opportunities", chapter_id="opportunities", kind="opportunities",
            title="合作机会评估与优先级",
            assertion_title=f"{top.opportunity_name}列为首选，但应先完成业务接洽再讨论立项",
            decision_question="哪些合作机会最值得推进，从哪里切入？",
            executive_takeaway=f"优先与{top.target_department}讨论{top.opportunity_name}，暂不直接进入项目实施。",
            analysis_paragraphs=paragraphs,
            limitations=["备选方向尚未获得对方业务部门确认，不应据此承诺项目或收益。"],
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
        # The action chapter carries ONE 30/60/90 chain (top opportunity);
        # per-opportunity action rows stay in the opportunities table so the
        # chapter does not repeat the same three action templates N times.
        top = opportunities[0]
        actions = [
            f"30 天｜{top.opportunity_name}：{top.first_30_day_action}",
            f"60 天｜{top.opportunity_name}：{top.day_60_action}",
            f"90 天｜{top.opportunity_name}：{top.day_90_milestone}",
        ]
        if len(opportunities) > 1:
            actions.append(
                f"其余 {len(opportunities) - 1} 个备选方向（{'、'.join(item.opportunity_name for item in opportunities[1:])}）"
                "分别确认对方需求，不沿用首位方向的人员和预算安排。"
            )
        module = StoryModule(
            module_id="mod-action", chapter_id="action_plan", kind="action_plan",
            title="优先切入方案与 90 天行动",
            assertion_title=f"用 90 天判断{top.opportunity_name}是否具备立项条件",
            decision_question="未来 90 天应完成什么，谁负责，如何判断成功？",
            executive_takeaway=f"先确认需求，再验证具体课题，最后决定是否为{top.opportunity_name}立项。",
            analysis_paragraphs=[
                f"前 30 天先与{top.target_department}核实具体需求并确定负责人。"
                f"第 31—60 天围绕{top.opportunity_name}选择一个可验证课题，明确技术指标、所需数据、双方分工和知识产权边界。"
                "第 61—90 天根据课题结果决定立项、缩小范围或结束接洽。",
                f"判断标准应写得具体：对方是否确认需求，课题是否有可量化指标，{top.client_name}能否落实人员和验证资源。"
                "其中任何一项无法确认，都不进入下一阶段。",
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
        critical = [item for item in decision.due_diligence if item.decision_blocker][:5]
        due_rows = [{"关键不确定性": item.item, "可能改变的判断": item.affected_decision} for item in critical]
        return StoryModule(
            module_id="mod-risks", chapter_id="risks_evidence", kind="risks_evidence",
            title="企业风险、关键不确定性与停止条件",
            assertion_title="市场竞争和关键经营信息不足是当前接洽的主要限制",
            decision_question="哪些企业风险或反证会改变当前合作判断？",
            executive_takeaway="立项前需核实会影响技术范围、投入规模和合作意愿的关键事项。",
            context_paragraphs=[
                "风险判断仅纳入公司已披露的经营风险，以及会直接改变合作方向、投入规模或停止条件的待确认事项。"
            ],
            analysis_paragraphs=[
                *(decision.key_risks or ["当前已核验披露未识别需要单列的企业特定风险；这不等于企业不存在风险。"]),
                "如对方未提出具体需求、双方技术路线或交付范围无法对齐，或创新中心无法落实必要人员和验证资源，应结束接洽；对方若已明确选择其他技术路径，也不再继续投入。",
                "监管、客户集中、供应链依赖、技术路线或财务压力只有在公司披露或可靠事件中得到支持时才列为企业风险。缺少某项公开资料本身不代表公司存在相应风险。",
                "正文仅保留可能改变合作方向或投入规模的未知事项；其他待核实信息列入附录。",
            ],
            recommendations=[
                "优先核实会影响技术范围、投入规模和对方合作意愿的事项。"
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
            None,
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
        if not facts:
            return f"研究主体为{entity.canonical_name}。"
        return f"{entity.canonical_name}：{'；'.join(facts)}。"

    def _operating_disclosure_paragraphs(self, bundle: FrozenResearchBundle) -> list[str]:
        """Describe the enterprise's actual disclosure scope in market-research prose.

        The paragraph content is assembled from target-bound claim values,
        reporting periods and named sources.  It adds analytical depth without
        repeating chapter scaffolding or narrating the research workflow.
        """
        entity = self._canonical_entity(bundle)
        if entity is None:
            return []
        all_claims = self._verified_claims(bundle)
        grouped_fields = {
            "registered_name", "brand_operator", "parent_company",
            "customer_name", "customer_segment", "supplier_relationship", "sales_channel",
            "contract", "application_case",
            "strategic_priority", "strategy_event", "technology_route",
        }
        evidence_claims = [
            claim for claim in all_claims
            if claim.field_name not in {
                "canonical_company_name", "registered_name", "aliases", "former_names",
                "official_website", "registration_region", "headquarters", "founded_date",
            }
        ]
        claims = [claim for claim in evidence_claims if claim.field_name not in grouped_fields]
        sources = {source.source_id: source for source in bundle.sources}
        fact_samples: list[str] = []
        for claim in claims:
            if isinstance(claim.value, (dict, list, tuple, set)):
                continue
            value = str(claim.value).strip()
            if not value:
                continue
            label = field_label(claim.field_name)
            if "_" in label:
                continue
            display = f"{label}为{value}{claim.unit or ''}"
            if display not in fact_samples:
                fact_samples.append(display)
        source_names = list(dict.fromkeys(
            (sources[claim.source_id].source_title or sources[claim.source_id].publisher or sources[claim.source_id].source_domain)
            for claim in evidence_claims if claim.source_id in sources
        ))
        periods = sorted({
            str(claim.period_end.year if claim.period_end else claim.as_of_date.year)
            for claim in evidence_claims if claim.period_end or claim.as_of_date
        })
        paragraphs: list[str] = []

        def values(*fields: str, limit: int = 4) -> list[str]:
            return list(dict.fromkeys(
                str(claim.value).strip().rstrip("。；;")
                for claim in all_claims
                if claim.field_name in fields
                and not isinstance(claim.value, (dict, list, tuple, set))
                and str(claim.value).strip().rstrip("。；;")
            ))[:limit]

        legal_names = values("registered_name", "brand_operator", limit=2)
        parents = values("parent_company", limit=2)
        if legal_names or parents:
            boundary = (
                f"主体边界方面，公开披露将{entity.canonical_name}对应的注册或品牌运营主体识别为"
                f"{'、'.join(legal_names) if legal_names else '待进一步核对的法人主体'}"
            )
            if parents:
                boundary += f"，并披露其母公司为{'、'.join(parents)}"
            paragraphs.append(
                boundary
                + "。这一边界直接影响商务对接：品牌运营、合同签署、知识产权归属、付款责任和集团资源调用可能由不同主体承担。"
                "在进入合作方案或报价前，应以工商信息、合同抬头和授权文件逐项核对责任主体，不把集团层能力直接视为目标公司的可支配资源。"
            )

        market_signals = values(
            "customer_name", "customer_segment", "supplier_relationship", "sales_channel",
            limit=5,
        )
        if market_signals:
            paragraphs.append(
                "市场与渠道证据显示，" + "；".join(market_signals) + "。"
                "这些事实可以证明公司已进入相应客户触点、设备市场或公共充电服务链条，但客户关系、供应商关系、渠道触达和资产运营并不是同一收入确认口径。"
                "下一步应分别核对获客入口、充电资产归属、订单或框架协议、结算方式、服务费口径及合作期限，才能判断渠道的商业贡献与持续性。"
            )

        contracts = values("contract", limit=3)
        cases = values("application_case", limit=3)
        if contracts or cases:
            disclosed = "；".join([*contracts, *cases])
            paragraphs.append(
                f"交付与运营改善方面，现有公开案例披露{disclosed}。"
                "该证据说明公司曾在具体项目或管理场景中取得可观察结果，可用于识别其运营改善诉求和外部协同经验；"
                "但单一案例不能直接外推为全公司、全基地或未来期间的稳定表现。后续尽调需确认基期、统计周期、适用组织、计算方法及改善措施的可归因性。"
            )

        strategic_signals = values(
            "strategic_priority", "strategy_event", "technology_route", limit=5,
        )
        if strategic_signals:
            paragraphs.append(
                "战略与技术协同方面，公开披露集中指向" + "；".join(strategic_signals) + "。"
                "这些事项共同界定了现阶段可讨论的技术方向与合作场景，适合转化为充电功率、检测能力、站点建设、系统接口和运营指标等可验收课题。"
                "是否形成真实合作窗口，仍取决于对方业务部门是否给出明确需求、预算责任和项目时点，不能仅凭合作新闻或技术表述推定立项。"
            )

        if fact_samples:
            paragraphs.append(
                f"{entity.canonical_name}当前可直接确认的经营事实包括"
                + "；".join(fact_samples[:6])
                + "。这些披露确定了业务边界和现有经营载体；对未同时给出期间、范围或单位的数值，不进行增长率、市场份额或产能利用率推算。"
            )
        if source_names or periods:
            period_text = "、".join(periods) + "年" if periods else "未标明统一报告期"
            source_text = "、".join(source_names[:4]) if source_names else "企业公开披露"
            paragraphs.append(
                f"现有经营口径主要来自{source_text}，涉及期间为{period_text}。"
                "同一指标只有在主体、会计口径、币种和报告期一致时才进行比较；"
                "单期披露用于判断当前规模，不替代跨期增长、盈利质量或现金流持续性分析。"
            )
        return paragraphs

    @staticmethod
    def _verified_claims(bundle: FrozenResearchBundle) -> list[Claim]:
        canonical_id = bundle.run_manifest.canonical_entity_id
        return [
            claim for claim in bundle.claims
            if claim.entity_id == canonical_id
            and claim.verification_status == VerificationStatus.VERIFIED
        ]

    def _default_synthesis(self, bundle: FrozenResearchBundle, entity) -> ResearchSynthesis:
        from energy_research_agent.research.synthesis import ResearchSynthesizer
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
            linked = [
                image for image in candidates
                if image.product_id and image.product_id in (product_ids or set())
            ]
            # Official product photography bound to the subject entity but
            # never linked to an individual product record still documents
            # the product portfolio — it is verified entity evidence, not a
            # contextual guess.  Use it only after product-linked images.
            fallback = [
                image for image in candidates
                if image not in linked and not image.product_id
                and image.target_entity_type == "product"
                and entity_id is not None and image.target_entity_id == entity_id
            ]
            # Deep-research product photos are often archived under a
            # product-level entity id (ENT-*) rather than a Product record
            # id or the company entity id.  They are pixel-verified product
            # photographs approved by the publication pipeline for this
            # subject, so publish them in the portfolio instead of dropping
            # them on a linkage miss — crawling them otherwise buys nothing.
            unlinked = [
                image for image in candidates
                if image not in linked and image not in fallback
                and not image.product_id and image.target_entity_type == "product"
            ]
            candidates = linked + fallback + unlinked
            # A verified product photo never loses to chapter pacing: widen
            # the budget so every candidate enters the products chapter.
            budget = max(budget, len(candidates))
        elif chapter == "factories":
            candidates = [image for image in candidates if image.factory_id and image.factory_id in (factory_ids or set())]
        elif chapter in {"executive_summary", "entity_profile"}:
            candidates = [
                image for image in candidates
                if image.target_entity_type in {"logo", "headquarters", "office", "editorial"}
                or (
                    (image.entity_id == entity_id or image.target_entity_id == entity_id)
                    and not image.product_id and not image.factory_id
                    and image.target_entity_type not in {
                        "product", "factory", "production_line", "workshop",
                    }
                )
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
