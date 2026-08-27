"""T2 修复回归：蒸馏表拆批调用合并 + 五观正文驱动 PPT storyline。"""
from __future__ import annotations

import csv
from pathlib import Path

from energy_research_agent.agent.market_production import (
    MarketProductionPipeline,
    MarketTables,
    AnalysisBundle,
    InsightBody,
)
from energy_research_agent.gateway.base import StructuredRequest


class _FakeGateway:
    """按 purpose 分发结构化结果，并记录全部请求。"""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requests: list[StructuredRequest] = []

    def structured(self, request: StructuredRequest):
        self.requests.append(request)
        for key, value in self.responses.items():
            if key in request.purpose:
                return value
        raise AssertionError(f"unexpected purpose: {request.purpose}")


_HEADERS = {
    "01_Market_Scan.csv": ["record_id", "metric", "year_period", "raw_value", "currency", "source_id"],
    "02_Competitor_List.csv": ["brand", "player_type", "country"],
    "03_Model_Identifier_Check.csv": ["model_id", "brand", "exact_model"],
    "04_Product_Parameters.csv": ["parameter_id", "brand", "exact_model"],
    "05_Pricing_Channel.csv": ["pricing_id", "brand", "exact_model", "list_price", "currency"],
    "06_Channel_Service.csv": ["brand", "exact_model", "online_channel"],
    "07_Raw_Reviews.csv": ["review_id", "platform", "original_text"],
    "08_Review_Coding.csv": ["theme_id", "theme", "frequency_count"],
    "09_Integrated_Matrix.csv": ["competitor_id", "brand", "price", "capacity_kwh", "user_pain_score"],
    "10_SWOT_Opportunity.csv": ["brand", "opportunity", "opportunity_priority", "risk_level"],
}


def _make_project(tmp_path: Path) -> Path:
    for name, header in _HEADERS.items():
        with (tmp_path / name).open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerow(header)
    (tmp_path / "00_Source_Ledger.csv").write_text(
        "source_id,source_title,source_url,local_file_path,source_type,verification_status\n"
        "SRC-0001,示例来源,https://example.com,,web,unverified\n",
        encoding="utf-8",
    )
    return tmp_path


def test_table_distillation_split_into_two_batches_and_merged(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    batch_a = MarketTables(market_scan=[{"record_id": "MS-001", "metric": "market_size",
                                         "year_period": "2024", "raw_value": "100",
                                         "currency": "EUR", "source_id": "SRC-0001"}])
    batch_b = MarketTables(pricing_channel=[{"pricing_id": "PR-001", "brand": "A",
                                             "exact_model": "A1", "list_price": "999",
                                             "currency": "EUR"}],
                           raw_reviews=[{"review_id": "RV-001", "platform": "amazon",
                                         "original_text": "证据未含用户评论"}])
    gateway = _FakeGateway({
        "market_distill_tables_b": batch_b,  # 更具体的 purpose 先匹配
        "market_distill_tables": batch_a,
        "market_distill_analysis": AnalysisBundle(),
        "market_distill_insight_body_p2": InsightBody(),
        "market_distill_insight_body": InsightBody(),
    })
    pipeline = MarketProductionPipeline(project, gateway, scripts_dir=tmp_path)
    pipeline._distill(pipeline._ledger_rows(), {"region": "德国", "category": "户用储能"})

    purposes = [request.purpose for request in gateway.requests]
    assert purposes.count("agent.market_distill_tables") == 1
    assert purposes.count("agent.market_distill_tables_b") == 1
    prompt_a = next(r.messages[0]["content"] for r in gateway.requests
                    if r.purpose == "agent.market_distill_tables")
    prompt_b = next(r.messages[0]["content"] for r in gateway.requests
                    if r.purpose == "agent.market_distill_tables_b")
    assert "05_Pricing_Channel" not in prompt_a  # 价格表已移入第二批
    assert "03_Model_Identifier_Check" in prompt_a
    assert "07_Raw_Reviews" in prompt_b

    with (project / "05_Pricing_Channel.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and rows[0]["pricing_id"] == "PR-001"  # 第二批结果合并落表
    with (project / "01_Market_Scan.csv").open(encoding="utf-8-sig", newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 1


INSIGHT_BODY = """---
method_id: embedded-market-insight-five-views-v1
status: final
---

## 一、看宏观
德国电价与补贴政策构成户用储能的核心驱动。政策窗口正在收窄。

### 对本企业/产品的启示
进入窗口需以电价证据为准。

## 五、看竞争
本地品牌渠道深、外来品牌靠性价比切入。

## 八、优先行动建议
先完成准入认证与电价口径核对。再小批量试点验证单位经济性。

## 九、风险与不确定性
政策回退风险存在。
"""


def _write_insight(project: Path, body: str) -> None:
    target = project / "intermediate" / "market-insight" / "market_insight_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_load_insight_sections_parses_chapters_and_rejects_skeleton(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    pipeline = MarketProductionPipeline(project, None, scripts_dir=tmp_path)
    assert pipeline._load_insight_sections() == {}  # 无正文文件
    _write_insight(project, INSIGHT_BODY)
    sections = pipeline._load_insight_sections()
    assert "一、看宏观" in sections and any("政策窗口" in line for line in sections["一、看宏观"])
    _write_insight(project, "---\nstatus: draft\n---\n\n[[填写]] 占位")
    assert pipeline._load_insight_sections() == {}  # 模板骨架拒绝入 storyline


def test_ppt_plan_adds_five_views_slides_when_insight_present(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _write_insight(project, INSIGHT_BODY)
    pipeline = MarketProductionPipeline(project, None, scripts_dir=tmp_path)
    plan = pipeline._ppt_plan({"region": "德国", "category": "户用储能"})
    layouts = [slide["layout"] for slide in plan["slides"]]
    titles = [slide.get("title", "") for slide in plan["slides"]]
    assert any(layout == "comparison" and "五观洞察" in title
               for layout, title in zip(layouts, titles))
    assert any(layout == "decision" and "优先行动建议" in title
               for layout, title in zip(layouts, titles))


def test_ppt_plan_without_insight_keeps_deterministic_deck(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    pipeline = MarketProductionPipeline(project, None, scripts_dir=tmp_path)
    plan = pipeline._ppt_plan({"region": "德国", "category": "户用储能"})
    titles = [slide.get("title", "") for slide in plan["slides"]]
    assert not any("五观洞察" in title for title in titles)
    assert plan["slides"][0]["layout"] == "cover"
