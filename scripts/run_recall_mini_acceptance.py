from __future__ import annotations

"""Non-publishing Daily Recall acceptance with a fixed-window baseline."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.base import SearchRequest
from enterprise_energy_research.automation.intelligence.collector import DAILY_QUERIES, IntelligenceCollector
from enterprise_energy_research.automation.intelligence.freshness import apply_freshness_gate
from enterprise_energy_research.automation.intelligence.scorer import deduplicate, score_item, select_top
from enterprise_energy_research.research.recall import RecallBudgetPolicy, SearchPass
from enterprise_energy_research.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def build_gateway():
    settings = Settings()
    if not (settings.deepseek_api_key or settings.openai_api_key):
        return None
    from enterprise_energy_research.gateway.http_json_gateway import HttpJsonModelGateway
    gateway = HttpJsonModelGateway(settings)
    return gateway if gateway.health()["available"] else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=72)
    parser.add_argument("--cutoff", default="")
    args = parser.parse_args()
    cutoff = (
        datetime.fromisoformat(args.cutoff)
        if args.cutoff else datetime.now(ZoneInfo("Asia/Shanghai")).replace(second=0, microsecond=0)
    )
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=ZoneInfo("Asia/Shanghai"))

    adapter = AnySearchCliAdapter()
    health = adapter.health(refresh=True)
    gateway = build_gateway()
    if not health.available or gateway is None:
        result = {
            "status": "BLOCKED", "anysearch_available": health.available,
            "anysearch_diagnostics": health.diagnostics,
            "gateway_available": gateway is not None,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 2

    start = (cutoff - timedelta(hours=24)).date().isoformat()
    end = (cutoff + timedelta(days=1)).date().isoformat()
    baseline_urls: set[str] = set()
    baseline_domains: set[str] = set()
    baseline_hits = 0
    for index, (query, _topic) in enumerate(DAILY_QUERIES):
        envelope = adapter.search(SearchRequest(
            query_id=f"BASE-{index:02d}", query=f"{query} 最新 发布 公告 after:{start} before:{end}",
            entity_id="intel", purpose="fixed-12-query acceptance baseline", max_results=1,
        ))
        baseline_hits += len(envelope.hits)
        for hit in envelope.hits:
            if not hit.final_url:
                continue
            canonical = str(hit.final_url).split("#", 1)[0].rstrip("/")
            baseline_urls.add(canonical)
            domain = urlparse(canonical).netloc.lower()
            if domain:
                baseline_domains.add(domain)

    minimums = {
        SearchPass.PRIMARY: 1, SearchPass.RECOVERY: 1,
        SearchPass.UPDATE: 1, SearchPass.SOURCE_PATROL: 1,
        SearchPass.FRONTIER: 2, SearchPass.ENTERPRISE_SEED: 1,
        SearchPass.ENTERPRISE_FRONTIER: 2, SearchPass.ANOMALY: 1,
    }
    policy = RecallBudgetPolicy(
        total_result_slots=args.slots,
        frontier_reserve=min(8, max(2, args.slots // 8)),
        minimum_by_pass=minimums,
    )
    collector = IntelligenceCollector(
        {"anysearch": adapter}, gateway, recall_policy=policy,
    )
    raw_items = collector.collect(current_time=cutoff)
    recall = collector.recall_result
    gate = apply_freshness_gate(raw_items, history=[], current_time=cutoff)
    scored = [score_item(item, cutoff) for item in gate.accepted]
    unique = deduplicate(scored)
    selected = select_top(unique)
    in_scope = select_top(unique, maximum=max(1, len(unique)))
    if recall is not None:
        recall.funnel.candidate_items = len(raw_items)
        recall.funnel.freshness_accepted = len(gate.accepted)
        recall.funnel.freshness_rejected = len(gate.rejected)
        recall.funnel.same_event_deduped = max(0, len(scored) - len(unique))
        recall.funnel.in_scope_items = len(in_scope)
        recall.funnel.final_selected = len(selected)
        recall.funnel.unknown_publication_time_count = sum(1 for item in gate.accepted if item.published_at_iso is None)
        recall.funnel.secondary_source_count = sum(1 for item in gate.accepted if not item.is_original_source)
        recall.funnel.original_source_count = sum(1 for item in gate.accepted if item.is_original_source)
    recall_urls = {
        item.canonical_url or item.url for item in (recall.url_dispositions if recall else [])
        if item.canonical_url or item.url
    }
    recall_domains = {urlparse(url).netloc.lower() for url in recall_urls if urlparse(url).netloc}
    result = {
        "status": recall.status.value if recall else "SOURCE_UNAVAILABLE",
        "cutoff": cutoff.isoformat(),
        "baseline": {
            "seed_queries": len(DAILY_QUERIES), "search_hits": baseline_hits,
            "unique_urls": len(baseline_urls), "unique_domains": len(baseline_domains),
        },
        "recall": {
            **(recall.funnel.model_dump(mode="json") if recall else {}),
            "query_variants": len(recall.query_specs) if recall else 0,
            "deferred_queries": len(recall.deferred_queries) if recall else 0,
            "source_lanes_attempted": sorted({item.source_lane.value for item in recall.query_specs}) if recall else [],
            "frontier_entries": len(recall.frontier_entries) if recall else 0,
            "unique_domains": len(recall_domains),
            "new_urls_vs_fixed12": len(recall_urls - baseline_urls),
            "new_domains_vs_fixed12": sorted(recall_domains - baseline_domains),
            "candidate_items": len(raw_items),
            "freshness_accepted": len(gate.accepted),
            "freshness_rejected": len(gate.rejected),
            "unknown_time_items": sum(1 for item in gate.accepted if item.published_at_iso is None),
            "secondary_sources": sum(1 for item in gate.accepted if not item.is_original_source),
            "original_sources": sum(1 for item in gate.accepted if item.is_original_source),
            "final_top5": [item.title for item in selected],
        },
        "budget_exhausted": bool(recall and recall.status.value == "RECALL_BUDGET_EXHAUSTED"),
        "collection_failures": collector.extraction_failures[:20],
        "publication": "DISABLED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
