from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.artifacts.image_publication import prepare_publication_images, write_image_publication_manifest
from enterprise_energy_research.artifacts.visuals import build_visual_manifest, render_visual_bundle, write_visual_manifest
from enterprise_energy_research.domain.enums import ArtifactType, VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.vendor import embedded_skill_root


FIELD_LABELS = {
    "canonical_company_name": "公司名称", "stock_code": "股票代码", "core_business": "核心业务",
    "revenue": "营业收入", "profit": "净利润", "employees": "员工", "employee_count": "员工",
    "capacity": "产能", "electricity_consumption": "年度用电量", "roof_area": "可用屋面面积",
}


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
        available = (self.skill_root / "SKILL.md").is_file() and (self.skill_root / "LICENSE.txt").is_file()
        return AdapterHealth(name=self.name, available=available, version="embedded", diagnostics=[] if available else ["Embedded frontend-design instructions or license are missing"])

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
        asset_root = output_path.parent / f"{output_path.stem}_assets"
        visual_manifest = build_visual_manifest(bundle, binding)
        write_visual_manifest(visual_manifest, asset_root / "visual_manifest.json")
        visual_assets = asset_root / "figures"
        inline_visuals: dict[str, str] = {}
        for visual in visual_manifest.visuals:
            _, svg_path = render_visual_bundle(visual, visual_assets)
            inline_visuals[visual.visual_id] = svg_path.read_text(encoding="utf-8")
        extra_roots = [self.asset_root] if self.asset_root else []
        image_manifest = prepare_publication_images(bundle, binding, asset_root, extra_search_roots=extra_roots)
        image_manifest = image_manifest.model_copy(update={"artifact_selections": {"html": image_manifest.prepared_image_ids}})
        write_image_publication_manifest(image_manifest, asset_root)
        prepared = {item.image_id: item for item in image_manifest.prepared_images}
        verified_claims = [item for item in bundle.claims if item.claim_id in binding.claim_ids and item.verification_status == VerificationStatus.VERIFIED]
        sources = {item.source_id: item for item in bundle.sources}
        claims = [{
            "id": item.claim_id, "field": FIELD_LABELS.get(item.field_name, item.field_name), "fieldKey": item.field_name,
            "value": item.value, "unit": item.unit, "asOf": item.as_of_date.isoformat() if item.as_of_date else None,
            "sourceId": item.source_id, "source": sources[item.source_id].source_title or sources[item.source_id].source_domain,
            "url": str(sources[item.source_id].canonical_url), "level": sources[item.source_id].source_level.value, "quote": item.raw_text,
        } for item in verified_claims]
        products = []
        missing_product_images: list[str] = []
        for product in bundle.products:
            if product.verification_status != VerificationStatus.VERIFIED:
                continue
            publication = prepared.get(product.image_id or "")
            if publication is None:
                missing_product_images.append(product.product_id)
                continue
            products.append({
                "id": product.product_id, "name": product.name, "brand": product.brand, "model": product.model,
                "family": product.category or "未分类", "series": product.category or "未披露系列",
                "description": product.description or "公开资料未披露产品说明", "applications": [],
                "parameters": [item.model_dump(mode="json") for item in product.parameters],
                "imageId": product.image_id, "offlineAsset": self._data_uri(asset_root, publication.publication_path) if publication else None,
                "imageSource": publication.source_page_url if publication else None,
                "evidenceStatus": product.verification_status.value, "sourceIds": product.source_ids,
            })
        if missing_product_images:
            raise ValueError("Unified formal HTML requires 100% archived product-image coverage: " + ", ".join(missing_product_images))
        gallery = [{
            "id": item.image_id, "role": item.image_type, "entityId": item.entity_id, "factoryId": item.factory_id,
            "productId": item.product_id, "caption": item.caption, "source": item.source_page_url,
            "asset": self._data_uri(asset_root, item.publication_path),
        } for item in image_manifest.prepared_images]
        children = [{"from": edge.from_id, "to": edge.to_id, "relation": edge.relation, "status": edge.verification_status.value} for edge in bundle.edges]
        visuals = [{
            "id": item.visual_id, "chapter": item.chapter_key, "title": item.title, "purpose": item.purpose,
            "family": item.family, "type": item.canonical_type, "class": item.visual_class,
            "renderer": item.renderer, "templateId": item.template_id, "templateName": item.template_name,
            "templateSource": item.template_source, "templateCardTitle": item.template_card_title,
            "colorSystem": item.color_system,
            "templateCandidates": item.template_candidates, "templateRationale": item.template_rationale,
            "items": [datum.model_dump(mode="json") for datum in item.items], "claimIds": item.source_claim_ids,
            "sourceIds": item.source_ids, "sourceNote": item.source_note, "transformation": item.transformation,
            "markup": inline_visuals[item.visual_id],
        } for item in visual_manifest.visuals if "html" in item.artifact_targets]
        high_priority = [item for item in bundle.solutions if str(item.priority).upper() in {"HIGH", "P0", "P1", "A", "1"}]
        insights = [item.opportunity for item in high_priority[:3]] or [item.opportunity for item in bundle.solutions[:3]]
        insights.extend([
            f"当前冻结版本含 {len(verified_claims)} 条已核验主张与 {len(bundle.sources)} 个来源。",
            f"仍有 {len(bundle.gaps)} 项数据缺口，正式投资决策前须完成现场尽调。",
        ])
        payload = {
            "entity": {"id": entity.entity_id, "name": entity.canonical_name, "type": entity.entity_type, "region": entity.registration_region, "website": str(entity.official_website or ""), "status": entity.verification_status.value},
            "entities": [{"id": item.entity_id, "name": item.canonical_name, "type": item.entity_type, "status": item.verification_status.value} for item in bundle.entities],
            "factories": [{"id": item.factory_id, "name": item.name or "未命名基地", "address": item.address, "processes": item.processes} for item in bundle.factories],
            "edges": children, "claims": claims, "products": products, "gallery": gallery, "visuals": visuals,
            "gaps": [{"field": FIELD_LABELS.get(item.field_name, item.field_name), "importance": item.importance, "reason": item.reason, "next": item.next_action} for item in bundle.gaps],
            "solutions": [{"engine": item.engine, "opportunity": item.opportunity, "solution": item.proposed_solution, "priority": item.priority, "type": item.statement_type.value, "claims": item.claim_ids, "assumptions": item.assumptions} for item in bundle.solutions],
            "sources": [{"id": item.source_id, "title": item.source_title or item.source_domain, "domain": item.source_domain, "level": item.source_level.value, "url": str(item.canonical_url)} for item in bundle.sources],
            "insights": insights[:5],
            "meta": {"freeze": bundle.freeze.freeze_id, "rootHash": bundle.freeze.root_hash, "researchDate": bundle.freeze.created_at.date().isoformat(), "complexity": bundle.run_manifest.complexity.value if bundle.run_manifest.complexity else "UNKNOWN"},
        }
        return self._document(entity.canonical_name, payload), [item.claim_id for item in verified_claims], image_manifest.prepared_image_ids

    @staticmethod
    def _data_uri(root: Path, relative: str) -> str:
        return "data:image/png;base64," + base64.b64encode((root / relative).read_bytes()).decode("ascii")

    @staticmethod
    def _document(title: str, payload: dict[str, Any]) -> str:
        safe_title = html.escape(title)
        nav = "".join(f'<a href="#{key}"><b>{index:02d}</b><span>{label}</span></a>' for index, (key, label) in enumerate(NAV_ITEMS, 1))
        return f'''<!doctype html><html lang="zh-CN" data-visual-system="lieflat-mono"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#1C1C1A"><link rel="icon" href="data:,"><title>{safe_title}｜企业研究决策驾驶舱</title><style>{CSS}</style></head>
<body data-color-system="mono"><aside class="sidebar" aria-label="报告索引"><div class="brand"><strong>SEVC</strong><span>RESEARCH INTELLIGENCE</span></div><nav aria-label="章节导航">{nav}</nav><div class="freeze">FREEZE<br><code>{html.escape(payload['meta']['freeze'])}</code></div></aside>
<main><section id="overview" class="hero"><div><span class="eyebrow">EVIDENCE-FIRST ENTERPRISE RESEARCH</span><h1>{safe_title}</h1><p>{html.escape(payload['entity']['type'])} · {html.escape(payload['entity']['region'] or '区域待核验')} · 研究日期 {payload['meta']['researchDate']}</p></div><div class="coverage"><b>{len(payload['claims'])}</b><span>VERIFIED CLAIMS</span><small>{len(payload['sources'])} SOURCES · {len(payload['gaps'])} GAPS</small></div></section>
<section class="workspace"><div id="kpis" class="kpis"></div><article class="panel insight"><header><span>EXECUTIVE INSIGHT</span><h2>是否值得合作，以及从哪里切入</h2></header><ol id="insights"></ol></article><div class="visual-grid" data-chapter="research_scope"></div></section>
<section id="company" class="workspace"><header class="section-title"><b>02</b><div><span>COMPANY PROFILE</span><h2>企业画像</h2></div></header><div id="companyProfile" class="split"></div><div id="gallery" class="gallery"></div><div class="visual-grid" data-chapter="appendix_images"></div></section>
<section id="organization" class="workspace"><header class="section-title"><b>03</b><div><span>ENTITY REGISTER</span><h2>集团与成员证据名录</h2></div></header><p class="section-deck">成员实体按冻结证据逐条列示；本页不使用关系图、层级图或推测性连接。</p><div id="entityRegister" class="entity-register"></div></section>
<section id="operations" class="workspace"><header class="section-title"><b>04</b><div><span>OPERATIONS</span><h2>经营与产业</h2></div></header><div class="visual-grid" data-chapter="operating_metrics"></div></section>
<section id="factories" class="workspace"><header class="section-title"><b>05</b><div><span>FACTORY FOOTPRINT</span><h2>子公司与工厂</h2></div></header><div id="factoryGrid" class="card-grid"></div><div class="visual-grid" data-chapter="factories"></div></section>
<section id="product-matrix" class="workspace"><header class="section-title"><b>06</b><div><span>PRODUCT MATRIX</span><h2>产品矩阵</h2></div></header><div class="visual-grid" data-chapter="products"></div></section>
<section id="products" class="workspace"><header class="section-title"><b>07</b><div><span>PRODUCT INTELLIGENCE</span><h2>产品数据库</h2></div></header><div class="filters"><input id="productSearch" placeholder="搜索产品、品牌、型号、参数"><select id="categoryFilter"><option value="">全部产品族</option></select><select id="sortProducts"><option value="name">按名称</option><option value="model">按型号</option></select><button id="clearCompare">清空对比</button></div><p id="productCount" class="muted"></p><div id="productGrid" class="product-grid"></div><div id="comparePanel" class="compare"></div></section>
<section id="energy" class="workspace"><header class="section-title"><b>08</b><div><span>ENERGY PROFILE</span><h2>能源画像</h2></div></header><div class="visual-grid" data-chapter="energy"></div></section>
<section id="efficiency" class="workspace"><header class="section-title"><b>09</b><div><span>EFFICIENCY</span><h2>节能潜力</h2></div></header><div class="visual-grid" data-chapter="zero_carbon"></div></section>
<section id="pv" class="workspace"><header class="section-title"><b>10</b><div><span>SOLAR</span><h2>光伏机会</h2></div></header><div class="evidence-boundary">仅在冻结证据或显式场景测算存在时展示数值；场景测算不构成投资承诺。</div></section>
<section id="storage" class="workspace"><header class="section-title"><b>11</b><div><span>STORAGE</span><h2>储能机会</h2></div></header><div class="visual-grid" data-chapter="storage_odm"></div></section>
<section id="epc" class="workspace"><header class="section-title"><b>12</b><div><span>INTEGRATED ENERGY / EPC</span><h2>综合能源与 EPC</h2></div></header><div class="visual-grid" data-chapter="epc"></div></section>
<section id="carbon" class="workspace"><header class="section-title"><b>13</b><div><span>ZERO CARBON</span><h2>零碳与能碳</h2></div></header><div class="visual-grid" data-chapter="core_evidence"></div></section>
<section id="opportunities" class="workspace"><header class="section-title"><b>14</b><div><span>OPPORTUNITY MATRIX</span><h2>合作机会矩阵</h2></div></header><div id="solutionGrid" class="card-grid"></div><div class="visual-grid" data-chapter="cooperation"></div></section>
<section id="business-model" class="workspace"><header class="section-title"><b>15</b><div><span>COMMERCIAL MODEL</span><h2>商务模式</h2></div></header><div class="visual-grid" data-chapter="overseas"></div></section>
<section id="roadmap" class="workspace"><header class="section-title"><b>16</b><div><span>90-DAY ROADMAP</span><h2>90 天推进路径</h2></div></header><div class="visual-grid" data-chapter="roadmap"></div></section>
<section id="risks" class="workspace"><header class="section-title"><b>17</b><div><span>RISK & EVIDENCE</span><h2>风险与证据</h2></div></header><div id="gapGrid" class="card-grid"></div><div class="visual-grid" data-chapter="risks"></div></section>
<section id="sources" class="workspace"><header class="section-title"><b>18</b><div><span>SOURCE LEDGER</span><h2>数据来源</h2></div></header><div class="visual-grid" data-chapter="appendix_sources"></div><input id="claimSearch" class="wide-search" placeholder="筛选字段、取值、来源、claim_id"><div id="claimList" class="ledger"></div></section>
</main><dialog id="detailDialog"><button class="close" aria-label="关闭">×</button><div id="dialogBody"></div></dialog><dialog id="lightbox"><button class="close" aria-label="关闭">×</button><div id="lightboxBody"></div></dialog>
<script id="frozen-data" type="application/json">{_json_script(payload)}</script><script>{JS}</script></body></html>'''


