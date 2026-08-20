"""每日战略情报模块 tests：评分权重、去重、简报渲染、服务防重。"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from enterprise_energy_research.automation.intelligence import (
    DailyBrief,
    IntelligenceItem,
    IntelligenceService,
    RawIntelligenceItem,
    deduplicate,
    score_item,
    select_top,
)


def make_raw(**overrides) -> RawIntelligenceItem:
    payload = {
        "category": "政策监管",
        "title": "某省发布车网互动规模化试点政策",
        "fact": "某省发改委发布车网互动试点方案，计划建设120台60kW V2G设备，总投资2亿元。",
        "impact_company": "有利于V2G设备制造商获取订单",
        "source_name": "省发改委官网",
        "source_url": "https://example.com/policy",
        "published_at": "2026-08-19",
        "entity": "某省发改委",
    }
    payload.update(overrides)
    return RawIntelligenceItem.model_validate(payload)


class ScorerTests(unittest.TestCase):
    def test_score_weights(self):
        item = score_item(make_raw(), date(2026, 8, 19))
        self.assertGreaterEqual(item.score, 80)  # 政策+高相关+数字丰富
        self.assertEqual(item.score_reasons.__len__(), 5)  # 五维权重

    def test_breaking_threshold(self):
        strong = score_item(make_raw(), date(2026, 8, 19))
        self.assertEqual(strong.is_breaking, strong.score >= 90)

    def test_low_value_filtered(self):
        low = make_raw(category="技术与产品", title="某实验室发布论文",
                       fact="某团队发表储能材料实验室论文，无产业化信息。",
                       published_at="2026-01-01")
        scored = score_item(low, date(2026, 8, 19))
        self.assertLess(scored.score, 70)

    def test_deduplicate_keeps_highest(self):
        a = score_item(make_raw(title="同事件报道A", entity="某省发改委"), date(2026, 8, 19))
        b = score_item(make_raw(title="同事件报道B", entity="某省发改委", published_at="2026-01-01"), date(2026, 8, 19))
        unique = deduplicate([a, b])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0].title, "同事件报道A")

    def test_select_top_floor(self):
        items = [score_item(make_raw(published_at=f"2026-08-{d:02d}"), date(2026, 8, 19)) for d in (19, 18, 17)]
        selected = select_top(items, maximum=5, floor=70)
        self.assertLessEqual(len(selected), 3)


class BriefingTests(unittest.TestCase):
    def test_render_text_structure(self):
        item = IntelligenceItem(**make_raw().model_dump(), score=85.0, insight="行业意义", is_breaking=False)
        brief = DailyBrief(
            brief_date=date(2026, 8, 19),
            judgment="V2G政策从示范走向规模化，储能价格仍处下降周期。",
            items=[item],
            watch_list=["跟踪某省试点招标"],
            sources=["省发改委官网"],
        )
        text = brief.render_text()
        self.assertIn("V2G & 储能每日情报｜2026.08.19", text)
        self.assertIn("今日判断", text)
        self.assertIn("【政策监管｜高重要性】", text)
        self.assertIn("事实：", text)
        self.assertIn("判断：", text)
        self.assertIn("对公司：", text)
        self.assertIn("今日建议关注", text)
        self.assertIn("来源：省发改委官网", text)

    def test_breaking_alert(self):
        item = IntelligenceItem(**make_raw().model_dump(), score=95.0, insight="重大变化", is_breaking=True)
        brief = DailyBrief(brief_date=date(2026, 8, 19), items=[item])
        alert = brief.render_breaking(item)
        self.assertIn("V2G/储能重大情报｜高优先级", alert)
        self.assertIn("事件：", alert)
        self.assertIn("建议：", alert)


class ServiceTests(unittest.TestCase):
    def test_run_daily_idempotent(self):
        class FakeGateway:
            def structured(self, request):
                from enterprise_energy_research.automation.intelligence import IntelligenceExtraction

                if request.response_model is str:
                    return "V2G政策持续向规模化推进。"
                return IntelligenceExtraction(
                    category="政策监管", title="车网互动政策", fact="某省发布V2G试点方案。",
                    source_name="官网", source_url="https://example.com", published_at="2026-08-19",
                )

        class FakeAdapter:
            name = "fake"
            available = True
            sent = []

            def health(self):
                return type("H", (), {"available": True})()

            def search(self, request):
                from enterprise_energy_research.adapters.base import SearchHit, SearchResultEnvelope

                return SearchResultEnvelope(
                    adapter="fake", query_id=request.query_id, status="ok",
                    hits=[SearchHit(final_url="https://example.com/1", title="情报页", text="储能行业新闻内容" * 50,
                                    status="ok", retrieved_at="2026-08-19T00:00:00Z")],
                )

        with tempfile.TemporaryDirectory() as tmp:
            from enterprise_energy_research.automation.db import AutomationDatabase

            db = AutomationDatabase(f"sqlite:///{Path(tmp)}/i.db")
            try:
                service = IntelligenceService(
                    db, Path(tmp), adapters={"anysearch": FakeAdapter()}, gateway=FakeGateway(),
                )
                brief1 = service.run_daily(date(2026, 8, 19))
                self.assertIsNotNone(brief1)
                self.assertEqual(brief1.brief_date, date(2026, 8, 19))
                # 同日再次触发 → 幂等返回，不重复采集
                brief2 = service.run_daily(date(2026, 8, 19))
                self.assertEqual(brief1.brief_date, brief2.brief_date)
            finally:
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
