from __future__ import annotations

from enterprise_energy_research.adapters.base import SearchAdapter, SearchRequest, SearchResultEnvelope
from enterprise_energy_research.domain.models import ResearchPlan


class SearchExecutor:
    def __init__(self, adapters: dict[str, SearchAdapter]) -> None:
        self.adapters = adapters

    def execute(self, plan: ResearchPlan) -> list[SearchResultEnvelope]:
        results: list[SearchResultEnvelope] = []
        page_budget = int(plan.budget.get("max_pages", 120))
        used_pages = 0
        round_order = {"R1": 0, "R2": 1, "R3": 2}
        ordered_queries = sorted(enumerate(plan.queries), key=lambda row: (round_order[row[1].collection_round], row[0]))
        for _, query in ordered_queries:
            if used_pages >= page_budget:
                results.append(SearchResultEnvelope(
                    adapter=query.adapter_preference, query_id=query.query_id, status="blocked",
                    diagnostics=["Research page budget exhausted"],
                ))
                continue
            adapter = self.adapters.get(query.adapter_preference)
            if adapter is None:
                results.append(SearchResultEnvelope(
                    adapter=query.adapter_preference, query_id=query.query_id, status="blocked",
                    diagnostics=[f"Approved adapter is not configured: {query.adapter_preference}"],
                ))
                continue
            result = adapter.search(SearchRequest(
                query_id=query.query_id, query=query.query, entity_id=query.entity_id,
                purpose=query.purpose, preferred_source_levels=[str(item) for item in query.preferred_source_levels],
                max_results=min(query.max_results, page_budget - used_pages), requires_browser=query.requires_browser,
                metadata={
                    "collection_round": query.collection_round,
                    "round_goal": query.round_goal,
                    "high_priority": query.high_priority,
                    "raw_capture_required": query.raw_capture_required,
                },
            ))
            used_pages += len(result.hits)
            results.append(result)
        return results
