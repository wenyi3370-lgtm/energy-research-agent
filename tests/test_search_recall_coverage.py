from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from energy_research_agent.adapters.base import SearchHit, SearchResultEnvelope
from energy_research_agent.automation.intelligence.freshness import apply_freshness_gate
from energy_research_agent.automation.intelligence.models import DailyBrief, IntelligenceItem, RawIntelligenceItem
from energy_research_agent.automation.intelligence.scorer import deduplicate, score_item, select_top
from energy_research_agent.domain.models import Claim, FrozenResearchBundle
from energy_research_agent.research.recall import (
    AnomalyHunter, CoverageTracker, DailyRecallBudgetPlanner, EntityEventMiner, FrontierEntry,
    FrontierPriority, QueryExpander, QueryPriority, RecallAudit,
    RecallBudgetPolicy, RecallConvergenceTracker, RecallEngine, RecallProfile,
    RecallQuerySpec, RecallStatus, SearchFrontier, SearchPass, SourceLane,
    UrlDispositionReason,
)


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=TZ)


def raw(*, title="储能项目", published=NOW - timedelta(hours=2), confidence="HIGH", source_type="industry_media", event_key="event-1"):
    return RawIntelligenceItem(
        category="重大项目", title=title, fact="某储能项目新增100MWh并网规模。",
        source="行业媒体", source_name="行业媒体", source_url=f"https://news.example/{title}",
        published_at=published.strftime("%Y-%m-%d %H:%M") if published else "",
        published_at_iso=published, publication_time_precision="EXACT" if published else "UNKNOWN",
        publication_time_evidence="页面时间" if published else "",
        first_seen_at=NOW, crawl_at=NOW, topic="储能项目", company="某企业", entity="某项目",
        content_hash="a" * 64, event_key=event_key, source_type=source_type,
        is_original_source=source_type == "official_latest", confidence_level=confidence,
    )


def spec(query_id: str, search_pass: SearchPass, priority: QueryPriority, *, seed=False, desired=4):
    return RecallQuerySpec(
        query_id=query_id, topic="storage", query=query_id,
        search_pass=search_pass, source_lane=SourceLane.MEDIA_DISCOVERY,
        priority=priority, desired_results=desired, seed_query=seed,
    )


class TestBudgetAndExpansion:
    def test_01_daily_budget_is_dynamic_not_fixed_100(self):
        engine = RecallEngine(RecallProfile.DAILY_INTELLIGENCE)
        allocation = engine.plan_daily([("储能 项目", "storage")], current_time=NOW)
        assert allocation.used_slots != 100
        assert allocation.used_slots + allocation.reserved_frontier_slots <= 168

    def test_02_primary_recovery_update_fit_without_exhaustion(self):
        engine = RecallEngine(RecallProfile.DAILY_INTELLIGENCE)
        updates = [SimpleNamespace(entity="企业", title=f"事件{i}", topic="storage") for i in range(12)]
        seeds = [(f"储能 项目 {i}", "storage") for i in range(12)]
        allocation = engine.plan_daily(seeds, current_time=NOW, update_targets=updates)
        passes = {item.search_pass for item in allocation.planned}
        assert {SearchPass.PRIMARY, SearchPass.RECOVERY, SearchPass.UPDATE, SearchPass.SOURCE_PATROL} <= passes
        assert allocation.used_slots + allocation.reserved_frontier_slots <= 168

    def test_03_expansion_remains_strictly_bounded(self):
        planner = DailyRecallBudgetPlanner(RecallBudgetPolicy(total_result_slots=30, frontier_reserve=6))
        allocation = planner.allocate([spec(f"q{i}", SearchPass.PRIMARY, QueryPriority.P1) for i in range(50)])
        assert allocation.used_slots + 6 <= 30
        assert allocation.deferred

    def test_04_low_priority_defers_before_recovery_update(self):
        planner = DailyRecallBudgetPlanner(RecallBudgetPolicy(total_result_slots=20, frontier_reserve=4))
        candidates = [
            spec("r", SearchPass.RECOVERY, QueryPriority.P0),
            spec("u", SearchPass.UPDATE, QueryPriority.P0),
            *[spec(f"p{i}", SearchPass.PRIMARY, QueryPriority.P2) for i in range(12)],
        ]
        allocation = planner.allocate(candidates)
        planned_ids = {item.query_id for item in allocation.planned}
        assert {"r", "u"} <= planned_ids
        assert any(item.query_id.startswith("p") for item in allocation.deferred)

    def test_05_v2g_variants_cover_controlled_aliases(self):
        items = QueryExpander().daily_specs(
            [("V2G 车网互动 试点 政策", "v2g")],
            primary_start="2026-08-23", recovery_start="2026-08-21", end_exclusive="2026-08-25",
        )
        text = " ".join(item.query for item in items)
        assert "车网互动" in text and "反向放电" in text and "vehicle-to-grid" in text
        assert "双向充电" in " ".join(QueryExpander().topics["v2g"]["aliases"])

    def test_06_storage_variants_cover_bess(self):
        items = QueryExpander().daily_specs(
            [("新型储能 项目", "storage")],
            primary_start="2026-08-23", recovery_start="2026-08-21", end_exclusive="2026-08-25",
        )
        text = " ".join(item.query for item in items)
        aliases = " ".join(QueryExpander().topics["storage"]["aliases"])
        assert "储能" in text and "新型储能" in aliases and "独立储能" in aliases and "BESS" in text


