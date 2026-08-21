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
                results.append(self._blocked(query, ["Research page budget exhausted"]))
                continue
            adapter = self.adapters.get(query.adapter_preference)
            if adapter is None:
                results.append(self._blocked(
                    query, [f"Approved adapter is not configured: {query.adapter_preference}"],
                ))
                continue
            request = SearchRequest(
                query_id=query.query_id, query=query.query, entity_id=query.entity_id,
                purpose=query.purpose, preferred_source_levels=[str(item) for item in query.preferred_source_levels],
                max_results=min(query.max_results, page_budget - used_pages), requires_browser=query.requires_browser,
                metadata={
                    "collection_round": query.collection_round,
                    "round_goal": query.round_goal,
                    "high_priority": query.high_priority,
                    "raw_capture_required": query.raw_capture_required,
                },
                # P0-2: the full research goal travels with the request so the
                # extraction stage knows what this page is being searched FOR.
                topic=query.topic,
                collection_round=query.collection_round,
                round_goal=query.round_goal,
                trigger=query.trigger,
                target_gap_ids=list(query.target_gap_ids),
                target_conflict_ids=list(query.target_conflict_ids),
                target_claim_ids=list(query.target_claim_ids),
                canonical_company_name=self._canonical_name_for(query, plan),
                expected_fields=self._expected_fields_for(query),
            )
            result = adapter.search(request)
            # Echo the goal context onto the envelope so later pipeline stages
            # (EvidenceExtractor, trace) never lose it.
            result = result.model_copy(update={
                "topic": query.topic,
                "purpose": query.purpose,
                "collection_round": query.collection_round,
                "round_goal": query.round_goal,
                "trigger": query.trigger,
                "target_gap_ids": list(query.target_gap_ids),
                "target_conflict_ids": list(query.target_conflict_ids),
                "target_claim_ids": list(query.target_claim_ids),
                "canonical_company_name": request.canonical_company_name,
                "expected_fields": request.expected_fields,
            })
            used_pages += len(result.hits)
            results.append(result)
        return results

    @staticmethod
    def _blocked(query, diagnostics: list[str]) -> SearchResultEnvelope:
        return SearchResultEnvelope(
            adapter=query.adapter_preference, query_id=query.query_id, status="blocked",
            diagnostics=diagnostics,
            topic=query.topic, purpose=query.purpose,
            collection_round=query.collection_round, round_goal=query.round_goal,
            trigger=query.trigger,
            target_gap_ids=list(query.target_gap_ids),
            target_conflict_ids=list(query.target_conflict_ids),
            target_claim_ids=list(query.target_claim_ids),
        )

    @staticmethod
    def _canonical_name_for(query, plan: ResearchPlan) -> str | None:
        return query.canonical_company_name or plan.canonical_company_name

    @staticmethod
    def _expected_fields_for(query) -> list[str]:
        if query.expected_fields:
            return list(query.expected_fields)
        from enterprise_energy_research.research.contracts import contract_for
        return list(contract_for(query.topic).expected_fields)
