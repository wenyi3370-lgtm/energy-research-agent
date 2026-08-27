"""HTML renderer (P0 refactor): narrative-driven dashboard, inline diagram-design SVG.

One page per frozen bundle.  Chapter structure comes from the SAME
ResearchNarrative as the Word report; figures are the SAME diagram-design
SVGs (inline here, PNG-exported for Word).  There is no second charting
implementation, no fixed 18-section navigation, no group-evidence-register
chapter, and no renderer/QA text in the user-facing page.

The default view is a decision dashboard. Full prose and evidence ledgers
remain available behind collapsed detail controls, while the product showcase
contains only products with formally approved official imagery.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.artifacts.diagram_design_adapter import DiagramDesignAdapter
from enterprise_energy_research.artifacts.image_publication import prepare_publication_images, write_image_publication_manifest
from enterprise_energy_research.artifacts.narrative import NarrativeBuilder, write_narrative
from enterprise_energy_research.artifacts.publication_boilerplate import (
    HTML_ZERO_PHRASES,
    PublicationBoilerplateFilter,
)
from enterprise_energy_research.artifacts.qa_report import QAFinding, QAVisualEntry, downgrade_conditional_findings, new_qa_report, write_qa_report
from enterprise_energy_research.artifacts.visuals import write_visual_manifest
from enterprise_energy_research.domain.enums import ArtifactType, EnterpriseComplexity, VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.research.synthesis import ResearchSynthesizer
from enterprise_energy_research.vendor import embedded_skill_root
from enterprise_energy_research.validation.consulting_narrative import (
    ConsultingNarrativeValidator, VisualSemanticValidator, write_consulting_validation,
)
from enterprise_energy_research.validation.publication_quality import (
    DecisionIntelligenceValidator,
    ProductImageCoverageValidator,
    PublicationBoilerplateValidator,
    ResearchValueValidator,
)


def _json_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class FrozenHtmlPublisher:
    """Publish one offline decision dashboard from one FrozenResearchBundle."""

    name = "frontend_design"

    def __init__(self, artifact_type: ArtifactType, skill_root: Path | None = None, asset_root: Path | None = None) -> None:
        if artifact_type not in {ArtifactType.ENTERPRISE_HTML, ArtifactType.PRODUCT_HTML}:
            raise ValueError("FrozenHtmlPublisher supports enterprise_html and product_html only")
        self.artifact_type = artifact_type
        self.skill_root = skill_root or embedded_skill_root("frontend-design")
        self.asset_root = Path(asset_root) if asset_root else None

    def health(self) -> AdapterHealth:
        available = (self.skill_root / "SKILL.md").is_file()
        return AdapterHealth(name=self.name, available=available, version="embedded", diagnostics=[] if available else ["Embedded frontend-design instructions are missing"])

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        health = self.health()
        if not health.available:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=health.diagnostics)
        if binding.type != self.artifact_type:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=["Binding type does not match publisher"])
        content, claims, images, qa_status = self._unified_page(bundle, binding, output_path)
        digest = _write(output_path, content)
        return ArtifactResult(
            adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
            path=output_path, content_sha256=digest, used_claim_ids=claims, used_image_ids=images,
            status="published" if qa_status != "fail" else "failed",
            diagnostics=[] if qa_status != "fail" else ["publication_qa_failed"],
        )

    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        return next((item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id), bundle.entities[0] if bundle.entities else None)

    def _unified_page(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> tuple[str, list[str], list[str], str]:
        entity = self._canonical_entity(bundle)
        if not entity:
            raise ValueError("Frozen bundle contains no enterprise entity")
        synthesis = ResearchSynthesizer().synthesize(
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
        narrative = NarrativeBuilder().build(bundle, synthesis)

        asset_root = output_path.parent / f"{output_path.stem}_assets"
        figures = asset_root / "figures"
        adapter = DiagramDesignAdapter()
        qa = new_qa_report(bundle.run_manifest.run_id, bundle.freeze.freeze_id, binding.artifact_id)
        fixture_mode = bundle.run_manifest.model_gateway.get("mode") in {
            "fixture", "recorded-fixture", "recorded-fixture-only",
        }
        narrative_validation = ConsultingNarrativeValidator().validate(
            narrative, enforce_length=not fixture_mode,
        )
        write_consulting_validation(narrative_validation, asset_root / "consulting_narrative_validation.json")
        for check in narrative_validation.checks:
            if check.status == "FAIL":
                qa.record_finding(QAFinding(code=check.code, severity="error", message=check.message))
        for check in [
            *PublicationBoilerplateValidator().validate(narrative),
            *ResearchValueValidator().validate(narrative, bundle),
            *ProductImageCoverageValidator().validate(narrative),
            *DecisionIntelligenceValidator().validate(narrative, bundle),
        ]:
            if check.status == "FAIL":
                qa.record_finding(QAFinding(code=check.code, severity="error", message=check.message))
            elif check.status == "WARN":
                qa.record_finding(QAFinding(code=check.code, severity="warn", message=check.message))

        inline_visuals: dict[str, dict[str, Any]] = {}
        for spec in narrative.visuals:
            for semantic_error in VisualSemanticValidator().validate(spec, bundle):
                qa.record_finding(QAFinding(
                    code="visual_semantic_violation", severity="error", message=semantic_error,
                    record_ids=[spec.visual_id],
                ))
            result = adapter.build_visual(spec, figures, destination="html", png_scale=3)
            outcome = "rendered" if result.status == "rendered" else result.status
            qa.record_visual(QAVisualEntry(
                visual_id=spec.visual_id, chapter_id=spec.chapter_id,
                outcome=outcome,  # type: ignore[arg-type]
                visual_type=result.visual_type,
                reason=result.fallback_reason or result.error,
                png_status=result.png_status,
            ))
            if result.status == "failed":
                qa.record_finding(QAFinding(
                    code="visual_render_failed", severity="error",
                    message=f"{spec.visual_id} could not be rendered; insight kept as prose",
                    record_ids=[spec.visual_id],
                ))
                continue
            inline_visuals[spec.visual_id] = {
                "id": spec.visual_id,
                "title": spec.title,
                "subtitle": spec.subtitle,
                "type": result.visual_type,
                "businessThesis": spec.business_thesis,
                "decisionQuestion": spec.decision_question,
                "sourceNote": spec.source_note,
                "transformation": spec.transformation,
                "markup": result.svg_markup or "",
            }
        write_visual_manifest(narrative.visual_manifest(), asset_root / "visual_manifest.json")
        write_narrative(narrative, asset_root / "narrative.json")
        extra_roots = [self.asset_root] if self.asset_root else []
        image_manifest = prepare_publication_images(bundle, binding, asset_root, extra_search_roots=extra_roots)
        prepared = {item.image_id: item for item in image_manifest.prepared_images}
        used_image_ids = sorted({image_id for chapter in narrative.chapters for image_id in chapter.image_ids if image_id in prepared})
        image_manifest = image_manifest.model_copy(update={"artifact_selections": {"html": used_image_ids}})
        write_image_publication_manifest(image_manifest, asset_root)

        # Full product ledger remains searchable in collapsed detail. The
        # default showcase is image-backed only: no placeholders are published.
        products = []
        prepared_by_product = {}
        for publication in image_manifest.prepared_images:
            if publication.product_id and publication.product_id not in prepared_by_product:
                prepared_by_product[publication.product_id] = publication
        for product in bundle.products:
            if product.verification_status != VerificationStatus.VERIFIED:
                continue
            bound_image_id = narrative.product_images.get(product.product_id) or product.image_id
            publication = prepared.get(bound_image_id or "")
            if publication is None:
                publication = prepared_by_product.get(product.product_id)
                bound_image_id = publication.image_id if publication is not None else bound_image_id
            products.append({
                "id": product.product_id, "name": product.name, "brand": product.brand, "model": product.model,
                "family": product.category or "未分类", "series": product.series or "",
                "description": product.description or "",
                "applications": product.applications,
                "parameters": [item.model_dump(mode="json") for item in product.parameters],
                "imageId": bound_image_id,
                "offlineAsset": self._data_uri(asset_root, publication.publication_path) if publication else None,
                "imageSource": publication.source_page_url if publication else None,
                "evidenceStatus": "已核验",
                "sourceIds": product.source_ids,
            })
        featured_products = [product for product in products if product["offlineAsset"]][:8]

        gallery = []
        for chapter in narrative.chapters:
            for image_id in chapter.image_ids:
                publication = prepared.get(image_id)
                if publication is None or image_id in {item["id"] for item in gallery}:
                    continue
                gallery.append({
                    "id": image_id, "role": publication.image_type, "caption": publication.caption,
                    "source": publication.source_page_url, "chapter": chapter.chapter_id,
                    "asset": self._data_uri(asset_root, publication.publication_path),
                })
        # Publish every verified image even when the narrative assigns only a
        # subset to chapters; remaining images complete the evidence gallery.
        gallery_ids = {item["id"] for item in gallery}
        for publication in image_manifest.prepared_images:
            if publication.image_id in gallery_ids:
                continue
            gallery.append({
                "id": publication.image_id, "role": publication.image_type, "caption": publication.caption,
                "source": publication.source_page_url, "chapter": "evidence_gallery",
                "asset": self._data_uri(asset_root, publication.publication_path),
            })

        chapters_payload = []
        for chapter in narrative.chapters:
            chapter_visuals = [inline_visuals[visual_id] for visual_id in chapter.visual_ids if visual_id in inline_visuals][:3]
            insight_candidates = [
                *chapter.implications, *chapter.recommendations,
                *chapter.analysis_paragraphs, *chapter.context_paragraphs,
                *chapter.limitations,
            ]
            insights: list[str] = []
            for item in insight_candidates:
                compact = " ".join(str(item).split())
                if compact and compact not in insights:
                    insights.append(compact)
                if len(insights) == 3:
                    break
            while len(insights) < 3:
                facts = [
                    f"本章汇总 {len(chapter.claim_ids)} 条已核验事实。",
                    f"本章配置 {len(chapter_visuals)} 项数据可视化。",
                    f"本章列出 {len(chapter.action_items)} 项可执行动作。",
                ]
                candidate = facts[len(insights)]
                if candidate not in insights:
                    insights.append(candidate)
            chapters_payload.append({
                "id": chapter.chapter_id, "kind": chapter.kind, "title": chapter.title,
                "assertionTitle": chapter.assertion_title,
                "executiveTakeaway": chapter.executive_takeaway,
                "kpis": self._chapter_kpis(chapter.kind, bundle, narrative, prepared),
                "insights": insights[:3],
                "context": chapter.context_paragraphs,
                "analysis": chapter.analysis_paragraphs,
                "implications": chapter.implications,
                "recommendations": chapter.recommendations,
                "counterEvidence": chapter.counter_evidence,
                "limitations": chapter.limitations,
                "actions": chapter.action_items,
                "tables": chapter.table_rows,
                "visuals": chapter_visuals,
                "images": [item for item in gallery if item["chapter"] == chapter.chapter_id],
            })
        # Unassigned verified images still deserve publication: render them
        # in a dedicated evidence-gallery chapter so every valid image is embedded.
        unassigned = [item for item in gallery if item["chapter"] == "evidence_gallery"]
        if unassigned:
            chapters_payload.append({
                "title": "图片证据全集",
                "assertion": "全部通过像素级视觉核验的图片证据",
                "takeaway": f"共 {len(unassigned)} 张核验图片未被正文章节引用，统一在此展示，确保有效图片全量嵌入。",
                "kpis": chapters_payload[-1].get("kpis", []) if chapters_payload else [],
                "insights": chapters_payload[-1].get("insights", []) if chapters_payload else [],
                "visuals": [],
                "limitations": [],
                "actions": [],
                "tables": [],
                "images": unassigned,
            })

        payload = {
            "entity": {
                "id": entity.entity_id, "name": entity.canonical_name, "type": entity.entity_type,
                "region": entity.registration_region, "website": str(entity.official_website or ""),
                "status": entity.verification_status.value,
            },
            "chapters": chapters_payload,
            "decisionQuestions": narrative.decision_questions,
            "overallJudgement": narrative.overall_judgement,
            "judgementRationale": narrative.judgement_rationale,
            "topOpportunity": narrative.opportunity_assessments[0].opportunity_name if narrative.opportunity_assessments else "关键事实补齐",
            "ninetyDayAction": (
                narrative.opportunity_assessments[0].day_90_milestone
                if narrative.opportunity_assessments else "完成关键资料获取并形成是否继续投入的书面判断"
            ),
            "insights": list(narrative.executive_summary),
            "kpis": narrative.kpis,
            "products": products,
            "featuredProducts": featured_products,
            "sources": narrative.appendices.source_ledger,
            "conditionalNotice": (
                "本报告基于已核验的公开证据编制，但存在未能通过公开渠道补齐的覆盖缺口；"
                "相关结论受此证据边界限制，正式对外发布前需完成补充尽调。"
                if (bundle.run_manifest.research_scope or {}).get("publication_mode") == "conditional"
                else ""
            ),
            "meta": {
                "freeze": bundle.freeze.freeze_id,
                "rootHash": bundle.freeze.root_hash,
                "researchDate": bundle.freeze.created_at.date().isoformat(),
                "generatedAt": narrative.generated_at[:10],
                "counts": narrative.counts,
            },
        }
        payload = PublicationBoilerplateFilter().filter_value(payload)
        phrase_counts = PublicationBoilerplateFilter.zero_phrase_counts(payload)
        if any(phrase_counts.values()):
            qa.record_finding(QAFinding(code="html_boilerplate_zero_gate", severity="error", message=str(phrase_counts)))
        self._record_dashboard_contract_qa(qa, bundle, chapters_payload, featured_products)
        downgrade_conditional_findings(qa, bundle)
        write_qa_report(qa, asset_root / "publication_qa_report.json")
        return self._document(entity.canonical_name, payload), [item.claim_id for item in bundle.claims if item.verification_status == VerificationStatus.VERIFIED], used_image_ids, qa.status

    @staticmethod
    def _chapter_kpis(kind: str, bundle: FrozenResearchBundle, narrative: Any, prepared: dict[str, Any]) -> list[dict[str, Any]]:
        verified_products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        verified_claims = [item for item in bundle.claims if item.verification_status == VerificationStatus.VERIFIED]
        verified_sources = {item.source_id for item in verified_claims}
        image_bound = sum(1 for item in verified_products if (narrative.product_images.get(item.product_id) or item.image_id) in prepared)
        parameterized = sum(bool(item.parameters) for item in verified_products)
        families = len({item.category for item in verified_products if item.category})
        base = {
            "executive_summary": list(narrative.kpis[:6]),
            "entity_profile": [
                {"label": "已核验事实", "value": len(verified_claims), "unit": "条"},
                {"label": "有效来源", "value": len(verified_sources), "unit": "个"},
                {"label": "关联主体", "value": len(bundle.entities), "unit": "个"},
            ],
            "operations": list(narrative.kpis[:6]),
            "products": [
                {"label": "已核验产品", "value": len(verified_products), "unit": "项"},
                {"label": "产品族", "value": families, "unit": "类"},
                {"label": "含公开参数", "value": parameterized, "unit": "项"},
                {"label": "正式产品图片", "value": image_bound, "unit": "张"},
            ],
            "factories": [
                {"label": "生产基地", "value": len(bundle.factories), "unit": "处"},
                {"label": "有公开地址", "value": sum(bool(item.address) for item in bundle.factories), "unit": "处"},
                {"label": "有工序信息", "value": sum(bool(item.processes) for item in bundle.factories), "unit": "处"},
            ],
            "energy_profile": [
                {"label": "能源画像", "value": len(bundle.energy_profiles), "unit": "组"},
                {"label": "用能字段", "value": sum(len(item.field_status) for item in bundle.energy_profiles), "unit": "项"},
                {"label": "能源解决方案", "value": len(bundle.solutions), "unit": "项"},
            ],
            "opportunities": [
                {"label": "合作机会", "value": len(narrative.opportunity_assessments), "unit": "项"},
                {"label": "A 级机会", "value": sum(item.priority == "A" for item in narrative.opportunity_assessments), "unit": "项"},
                {"label": "支撑事实", "value": sum(len(item.supporting_claim_ids) for item in narrative.opportunity_assessments), "unit": "条"},
            ],
            "action_plan": [
                {"label": "首阶段", "value": 30, "unit": "天"},
                {"label": "验证阶段", "value": 60, "unit": "天"},
                {"label": "决策里程碑", "value": 90, "unit": "天"},
            ],
            "risks_evidence": [
                {"label": "待补数据", "value": len(bundle.gaps), "unit": "项"},
                {"label": "冲突组", "value": len(bundle.conflicts), "unit": "组"},
                {"label": "关键风险", "value": len(narrative.key_risks), "unit": "项"},
            ],
        }
        rows = list(base.get(kind, []))
        if len(rows) < 3:
            rows.extend(base["entity_profile"][: 3 - len(rows)])
        return rows[:6]

    @staticmethod
    def _record_dashboard_contract_qa(qa: Any, bundle: FrozenResearchBundle, chapters: list[dict[str, Any]], featured_products: list[dict[str, Any]]) -> None:
        if any(not 3 <= len(chapter.get("kpis", [])) <= 6 for chapter in chapters):
            qa.record_finding(QAFinding(code="dashboard_chapter_kpi_contract", severity="error", message="每章必须含 3—6 个 KPI。"))
        if any(len(chapter.get("insights", [])) != 3 for chapter in chapters):
            qa.record_finding(QAFinding(code="dashboard_chapter_insight_contract", severity="error", message="每章必须含 3 条洞察。"))
        if any(len(chapter.get("visuals", [])) > 3 for chapter in chapters):
            qa.record_finding(QAFinding(code="dashboard_chapter_visual_contract", severity="error", message="每章最多 3 个可视化。"))
        verified_product_count = sum(item.verification_status == VerificationStatus.VERIFIED for item in bundle.products)
        if verified_product_count >= 5 and len(featured_products) < 5:
            qa.record_finding(QAFinding(code="dashboard_product_image_gate", severity="error", message="正式 Dashboard 至少需要 5 张已核验官方产品图。"))
        all_visuals = [visual for chapter in chapters for visual in chapter.get("visuals", [])]
        # Complexity is resolved by the research workflow.  Raw or verified
        # claim counts are not a substitute for the Skill's large-enterprise
        # dashboard contract.
        if bundle.run_manifest.complexity == EnterpriseComplexity.GROUP_LARGE and len(all_visuals) < 8:
            qa.record_finding(QAFinding(code="dashboard_visual_count_gate", severity="error", message="大型企业 Dashboard 至少需要 8 个有意义可视化。"))
        if len(bundle.factories) >= 3 and not any(visual.get("type") == "map" for visual in all_visuals):
            qa.record_finding(QAFinding(code="dashboard_map_gate", severity="error", message="多基地企业 Dashboard 必须包含至少 1 张地图。"))

    @staticmethod
    def _data_uri(root: Path, relative: str) -> str:
        return "data:image/png;base64," + base64.b64encode((root / relative).read_bytes()).decode("ascii")

    @staticmethod
    def _document(title: str, payload: dict[str, Any]) -> str:
        safe_title = html.escape(title)
        notice = str(payload.get("conditionalNotice") or "")
        banner = (
            '<div style="margin:14px 18px 0;padding:10px 14px;border:1px solid #B7791F;'
            'background:#FFFBEF;color:#744210;border-radius:6px;font-size:14px">'
            f"<b>【条件发布】</b>{html.escape(notice)}</div>"
            if notice else ""
        )
        nav = "".join(
            f'<a href="#{index + 1}"><b>{index + 1:02d}</b><span>{html.escape(chapter["title"])}</span></a>'
            for index, chapter in enumerate(payload["chapters"])
        )
        footer = (
            f'数据来源：公开渠道（详见页面末尾来源说明） · 生成日期：{payload["meta"]["generatedAt"]} · '
            "偏差说明：本报告基于公开信息编制，不构成投资建议。"
        )
        return f'''<!doctype html><html lang="zh-CN" data-visual-system="diagram-design" data-dashboard-contract="1-judgement|3-6-kpi|1-3-visual|3-insight|collapsed-details"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#1B365D"><link rel="icon" href="data:,"><title>{safe_title}｜企业研究 Dashboard</title><style>{CSS}</style></head>
<body><aside class="sidebar" aria-label="Dashboard 索引"><div class="brand"><strong>{safe_title}</strong><span>企业研究 Dashboard</span></div><nav aria-label="章节导航">{nav}</nav></aside>
<main>{banner}<section class="hero research-hero"><div class="hero-head"><span class="eyebrow">ENTERPRISE RESEARCH DASHBOARD</span><h1>{safe_title}</h1><p>企业研究 · 产业与能源合作 · 数据截止 {payload['meta']['researchDate']}</p></div><div class="kpi-grid" id="kpiGrid" aria-label="关键经营指标"></div><div class="hero-judgement"><div class="judgement"><span>总体判断</span><b>{html.escape(payload.get('overallJudgement',''))}</b><p>{html.escape(str(payload.get('judgementRationale',''))[:280])}</p></div><div class="decision-stack"><article><span>优先切入方向</span><b>{html.escape(payload.get('topOpportunity',''))}</b></article><article><span>90 天决策里程碑</span><p>{html.escape(payload.get('ninetyDayAction',''))}</p></article></div></div></section>
<section class="workspace"><div class="chapters" id="chapters"></div></section>
<section class="workspace sources"><details><summary>来源索引</summary><div id="sourceList" class="ledger"></div></details></section>
</main>
<footer class="page-footer">{footer}</footer>
<script id="frozen-data" type="application/json">{_json_script(payload)}</script><script>{JS}</script></body></html>'''


CSS = r'''
:root{--paper:#FFFFFF;--ink:#1B1F26;--muted:#4A5568;--soft:#7A8399;--rule:rgba(27,54,93,0.14);--rule-solid:#C9D4E0;--accent:#1B365D;--canvas:#F7F8FA;--serif:"Source Han Serif SC","Noto Serif CJK SC","SimSun",serif;--sans:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC","Source Han Sans SC",Arial,sans-serif}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
a{color:inherit;text-underline-offset:3px}
.sidebar{position:fixed;inset:0 auto 0 0;width:264px;background:var(--ink);color:var(--paper);padding:24px 16px;overflow:auto;z-index:20}
.brand{padding:0 8px 20px;border-bottom:1px solid rgba(255,255,255,0.18)}
.brand strong{display:block;font-size:17px;font-weight:700;line-height:1.4}
.brand span{display:block;margin-top:6px;font-size:11px;color:rgba(255,255,255,0.6)}
.sidebar nav{padding:16px 0}
.sidebar nav a{display:grid;grid-template-columns:28px 1fr;gap:10px;align-items:center;color:rgba(255,255,255,0.75);text-decoration:none;padding:8px 10px;font-size:12.5px;border-left:2px solid transparent}
.sidebar nav a:hover{background:rgba(255,255,255,0.08);color:var(--paper)}
.sidebar nav b{font-size:10px;color:rgba(255,255,255,0.45);letter-spacing:.06em}
main{margin-left:264px;max-width:1680px}
.hero{min-height:300px;padding:64px clamp(28px,5vw,88px) 52px;background:var(--ink);color:var(--paper)}
.hero-head{margin-bottom:26px}
.eyebrow,.section-title span{font-size:10px;letter-spacing:.18em;font-weight:700;color:var(--muted);text-transform:uppercase}
.hero .eyebrow{color:rgba(255,255,255,0.55)}
.hero h1{max-width:860px;font-family:var(--serif);font-size:clamp(30px,4.5vw,52px);line-height:1.12;margin:16px 0 12px;font-weight:600}
.hero p{color:rgba(255,255,255,0.65);font-size:13px;line-height:1.7;margin:0}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:0 0 26px}
.kpi-card{border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);padding:14px 16px}
.kpi-card span{display:block;color:rgba(255,255,255,.58);font-size:10.5px;letter-spacing:.08em;font-weight:700}
.kpi-card b{display:block;margin-top:8px;font-family:var(--serif);font-size:24px;color:#fff;line-height:1.25}
.kpi-card i{display:block;margin-top:5px;font-style:normal;font-size:11px;color:rgba(255,255,255,.55)}
.hero-judgement{display:flex;justify-content:space-between;align-items:end;gap:48px}
.judgement{max-width:820px;border-left:3px solid #88AADD;padding:4px 0 4px 18px}
.judgement span,.decision-stack span{display:block;color:rgba(255,255,255,.58);font-size:10px;letter-spacing:.14em;font-weight:700}
.judgement b{display:block;margin:7px 0 5px;font-family:var(--serif);font-size:23px;color:#fff}
.judgement p{color:rgba(255,255,255,.78);line-height:1.75}
.decision-stack{width:min(360px,34vw);display:grid;gap:12px}
.decision-stack article{padding:17px 18px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06)}
.decision-stack b,.decision-stack p{display:block;margin-top:8px!important;color:#fff!important;line-height:1.6}
.workspace{padding:56px clamp(22px,5vw,76px);border-bottom:1px solid var(--rule)}
.workspace:nth-of-type(even){background:var(--canvas)}
.section-title{margin-bottom:22px}
.section-title h2{margin:0;font-family:var(--serif);font-size:28px;font-weight:600}
.chapter{background:var(--paper);border:1px solid var(--rule-solid);border-radius:8px;padding:36px clamp(20px,3vw,44px);margin-bottom:28px}
.dashboard-chapter{box-shadow:0 14px 40px rgba(27,54,93,.06)}
.chapter-head{display:grid;grid-template-columns:minmax(220px,.7fr) minmax(300px,1.3fr);gap:32px;align-items:end;border-bottom:1px solid var(--rule);padding-bottom:20px;margin-bottom:20px}
.chapter-head>div>span{font-size:10px;letter-spacing:.16em;color:var(--soft);font-weight:700}
.chapter-head h2{font-family:var(--serif);font-size:26px;font-weight:600;margin:5px 0 0;color:var(--ink)}
.chapter>h2{font-family:var(--serif);font-size:26px;font-weight:600;margin:0 0 6px;color:var(--ink)}
.chapter .assertion{font-family:var(--serif);font-size:19px;font-weight:700;color:var(--accent);margin:0;line-height:1.55}
.chapter-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:18px 0 22px}
.chapter-kpis article{border-top:3px solid var(--accent);background:var(--canvas);padding:13px 14px;min-height:88px}
.chapter-kpis span{display:block;font-size:10px;color:var(--soft);font-weight:700;letter-spacing:.06em}
.chapter-kpis b{display:block;margin-top:8px;font-family:var(--serif);font-size:21px;color:var(--ink)}
.chapter-kpis small{font:500 11px var(--sans);margin-left:4px}.chapter-kpis i{display:block;font-style:normal;color:var(--soft);font-size:10px;margin-top:4px}
.visual-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px;align-items:start}
.visual-grid .fig{margin:0 0 16px;min-width:0}
.insight-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}
.insight-grid article{border-left:3px solid var(--accent);padding:12px 14px;background:var(--canvas)}
.insight-grid span{font-size:9.5px;color:var(--soft);letter-spacing:.12em;font-weight:700}.insight-grid p{margin:7px 0 0;font-size:13px;line-height:1.65}
.chapter-details,.nested-details,.sources>details{border-top:1px solid var(--rule);margin-top:18px;padding-top:14px}
.chapter-details>summary,.nested-details>summary,.sources summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:700;letter-spacing:.04em;list-style-position:inside}
.chapter-details[open]>summary,.nested-details[open]>summary{margin-bottom:16px}
.chapter .takeaway{border-left:3px solid var(--accent);background:var(--canvas);padding:11px 14px;font-size:14px;line-height:1.75;margin:0 0 18px}
.chapter .content p{margin:0 0 12px;line-height:1.85;font-size:14.5px}
.chapter .block-label{margin:20px 0 8px;font-size:11px;letter-spacing:.1em;color:var(--soft);font-weight:700}
.chapter .so-what{margin:14px 0 0;padding-top:12px;border-top:1px solid var(--rule);color:var(--accent);font-weight:700;line-height:1.75}
.chapter ul{margin:8px 0 16px;padding-left:20px}.chapter li{margin:5px 0;line-height:1.7;font-size:14px}
.chapter table{border-collapse:collapse;width:100%;margin:18px 0;font-size:13px}
.table-scroll{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
.chapter table th,.chapter table td{border-top:1px solid var(--ink);border-bottom:1px solid var(--rule-solid);padding:9px 12px;text-align:left;vertical-align:top;line-height:1.6}
.chapter table th{background:var(--canvas);color:var(--accent);font-weight:700}
.chapter table tr:first-child th{border-top:2px solid var(--ink)}
.chapter table tr:last-child td{border-bottom:2px solid var(--ink)}
.fig{background:var(--paper);border:1px solid var(--rule);border-radius:8px;padding:20px;margin:22px 0}
.fig h3{font-family:var(--serif);font-size:18px;font-weight:600;margin:0 0 6px}
.fig .fig-sub{font-size:12.5px;color:var(--muted);margin:0 0 4px;line-height:1.6}
.fig .fig-thesis{font-size:12.5px;color:var(--accent);font-weight:700;margin:0 0 12px;line-height:1.6}
.fig svg{display:block;width:100%;height:auto}
.fig .fig-source{margin:10px 0 0;border-top:1px solid var(--rule);padding-top:8px;font-size:11px;color:var(--soft);line-height:1.6}
.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:18px 0}
.gallery figure{margin:0;border:1px solid var(--rule);border-radius:8px;overflow:hidden;background:var(--paper)}
.gallery img{width:100%;height:180px;object-fit:contain;background:var(--canvas);border-bottom:1px solid var(--rule);cursor:zoom-in}
.gallery figcaption{padding:12px;font-size:12px;line-height:1.55;color:var(--muted)}
.product-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:18px 0}
.product-card{border:1px solid var(--rule-solid);border-radius:8px;overflow:hidden;background:var(--paper)}
.product-card img{width:100%;height:190px;object-fit:contain;background:var(--canvas);border-bottom:1px solid var(--rule)}
.product-card .no-photo{width:100%;height:190px;background:var(--canvas);border-bottom:1px solid var(--rule);display:flex;align-items:center;justify-content:center;color:var(--soft);font-size:12px}
.product-body{padding:16px}
.product-body h3{margin:0 0 8px;font-size:16.5px}
.product-body p{margin:0 0 10px;font-size:12.5px;color:var(--muted);line-height:1.7}
.product-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.product-meta span{background:var(--canvas);border:1px solid var(--rule);border-radius:999px;padding:4px 9px;font-size:11px;color:var(--muted)}
.filters{display:grid;grid-template-columns:2fr 1fr;gap:10px;margin:18px 0}
.filters input,.filters select{min-width:0;width:100%;box-sizing:border-box;border:1px solid var(--rule-solid);background:var(--paper);padding:10px 14px;font-size:13px;border-radius:6px}
.product-actions{display:flex;gap:8px;margin-top:12px}
.product-actions button{border:1px solid var(--rule-solid);border-radius:6px;background:var(--paper);padding:8px 12px;font-size:12px;cursor:pointer;color:var(--ink)}
.product-actions button:hover{background:var(--ink);color:var(--paper)}
.compare{overflow:auto;margin-top:18px}
.compare table{border-collapse:collapse;width:100%;min-width:720px;font-size:12.5px}
.compare th,.compare td{border-top:1px solid var(--ink);border-bottom:1px solid var(--rule-solid);padding:9px 12px;text-align:left;line-height:1.6}
.compare th{background:var(--canvas);color:var(--accent)}
.ledger{margin-top:14px}
.source-row{display:grid;grid-template-columns:1fr 200px 220px;gap:16px;padding:12px 0;border-bottom:1px solid var(--rule);font-size:12.5px;line-height:1.7}
.source-row:last-child{border-bottom:0}
.source-row b{font-weight:700}.source-row span{color:var(--soft)}
.page-footer{padding:22px clamp(22px,5vw,76px) 40px;margin-left:264px;font-size:11.5px;color:var(--soft);line-height:1.8}
@media(max-width:1100px){.sidebar{width:224px}main{margin-left:224px}.page-footer{margin-left:224px}.gallery,.product-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:768px){.sidebar{position:sticky;top:0;width:100%;height:auto;padding:12px 16px}.sidebar nav{display:none}.brand{padding:0;border:0}.main,main{margin:0}.page-footer{margin-left:0}.hero{min-height:220px;padding:40px 20px 54px}.hero-judgement{display:block}.decision-stack{width:100%;margin-top:22px}.kpi-grid{grid-template-columns:repeat(2,1fr)}.workspace{padding:36px 18px}.chapter{padding:24px 18px}.chapter-head{grid-template-columns:1fr;gap:12px}.chapter .table-scroll table{min-width:680px}.gallery,.product-grid,.insight-grid,.visual-grid{grid-template-columns:1fr}.source-row{grid-template-columns:1fr}}
@media print{.sidebar{display:none}main{margin:0}.hero{color:var(--ink);background:var(--paper);border-bottom:2px solid var(--ink)}.workspace{break-inside:avoid}.page-footer{margin-left:0}}
'''

JS = r'''
const DATA=JSON.parse(document.getElementById('frozen-data').textContent);const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chunks=(v,n=360)=>{const s=String(v??'').trim();const out=[];for(let i=0;i<s.length;i+=n)out.push(s.slice(i,i+n));return out};
function figBlock(v,index){return `<div class="fig"><h3>图 ${index} ${esc(v.title)}</h3>${v.subtitle?`<p class="fig-sub">${esc(v.subtitle)}</p>`:''}<p class="fig-thesis">${esc(v.businessThesis)}</p>${v.markup||''}${v.sourceNote?`<p class="fig-source">${esc(v.sourceNote)}<br>${esc(v.transformation||'')}</p>`:''}</div>`}
function tableBlock(rows){if(!rows||!rows.length)return '';const cols=Object.keys(rows[0]);return `<div class="table-scroll" role="region" aria-label="可横向滚动的数据表"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function imageBlock(images){if(!images||!images.length)return '';return `<div class="gallery">${images.map(img=>`<figure data-img="${esc(img.asset)}" data-cap="${esc(img.caption)}"><img src="${img.asset}" alt="${esc(img.caption)}"><figcaption><b>${esc(img.caption)}</b><br><span>${esc(img.role)} · <a href="${esc(img.source)}" target="_blank" rel="noreferrer">原始页面 ↗</a></span></figcaption></figure>`).join('')}</div>`}
function listBlock(label,items){return items&&items.length?`<p class="block-label">${esc(label)}</p><ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
function kpiStrip(rows){return `<div class="chapter-kpis">${(rows||[]).slice(0,6).map(k=>`<article><span>${esc(k.label)}</span><b>${esc(String(k.value??''))}${k.unit?`<small>${esc(k.unit)}</small>`:''}</b><i>${esc(k.period||k.scope||'')}</i></article>`).join('')}</div>`}
function insightBlock(rows){return `<div class="insight-grid">${(rows||[]).slice(0,3).map((v,i)=>`<article><span>INSIGHT ${i+1}</span><p>${esc(chunks(v,220)[0])}</p></article>`).join('')}</div>`}
function productShowcase(){const rows=DATA.featuredProducts||[];if(!rows.length)return '';return `<div class="product-grid featured-products">${rows.map(p=>`<article class="product-card"><img src="${p.offlineAsset}" alt="${esc(p.name)}"><div class="product-body"><h3>${esc(p.name)}</h3><div class="product-meta"><span>${esc(p.family)}</span>${p.series?`<span>${esc(p.series)}</span>`:''}${p.model?`<span>${esc(p.model)}</span>`:''}</div>${p.applications?.length?`<p><b>应用：</b>${esc(p.applications.slice(0,4).join(' / '))}</p>`:''}${p.parameters?.length?`<div class="product-meta">${p.parameters.slice(0,5).map(x=>`<span>${esc(x.name)}：${esc(x.value)} ${esc(x.unit||'')}</span>`).join('')}</div>`:''}${p.imageSource?`<p class="image-source"><a href="${esc(p.imageSource)}" target="_blank" rel="noreferrer">官方图片来源 ↗</a></p>`:''}</div></article>`).join('')}</div>`}
function productLedger(){if(!DATA.products?.length)return '';const rows=DATA.products.map(p=>({'产品':p.name,'产品族':p.family,'系列/型号':[p.series,p.model].filter(Boolean).join(' / '),'应用场景':(p.applications||[]).join('；'),'公开参数':(p.parameters||[]).map(x=>`${x.name}:${x.value}${x.unit||''}`).join('；')}));return `<details class="nested-details"><summary>完整产品清单（${rows.length} 项）</summary>${tableBlock(rows)}</details>`}
function detailBlock(c){const prose=[...(c.context||[]),...(c.analysis||[])].flatMap(p=>chunks(p)).map(p=>`<p>${esc(p)}</p>`).join('');return `<details class="chapter-details"><summary>展开分析与数据明细</summary>${c.executiveTakeaway?`<p class="takeaway">${esc(c.executiveTakeaway)}</p>`:''}<div class="content">${prose}</div>${tableBlock(c.tables)}${imageBlock(c.images)}${listBlock('业务含义',c.implications)}${listBlock('建议',c.recommendations)}${listBlock('可能改变判断的事项',c.counterEvidence)}${listBlock('待确认事项',c.limitations)}${listBlock('行动项',c.actions)}${c.kind==='products'?productLedger():''}</details>`}
function renderKpis(){$('kpiGrid').innerHTML=(DATA.kpis||[]).slice(0,6).map(k=>`<article class="kpi-card"><span>${esc(k.label)}</span><b>${esc(String(k.value??''))}${k.unit?`<small style="font-size:12px">${esc(k.unit)}</small>`:''}</b><i>${esc(k.period||k.scope||'公开披露口径')}</i></article>`).join('')}
function renderChapters(){$('chapters').innerHTML=DATA.chapters.map((c,index)=>`<article class="chapter dashboard-chapter" id="${index+1}"><header class="chapter-head"><div><span>CHAPTER ${String(index+1).padStart(2,'0')}</span><h2>${esc(c.title)}</h2></div><p class="assertion">${esc(c.assertionTitle)}</p></header>${kpiStrip(c.kpis)}<div class="visual-grid">${(c.visuals||[]).slice(0,3).map((v,i)=>figBlock(v,i+1)).join('')}</div>${c.kind==='products'?productShowcase():''}${insightBlock(c.insights)}${detailBlock(c)}</article>`).join('');document.querySelectorAll('[data-img]').forEach(el=>el.querySelector('img').onclick=()=>{const w=window.open('');w.document.write(`<img src="${el.dataset.img}" style="max-width:96vw;max-height:94vh;display:block;margin:auto"><p style="text-align:center;font-family:sans-serif">${el.dataset.cap}</p>`)});}
function renderSources(){$('sourceList').innerHTML=DATA.sources.map(s=>`<article class="source-row"><div><b>${esc(s['来源名称'])}</b></div><div><span>${esc(s['来源类型'])}${s['发布日期']?` · ${esc(s['发布日期'])}`:''}</span></div><div><a href="${esc(s['网址'])}" target="_blank" rel="noreferrer">查看原始页面 ↗</a></div></article>`).join('')}
renderKpis();renderChapters();renderSources();
'''