class TestFrontier:
    def test_07_project_discovery_enters_frontier(self):
        entries = EntityEventMiner().mine(
            "江苏车网互动示范项目正式启动。", run_id="RUN", origin_query_id="Q", origin_url="https://x",
            profile=RecallProfile.DAILY_INTELLIGENCE,
        )
        assert any(item.entry_type == "project" for item in entries)

    def test_08_subsidiary_discovery_enters_frontier(self):
        entries = EntityEventMiner().mine(
            "四川时代新能源科技有限公司建设宜宾基地。", run_id="RUN", origin_query_id="Q", origin_url="https://x",
            profile=RecallProfile.DEEP_RESEARCH,
        )
        assert any(item.entry_type == "subsidiary" for item in entries)

    def test_09_alias_duplicate_not_repeated(self):
        frontier = SearchFrontier(RecallProfile.DEEP_RESEARCH)
        one = FrontierEntry(
            frontier_id="F1", run_id="R", entry_type="subsidiary", canonical_name="四川时代新能源科技有限公司",
            aliases=["四川时代"], origin_query_id="Q", origin_url="https://x",
            priority=FrontierPriority.P1, expansion_allowed=True, max_expansion_depth=2,
        )
        two = one.model_copy(update={"frontier_id": "F2", "canonical_name": "四川时代", "aliases": ["四川时代新能源科技有限公司"]})
        assert len(frontier.add([one, two])) == 1
        assert len(frontier.entries) == 1

    def test_10_daily_p0_p1_is_one_hop(self):
        frontier = SearchFrontier(RecallProfile.DAILY_INTELLIGENCE)
        entry = FrontierEntry(
            frontier_id="F", run_id="R", entry_type="project", canonical_name="车网互动示范项目",
            origin_query_id="Q", origin_url="https://x", priority=FrontierPriority.P0,
            expansion_allowed=True, expansion_depth=0, max_expansion_depth=1,
        )
        frontier.add([entry])
        assert frontier.followup_specs()
        deep = entry.model_copy(update={"frontier_id": "F2", "expansion_depth": 1})
        frontier2 = SearchFrontier(RecallProfile.DAILY_INTELLIGENCE); frontier2.add([deep])
        assert frontier2.followup_specs() == []

    def test_11_daily_p2_p3_do_not_expand(self):
        for priority in (FrontierPriority.P2, FrontierPriority.P3):
            frontier = SearchFrontier(RecallProfile.DAILY_INTELLIGENCE)
            frontier.add([FrontierEntry(
                frontier_id=priority.value, run_id="R", entry_type="other", canonical_name=priority.value,
                origin_query_id="Q", origin_url="https://x", priority=priority, expansion_allowed=False,
            )])
            assert frontier.followup_specs() == []

    def test_12_enterprise_p0_p1_support_bounded_deeper_expansion(self):
        frontier = SearchFrontier(RecallProfile.DEEP_RESEARCH)
        entry = FrontierEntry(
            frontier_id="F", run_id="R", entry_type="subsidiary", canonical_name="四川时代",
            origin_query_id="Q", origin_url="https://x", priority=FrontierPriority.P1,
            expansion_allowed=True, expansion_depth=1, max_expansion_depth=2,
        )
        frontier.add([entry])
        assert frontier.followup_specs()

    def test_13_enterprise_saturates_after_min_three_and_two_empty(self):
        tracker = RecallConvergenceTracker(RecallProfile.DEEP_RESEARCH)
        assert tracker.record_round(2) is None
        assert tracker.record_round(0) is None
        assert tracker.record_round(0) == RecallStatus.RECALL_SATURATED

    def test_14_daily_converges_on_empty_frontier_round(self):
        tracker = RecallConvergenceTracker(RecallProfile.DAILY_INTELLIGENCE)
        tracker.record_round(2)
        assert tracker.record_round(0) == RecallStatus.RECALL_SATURATED

    def test_15_budget_exhaustion_is_never_complete(self):
        tracker = RecallConvergenceTracker(RecallProfile.DEEP_RESEARCH)
        tracker.record_round(0); tracker.record_round(0); tracker.record_round(0)
        tracker.budget_exhausted = True
        assert tracker.status() == RecallStatus.RECALL_BUDGET_EXHAUSTED


