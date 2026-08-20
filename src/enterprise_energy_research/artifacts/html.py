from __future__ import annotations

import hashlib
import html
import json
import base64
import mimetypes
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.domain.enums import ArtifactType, VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.vendor import embedded_skill_root


FIELD_LABELS = {
    "canonical_company_name": "公司名称", "stock_code": "股票代码", "core_business": "核心业务",
    "revenue": "营业收入", "profit": "归母净利润", "rd_expense": "研发费用", "process": "主要工艺",
    "product_portfolio": "产品组合", "export": "销售区域", "polarizer_market_share": "偏光片市场份额",
    "polarizer_capacity": "偏光片规划产能", "green_electricity_transaction_volume": "绿电交易量",
    "roof_pv_generation": "屋顶光伏发电量", "green_factory_count": "绿色工厂数量",
    "energy_management_certified_sites": "能源管理体系认证厂区", "energy_efficiency_signal": "节能管理信号",
    "sichuan_factory_efficiency_improvement": "四川基地生产效率提升", "sichuan_factory_unit_energy_reduction": "四川基地单位能耗下降",
    "waste_heat_recovery": "余热回收", "planned_overseas_project": "海外规划项目",
    "planned_overseas_investment": "海外规划投资上限", "electricity_consumption": "年度用电量",
    "load_curve": "负荷曲线", "operating_schedule": "生产班次", "transformer_capacity": "变压器容量", "roof_area": "可用屋面面积",
}


