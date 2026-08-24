"""每日战略情报模块 tests：评分权重、去重、简报渲染、服务防重。"""

import tempfile
import unittest
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from enterprise_energy_research.automation.intelligence import (
    DailyBrief,
    IntelligenceItem,
    IntelligenceService,
    RawIntelligenceItem,
    apply_freshness_gate,
    deduplicate,
    filter_last_24_hours,
    parse_exact_publication_time,
    score_item,
    select_top,
)

TZ = ZoneInfo("Asia/Shanghai")


def make_raw(**overrides) -> RawIntelligenceItem:
    payload = {
        "category": "政策监管",
        "title": "某省发布车网互动规模化试点政策",
        "fact": "某省发改委发布车网互动试点方案，计划建设120台60kW V2G设备，总投资2亿元。",
        "impact_company": "有利于V2G设备制造商获取订单",
        "source": "省发改委官网",
        "source_name": "省发改委官网",
        "source_url": "https://example.com/policy",
        "published_at": "2026-08-19 09:30",
        "original_published_at": "2026-08-19 09:30",
        "original_source_name": "省发改委官网",
        "original_source_url": "https://example.com/policy",
        "is_original_source": True,
        "publication_time_evidence": "发布时间：2026-08-19 09:30",
        "entity": "某省发改委",
        "topic": "policy",
        "source_type": "official_latest",
    }
    payload.update(overrides)
    if ("published_at" in overrides or "original_published_at" in overrides) and (
        "publication_time_evidence" not in overrides
    ):
        payload["publication_time_evidence"] = (
            "发布时间：" + str(payload.get("original_published_at") or payload.get("published_at") or "")
        )
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
                       published_at="2026-01-01 09:30",
                       original_published_at="2026-01-01 09:30")
        scored = score_item(low, date(2026, 8, 19))
        self.assertLess(scored.score, 70)

    def test_deduplicate_keeps_highest(self):
        a = score_item(make_raw(title="同事件报道A", entity="某省发改委"), date(2026, 8, 19))
        b = score_item(make_raw(
            title="同事件报道B", entity="某省发改委",
            published_at="2026-01-01 09:30", original_published_at="2026-01-01 09:30",
        ), date(2026, 8, 19))
        unique = deduplicate([a, b])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0].title, "同事件报道A")

    def test_deduplicate_prefers_official_source_for_same_event(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=TZ)
        official = apply_freshness_gate([make_raw()], current_time=now).accepted[0]
        media = apply_freshness_gate([make_raw(
            source="权威媒体", source_name="权威媒体",
            source_url="https://media.example/report",
            original_source_name="权威媒体",
            original_source_url="https://media.example/report",
            source_type="authoritative_media",
        )], current_time=now).accepted[0]
        selected = deduplicate([score_item(media, now), score_item(official, now)])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].source_type, "official_latest")

    def test_select_top_has_no_score_floor_and_orders_time_before_confidence(self):
        now = datetime(2026, 8, 22, 8, 0, tzinfo=TZ)
        newest_high = apply_freshness_gate([make_raw(
            title="最新官方储能材料论文",
            fact="官方发布储能材料实验结果，无产业化信息。",
            category="技术与产品",
            published_at="2026-08-22 07:45",
            original_published_at="2026-08-22 07:45",
        )], current_time=now).accepted[0]
        newer_low = apply_freshness_gate([make_raw(
            title="行业媒体转载V2G项目消息",
            source="行业媒体", source_name="行业媒体",
            source_url="https://media.example/newer",
            is_original_source=False, source_type="repost",
            published_at="2026-08-22 07:30",
            original_published_at="2026-08-20 10:00",
        )], current_time=now).accepted[0]
        older_high = apply_freshness_gate([make_raw(
            title="稍早官方V2G政策",
            source_url="https://example.com/older",
            original_source_url="https://example.com/older",
            published_at="2026-08-22 07:00",
            original_published_at="2026-08-22 07:00",
        )], current_time=now).accepted[0]
        items = [score_item(item, now) for item in (older_high, newer_low, newest_high)]
        selected = select_top(items, maximum=5, floor=99)
        self.assertEqual([item.title for item in selected], [
            "最新官方储能材料论文", "行业媒体转载V2G项目消息", "稍早官方V2G政策",
        ])
        self.assertLess(selected[0].score, 70)

    def test_select_top_rejects_generic_pv_tender_without_storage_or_v2g_scope(self):
        unrelated = score_item(make_raw(
            category="重大项目",
            title="产业园50MW分布式光伏工程量清单及最高投标限价编制服务",
            fact="项目启动招标，规模50MW，服务内容为工程量清单和最高投标限价编制。",
            impact_company="",
            topic="project",
        ), date(2026, 8, 19))
        self.assertGreaterEqual(unrelated.score, 70)
        self.assertEqual(select_top([unrelated]), [])

    def test_select_top_keeps_direct_storage_project(self):
        storage = score_item(make_raw(
            category="重大项目",
            title="产业园50MW/100MWh储能项目启动招标",
            fact="项目启动招标，储能规模50MW/100MWh。",
            topic="储能项目",
        ), date(2026, 8, 19))
        self.assertEqual(select_top([storage]), [storage])


class FreshnessGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 22, 8, 0, tzinfo=TZ)

    def test_primary_search_exact_24_hour_boundary_is_new(self):
        item = make_raw(
            published_at="2026-08-21 08:00",
            original_published_at="2026-08-21 08:00",
            search_layer="PRIMARY",
        )
        result = apply_freshness_gate([item], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertEqual(result.accepted[0].published_at_iso, self.now - timedelta(hours=24))

    def test_recovery_search_accepts_first_discovery_within_72_hours(self):
        item = make_raw(
            published_at="2026-08-20 08:01",
            original_published_at="2026-08-20 08:01",
            search_layer="RECOVERY",
        )
        result = apply_freshness_gate([item], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertEqual(result.accepted[0].search_layer, "RECOVERY")

    def test_first_discovery_older_than_72_hours_is_old(self):
        item = make_raw(
            published_at="2026-08-19 07:59",
            original_published_at="2026-08-19 07:59",
        )
        result = apply_freshness_gate([item], current_time=self.now)
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.evaluated[0].freshness_status, "OLD")
        self.assertIn("72-hour", result.rejected[0])

    def test_confirmed_date_only_inside_safe_72_hour_window_is_low_confidence_new(self):
        date_only = make_raw(published_at="2026-08-22", original_published_at="2026-08-22")
        result = apply_freshness_gate([date_only], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertEqual(result.accepted[0].publication_time_precision, "DATE_ONLY")
        self.assertEqual(result.accepted[0].confidence_level, "LOW")

    def test_unknown_date_is_retained_low_confidence_but_old_boundary_is_rejected(self):
        unknown = make_raw(published_at="", original_published_at="")
        boundary = make_raw(
            published_at="2026-08-19", original_published_at="2026-08-19",
            source_url="https://example.com/boundary",
            original_source_url="https://example.com/boundary",
        )
        result = apply_freshness_gate([unknown, boundary], current_time=self.now)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].published_at_iso, None)
        self.assertEqual(result.accepted[0].confidence_level, "LOW")
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(all(item.confidence_level == "LOW" for item in result.evaluated))

    def test_recent_repost_of_old_original_is_retained_from_current_page(self):
        repost = make_raw(
            source_name="行业转载站", source_url="https://media.example/repost",
            is_original_source=False,
            published_at="2026-08-22 07:00",
            original_published_at="2026-08-19 10:00",
            original_source_name="国家主管部门",
            original_source_url="https://gov.example/original",
            publication_time_evidence="原文发布于2026-08-19 10:00；转载于2026-08-22 07:00",
            source_type="repost",
        )
        result = apply_freshness_gate([repost], current_time=self.now)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertEqual(result.accepted[0].published_at_iso, datetime(2026, 8, 22, 7, 0, tzinfo=TZ))
        self.assertEqual(result.accepted[0].source_url, "https://media.example/repost")
        self.assertEqual(result.accepted[0].original_source_url, "https://gov.example/original")
        self.assertEqual(result.accepted[0].confidence_level, "LOW")

    def test_republished_old_article_inside_window_is_retained_for_awareness(self):
        item = make_raw(
            published_at="2026-08-22 07:00",
            original_published_at="2026-08-22 07:00",
            event_at="2026-08-01",
            is_republished_old=True,
        )
        result = apply_freshness_gate([item], current_time=self.now)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertIn("awareness", result.accepted[0].freshness_reason)

    def test_historical_event_with_concrete_update_is_updated(self):
        history = make_raw(
            published_at="2026-08-19 10:00",
            original_published_at="2026-08-19 10:00",
            first_seen_at=datetime(2026, 8, 19, 12, 0, tzinfo=TZ),
        )
        updated = make_raw(
            published_at="2026-08-19 10:00",
            original_published_at="2026-08-19 10:00",
            updated_at="2026-08-22 07:00",
            update_time_evidence="更新时间2026-08-22 07:00",
            is_substantive_update=True,
            update_facts="新增中标价格为0.62元/Wh，并披露120MWh项目规模。",
            publication_time_evidence="发布时间2026-08-19 10:00；更新时间2026-08-22 07:00",
            search_layer="UPDATE",
        )
        result = apply_freshness_gate([updated], history=[history], current_time=self.now)
        self.assertEqual(result.rejected, [])
        self.assertEqual(result.accepted[0].freshness_status, "UPDATED")
        self.assertEqual(result.accepted[0].updated_at_iso, datetime(2026, 8, 22, 7, 0, tzinfo=TZ))
        self.assertEqual(result.accepted[0].first_seen_at, history.first_seen_at)

    def test_updated_item_with_unknown_original_publication_is_low_confidence(self):
        history = make_raw(first_seen_at=datetime(2026, 8, 19, 12, 0, tzinfo=TZ))
        updated = make_raw(
            published_at="", original_published_at="", publication_time_evidence="",
            updated_at="2026-08-22 07:00",
            update_time_evidence="更新时间2026-08-22 07:00",
            is_substantive_update=True,
            update_facts="新增监管要求：聚合商须按月报送V2G放电数据。",
        )
        result = apply_freshness_gate([updated], history=[history], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "UPDATED")
        self.assertEqual(result.accepted[0].confidence_level, "LOW")

    def test_update_older_than_seven_days_is_old(self):
        history = make_raw(first_seen_at=datetime(2026, 8, 10, 12, 0, tzinfo=TZ))
        updated = make_raw(
            published_at="2026-08-10 09:30",
            original_published_at="2026-08-10 09:30",
            updated_at="2026-08-15 07:00",
            update_time_evidence="更新时间2026-08-15 07:00",
            is_substantive_update=True,
            update_facts="新增项目进度信息。",
        )
        result = apply_freshness_gate([updated], history=[history], current_time=self.now)
        self.assertEqual(result.accepted, [])
        self.assertIn("72-hour", result.rejected[0])

    def test_historical_event_with_recent_cosmetic_update_is_retained_as_new(self):
        history = make_raw(first_seen_at=datetime(2026, 8, 21, 8, 0, tzinfo=TZ))
        updated = make_raw(
            updated_at="2026-08-22 07:00",
            is_substantive_update=False,
            update_facts="",
        )
        result = apply_freshness_gate([updated], history=[history], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")
        self.assertIn("previously discovered", result.accepted[0].freshness_reason)

    def test_previously_sent_event_with_recent_publication_is_retained(self):
        history = make_raw(first_seen_at=datetime(2026, 8, 21, 8, 0, tzinfo=TZ))
        repeated = make_raw(title="某省车网互动试点政策最新报道")
        result = apply_freshness_gate([repeated], history=[history], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")

    def test_repeated_update_facts_on_recent_page_are_retained_as_new(self):
        history = make_raw(
            updated_at="2026-08-22 06:00",
            update_time_evidence="更新时间2026-08-22 06:00",
            is_substantive_update=True,
            update_facts="新增中标价格为0.62元/Wh。",
        )
        repeated = make_raw(
            updated_at="2026-08-22 07:00",
            update_time_evidence="更新时间2026-08-22 07:00",
            is_substantive_update=True,
            update_facts="新增中标价格为0.62元/Wh。",
        )
        result = apply_freshness_gate([repeated], history=[history], current_time=self.now)
        self.assertEqual(result.accepted[0].freshness_status, "NEW")

    def test_event_time_is_distinct_from_publication_time(self):
        item = make_raw(
            published_at="2026-08-22 07:00",
            original_published_at="2026-08-22 07:00",
            event_at="2026-08-18",
            event_time_evidence="项目于2026年8月18日完成并网",
        )
        result = apply_freshness_gate([item], current_time=self.now)
        self.assertIn("今日披露", result.accepted[0].disclosure_label)
        self.assertIn("2026年08月18日", result.accepted[0].disclosure_label)

    def test_future_time_and_unnamed_source_rejected_secondary_without_original_allowed(self):
        future = make_raw(
            published_at="2026-08-22 08:01", original_published_at="2026-08-22 08:01",
        )
        unknown_original = make_raw(
            is_original_source=False, original_source_url="", original_source_name="",
        )
        unnamed_original = make_raw(original_source_name="", source_name="", source="")
        result = apply_freshness_gate(
            [future, unknown_original, unnamed_original], current_time=self.now
        )
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].source_url, unknown_original.source_url)
        self.assertEqual(result.accepted[0].confidence_level, "LOW")
        self.assertEqual(len(result.rejected), 2)
        self.assertIn("source name or source URL", result.rejected[1])

    def test_parser_requires_hour_and_minute(self):
        self.assertIsNone(parse_exact_publication_time("2026-08-22"))
        self.assertEqual(
            parse_exact_publication_time("2026年8月22日 07:30"),
            datetime(2026, 8, 22, 7, 30, tzinfo=TZ),
        )

    def test_extraction_boundary_tolerates_common_model_transport_quirks(self):
        from enterprise_energy_research.automation.intelligence import IntelligenceExtraction

        extracted = IntelligenceExtraction.model_validate({
            "title": None,
            "fact": "某项目披露新增100MWh储能规模。",
            "published_at_iso": "2026-08-22",
            "numbers": [100, "MWh"],
            "unexpected_model_key": "ignored",
        })
        self.assertEqual(extracted.title, "")
        self.assertIsNone(extracted.published_at_iso)
        self.assertEqual(extracted.numbers, ["100", "MWh"])


