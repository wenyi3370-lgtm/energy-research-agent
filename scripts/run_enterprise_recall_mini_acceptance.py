from __future__ import annotations

"""Discovery-only enterprise recall comparison; no Claim/freeze/publication."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from energy_research_agent.adapters.anysearch import AnySearchCliAdapter
from energy_research_agent.adapters.base import SearchRequest
from energy_research_agent.research.recall import (
    EntityEventMiner, RecallProfile, RecallStatus, SearchFrontier,
)
from energy_research_agent.research.recall.recall_engine import RecallEngine


TOPICS = [
    "company_identity", "subsidiaries", "factories", "products",
    "product_models", "customers", "financials", "energy_projects",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=24)
    args = parser.parse_args()
    adapter = AnySearchCliAdapter()
    engine = RecallEngine(RecallProfile.DEEP_RESEARCH)
    allocation = engine.plan_enterprise(args.company, TOPICS, max_slots=args.slots)
    envelopes = engine.execute(
        allocation.planned, {"anysearch": adapter},
        run_id="enterprise-recall-acceptance", canonical_name=args.company,
    )
    urls: dict[str, tuple[str, str]] = {}
    domains: set[str] = set()
    for envelope in envelopes:
        for hit in envelope.hits:
            if not hit.final_url:
                continue
            canonical = str(hit.final_url).split("#", 1)[0].rstrip("/")
            urls.setdefault(canonical, (envelope.query_id, hit.title or ""))
            domain = urlparse(canonical).netloc.lower()
            if domain:
                domains.add(domain)

    miner = EntityEventMiner()
    frontier = SearchFrontier(RecallProfile.DEEP_RESEARCH, max_entries=80)
    hydrated = 0
    hydration_failed = 0
    for url, (query_id, _title) in list(urls.items())[:8]:
        result = adapter.search(SearchRequest(
            query_id=query_id, query=url, entity_id="acceptance",
            purpose="enterprise recall target-page hydration",
            max_results=1, metadata={"url": url, "extract": True},
        ))
        full = next((hit for hit in result.hits if hit.text), None)
        if full is None:
            hydration_failed += 1
            continue
        hydrated += 1
        frontier.add(miner.mine(
            full.text or "", run_id="enterprise-recall-acceptance",
            origin_query_id=query_id, origin_url=url,
            profile=RecallProfile.DEEP_RESEARCH,
        ))
    followup_specs = frontier.followup_specs(max_queries=3)
    followup_allocation = engine.budget_planner.allocate_frontier(
        followup_specs, remaining_slots=allocation.reserved_frontier_slots,
    )
    followups = engine.execute(
        followup_allocation.planned, {"anysearch": adapter},
        run_id="enterprise-recall-acceptance", canonical_name=args.company,
    )
    followup_hits = sum(len(item.hits) for item in followups)
    result = {
        "company": args.company,
        "status": RecallStatus.BOUNDED_COMPLETE.value,
        "query_variants": len(allocation.planned),
        "deferred_queries": len(allocation.deferred),
        "result_slots_used": allocation.used_slots + followup_allocation.used_slots,
        "budget_exhausted": False,
        "search_hits": sum(len(item.hits) for item in envelopes) + followup_hits,
        "unique_urls": len(urls),
        "unique_domains": len(domains),
        "hydration_attempts": min(8, len(urls)),
        "hydration_successes": hydrated,
        "hydration_failures": hydration_failed,
        "frontier_entries": len(frontier.entries),
        "frontier_followup_queries": len(followup_allocation.planned),
        "frontier_types": {
            kind: sum(1 for item in frontier.entries if item.entry_type == kind)
            for kind in sorted({item.entry_type for item in frontier.entries})
        },
        "frontier_names": [item.canonical_name for item in frontier.entries[:20]],
        "verified_claims": 0,
        "evidence_boundary": "DISCOVERY_ONLY; FrontierEntry is not Claim",
        "publication": "DISABLED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