class TestFreshnessPreservation:
    def test_16_recent_repost_is_new(self):
        result = apply_freshness_gate([raw(source_type="repost")], history=[], current_time=NOW)
        assert result.accepted[0].freshness_status == "NEW"

    def test_17_historical_event_recent_page_is_new(self):
        old = raw(title="旧报道", published=NOW - timedelta(days=5))
        current = raw(title="今日再披露", published=NOW - timedelta(hours=48))
        result = apply_freshness_gate([current], history=[old], current_time=NOW)
        assert result.accepted[0].freshness_status == "NEW"

    def test_18_current_page_over_72h_is_old(self):
        result = apply_freshness_gate([raw(published=NOW - timedelta(hours=73))], history=[], current_time=NOW)
        assert not result.accepted and result.evaluated[0].freshness_status == "OLD"

    def test_19_unknown_time_is_low_and_ranks_last(self):
        unknown = raw(title="未知时间", published=None)
        known = raw(title="已知时间", published=NOW - timedelta(hours=60), event_key="event-2")
        gate = apply_freshness_gate([unknown, known], history=[], current_time=NOW)
        scored = [score_item(item, NOW) for item in gate.accepted]
        ordered = select_top(scored)
        assert next(item for item in gate.accepted if item.title == "未知时间").confidence_level == "LOW"
        assert ordered[-1].title == "未知时间"

    def test_20_low_label_not_in_feishu_text(self):
        gate = apply_freshness_gate([raw(published=None)], history=[], current_time=NOW)
        item = score_item(gate.accepted[0], NOW)
        brief = DailyBrief(brief_date=NOW.date(), items=[item], updated_at=NOW, window_end=NOW, report_cutoff_time=NOW)
        assert "LOW" not in brief.render_text() and "低可信" not in brief.render_text()

    def test_21_newer_beats_older_high_confidence(self):
        newer = score_item(apply_freshness_gate([raw(title="新消息", confidence="LOW", event_key="n")], history=[], current_time=NOW).accepted[0], NOW)
        older = score_item(apply_freshness_gate([raw(title="旧消息", published=NOW - timedelta(hours=20), confidence="HIGH", event_key="o")], history=[], current_time=NOW).accepted[0], NOW)
        assert select_top([older, newer])[0].title == "新消息"

    def test_22_same_time_high_confidence_first(self):
        high = score_item(apply_freshness_gate([raw(title="高可信", confidence="HIGH", event_key="h")], history=[], current_time=NOW).accepted[0], NOW)
        low = score_item(apply_freshness_gate([raw(title="低可信", confidence="LOW", event_key="l")], history=[], current_time=NOW).accepted[0], NOW)
        high.confidence_level = "HIGH"
        low.confidence_level = "LOW"
        assert select_top([low, high])[0].title == "高可信"

    def test_23_score_floor_is_ignored(self):
        item = score_item(apply_freshness_gate([raw()], history=[], current_time=NOW).accepted[0], NOW)
        item.score = 1
        assert select_top([item], floor=99) == [item]

    def test_24_same_event_reposts_select_one(self):
        a = score_item(apply_freshness_gate([raw(title="报道A")], history=[], current_time=NOW).accepted[0], NOW)
        b = score_item(apply_freshness_gate([raw(title="报道B", published=NOW - timedelta(hours=3))], history=[], current_time=NOW).accepted[0], NOW)
        assert len(deduplicate([a, b])) == 1