NAV_ITEMS = (
    ("overview", "决策总览"), ("company", "企业画像"), ("organization", "集团/成员名录"),
    ("operations", "经营与产业"), ("factories", "子公司与工厂"), ("product-matrix", "产品矩阵"),
    ("products", "产品数据库"), ("energy", "能源画像"), ("efficiency", "节能潜力"), ("pv", "光伏机会"),
    ("storage", "储能机会"), ("epc", "综合能源 / EPC"), ("carbon", "零碳与能碳"),
    ("opportunities", "合作机会矩阵"), ("business-model", "商务模式"), ("roadmap", "90天推进路径"),
    ("risks", "风险与证据"), ("sources", "数据来源"),
)


CSS = r'''
:root{--paper:#F0EFEB;--ink:#1C1C1A;--muted:#8F8E88;--faint:#C6C5BF;--grid:#DEDDD6;--l1:#4A4944;--l2:#6A6963;--l3:#B0AFA9;--l4:#D8D7D1;--sidebar:252px}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Inter","Aptos","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-underline-offset:3px}
button,input,select{font:inherit;color:inherit}
button,input,select,a{outline-offset:3px}
button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--ink)}
.sidebar{position:fixed;inset:0 auto 0 0;width:var(--sidebar);background:var(--ink);color:var(--paper);padding:28px 18px 22px;overflow:auto;z-index:20}
.brand{padding:0 10px 22px;border-bottom:1px solid #4A4944}
.brand strong{display:block;font-size:25px;font-weight:800;letter-spacing:.16em}
.brand span{display:block;margin-top:4px;font-size:9px;font-weight:600;letter-spacing:.18em;color:var(--faint)}
.sidebar nav{padding:18px 0}
.sidebar nav a{display:grid;grid-template-columns:25px 1fr;gap:10px;align-items:center;color:var(--faint);text-decoration:none;padding:8px 10px;border-radius:12px;font-size:11px;font-weight:600;letter-spacing:.02em}
.sidebar nav a:hover{background:#2E2D29;color:var(--paper)}
.sidebar nav b{font-size:9px;color:var(--muted);letter-spacing:.08em}
.freeze{font-size:9px;color:var(--muted);border-top:1px solid #4A4944;padding:18px 10px;letter-spacing:.12em}
.freeze code{display:block;margin-top:7px;word-break:break-all;color:var(--faint);letter-spacing:0}
main{margin-left:var(--sidebar)}
.hero{min-height:360px;padding:72px clamp(28px,5vw,88px) 94px;background:var(--ink);color:var(--paper);display:flex;justify-content:space-between;align-items:end;gap:48px;border-bottom:1px solid #2E2D29}
.eyebrow,.section-title span,.panel header span{font-size:10px;letter-spacing:.18em;font-weight:700;color:var(--muted);text-transform:uppercase}
.hero h1{max-width:850px;font-size:clamp(38px,5vw,70px);line-height:1.03;letter-spacing:-.04em;margin:18px 0 14px;font-weight:800}
.hero p{color:var(--faint);font-size:13px;line-height:1.7;margin:0}
.coverage{border-left:1px solid #4A4944;padding-left:30px;min-width:210px}
.coverage b{display:block;font-size:58px;line-height:1;font-weight:800;letter-spacing:-.04em}
.coverage span,.coverage small{display:block;letter-spacing:.12em}
.coverage span{margin-top:7px;font-size:10px;font-weight:700}.coverage small{color:var(--muted);margin-top:12px;font-size:9px}
.workspace{padding:64px clamp(22px,5vw,76px);max-width:1680px;margin:auto;border-bottom:1px solid var(--grid)}
.workspace:nth-of-type(even){background:var(--grid)}
.workspace>.section-deck{max-width:800px;color:var(--l2);line-height:1.8;font-size:13px;margin:-14px 0 28px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-76px;position:relative}
.kpi{background:var(--paper);border-radius:24px;padding:22px 22px 18px;min-height:112px}
.kpi b{display:block;font-size:32px;line-height:1.15;font-weight:800;letter-spacing:-.03em}
.kpi span{display:block;margin-top:12px;font-size:9px;color:var(--muted);font-weight:600;letter-spacing:.1em;text-transform:uppercase}
.panel,.profile-card,.evidence-boundary,.entity-card,.solution-card,.gap-card,.visual-card,.product-card,.gallery figure,.ledger{background:var(--paper);border-radius:24px}
.panel{margin-top:28px;padding:30px}
.panel h2{margin:7px 0 20px;font-size:24px;letter-spacing:-.02em}
.insight li{padding:11px 0;border-bottom:1px solid var(--grid);line-height:1.75}.insight li:last-child{border-bottom:0}
.section-title{display:flex;gap:18px;align-items:center;margin-bottom:30px}
.section-title>b{font-size:44px;line-height:1;font-weight:800;color:var(--l3)}
.section-title h2{margin:5px 0 0;font-size:31px;letter-spacing:-.035em}
.split{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.profile-card,.evidence-boundary{padding:25px;line-height:1.85}
.profile-card b{display:block;font-size:18px;margin-bottom:10px}.profile-card p{margin:0;color:var(--l2);font-size:12px}
.card-grid,.visual-grid,.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.visual-grid{margin-top:22px}
.entity-card,.solution-card,.gap-card{padding:23px}
.entity-card h3,.solution-card h3,.gap-card h3{margin:9px 0;font-size:17px}
.tag{display:inline-block;color:var(--l1);background:var(--l4);border-radius:999px;padding:5px 8px;font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.muted,.entity-card p,.solution-card p,.gap-card p{color:var(--l2);font-size:12px;line-height:1.75}
.entity-register{background:var(--paper);border-radius:24px;overflow:hidden}
.entity-row{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:20px;align-items:center;padding:18px 24px;border-bottom:1px solid var(--grid)}
.entity-row:last-child{border-bottom:0}.entity-index{font-size:10px;color:var(--muted);font-weight:700;letter-spacing:.12em}.entity-main b{display:block;font-size:15px}.entity-main small{display:block;color:var(--muted);margin-top:4px}.entity-status{font-size:9px;color:var(--l2);font-weight:700;letter-spacing:.08em}
.visual-card{grid-column:1/-1;padding:28px;min-height:260px}
.visual-card header{min-height:0}.visual-card h3{margin:8px 0 4px;font-size:19px;letter-spacing:-.02em}.visual-card small{color:var(--muted);line-height:1.6}
.lieflat-inline{overflow:auto;margin-top:16px}.lieflat-inline svg{display:block;width:100%;height:auto;min-width:680px}
.source-note{margin-top:18px;border-top:1px solid var(--grid);padding-top:10px;font-size:9px;color:var(--muted);letter-spacing:.04em;line-height:1.6}
.gallery{margin-top:22px}.gallery figure{margin:0;overflow:hidden;cursor:zoom-in}.gallery img{width:100%;height:205px;object-fit:contain;background:var(--paper);border-bottom:1px solid var(--grid)}.gallery figcaption{padding:14px;font-size:11px;line-height:1.55}
.filters{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:9px;margin-bottom:18px}
.filters input,.filters select,.filters button,.wide-search{border:1px solid var(--faint);background:var(--paper);padding:12px 14px;font-size:12px;border-radius:999px}.wide-search{width:100%;margin-top:18px}
.filters button,.product-actions button,.zoom-tools button{cursor:pointer;font-weight:700}.filters button:hover,.product-actions button:hover,.zoom-tools button:hover{background:var(--ink);color:var(--paper)}
.product-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.product-card{overflow:hidden}.product-card img{width:100%;height:235px;object-fit:contain;background:var(--paper);border-bottom:1px solid var(--grid)}
.product-body{padding:21px}.product-body h3{margin:9px 0;font-size:18px}.product-meta{display:flex;gap:6px;flex-wrap:wrap}.product-meta span{background:var(--l4);border-radius:999px;padding:5px 8px;font-size:9px}
.product-actions{display:flex;gap:8px;margin-top:15px}.product-actions button,.zoom-tools button{border:1px solid var(--faint);border-radius:999px;background:var(--paper);padding:9px 12px}
.compare{overflow:auto;margin-top:24px}.compare table{border-collapse:separate;border-spacing:0;width:100%;min-width:760px;background:var(--paper);border-radius:20px;overflow:hidden}.compare th,.compare td{border:0;border-bottom:1px solid var(--grid);padding:12px;font-size:11px;vertical-align:top}.compare th{background:var(--ink);color:var(--paper);text-align:left}.compare tr:last-child td{border-bottom:0}
.ledger{margin-top:16px;overflow:hidden}.claim{display:grid;grid-template-columns:180px 1fr 190px;gap:18px;padding:16px 20px;border-bottom:1px solid var(--grid);font-size:11px;line-height:1.65}.claim:last-child{border:0}.claim b{color:var(--ink)}.claim a{font-weight:700}
dialog{width:min(980px,94vw);border:0;border-radius:24px;padding:30px;background:var(--paper);color:var(--ink)}dialog::backdrop{background:#1C1C1AD9}.close{float:right;border:0;border-radius:999px;background:var(--ink);color:var(--paper);width:36px;height:36px;cursor:pointer}.zoom-tools button{margin:4px}.dialog-image{max-width:100%;max-height:520px;display:block;margin:15px auto;object-fit:contain;transform-origin:center}.lightbox-image{max-width:100%;max-height:75vh;display:block;margin:auto;object-fit:contain}
@media(max-width:1100px){:root{--sidebar:214px}.kpis{grid-template-columns:repeat(2,1fr)}.card-grid,.visual-grid,.gallery,.product-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:768px){.sidebar{position:sticky;top:0;width:100%;height:auto;padding:12px 16px}.sidebar nav,.freeze{display:none}.brand{padding:0;border:0}.brand strong,.brand span{display:inline}.brand strong{margin-right:10px}.brand span{font-size:8px}main{margin:0}.hero{min-height:280px;padding:44px 22px 84px}.coverage{display:none}.workspace{padding:42px 18px}.kpis{margin-top:-66px}.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}.claim{grid-template-columns:1fr}.split{grid-template-columns:1fr}.entity-row{grid-template-columns:44px minmax(0,1fr)}.lieflat-inline svg{min-width:0}}
@media(max-width:480px){.hero h1{font-size:37px}.kpis,.card-grid,.visual-grid,.gallery,.product-grid{grid-template-columns:1fr}.filters{grid-template-columns:1fr}.filters input{grid-column:auto}.section-title h2{font-size:25px}.workspace{overflow:hidden}.entity-row{grid-template-columns:34px minmax(0,1fr);gap:10px;padding:15px}.entity-status{grid-column:2}.visual-card{padding:18px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
@media print{.sidebar{display:none}main{margin:0}.hero{min-height:auto;padding:34px;color:var(--ink);background:var(--paper);border-bottom:2px solid var(--ink)}.coverage{border-color:var(--ink)}.workspace{break-inside:avoid;border-bottom:1px solid var(--grid)}.filters,.product-actions,.zoom-tools,.close{display:none!important}}
'''


