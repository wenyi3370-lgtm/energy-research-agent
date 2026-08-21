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
    """One report section: conclusion-driven title + evidence-bound content."""

    module_id: str
    chapter_id: str
    kind: Literal[
        "executive_summary", "entity_profile", "group_structure", "partnerships",
        "operations", "factories", "products", "energy_profile", "opportunities",
        "risks_evidence", "sources",
    ]
    title: str
    decision_question: str
    thesis: str
    content: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    visual_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    table_rows: list[dict[str, Any]] = Field(default_factory=list)
    order: int = 0


class ResearchNarrative(BaseModel):
    schema_version: str = "2.0"
    run_id: str
    freeze_id: str
    entity_name: str
    entity_id: str | None = None
    decision_questions: list[str] = Field(default_factory=list)
    executive_summary: list[str] = Field(default_factory=list)
    chapters: list[StoryModule] = Field(default_factory=list)
    visuals: list[VisualSpec] = Field(default_factory=list)
    visual_events: list[VisualEvent] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
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

    # ── entry ──
    def build(self, bundle: FrozenResearchBundle, synthesis: ResearchSynthesis | None = None) -> ResearchNarrative:
        entity = self._canonical_entity(bundle)
        if entity is None:
            raise ValueError("Frozen bundle contains no enterprise entity")
        synthesis = synthesis or self._default_synthesis(bundle, entity)
        verified = self._verified_claims(bundle)
        by_field: dict[str, list[Claim]] = {}
        for claim in verified:
            by_field.setdefault(claim.field_name, []).append(claim)

        narrative = ResearchNarrative(
            run_id=bundle.run_manifest.run_id,
            freeze_id=bundle.freeze.freeze_id,
            entity_name=entity.canonical_name,
            entity_id=entity.entity_id,
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

        # decision questions drive the whole document
        narrative.decision_questions = self._decision_questions(bundle, synthesis, by_field)
        narrative.executive_summary = list(synthesis.executive_summary)

        executive = self._chapter_executive(bundle, synthesis, by_field, narrative, images_for)
        add(executive)

        profile = self._chapter_entity_profile(bundle, synthesis, by_field, narrative, images_for)
        add(profile)

        structure = self._chapter_group_structure(bundle, narrative)
        if structure is not None:
            add(structure)

        partnerships = self._chapter_partnerships(bundle, narrative)
        if partnerships is not None:
            add(partnerships)

        operations = self._chapter_operations(bundle, synthesis, by_field, narrative)
        if operations is not None:
            add(operations)

        factories = self._chapter_factories(bundle, narrative, images_for)
        if factories is not None:
            add(factories)

        products = self._chapter_products(bundle, narrative, images_for)
        if products is not None:
            add(products)

        energy = self._chapter_energy(bundle, synthesis, by_field, narrative)
        if energy is not None:
            add(energy)

        opportunities = self._chapter_opportunities(bundle, synthesis, narrative)
        if opportunities is not None:
            add(opportunities)

        risks = self._chapter_risks(bundle, synthesis, narrative)
        if risks is not None:
            add(risks)

        add(self._chapter_sources(bundle))

        narrative.counts = self._counts(bundle, narrative)
        return narrative

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
                confidence="high",
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
        return {
            "chapters": len(narrative.chapters),
            "visuals": len(narrative.visuals),
            "verified_claims": len(self._verified_claims(bundle)),
            "sources": len(bundle.sources),
            "factories": len(bundle.factories),
            "verified_products": len(verified_products),
            "images_publishable": len(publishable_images(bundle)),
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
            title="股权与组织关系",
            decision_question="集团边界与成员关系是什么，与谁谈？",
            thesis=f"经核验的股权关系涉及 {len(nodes)} 个主体。",
            content=content,
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