class TestAuditAndEvidenceBoundary:
    def test_25_search_snippet_cannot_become_enterprise_claim(self):
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q", status="ok",
            hits=[SearchHit(final_url="https://x/a", title="snippet", text="摘要", status="partial", retrieved_at=NOW.isoformat(), metadata={"snippet": True})],
        )
        assert all(not isinstance(item, Claim) for item in envelope.hits)

    def test_26_frontier_entry_cannot_enter_frozen_claims(self):
        entry = FrontierEntry(
            frontier_id="F", run_id="R", entry_type="project", canonical_name="项目",
            origin_query_id="Q", origin_url="https://x",
        )
        assert not isinstance(entry, Claim)
        assert "FrontierEntry" not in str(FrozenResearchBundle.model_fields["claims"].annotation)

    def test_27_every_skipped_url_gets_disposition_reason(self):
        s = spec("q", SearchPass.PRIMARY, QueryPriority.P0)
        audit = RecallAudit(RecallProfile.DAILY_INTELLIGENCE, [s], total_budget=10)
        audit.disposition("q", "https://x", UrlDispositionReason.LISTING_ROOT)
        assert audit.dispositions[0].reason == UrlDispositionReason.LISTING_ROOT
        assert audit.query_audits["q"].listing_root_skipped == 1

    def test_28_coverage_matrix_has_stable_lane_schema(self):
        tracker = CoverageTracker(RecallProfile.DAILY_INTELLIGENCE)
        matrix = tracker.matrix().model_dump()
        topic_fields = set(type(tracker.matrix()).model_fields)
        assert {"topics", "chinese_query_count", "english_query_count", "coverage_complete", "status"} <= topic_fields
        from energy_research_agent.research.recall.models import TopicCoverage
        assert {lane.value for lane in SourceLane} <= set(TopicCoverage.model_fields)

    def test_29_recall_metrics_count_unique_domains(self):
        s = spec("q", SearchPass.PRIMARY, QueryPriority.P0)
        tracker = CoverageTracker(RecallProfile.DAILY_INTELLIGENCE)
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q", status="ok",
            hits=[
                SearchHit(final_url="https://a.example/1", text="x", status="ok", retrieved_at=NOW.isoformat()),
                SearchHit(final_url="https://b.example/2", text="x", status="ok", retrieved_at=NOW.isoformat()),
                SearchHit(final_url="https://a.example/3", text="x", status="ok", retrieved_at=NOW.isoformat()),
            ],
        )
        tracker.record(s, envelope)
        assert tracker.matrix().unique_domain_count == 2

    def test_30_collection_ok_does_not_equal_coverage_complete(self):
        brief = DailyBrief(brief_date=NOW.date(), collection_status="OK")
        assert brief.collection_status == "OK" and brief.coverage_complete is False
        with pytest.raises(ValueError):
            DailyBrief(brief_date=NOW.date(), collection_status="OK", coverage_complete=True)

    def test_31_anomaly_hunter_requires_critical_gap_and_high_priority(self):
        entry = FrontierEntry(
            frontier_id="F", run_id="R", entry_type="subsidiary", canonical_name="四川时代",
            origin_query_id="Q", origin_url="https://x", priority=FrontierPriority.P1,
            aliases=["四川时代新能源"], expansion_allowed=True,
        )
        assert AnomalyHunter().queries([entry], critical_gap=False) == []
        queries = AnomalyHunter().queries([entry], critical_gap=True)
        assert len(queries) == 1 and "文件编号" in queries[0].query and "PDF" in queries[0].query

    def test_32_source_roster_traversal_limits_are_bounded(self):
        from energy_research_agent.research.recall.source_lanes import SourceRoster
        roster = SourceRoster()
        assert 1 <= roster.max_listing_pages_per_source <= 3
        assert roster.max_articles_per_source >= 1

    def test_33_frontier_global_entry_count_is_bounded(self):
        frontier = SearchFrontier(RecallProfile.DAILY_INTELLIGENCE, max_entries=2)
        entries = [FrontierEntry(
            frontier_id=f"F{i}", run_id="R", entry_type="project", canonical_name=f"项目{i}",
            origin_query_id="Q", origin_url="https://x", priority=FrontierPriority.P0,
            expansion_allowed=True,
        ) for i in range(5)]
        frontier.add(entries)
        assert len(frontier.entries) == 2

    def test_34_navigation_acronyms_are_not_product_models(self):
        entries = EntityEventMiner().mine(
            "ABOUT GROUP PROFILE URL；产品型号 NP3 已发布。",
            run_id="R", origin_query_id="Q", origin_url="https://x",
            profile=RecallProfile.DEEP_RESEARCH,
        )
        models = {item.canonical_name for item in entries if item.entry_type == "product_model"}
        assert "NP3" in models
        assert not {"ABOUT", "GROUP", "PROFILE", "URL"} & models