JS = r'''
const DATA=JSON.parse(document.getElementById('frozen-data').textContent);const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const value=(key,fallback='—')=>{const c=DATA.claims.find(x=>x.fieldKey===key);return c?`${typeof c.value==='object'?JSON.stringify(c.value):c.value}${c.unit||''}`:fallback};
function overview(){const metrics=[['营收',value('revenue')],['员工',value('employees',value('employee_count'))],['子公司',Math.max(DATA.entities.length-1,0)],['工厂',DATA.factories.length],['核心产品',DATA.products.length],['高优机会',DATA.solutions.filter(x=>String(x.priority).match(/HIGH|P0|P1|A|1/i)).length],['Evidence Sources',DATA.sources.length],['Verified Claims',DATA.claims.length]];$('kpis').innerHTML=metrics.map(x=>`<article class="kpi"><b>${esc(x[1])}</b><span>${esc(x[0])}</span></article>`).join('');$('insights').innerHTML=DATA.insights.map(x=>`<li>${esc(x)}</li>`).join('');$('companyProfile').innerHTML=`<article class="profile-card"><b>${esc(DATA.entity.name)}</b><p>实体类型：${esc(DATA.entity.type)}<br>注册区域：${esc(DATA.entity.region||'待核验')}<br>证据状态：${esc(DATA.entity.status)}</p></article><article class="profile-card"><b>研究边界</b><p>冻结版本：${esc(DATA.meta.freeze)}<br>根哈希：${esc(DATA.meta.rootHash)}<br>复杂度路由：${esc(DATA.meta.complexity)}</p></article>`}
function structures(){$('entityRegister').innerHTML=DATA.entities.map((e,i)=>`<article class="entity-row"><span class="entity-index">${String(i+1).padStart(2,'0')}</span><div class="entity-main"><b>${esc(e.name)}</b><small>${esc(e.type)}</small></div><span class="entity-status">${esc(e.status)}</span></article>`).join('')||'<article class="evidence-boundary">暂无满足证据门禁的成员实体记录。</article>';$('factoryGrid').innerHTML=DATA.factories.map(f=>`<article class="entity-card"><span class="tag">FACTORY</span><h3>${esc(f.name)}</h3><p>${esc(f.address||'地址待核验')}<br>${esc((f.processes||[]).join('、')||'工艺待核验')}</p></article>`).join('')||'<article class="entity-card"><h3>暂无已核验工厂记录</h3></article>';}
function visualMarkup(v){return `<div class="lieflat-inline" data-template="${esc(v.templateId)}" data-template-source="${esc(v.templateSource)}" data-color-system="${esc(v.colorSystem)}">${v.markup}</div>`}
function visuals(){document.querySelectorAll('.visual-grid').forEach(grid=>{const chapter=grid.dataset.chapter;const rows=DATA.visuals.filter(v=>v.chapter===chapter);grid.innerHTML=rows.map(v=>`<article class="visual-card"><header><span class="tag">LIEFLAT ${esc(v.templateId)} · ${esc(v.templateName)} · ${esc(v.colorSystem).toUpperCase()}</span></header>${visualMarkup(v)}<div class="source-note">${esc(v.sourceNote)}<br>${esc(v.transformation)}<br>TEMPLATE: ${esc(v.templateSource)} · ${esc(v.templateCardTitle)}</div></article>`).join('')||'<article class="evidence-boundary">该章节没有满足 Lieflat 数据契约的冻结数据，已改用正文或表格呈现，未生成旧式流程图、关系图或推测图。</article>'})}
function galleries(){$('gallery').innerHTML=DATA.gallery.filter(x=>!x.productId).map(x=>`<figure data-gallery="${esc(x.id)}"><img src="${x.asset}" alt="${esc(x.caption)}"><figcaption><b>${esc(x.caption)}</b><br><span class="muted">${esc(x.role)}</span></figcaption></figure>`).join('');document.querySelectorAll('[data-gallery]').forEach(el=>el.onclick=()=>{const x=DATA.gallery.find(i=>i.id===el.dataset.gallery);$('lightboxBody').innerHTML=`<img class="lightbox-image" src="${x.asset}" alt="${esc(x.caption)}"><h3>${esc(x.caption)}</h3><p><a href="${esc(x.source)}" target="_blank" rel="noreferrer">原始页面来源 ↗</a></p>`;$('lightbox').showModal()})}
function products(){let selected=[];const cats=[...new Set(DATA.products.map(p=>p.family))];$('categoryFilter').innerHTML+=[...cats].sort().map(x=>`<option>${esc(x)}</option>`).join('');function render(){let rows=DATA.products.filter(p=>(!$('categoryFilter').value||p.family===$('categoryFilter').value)&&JSON.stringify(p).toLowerCase().includes($('productSearch').value.toLowerCase()));rows.sort((a,b)=>String(a[$('sortProducts').value]||'').localeCompare(String(b[$('sortProducts').value]||''),'zh-CN'));$('productCount').textContent=`展示 ${rows.length} / ${DATA.products.length} 项已核验产品 · 最多 4 项对比`;$('productGrid').innerHTML=rows.map(p=>`<article class="product-card">${p.offlineAsset?`<img src="${p.offlineAsset}" alt="${esc(p.name)}">`:''}<div class="product-body"><span class="tag">${esc(p.family)} · ${esc(p.evidenceStatus)}</span><h3>${esc(p.name)}</h3><p class="muted">${esc(p.description)}</p><div class="product-meta"><span>${esc(p.brand||'品牌待核验')}</span><span>${esc(p.model||'型号待核验')}</span><span>${esc(p.series)}</span></div><div class="product-actions"><button data-detail="${esc(p.id)}">详情/放大</button><button data-compare="${esc(p.id)}">${selected.includes(p.id)?'已加入':'加入对比'}</button></div></div></article>`).join('')||'<article class="evidence-boundary">暂无满足证据与图片门禁的实体产品。</article>';document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>detail(DATA.products.find(p=>p.id===b.dataset.detail)));document.querySelectorAll('[data-compare]').forEach(b=>b.onclick=()=>{const id=b.dataset.compare;if(selected.includes(id))selected=selected.filter(x=>x!==id);else if(selected.length<4)selected.push(id);render();compare()})}function detail(p){$('dialogBody').innerHTML=`<span class="tag">${esc(p.family)} · ${esc(p.evidenceStatus)}</span><h2>${esc(p.name)}</h2><div class="zoom-tools">${[100,125,150,200].map(z=>`<button data-zoom="${z}">${z}%</button>`).join('')}</div><div style="overflow:auto;max-height:560px"><img id="dialogImage" class="dialog-image" src="${p.offlineAsset}" alt="${esc(p.name)}"></div><p>${esc(p.description)}</p><h3>参数</h3>${p.parameters.map(x=>`<p><b>${esc(x.name)}</b> ${esc(x.value)} ${esc(x.unit||'')}</p>`).join('')||'<p>暂无已核验参数。</p>'}<p><a href="${esc(p.imageSource)}" target="_blank" rel="noreferrer">图片原始页面 ↗</a></p>`;document.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{$('dialogImage').style.width=b.dataset.zoom+'%';$('dialogImage').style.maxWidth='none'});$('detailDialog').showModal()}function compare(){const rows=selected.map(id=>DATA.products.find(p=>p.id===id));$('comparePanel').innerHTML=rows.length?`<table><thead><tr><th>字段</th>${rows.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody><tr><td>图片</td>${rows.map(p=>`<td><img src="${p.offlineAsset}" style="width:120px;height:90px;object-fit:contain"></td>`).join('')}</tr><tr><td>型号</td>${rows.map(p=>`<td>${esc(p.model||'待核验')}</td>`).join('')}</tr><tr><td>产品族/系列</td>${rows.map(p=>`<td>${esc(p.family)} / ${esc(p.series)}</td>`).join('')}</tr><tr><td>参数</td>${rows.map(p=>`<td>${p.parameters.map(x=>`${esc(x.name)}: ${esc(x.value)} ${esc(x.unit||'')}`).join('<br>')||'待核验'}</td>`).join('')}</tr></tbody></table>`:''}$('productSearch').oninput=render;$('categoryFilter').onchange=render;$('sortProducts').onchange=render;$('clearCompare').onclick=()=>{selected=[];render();compare()};render();compare()}
function evidence(){$('solutionGrid').innerHTML=DATA.solutions.map(s=>`<article class="solution-card"><span class="tag">${esc(s.engine)} · ${esc(s.type)}</span><h3>${esc(s.opportunity)}</h3><p>${esc(s.solution)}</p><b>优先级 ${esc(s.priority)}</b></article>`).join('')||'<article class="evidence-boundary">暂无冻结合作方案。</article>';$('gapGrid').innerHTML=DATA.gaps.map(g=>`<article class="gap-card"><span class="tag">${esc(g.importance)} · ${esc(g.reason)}</span><h3>${esc(g.field)}</h3><p>${esc(g.next)}</p></article>`).join('')||'<article class="gap-card"><h3>无开放缺口</h3></article>';const draw=q=>$('claimList').innerHTML=DATA.claims.filter(c=>JSON.stringify(c).toLowerCase().includes(q)).map(c=>`<article class="claim"><div><b>${esc(c.field)}</b><br>${esc(c.level)} · ${esc(c.id)}</div><div>${esc(typeof c.value==='object'?JSON.stringify(c.value):c.value)} ${esc(c.unit||'')}<br><span class="muted">${esc(c.quote)}</span></div><div><a href="${esc(c.url)}" target="_blank" rel="noreferrer">${esc(c.source)} ↗</a></div></article>`).join('')||'<article class="claim">无匹配证据</article>';draw('');$('claimSearch').oninput=e=>draw(e.target.value.toLowerCase())}
document.querySelectorAll('dialog .close').forEach(b=>b.onclick=()=>b.closest('dialog').close());overview();structures();visuals();galleries();products();evidence();
'''