def _json_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class FrozenHtmlPublisher:
    """Standalone HTML publisher. It only reads the frozen bundle passed by the orchestrator."""

    name = "frontend_design"

    def __init__(
        self,
        artifact_type: ArtifactType,
        skill_root: Path | None = None,
        asset_root: Path | None = None,
    ) -> None:
        if artifact_type not in {ArtifactType.ENTERPRISE_HTML, ArtifactType.PRODUCT_HTML}:
            raise ValueError("FrozenHtmlPublisher supports enterprise_html and product_html only")
        self.artifact_type = artifact_type
        self.skill_root = skill_root or embedded_skill_root("frontend-design")
        self.asset_root = Path(asset_root) if asset_root else None

    def health(self) -> AdapterHealth:
        available = (self.skill_root / "SKILL.md").is_file() and (self.skill_root / "LICENSE.txt").is_file()
        diagnostics = [] if available else ["Embedded frontend-design instructions or license are missing"]
        return AdapterHealth(name=self.name, available=available, version="embedded", diagnostics=diagnostics)

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        health = self.health()
        if not health.available:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=health.diagnostics,
            )
        if binding.type != self.artifact_type:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=[f"Binding type {binding.type} does not match publisher {self.artifact_type}"],
            )
        if self.artifact_type == ArtifactType.PRODUCT_HTML:
            content, used_claims, used_images = self._product_page(bundle, binding, output_path)
        else:
            content, used_claims, used_images = self._enterprise_page(bundle, binding)
        digest = _write(output_path, content)
        return ArtifactResult(
            adapter=self.name,
            artifact_id=binding.artifact_id,
            artifact_type=binding.type,
            path=output_path,
            content_sha256=digest,
            used_claim_ids=used_claims,
            used_image_ids=used_images,
            status="published",
        )

    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        return next(
            (item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id),
            bundle.entities[0] if bundle.entities else None,
        )

    def _enterprise_page(self, bundle: FrozenResearchBundle, binding: ArtifactBinding) -> tuple[str, list[str], list[str]]:
        entity = self._canonical_entity(bundle)
        if not entity:
            raise ValueError("Frozen bundle contains no enterprise entity")
        verified_claims = [
            item for item in bundle.claims
            if item.claim_id in binding.claim_ids and item.verification_status == VerificationStatus.VERIFIED
        ]
        sources = {item.source_id: item for item in bundle.sources}
        claims_payload = [{
            "id": item.claim_id,
            "field": FIELD_LABELS.get(item.field_name, item.field_name),
            "value": item.value,
            "unit": item.unit,
            "asOf": item.as_of_date.isoformat() if item.as_of_date else None,
            "source": sources[item.source_id].source_title or sources[item.source_id].source_domain,
            "url": str(sources[item.source_id].canonical_url),
            "level": sources[item.source_id].source_level.value,
            "quote": item.raw_text,
        } for item in verified_claims]
        children = [
            {"from": edge.from_id, "to": edge.to_id, "relation": edge.relation, "status": edge.verification_status.value}
            for edge in bundle.edges
        ]
        payload = {
            "entity": {
                "id": entity.entity_id, "name": entity.canonical_name, "type": entity.entity_type,
                "region": entity.registration_region, "website": str(entity.official_website or ""),
                "status": entity.verification_status.value,
            },
            "entities": [{"id": item.entity_id, "name": item.canonical_name, "type": item.entity_type, "status": item.verification_status.value} for item in bundle.entities],
            "factories": [{"id": item.factory_id, "name": item.name or "未命名基地", "address": item.address, "processes": item.processes} for item in bundle.factories],
            "edges": children,
            "claims": claims_payload,
            "gaps": [{"field": FIELD_LABELS.get(item.field_name, item.field_name), "importance": item.importance, "reason": item.reason, "next": item.next_action} for item in bundle.gaps],
            "solutions": [{"engine": item.engine, "opportunity": item.opportunity, "solution": item.proposed_solution, "priority": item.priority, "type": item.statement_type.value, "claims": item.claim_ids, "assumptions": item.assumptions} for item in bundle.solutions],
            "sources": [{"id": item.source_id, "title": item.source_title or item.source_domain, "domain": item.source_domain, "level": item.source_level.value, "url": str(item.canonical_url)} for item in bundle.sources],
            "meta": {"freeze": bundle.freeze.freeze_id, "rootHash": bundle.freeze.root_hash, "complexity": bundle.run_manifest.complexity.value if bundle.run_manifest.complexity else "UNKNOWN"},
        }
        body = f"""
<section class="hero" id="overview"><div class="shell hero-grid"><div><div class="eyebrow">SEVC · ENTERPRISE ENERGY INTELLIGENCE</div><h1>{html.escape(entity.canonical_name)}</h1><p>产业链、生产足迹、能源场景与合作机会的证据化快照。所有正式结论来自冻结数据；缺口和推断均显式标注。</p><div class="hero-actions"><a href="#evidence">查看证据</a><a class="ghost" href="#solutions">合作机会</a></div></div><aside class="identity-card"><span>ENTITY STATUS</span><strong>{entity.verification_status.value}</strong><dl><dt>复杂度路由</dt><dd>{html.escape(payload['meta']['complexity'])}</dd><dt>注册区域</dt><dd>{html.escape(entity.registration_region or '待核验')}</dd><dt>冻结版本</dt><dd>{html.escape(bundle.freeze.freeze_id)}</dd></dl></aside></div></section>
<section class="metrics"><div class="shell metric-grid"><article><b>{len(bundle.entities)}</b><span>企业实体</span></article><article><b>{len(bundle.factories)}</b><span>生产基地</span></article><article><b>{len(verified_claims)}</b><span>已核验证据</span></article><article><b>{len(bundle.gaps)}</b><span>数据缺口</span></article></div></section>
<section id="structure"><div class="shell"><header class="section-head"><div><small>ENTERPRISE MAP</small><h2>企业与生产足迹</h2></div><p>组织关系未被证据确认时保持 UNVERIFIED，不以版式暗示确定性。</p></header><div id="entityGrid" class="card-grid"></div></div></section>
<section class="dark" id="solutions"><div class="shell"><header class="section-head"><div><small>COOPERATION ENGINES</small><h2>四类能源合作机会</h2></div><p>证据支持与分析推断使用不同标识。</p></header><div id="solutionGrid" class="solution-grid"></div></div></section>
<section id="evidence"><div class="shell"><header class="section-head"><div><small>EVIDENCE LEDGER</small><h2>核心证据与来源</h2></div><label class="search">筛选 <input id="claimSearch" placeholder="字段、取值或来源"></label></header><div id="claimList" class="ledger"></div></div></section>
<section id="gaps" class="soft"><div class="shell"><header class="section-head"><div><small>DATA GAPS</small><h2>待补充与现场尽调</h2></div></header><div id="gapGrid" class="gap-grid"></div></div></section>
"""
        return self._document(entity.canonical_name, body, payload, "enterprise"), [item.claim_id for item in verified_claims], []

    def _product_page(
        self,
        bundle: FrozenResearchBundle,
        binding: ArtifactBinding,
        output_path: Path,
    ) -> tuple[str, list[str], list[str]]:
        entity = self._canonical_entity(bundle)
        if not entity:
            raise ValueError("Frozen bundle contains no enterprise entity")
        images = {item.image_id: item for item in bundle.images if item.verification_status == VerificationStatus.VERIFIED}
        products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED and item.image_id in images]
        payload_products = []
        used_images: list[str] = []
        for product in products:
            image = images[product.image_id]
            embedded_asset = self._embedded_image(image.local_asset_ref, image.mime_type, output_path)
            used_images.append(image.image_id)
            payload_products.append({
                "id": product.product_id, "name": product.name, "brand": product.brand, "model": product.model,
                "category": product.category or "未分类", "description": product.description or "暂无已核验说明",
                "parameters": [item.model_dump(mode="json") for item in product.parameters],
                "image": str(image.source_url), "imageId": image.image_id, "imageSource": str(image.source_page_url),
                "offlineAsset": embedded_asset,
            })
        if not payload_products:
            raise ValueError("Product dashboard requires verified physical products with verified images")
        payload = {
            "entity": {"name": entity.canonical_name},
            "products": payload_products,
            "meta": {"freeze": bundle.freeze.freeze_id, "rootHash": bundle.freeze.root_hash},
        }
        body = f"""
<section class="hero product-hero"><div class="shell hero-grid"><div><div class="eyebrow">SEVC · VERIFIED PRODUCT INDEX</div><h1>{html.escape(entity.canonical_name)}<br><em>产品证据看板</em></h1><p>仅展示同时具备来源、真实性校验和本地归档原图的实体产品；所有图片已内嵌，可离线查看。</p></div><aside class="identity-card"><span>QUALIFIED PRODUCTS</span><strong>{len(products)}</strong><dl><dt>冻结版本</dt><dd>{html.escape(bundle.freeze.freeze_id)}</dd><dt>最大对比数</dt><dd>3</dd></dl></aside></div></section>
<div class="filterbar"><div class="shell filters"><input id="productSearch" placeholder="搜索产品、型号、品牌"><select id="categoryFilter"><option value="">全部类别</option></select><select id="sortProducts"><option value="name">按名称</option><option value="model">按型号</option></select><button id="clearCompare">清空对比</button></div></div>
<section><div class="shell"><div class="resultline"><span id="productCount"></span><span>选择最多 3 项进行横向对比</span></div><div id="productGrid" class="product-grid"></div></div></section>
<section class="dark"><div class="shell"><header class="section-head"><div><small>COMPARE</small><h2>产品横向对比</h2></div></header><div id="comparePanel" class="compare-panel"></div></div></section>
<dialog id="productDialog"><button class="dialog-close" aria-label="关闭">×</button><div id="dialogBody"></div></dialog>
"""
        return self._document(f"{entity.canonical_name}产品证据看板", body, payload, "product"), list(binding.claim_ids), used_images

    def _embedded_image(self, local_asset_ref: str | None, mime_type: str, output_path: Path) -> str:
        if not local_asset_ref:
            raise ValueError("Formal product dashboard requires an archived local image for every displayed product")
        if local_asset_ref.startswith("data:image/"):
            return local_asset_ref
        reference = Path(local_asset_ref)
        candidates = [reference] if reference.is_absolute() else []
        if self.asset_root:
            candidates.append(self.asset_root / reference)
        candidates.extend([
            output_path.parent / reference,
            output_path.parent.parent / "01_evidence" / reference,
            output_path.parent.parent / reference,
        ])
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise ValueError(f"Archived image asset cannot be resolved: {local_asset_ref}")
        detected = mimetypes.guess_type(source.name)[0] or mime_type
        if not detected.startswith("image/"):
            raise ValueError(f"Archived asset is not an image: {source}")
        return f"data:{detected};base64,{base64.b64encode(source.read_bytes()).decode('ascii')}"

    @staticmethod
    def _document(title: str, body: str, payload: dict[str, Any], mode: str) -> str:
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#32123f"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%236f2b86'/%3E%3Ctext x='32' y='39' text-anchor='middle' fill='white' font-size='19' font-family='Arial'%3ES%3C/text%3E%3C/svg%3E"><title>{html.escape(title)}</title>
<style>{_CSS}</style></head><body data-mode="{mode}">
<header class="topbar"><div class="shell nav"><a class="brand" href="#"><span class="mark">SEVC</span><span>企业产业与能源合作智能调研<small>EVIDENCE FIRST · SINGLE SOURCE OF TRUTH</small></span></a><nav><a href="#overview">总览</a><a href="#solutions">机会</a><a href="#evidence">证据</a></nav></div></header>
<main>{body}</main><footer><div class="shell"><strong>SEVC 企业产业与能源合作智能调研</strong><span>冻结数据版本：{html.escape(payload['meta']['freeze'])}</span><code>{html.escape(payload['meta']['rootHash'][:16])}…</code></div></footer>
<script id="frozen-data" type="application/json">{_json_script(payload)}</script><script>{_JS}</script></body></html>"""


_CSS_ROOT_TEMPLATE = (
    ":root{{--purple:{purple};--violet:#9c56b3;--navy:{navy};--cobalt:{cobalt};"
    "--deep:#21122b;--ink:{ink};--muted:{muted};--paper:{paper};--card:#fff;"
    "--line:{line};--mint:#27a47a;--amber:#db8a32;--red:#b9434e;"
    "--radius:22px;--shadow:0 18px 55px rgba(42,20,52,.10)}}"
)


def _css_root() -> str:
    """CSS :root variables driven by config/office_visual_policy.yaml.

    Editing the theme colors in the policy file restyles the dashboard
    without code changes; the built-in defaults mirror the v0.8.1 palette.
    """
    from enterprise_energy_research.artifacts.visual_policy import colors as theme_colors

    tc = theme_colors()
    return _CSS_ROOT_TEMPLATE.format(
        purple=tc["sevc_purple"], navy=tc["navy"], cobalt=tc["cobalt"],
        ink=tc["black"], muted=tc["cool_gray"], paper=tc["canvas"], line=tc["pale_gray"],
    )


_CSS = _css_root() + r"""
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Serif SC","Source Han Serif SC","Songti SC","Microsoft YaHei",serif}.shell{width:min(1380px,calc(100% - 48px));margin:auto}.topbar{position:sticky;top:0;z-index:50;background:rgba(31,16,39,.94);border-bottom:1px solid rgba(255,255,255,.1);backdrop-filter:blur(16px)}.nav{height:76px;display:flex;align-items:center;justify-content:space-between}.brand{display:flex;align-items:center;gap:13px;text-decoration:none;color:white;font-family:"Microsoft YaHei",sans-serif;font-weight:700}.brand small{display:block;color:#c9b5d0;font-size:9px;letter-spacing:1.7px;margin-top:3px}.mark{display:grid;place-items:center;width:64px;height:38px;border:1px solid rgba(255,255,255,.35);font-family:Georgia,serif;letter-spacing:2px}.nav nav{display:flex;gap:22px}.nav nav a{color:#d5c9d9;text-decoration:none;font:13px "Microsoft YaHei",sans-serif}.hero{min-height:570px;display:flex;align-items:center;background:radial-gradient(circle at 83% 18%,rgba(180,91,204,.25),transparent 28%),linear-gradient(135deg,#190c21 0%,#341743 63%,#5a246e 100%);color:white;position:relative;overflow:hidden}.hero:after{content:"";position:absolute;right:-8%;bottom:-48%;width:680px;height:680px;border:1px solid rgba(255,255,255,.13);transform:rotate(32deg)}.hero-grid{display:grid;grid-template-columns:1.4fr .6fr;gap:80px;align-items:center;position:relative;z-index:1}.eyebrow,.section-head small{font:800 11px "Microsoft YaHei",sans-serif;letter-spacing:2.8px;color:#d6a8e5}.hero h1{font-size:clamp(42px,5.6vw,82px);line-height:1.08;letter-spacing:-2px;margin:22px 0}.hero h1 em{font-style:normal;color:#dcb4e8}.hero p{max-width:720px;font-size:17px;line-height:2;color:#e3d9e6}.hero-actions{display:flex;gap:12px;margin-top:30px}.hero-actions a{background:white;color:var(--purple);padding:12px 18px;border-radius:12px;text-decoration:none;font:bold 13px "Microsoft YaHei",sans-serif}.hero-actions .ghost{background:transparent;color:white;border:1px solid rgba(255,255,255,.3)}.identity-card{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.2);padding:28px;border-radius:24px;backdrop-filter:blur(18px)}.identity-card span{font:11px "Microsoft YaHei",sans-serif;letter-spacing:2px;color:#cdbbd3}.identity-card strong{display:block;font:800 27px "Microsoft YaHei",sans-serif;color:#fff;margin:10px 0 25px}.identity-card dl{margin:0}.identity-card dt{font:11px "Microsoft YaHei",sans-serif;color:#bda9c4;margin-top:14px}.identity-card dd{margin:4px 0 0}.metrics{position:relative;margin-top:-56px;z-index:4}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metric-grid article{background:white;border:1px solid white;border-radius:20px;padding:24px;box-shadow:var(--shadow)}.metric-grid b{display:block;color:var(--purple);font:700 34px Georgia,serif}.metric-grid span{color:var(--muted);font:12px "Microsoft YaHei",sans-serif}section{padding:86px 0}.section-head{display:flex;justify-content:space-between;align-items:end;gap:32px;margin-bottom:28px}.section-head h2{font-size:34px;margin:8px 0 0}.section-head p{max-width:600px;color:var(--muted);line-height:1.8}.card-grid,.solution-grid,.gap-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.entity-card,.solution-card,.gap-card{background:white;border:1px solid var(--line);border-radius:var(--radius);padding:24px;box-shadow:0 8px 25px rgba(42,20,52,.05)}.entity-card .tag,.solution-card .tag,.gap-card .tag{font:800 10px "Microsoft YaHei",sans-serif;letter-spacing:1.4px;color:var(--purple)}.entity-card h3,.solution-card h3,.gap-card h3{margin:10px 0;font-size:19px}.entity-card p,.solution-card p,.gap-card p{color:var(--muted);line-height:1.75;font-size:13px}.dark{background:var(--deep);color:white}.dark .section-head p{color:#c8bacd}.solution-card{background:#2d1936;border-color:#493054;box-shadow:none}.solution-card p{color:#cdbfd1}.solution-card .tag{color:#dcafe9}.solution-card strong{display:inline-block;padding:5px 9px;border-radius:999px;background:#fff;color:var(--purple);font:800 10px "Microsoft YaHei",sans-serif}.ledger{background:white;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}.claim{display:grid;grid-template-columns:180px 1fr 180px;gap:20px;padding:18px 22px;border-bottom:1px solid var(--line);align-items:center}.claim:last-child{border:0}.claim .field{font:bold 12px "Microsoft YaHei",sans-serif;color:var(--purple)}.claim .value{word-break:break-word}.claim small{display:block;color:var(--muted);margin-top:6px}.claim a{color:var(--purple);font-size:12px}.search{font:12px "Microsoft YaHei",sans-serif;color:var(--muted)}.search input,.filters input,.filters select,.filters button{border:1px solid var(--line);background:white;border-radius:12px;padding:11px 13px;font:13px "Microsoft YaHei",sans-serif}.soft{background:#ebe5ed}.filterbar{position:sticky;top:76px;z-index:20;background:rgba(244,241,245,.92);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}.filters{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;padding:14px 0}.resultline{display:flex;justify-content:space-between;color:var(--muted);font:12px "Microsoft YaHei",sans-serif;margin-bottom:20px}.product-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}.product-card{background:white;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:0 8px 24px rgba(43,20,53,.06)}.product-visual{height:280px;background:linear-gradient(135deg,#2e1738,#713086);position:relative;display:grid;place-items:center;overflow:hidden}.product-visual img{width:100%;height:100%;object-fit:contain;background:white}.image-missing{padding:25px;text-align:center;color:#eadff0}.image-missing b{font-size:20px}.image-missing small{display:block;margin-top:10px;color:#cbb7d1}.product-content{padding:21px}.product-content h3{margin:9px 0;font-size:20px}.product-content p{color:var(--muted);font-size:13px;line-height:1.7;min-height:45px}.product-meta{display:flex;gap:6px;flex-wrap:wrap}.product-meta span{background:#f0e8f3;color:var(--purple);border-radius:8px;padding:5px 8px;font:700 10px "Microsoft YaHei",sans-serif}.product-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:18px}.product-actions button{border:1px solid var(--line);border-radius:11px;padding:10px;background:white;color:var(--purple);font:bold 12px "Microsoft YaHei",sans-serif}.product-actions .detail{background:var(--purple);color:white}.compare-panel{overflow:auto}.compare-panel table{border-collapse:collapse;width:100%;min-width:760px;background:white;color:var(--ink)}.compare-panel th,.compare-panel td{padding:13px;border:1px solid var(--line);text-align:left;font-size:12px}.compare-panel th{background:#eee5f1;color:var(--purple)}dialog{width:min(920px,94vw);border:0;border-radius:24px;padding:30px;box-shadow:0 30px 80px rgba(0,0,0,.35)}dialog::backdrop{background:rgba(24,12,29,.72);backdrop-filter:blur(7px)}.dialog-close{float:right;width:36px;height:36px;border:0;border-radius:50%;font-size:20px}footer{background:#130918;color:#b8a9be;padding:30px 0;font:12px "Microsoft YaHei",sans-serif}footer .shell{display:flex;justify-content:space-between;gap:20px;align-items:center}footer strong{color:white}footer code{color:#d5aadf}
@media(max-width:900px){.hero-grid{grid-template-columns:1fr}.identity-card{display:none}.metric-grid,.card-grid,.solution-grid,.gap-grid,.product-grid{grid-template-columns:repeat(2,1fr)}.nav nav{display:none}.claim{grid-template-columns:130px 1fr}.claim>div:last-child{grid-column:2}.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}}
@media(max-width:620px){.shell{width:min(100% - 28px,1380px)}.hero{min-height:620px}.hero h1{font-size:43px}.metric-grid{grid-template-columns:1fr 1fr}.metric-grid article{padding:17px}.card-grid,.solution-grid,.gap-grid,.product-grid{grid-template-columns:1fr}.section-head{display:block}.claim{display:block}.claim>div{margin:8px 0}.filters{grid-template-columns:1fr}.filters input{grid-column:auto}footer .shell{display:block}footer span,footer code{display:block;margin-top:8px}}
"""


_JS = r"""
const DATA=JSON.parse(document.getElementById('frozen-data').textContent);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function enterprise(){const eg=document.getElementById('entityGrid');if(!eg)return;const factories=DATA.factories||[];eg.innerHTML=DATA.entities.map(e=>`<article class="entity-card"><span class="tag">${esc(e.type)} · ${esc(e.status)}</span><h3>${esc(e.name)}</h3><p>${factories.filter(f=>DATA.edges.some(x=>x.from===e.id&&x.to===f.id)).map(f=>`${esc(f.name)}｜${esc(f.address||'地址待核验')}`).join('<br>')||'暂未形成可核验生产基地记录'}</p></article>`).join('');document.getElementById('solutionGrid').innerHTML=DATA.solutions.map(s=>`<article class="solution-card"><span class="tag">${esc(s.engine)} · ${esc(s.type)}</span><h3>${esc(s.opportunity)}</h3><p>${esc(s.solution)}</p><strong>优先级 ${esc(s.priority)}</strong></article>`).join('');const drawClaims=q=>{document.getElementById('claimList').innerHTML=DATA.claims.filter(c=>JSON.stringify(c).toLowerCase().includes(q)).map(c=>`<article class="claim"><div class="field">${esc(c.field)}<small>${esc(c.level)} · ${esc(c.id)}</small></div><div class="value">${esc(typeof c.value==='object'?JSON.stringify(c.value):c.value)} ${esc(c.unit||'')}<small>${esc(c.quote)}</small></div><div><a href="${esc(c.url)}" target="_blank" rel="noreferrer">${esc(c.source)} ↗</a></div></article>`).join('')||'<article class="claim">没有匹配证据</article>'};drawClaims('');document.getElementById('claimSearch').addEventListener('input',e=>drawClaims(e.target.value.trim().toLowerCase()));document.getElementById('gapGrid').innerHTML=DATA.gaps.map(g=>`<article class="gap-card"><span class="tag">${esc(g.importance)} · ${esc(g.reason)}</span><h3>${esc(g.field)}</h3><p>${esc(g.next)}</p></article>`).join('')||'<article class="gap-card"><h3>当前冻结版本无开放缺口</h3></article>'}
function products(){const grid=document.getElementById('productGrid');if(!grid)return;let selected=[];const cats=[...new Set(DATA.products.map(p=>p.category))];categoryFilter.innerHTML+=[...cats].sort().map(x=>`<option>${esc(x)}</option>`).join('');const visual=p=>`<img src="${esc(p.offlineAsset)}" alt="${esc(p.name)}" loading="lazy">`;function render(){let items=DATA.products.filter(p=>(!categoryFilter.value||p.category===categoryFilter.value)&&JSON.stringify(p).toLowerCase().includes(productSearch.value.toLowerCase()));items.sort((a,b)=>String(a[sortProducts.value]||'').localeCompare(String(b[sortProducts.value]||''),'zh-CN'));productCount.textContent=`展示 ${items.length} / ${DATA.products.length} 项已核验产品`;grid.innerHTML=items.map(p=>`<article class="product-card"><div class="product-visual">${visual(p)}</div><div class="product-content"><span class="eyebrow">${esc(p.category)}</span><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p><div class="product-meta"><span>${esc(p.brand||'品牌待核验')}</span><span>${esc(p.model||'型号待核验')}</span></div><div class="product-actions"><button class="detail" data-detail="${esc(p.id)}">查看证据详情</button><button data-compare="${esc(p.id)}">${selected.includes(p.id)?'已加入':'加入对比'}</button></div></div></article>`).join('');grid.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>show(DATA.products.find(p=>p.id===b.dataset.detail)));grid.querySelectorAll('[data-compare]').forEach(b=>b.onclick=()=>{const id=b.dataset.compare;if(selected.includes(id))selected=selected.filter(x=>x!==id);else if(selected.length<3)selected.push(id);render();compare()})}function show(p){dialogBody.innerHTML=`<span class="eyebrow">${esc(p.category)} · VERIFIED IMAGE ${esc(p.imageId)}</span><h2>${esc(p.name)}</h2><img src="${esc(p.offlineAsset)}" alt="${esc(p.name)}" style="max-width:100%;max-height:420px;display:block;margin:14px auto;object-fit:contain"><p>${esc(p.description)}</p><h3>参数</h3>${p.parameters.length?p.parameters.map(x=>`<p><b>${esc(x.name)}</b> ${esc(x.value)} ${esc(x.unit||'')}</p>`).join(''):'<p>暂无已核验参数，未进行推测补齐。</p>'}<p><a href="${esc(p.imageSource)}" target="_blank" rel="noreferrer">图片证据来源 ↗</a></p>`;productDialog.showModal()}function compare(){const items=selected.map(id=>DATA.products.find(p=>p.id===id));comparePanel.innerHTML=items.length?`<table><thead><tr><th>字段</th>${items.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody><tr><th>图片</th>${items.map(p=>`<td><img src="${esc(p.offlineAsset)}" alt="${esc(p.name)}" style="width:120px;height:90px;object-fit:contain"></td>`).join('')}</tr><tr><th>品牌</th>${items.map(p=>`<td>${esc(p.brand||'待核验')}</td>`).join('')}</tr><tr><th>型号</th>${items.map(p=>`<td>${esc(p.model||'待核验')}</td>`).join('')}</tr><tr><th>类别</th>${items.map(p=>`<td>${esc(p.category)}</td>`).join('')}</tr><tr><th>参数</th>${items.map(p=>`<td>${p.parameters.map(x=>`${esc(x.name)}: ${esc(x.value)} ${esc(x.unit||'')}`).join('<br>')||'待核验'}</td>`).join('')}</tr></tbody></table>`:'<p>从上方选择最多 3 项产品开始对比。</p>'}productSearch.oninput=render;categoryFilter.onchange=render;sortProducts.onchange=render;clearCompare.onclick=()=>{selected=[];render();compare()};document.querySelector('.dialog-close').onclick=()=>productDialog.close();render();compare()}
enterprise();products();
"""
