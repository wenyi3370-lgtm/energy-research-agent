"""一次性真实迷你研究：AnySearch 真实搜索 → CATL 官网真实抽取 → DeepSeek
真实结构化抽取 → Phase3/Freeze → diagram-design HTML/Word 发布。"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
ROOT = Path(__file__).resolve().parents[1]

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.base import SearchRequest
from enterprise_energy_research.domain.enums import RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    ExtractedClaim, ExtractedEntity, ExtractedEvidenceBatch, RunManifest,
)
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import Settings, load_yaml


def main() -> int:
    adapter = AnySearchCliAdapter()
    requests = [
        SearchRequest(query_id="LIVE-1", query='"宁德时代" 官网 年报 公司简介 营业收入', entity_id="LIVE",
                      purpose="R1 official identity discovery", max_results=3),
        SearchRequest(query_id="LIVE-2", query='"宁德时代" 储能系统 产品 型号 参数', entity_id="LIVE",
                      purpose="R1 product catalog discovery", max_results=3),
        SearchRequest(query_id="LIVE-3", query='"宁德时代" 生产基地 产能 工厂 能耗 绿色工厂', entity_id="LIVE",
                      purpose="R1 factory and energy discovery", max_results=3),
    ]
    print("== 1) AnySearch 真实搜索 ==")
    envelopes = [adapter.search(request) for request in requests]
    hits = [hit for env in envelopes for hit in env.hits]
    print(f"    命中 {len(hits)} 条:")
    for hit in hits[:6]:
        print("    -", hit.title, "|", hit.final_url)

    # 对官网做一次真实全文抽取
    official = next((hit for hit in hits if "catl.com" in (hit.final_url or "")), hits[0] if hits else None)
    full_text = ""
    if official:
        print("== 2) AnySearch 全文抽取:", official.final_url, "==")
        extracted = adapter.search(SearchRequest(
            query_id="LIVE-FULL", query=str(official.final_url), entity_id="LIVE",
            purpose="official page fulltext", metadata={"url": str(official.final_url), "extract": True},
        ))
        for hit in extracted.hits:
            if hit.text:
                full_text = hit.text
                break
        print(f"    全文 {len(full_text)} 字符")
    full_text = full_text or " ".join(hit.text or "" for hit in hits)
    text_sample = full_text[:6000]

    print("== 3) DeepSeek 真实结构化抽取 ==")
    from enterprise_energy_research.gateway.base import ModelRequest
    from enterprise_energy_research.gateway.http_json_gateway import HttpJsonModelGateway
    settings = Settings()
    gateway = HttpJsonModelGateway(settings)
    prompt = (
        "从以下关于宁德时代（CATL）的公开网页文本中，只提取文本明确陈述的事实，输出 JSON：\n"
        '{"company_name": str, "core_business": str, "revenue_text": str, "product_families": [str], '
        '"factory_mentions": [str]}\n'
        "不得编造文本中不存在的数字或事实；缺失字段用空字符串/空数组。\n\n文本：\n" + text_sample
    )
    response = gateway.complete(ModelRequest(
        purpose="live-mini-extraction",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=900,
    ))
    payload = json.loads(response.content.strip().strip("`").lstrip("json"))
    print("    DeepSeek 返回:", json.dumps(payload, ensure_ascii=False)[:400])

    company = str(payload.get("company_name") or "宁德时代新能源科技股份有限公司")
    revenue_text = str(payload.get("revenue_text") or "")
    revenue_value: float | int | str | None = None
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*亿元", revenue_text)
    if match:
        revenue_value = match.group(1)

    print("== 4) 组装证据批 → Phase3 → Freeze ==")
    from enterprise_energy_research.domain.models import ExtractedProduct
    batches = [ExtractedEvidenceBatch(
        source_url=official.final_url if official else "https://www.catl.com/",
        source_title=official.title if official else "CATL 官网",
        source_kind="official_company",
        extraction_method="model_structured",
        entities=[ExtractedEntity(
            entity_key="catl", canonical_name=company, entity_type="company",
            official_website="https://www.catl.com/",
        )],
        claims=[
            ExtractedClaim(entity_key="catl", field_name="core_business",
                           value=str(payload.get("core_business") or ""), value_type="string",
                           raw_text=str(payload.get("core_business") or ""), context_text=text_sample[:300]),
        ] + ([ExtractedClaim(entity_key="catl", field_name="revenue", value=revenue_value,
                             value_type="number", unit="亿元", raw_text=revenue_text,
                             context_text=text_sample[:300])] if revenue_value else []),
        products=[ExtractedProduct(product_key=f"prod{i}", entity_key="catl", name=name)
                  for i, name in enumerate((payload.get("product_families") or [])[:3], 1)],
    )]

    with tempfile.TemporaryDirectory() as temp:
        work = ROOT / "build" / "live_mini"
        work.mkdir(parents=True, exist_ok=True)
        store = EvidenceStore(work / "evidence.sqlite3")
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store.create_run(RunManifest(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                                     config_hash="live-mini", code_version="0.9.1",
                                     model_gateway={"mode": "live"}))
        state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
            company, batches, output_dir=work / "freeze",
        )
        print("    Phase3 状态:", state.status)
        bundle = FreezeService(store).load_bundle(state.freeze_id)
        print("    冻结实体:", len(bundle.entities), "| 主张:", len(bundle.claims),
              "| 产品:", len(bundle.products), "| 来源:", len(bundle.sources))

        print("== 5) diagram-design 发布（HTML + Word）==")
        from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
        from enterprise_energy_research.artifacts.word import FrozenWordPublisher
        html_binding = next(item for item in manifest.artifacts if item.type.value == "enterprise_html")
        word_binding = next(item for item in manifest.artifacts if item.type.value == "word")
        html_target = work / "enterprise_research_dashboard.html"
        word_target = work / "enterprise_research_report.docx"
        hr = FrozenHtmlPublisher(html_binding.type).publish(bundle, html_binding, html_target)
        wr = FrozenWordPublisher().publish(bundle, word_binding, word_target)
        print("    HTML:", hr.status, "| Word:", wr.status)
        html_text = html_target.read_text(encoding="utf-8")
        import zipfile
        with zipfile.ZipFile(word_target) as archive:
            word_text = archive.read("word/document.xml").decode("utf-8")
        print("    HTML 内联 <svg>:", html_text.count("<svg "))
        print("    Word <w:drawing>:", word_text.count("<w:drawing>"))
        figures = work / "enterprise_research_report_assets" / "figures"
        pngs = sorted(figures.glob("*.png"))
        print("    PNG 图:", [(p.name, p.stat().st_size) for p in pngs])
        forbidden = [t for t in ("lieflat", "renderer", "qa_report", "冻结数据不足") if t in html_text.lower()]
        print("    用户报告禁止词:", forbidden or "无 ✓")
        narrative_path = html_target.parent / f"{html_target.stem}_assets" / "narrative.json"
        narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
        print("    叙事章节:", [chapter["title"] for chapter in narrative["chapters"]])
        print("    决策问题:", narrative["decision_questions"][:2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