class CollectorPipelineTests(unittest.TestCase):
    def test_daily_page_budget_covers_every_planned_search_layer(self):
        from unittest.mock import patch

        from enterprise_energy_research.automation.intelligence import IntelligenceCollector

        captured = {}

        class CapturingExecutor:
            def __init__(self, adapters):
                self.adapters = adapters

            def execute(self, plan):
                captured["plan"] = plan
                return []

        collector = IntelligenceCollector({}, object())
        with patch(
            "enterprise_energy_research.automation.intelligence.collector.SearchExecutor",
            CapturingExecutor,
        ):
            collector.collect(
                current_time=datetime(2026, 8, 24, 10, 0, tzinfo=TZ),
                update_targets=[make_raw(title=f"历史事件{i}") for i in range(12)],
            )

        plan = captured["plan"]
        self.assertEqual(len(plan.queries), 36)
        self.assertEqual(sum(query.max_results for query in plan.queries), 168)
        self.assertEqual(plan.budget["max_pages"], 168)

    def test_root_listing_pages_are_not_sent_to_the_llm(self):
        from enterprise_energy_research.adapters.base import (
            AdapterHealth, SearchHit, SearchResultEnvelope,
        )
        from enterprise_energy_research.automation.intelligence import IntelligenceCollector

        class FakeAnySearch:
            name = "anysearch"

            def health(self):
                return AdapterHealth(name=self.name, available=True)

            def search(self, request):
                return SearchResultEnvelope(
                    adapter=self.name, query_id=request.query_id, status="ok",
                    hits=[SearchHit(
                        final_url="https://news.example.com/", title="新闻首页",
                        text="多条新闻聚合列表", status="ok",
                        retrieved_at="2026-08-22T00:00:00Z", metadata={"snippet": True},
                    )],
                )

        class FailIfCalledGateway:
            def structured(self, request):
                raise AssertionError("listing root must not reach the LLM")

        collector = IntelligenceCollector(
            {"anysearch": FakeAnySearch()}, FailIfCalledGateway(),
            queries=[("储能 项目", "project")],
        )
        items = collector.collect(current_time=datetime(2026, 8, 22, 8, 0, tzinfo=TZ))
        self.assertEqual(items, [])
        self.assertEqual(collector.extraction_attempt_count, 0)

    def test_anysearch_snippet_is_hydrated_before_llm_extraction(self):
        from enterprise_energy_research.adapters.base import (
            AdapterHealth, SearchHit, SearchResultEnvelope,
        )
        from enterprise_energy_research.automation.intelligence import (
            IntelligenceCollector, IntelligenceExtraction,
        )

        class FakeAnySearch:
            name = "anysearch"

            def __init__(self):
                self.requests = []

            def health(self):
                return AdapterHealth(name=self.name, available=True)

            def search(self, request):
                self.requests.append(request)
                if request.metadata.get("url"):
                    return SearchResultEnvelope(
                        adapter=self.name, query_id=request.query_id, status="ok",
                        hits=[SearchHit(
                            final_url=request.metadata["url"], title="官方原文",
                            text="官方原文完整内容；发布时间：2026-08-22 07:30；项目规模100MWh。",
                            status="ok", retrieved_at="2026-08-22T00:00:00Z",
                            metadata={"snippet": False},
                        )],
                    )
                return SearchResultEnvelope(
                    adapter=self.name, query_id=request.query_id, status="ok",
                    hits=[SearchHit(
                        final_url="https://official.example/news/1", title="搜索摘要",
                        text="只有搜索摘要", status="ok",
                        retrieved_at="2026-08-22T00:00:00Z", metadata={"snippet": True},
                    )],
                )

        class FakeGateway:
            def __init__(self):
                self.prompts = []

            def structured(self, request):
                self.prompts.append(request.messages[0]["content"])
                return IntelligenceExtraction(
                    category="重大项目", title="新储能项目", fact="项目规模100MWh。",
                    source_name="官方机构", source_url="https://official.example/news/1",
                    published_at="2026-08-22 07:30", original_published_at="2026-08-22 07:30",
                    original_source_name="官方机构",
                    original_source_url="https://official.example/news/1",
                    is_original_source=True,
                    publication_time_evidence="发布时间：2026-08-22 07:30",
                    entity="示范项目", topic="储能项目", source_type="official_latest",
                )

        adapter = FakeAnySearch()
        gateway = FakeGateway()
        collector = IntelligenceCollector(
            {"anysearch": adapter}, gateway, queries=[("储能 项目", "project")]
        )
        items = collector.collect(current_time=datetime(2026, 8, 22, 8, 0, tzinfo=TZ))
        self.assertEqual(len(items), 1)
        self.assertEqual(collector.extraction_attempt_count, 1)
        self.assertEqual(collector.extraction_success_count, 1)
        self.assertTrue(any(request.metadata.get("url") for request in adapter.requests))
        self.assertIn("官方原文完整内容", gateway.prompts[0])
        self.assertNotIn("只有搜索摘要", gateway.prompts[0])


