"""HTML renderer (P0 refactor): narrative-driven dashboard, inline diagram-design SVG.

One page per frozen bundle.  Chapter structure comes from the SAME
ResearchNarrative as the Word report; figures are the SAME diagram-design
SVGs (inline here, PNG-exported for Word).  There is no second charting
implementation, no fixed 18-section navigation, no group-evidence-register
chapter, and no renderer/QA text in the user-facing page.

Verified products appear in the product matrix even when no photo passed
the publication gate (image-less products keep their name, model,
parameters and source references).
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
from enterprise_energy_research.artifacts.qa_report import QAFinding, QAVisualEntry, new_qa_report, write_qa_report
from enterprise_energy_research.artifacts.visuals import write_visual_manifest
from enterprise_energy_research.domain.enums import ArtifactType, VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.research.synthesis import ResearchSynthesizer
from enterprise_energy_research.vendor import embedded_skill_root
from enterprise_energy_research.validation.consulting_narrative import (
    ConsultingNarrativeValidator, VisualSemanticValidator, write_consulting_validation,
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
        content, claims, images = self._unified_page(bundle, binding, output_path)
        digest = _write(output_path, content)
        return ArtifactResult(
            adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
            path=output_path, content_sha256=digest, used_claim_ids=claims, used_image_ids=images, status="published",
        )

    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        return next((item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id), bundle.entities[0] if bundle.entities else None)

    def _unified_page(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> tuple[str, list[str], list[str]]:
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
        narrative_validation = ConsultingNarrativeValidator().validate(narrative)
        write_consulting_validation(narrative_validation, asset_root / "consulting_narrative_validation.json")
        for check in narrative_validation.checks:
            if check.status == "FAIL":
                qa.record_finding(QAFinding(code=check.code, severity="error", message=check.message))

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
        write_qa_report(qa, asset_root / "publication_qa_report.json")

        extra_roots = [self.asset_root] if self.asset_root else []
        image_manifest = prepare_publication_images(bundle, binding, asset_root, extra_search_roots=extra_roots)
        prepared = {item.image_id: item for item in image_manifest.prepared_images}
        used_image_ids = sorted({image_id for chapter in narrative.chapters for image_id in chapter.image_ids if image_id in prepared})
        image_manifest = image_manifest.model_copy(update={"artifact_selections": {"html": used_image_ids}})
        write_image_publication_manifest(image_manifest, asset_root)

        # ── products: VERIFIED products always appear; photos are optional ──
        products = []
        for product in bundle.products:
            if product.verification_status != VerificationStatus.VERIFIED:
                continue
            bound_image_id = narrative.product_images.get(product.product_id) or product.image_id
            publication = prepared.get(bound_image_id or "")
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

        chapters_payload = [
            {
                "id": chapter.chapter_id, "kind": chapter.kind, "title": chapter.title,
                "assertionTitle": chapter.assertion_title,
                "executiveTakeaway": chapter.executive_takeaway,
                "context": chapter.context_paragraphs,
                "analysis": chapter.analysis_paragraphs,
                "implications": chapter.implications,
                "recommendations": chapter.recommendations,
                "counterEvidence": chapter.counter_evidence,
                "limitations": chapter.limitations,
                "actions": chapter.action_items,
                "tables": chapter.table_rows,
                "visuals": [inline_visuals[visual_id] for visual_id in chapter.visual_ids if visual_id in inline_visuals],
                "images": [item for item in gallery if item["chapter"] == chapter.chapter_id],
            }
            for chapter in narrative.chapters
        ]

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
            "sources": narrative.appendices.source_ledger,
            "meta": {
                "freeze": bundle.freeze.freeze_id,
                "rootHash": bundle.freeze.root_hash,
                "researchDate": bundle.freeze.created_at.date().isoformat(),
                "generatedAt": narrative.generated_at[:10],
                "counts": narrative.counts,
            },
        }
        return self._document(entity.canonical_name, payload), [item.claim_id for item in bundle.claims if item.verification_status == VerificationStatus.VERIFIED], used_image_ids

    @staticmethod
    def _data_uri(root: Path, relative: str) -> str:
        return "data:image/png;base64," + base64.b64encode((root / relative).read_bytes()).decode("ascii")

    @staticmethod
    def _document(title: str, payload: dict[str, Any]) -> str:
        safe_title = html.escape(title)
        nav = "".join(
            f'<a href="#{index + 1}"><b>{index + 1:02d}</b><span>{html.escape(chapter["title"])}</span></a>'
            for index, chapter in enumerate(payload["chapters"])
        )
        footer = (
            f'数据来源：公开渠道（详见页面末尾来源说明） · 生成日期：{payload["meta"]["generatedAt"]} · '
            "偏差说明：本报告基于公开信息编制，不构成投资建议。"
        )
        return f'''<!doctype html><html lang="zh-CN" data-visual-system="diagram-design"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#1B365D"><link rel="icon" href="data:,"><title>{safe_title}｜企业产业与能源合作调研</title><style>{CSS}</style></head>
<body><aside class="sidebar" aria-label="报告索引"><div class="brand"><strong>{safe_title}</strong><span>企业产业与能源合作调研</span></div><nav aria-label="章节导航">{nav}</nav></aside>
<main><section class="hero research-hero"><div class="hero-head"><span class="eyebrow">ENTERPRISE RESEARCH DASHBOARD</span><h1>{safe_title}</h1><p>企业研究 · 产业与能源合作 · 数据截止 {payload['meta']['researchDate']}</p></div><div class="kpi-grid" id="kpiGrid" aria-label="关键经营指标"></div><div class="hero-judgement"><div class="judgement"><span>总体判断</span><b>{html.escape(payload.get('overallJudgement',''))}</b><p>{html.escape(payload.get('judgementRationale',''))}</p></div><div class="decision-stack"><article><span>优先切入方向</span><b>{html.escape(payload.get('topOpportunity',''))}</b></article><article><span>90 天决策里程碑</span><p>{html.escape(payload.get('ninetyDayAction',''))}</p></article></div></div></section>
<section class="workspace"><div class="chapters" id="chapters"></div></section>
<section class="workspace sources"><header class="section-title"><h2>来源与方法</h2></header><div id="sourceList" class="ledger"></div></section>
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
.chapter>h2{font-family:var(--serif);font-size:26px;font-weight:600;margin:0 0 6px;color:var(--ink)}
.chapter .assertion{font-family:var(--serif);font-size:19px;font-weight:700;color:var(--accent);margin:0 0 16px;line-height:1.55}
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
@media(max-width:768px){.sidebar{position:sticky;top:0;width:100%;height:auto;padding:12px 16px}.sidebar nav{display:none}.brand{padding:0;border:0}.main,main{margin:0}.page-footer{margin-left:0}.hero{min-height:220px;padding:40px 20px 54px}.hero-judgement{display:block}.decision-stack{width:100%;margin-top:22px}.kpi-grid{grid-template-columns:repeat(2,1fr)}.workspace{padding:36px 18px}.chapter{padding:24px 18px}.chapter .table-scroll table{min-width:680px}.gallery,.product-grid{grid-template-columns:1fr}.source-row{grid-template-columns:1fr}}
@media print{.sidebar{display:none}main{margin:0}.hero{color:var(--ink);background:var(--paper);border-bottom:2px solid var(--ink)}.workspace{break-inside:avoid}.page-footer{margin-left:0}}
'''

JS = r'''
const DATA=JSON.parse(document.getElementById('frozen-data').textContent);const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function figBlock(v,index){const items=v.markup||'';return `<div class="fig"><h3>图 ${index} ${esc(v.title)}</h3>${v.subtitle?`<p class="fig-sub">${esc(v.subtitle)}</p>`:''}<p class="fig-thesis">${esc(v.businessThesis)}</p>${items}${v.sourceNote?`<p class="fig-source">${esc(v.sourceNote)}<br>${esc(v.transformation||'')}</p>`:''}</div>`}
function tableBlock(rows){if(!rows||!rows.length)return '';const cols=Object.keys(rows[0]);return `<div class="table-scroll" role="region" aria-label="可横向滚动的数据表"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function imageBlock(images){if(!images||!images.length)return '';return `<div class="gallery">${images.map(img=>`<figure data-img="${esc(img.asset)}" data-cap="${esc(img.caption)}"><img src="${img.asset}" alt="${esc(img.caption)}"><figcaption><b>${esc(img.caption)}</b><br><span>${esc(img.role)} · <a href="${esc(img.source)}" target="_blank" rel="noreferrer">原始页面 ↗</a></span></figcaption></figure>`).join('')}</div>`}
function productBlock(products){return `<div class="filters"><input id="productSearch" placeholder="搜索产品、品牌、型号"><select id="categoryFilter"><option value="">全部产品族</option></select></div><div class="product-grid" id="productGrid"></div><p class="muted">最多 4 项对比</p><div class="compare" id="comparePanel"></div>`}
function renderProducts(){let rows=DATA.products;const q=$('productSearch').value.toLowerCase();rows=rows.filter(p=>JSON.stringify(p).toLowerCase().includes(q)&&(!$('categoryFilter').value||(p.family||'未分类')===$('categoryFilter').value));$('productGrid').innerHTML=rows.map(p=>`<article class="product-card">${p.offlineAsset?`<img src="${p.offlineAsset}" alt="${esc(p.name)}">`:`<div class="no-photo">产品图片待补充（不影响产品记录发布）</div>`}<div class="product-body"><h3>${esc(p.name)}</h3><p>${esc(p.description||'')}</p><div class="product-meta"><span>${esc(p.brand||'品牌待核验')}</span><span>${esc(p.model||'型号待核验')}</span><span>${esc(p.family)}</span>${p.series?`<span>${esc(p.series)}</span>`:''}</div>${p.parameters.length?`<div class="product-meta" style="margin-top:8px">${p.parameters.map(x=>`<span>${esc(x.name)}：${esc(x.value)} ${esc(x.unit||'')}</span>`).join('')}</div>`:''}<div class="product-actions"><button data-compare="${esc(p.id)}">${selected.includes(p.id)?'已加入':'加入对比'}</button></div></div></article>`).join('')||'<article class="chapter"><p>暂无满足核验门禁的产品记录。</p></article>';document.querySelectorAll('[data-compare]').forEach(b=>b.onclick=()=>{const id=b.dataset.compare;if(selected.includes(id))selected=selected.filter(x=>x!==id);else if(selected.length<4)selected.push(id);renderProducts();compare()})}
function compare(){const rows=selected.map(id=>DATA.products.find(p=>p.id===id)).filter(Boolean);$('comparePanel').innerHTML=rows.length?`<table><thead><tr><th>字段</th>${rows.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody><tr><td>产品族</td>${rows.map(p=>`<td>${esc(p.family)}</td>`).join('')}</tr><tr><td>型号</td>${rows.map(p=>`<td>${esc(p.model||'待核验')}</td>`).join('')}</tr><tr><td>参数</td>${rows.map(p=>`<td>${p.parameters.map(x=>`${esc(x.name)}：${esc(x.value)} ${esc(x.unit||'')}`).join('<br>')||'待核验'}</td>`).join('')}</tr></tbody></table>`:''}
function listBlock(label,items){return items&&items.length?`<p class="block-label">${esc(label)}</p><ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
function renderKpis(){$('kpiGrid').innerHTML=(DATA.kpis||[]).slice(0,6).map(k=>`<article class="kpi-card"><span>${esc(k.label)}</span><b>${esc(String(k.value??''))}${k.unit?`<small style="font-size:12px">${esc(k.unit)}</small>`:''}</b><i>${esc(k.period||k.scope||'公开披露口径')}</i></article>`).join('')}
function renderChapters(){$('chapters').innerHTML=DATA.chapters.map((c,index)=>{const extra=c.kind==='products'?productBlock(c):'';const prose=[...(c.context||[]),...(c.analysis||[])];return `<article class="chapter" id="${index+1}"><h2>${String(index+1).padStart(2,'0')} ${esc(c.title)}</h2><p class="assertion">${esc(c.assertionTitle)}</p>${c.executiveTakeaway?`<p class="takeaway">${esc(c.executiveTakeaway)}</p>`:''}<div class="content">${prose.map(p=>`<p>${esc(p)}</p>`).join('')}</div>${tableBlock(c.tables)}${c.visuals.map((v,i)=>figBlock(v,i+1)).join('')}${imageBlock(c.images)}${listBlock('业务含义',c.implications)}${listBlock('建议',c.recommendations)}${listBlock('反向证据',c.counterEvidence)}${listBlock('局限与待确认',c.limitations)}${listBlock('行动项',c.actions)}${c.implications&&c.implications.length?`<p class="so-what">${esc(c.implications[0])}</p>`:''}${extra}</article>`}).join('');if(DATA.products.length){const cats=[...new Set(DATA.products.map(p=>p.family||'未分类'))];$('categoryFilter').innerHTML+=cats.sort().map(c=>`<option>${esc(c)}</option>`).join('');$('productSearch').oninput=renderProducts;$('categoryFilter').onchange=renderProducts;renderProducts()}document.querySelectorAll('[data-img]').forEach(el=>el.querySelector('img').onclick=()=>{const w=window.open('');w.document.write(`<img src="${el.dataset.img}" style="max-width:96vw;max-height:94vh;display:block;margin:auto"><p style="text-align:center;font-family:sans-serif">${el.dataset.cap}</p>`)});}
const selected=[];
function renderSources(){$('sourceList').innerHTML=DATA.sources.map(s=>`<article class="source-row"><div><b>${esc(s['来源名称'])}</b></div><div><span>${esc(s['来源类型'])}${s['发布日期']?` · ${esc(s['发布日期'])}`:''}</span></div><div><a href="${esc(s['网址'])}" target="_blank" rel="noreferrer">查看原始页面 ↗</a></div></article>`).join('')}
renderKpis();renderChapters();renderSources();
'''