class BriefingTests(unittest.TestCase):
    def test_render_text_structure(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=TZ)
        recent, _ = filter_last_24_hours([make_raw()], now)
        item = IntelligenceItem(**recent[0].model_dump(), score=85.0, insight="行业意义", is_breaking=False)
        brief = DailyBrief(
            brief_date=date(2026, 8, 19),
            judgment="V2G政策从示范走向规模化，储能价格仍处下降周期。",
            items=[item],
            watch_list=["跟踪某省试点招标"],
            sources=["省发改委官网"],
            updated_at=now,
            window_start=now - timedelta(hours=24),
            window_end=now,
        )
        text = brief.render_text()
        self.assertIn("V2G & 储能每日情报｜2026.08.19", text)
        self.assertIn("情报截止：12:00｜24小时主搜｜72小时恢复｜7天更新检查", text)
        self.assertIn("今日判断", text)
        self.assertIn("①【政策｜高重要性｜2小时前】【NEW】", text)
        self.assertIn("时效说明：事件时间未确认，不作推测", text)
        self.assertIn("事实：", text)
        self.assertIn("判断：", text)
        self.assertIn("对公司：", text)
        self.assertIn("今日建议关注", text)
        self.assertIn("来源：省发改委官网", text)

    def test_low_confidence_stays_internal_and_is_not_rendered_as_a_label(self):
        now = datetime(2026, 8, 22, 8, 0, tzinfo=TZ)
        raw = make_raw(
            published_at="", original_published_at="", publication_time_evidence="",
        )
        accepted = apply_freshness_gate([raw], current_time=now).accepted[0]
        item = IntelligenceItem(**accepted.model_dump(), score=65.0)
        brief = DailyBrief(
            brief_date=now.date(), items=[item], updated_at=now,
            window_start=now - timedelta(hours=72), window_end=now,
            report_cutoff_time=now,
        )
        self.assertEqual(item.confidence_level, "LOW")
        self.assertIn("时间未核验", brief.render_text())
        self.assertNotIn("低可信", brief.render_text())

    def test_breaking_alert(self):
        item = IntelligenceItem(**make_raw().model_dump(), score=95.0, insight="重大变化", is_breaking=True)
        brief = DailyBrief(brief_date=date(2026, 8, 19), items=[item])
        alert = brief.render_breaking(item)
        self.assertIn("V2G/储能重大情报｜高优先级", alert)
        self.assertIn("事件：", alert)
        self.assertIn("建议：", alert)

    def test_empty_brief_uses_required_no_news_copy(self):
        now = datetime(2026, 8, 22, 8, 0, tzinfo=TZ)
        brief = DailyBrief(
            brief_date=now.date(), updated_at=now,
            window_start=now - timedelta(hours=24), window_end=now,
        )
        self.assertIn(
            "截至当前时间，未发现符合 NEW/UPDATED 标准的V2G及储能重大新增信息。",
            brief.render_text(),
        )

    def test_final_brief_rechecks_every_item_age(self):
        from pydantic import ValidationError

        now = datetime(2026, 8, 22, 8, 0, tzinfo=TZ)
        payload = make_raw().model_dump()
        payload["published_at_iso"] = now - timedelta(hours=73)
        payload["freshness_status"] = "NEW"
        stale = IntelligenceItem(**payload, score=85.0)
        with self.assertRaises(ValidationError):
            DailyBrief(
                brief_date=now.date(), items=[stale], updated_at=now,
                window_start=now - timedelta(hours=72), window_end=now,
                report_cutoff_time=now,
            )


class ServiceTests(unittest.TestCase):
    def test_run_daily_idempotent(self):
        class FakeGateway:
            def structured(self, request):
                from enterprise_energy_research.automation.intelligence import IntelligenceExtraction

                if request.response_model is str:
                    return "V2G政策持续向规模化推进。"
                return IntelligenceExtraction(
                    category="政策监管", title="车网互动政策", fact="某省发布V2G试点方案。",
                    source_name="官网", source_url="https://example.com",
                    published_at="2026-08-19 10:00",
                    original_published_at="2026-08-19 10:00",
                    original_source_name="官网", original_source_url="https://example.com",
                    is_original_source=True,
                    publication_time_evidence="发布时间：2026-08-19 10:00",
                )

        class FakeAdapter:
            name = "fake"
            available = True
            sent = []

            def health(self):
                return type("H", (), {"available": True})()

            def search(self, request):
                from enterprise_energy_research.adapters.base import SearchHit, SearchResultEnvelope

                self.sent.append(request)
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
                current_time = datetime(2026, 8, 19, 12, 0, tzinfo=TZ)
                brief1 = service.run_daily(date(2026, 8, 19), current_time=current_time)
                self.assertIsNotNone(brief1)
                self.assertEqual(brief1.brief_date, date(2026, 8, 19))
                self.assertEqual(len(brief1.items), 1)
                self.assertEqual(brief1.freshness_rejected_count, 0)
                self.assertTrue(any(request.query_id.startswith("IQ-P-") for request in FakeAdapter.sent))
                self.assertTrue(any(request.query_id.startswith("IQ-R-") for request in FakeAdapter.sent))
                self.assertTrue((Path(tmp) / "intelligence" / "freshness-ledger.json").is_file())
                audit_path = Path(tmp) / "intelligence" / "freshness-audit" / "2026-08-19.json"
                self.assertTrue(audit_path.is_file())
                candidate = json.loads(audit_path.read_text(encoding="utf-8"))["candidates"][0]
                required = {
                    "title", "source", "source_url", "published_at", "updated_at",
                    "event_at", "first_seen_at", "crawl_at", "company", "entity",
                    "topic", "content_hash", "freshness_status",
                }
                self.assertTrue(required.issubset(candidate))
                # 同日再次触发 → 幂等返回，不重复采集
                brief2 = service.run_daily(date(2026, 8, 19), current_time=current_time)
                self.assertEqual(brief1.brief_date, brief2.brief_date)
                # 次日再次发现且当前页面发布时间仍在窗口内，可继续作为传播信息进入日报。
                next_time = datetime(2026, 8, 20, 12, 0, tzinfo=TZ)
                brief3 = service.run_daily(date(2026, 8, 20), current_time=next_time)
                self.assertEqual(len(brief3.items), 1)
                self.assertEqual(brief3.items[0].freshness_status, "NEW")
                self.assertTrue(any(request.query_id.startswith("IQ-U-") for request in FakeAdapter.sent))
            finally:
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
