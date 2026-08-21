"""P0-2 / P0-3 regression: the ResearchGoal travels from the planner through
the executor into the EvidenceExtractor prompt — topic, purpose, round,
gap/conflict targets, canonical name and expected fields are never lost.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from enterprise_energy_research.adapters.base import SearchRequest, SearchResultEnvelope
from enterprise_energy_research.domain.enums import EnterpriseComplexity
from enterprise_energy_research.domain.models import ResearchPlan, ResearchQuery
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.research.contracts import GOAL_CONTRACTS, contract_for
from enterprise_energy_research.research.executor import SearchExecutor
from enterprise_energy_research.research.extractor import EvidenceExtractor, extract_goal_context
from enterprise_energy_research.research.planner import GOAL_FAMILIES, ResearchPlanner


class _CapturingAdapter:
    name = "anysearch"

    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    def health(self):
        from enterprise_energy_research.adapters.base import AdapterHealth
        return AdapterHealth(name=self.name, available=True)

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        self.requests.append(request)
        return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="ok", hits=[])


def _query(**overrides) -> ResearchQuery:
    payload = {
        "query_id": new_sortable_id("QUERY"), "entity_id": "ENT-1", "topic": "factories",
        "query": '"ACME" 生产基地 工厂', "purpose": "R1 coverage: collect factories evidence for ACME",
        "collection_round": "R1", "round_goal": "coverage", "trigger": "baseline",
        "canonical_company_name": "ACME科技有限公司",
        "expected_fields": ["factory_name", "operator", "capacity"],
    }
    payload.update(overrides)
    return ResearchQuery.model_validate(payload)


class ExtractionContractTests(unittest.TestCase):
    def test_extractor_receives_goal_context(self) -> None:
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q1", status="ok",
            topic="factories", purpose="R2 gap-driven search for GAP-1", collection_round="R2",
            round_goal="depth", canonical_company_name="ACME",
            expected_fields=["factory_name", "capacity"],
            hits=[],
        )
        context = extract_goal_context(envelope)
        self.assertEqual(context["topic"], "factories")
        self.assertEqual(context["collection_round"], "R2")
        prompt = EvidenceExtractor(None)._build_prompt(envelope, type("H", (), {
            "final_url": "https://example.com/factory", "title": "厂区页", "text": "厂区介绍",
        })())
        self.assertIn("CURRENT RESEARCH GOAL:", prompt)
        self.assertIn("factories", prompt)
        self.assertIn("RESEARCH QUESTION:", prompt)
        self.assertIn("查明企业主要生产基地、运营主体及生产活动", prompt)
        self.assertIn("PRIORITY:", prompt)
        self.assertIn("RULE:", prompt)

    def test_extractor_receives_expected_fields(self) -> None:
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q1", status="ok",
            topic="factories",
            expected_fields=["factory_name", "operator", "address", "capacity"],
        )
        prompt = EvidenceExtractor(None)._build_prompt(envelope, type("H", (), {
            "final_url": "https://example.com/f", "title": "t", "text": "x",
        })())
        for field in ("factory_name", "operator", "address", "capacity"):
            self.assertIn(field, prompt)

    def test_extractor_receives_round_context(self) -> None:
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q1", status="ok", topic="factories",
            collection_round="R2", round_goal="depth",
        )
        context = extract_goal_context(envelope)
        self.assertEqual(context["collection_round"], "R2")
        self.assertEqual(context["round_goal"], "depth")

    def test_extractor_receives_gap_context(self) -> None:
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q1", status="ok", topic="factories",
            trigger="gap", target_gap_ids=["GAP-1"],
        )
        context = extract_goal_context(envelope)
        self.assertEqual(context["trigger"], "gap")
        self.assertEqual(context["target_gap_ids"], ["GAP-1"])

    def test_extractor_receives_conflict_context(self) -> None:
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="q1", status="ok", topic="financials",
            trigger="conflict", target_conflict_ids=["CONFLICT-1"], target_claim_ids=["C1", "C2"],
        )
        context = extract_goal_context(envelope)
        self.assertEqual(context["trigger"], "conflict")
        self.assertEqual(context["target_conflict_ids"], ["CONFLICT-1"])
        self.assertEqual(context["target_claim_ids"], ["C1", "C2"])

    def test_executor_passes_goal_context_through_envelope(self) -> None:
        adapter = _CapturingAdapter()
        query = _query(trigger="gap", target_gap_ids=["GAP-7"])
        plan = ResearchPlan(
            plan_id=new_sortable_id("PLAN"), run_id="RUN-1", complexity=EnterpriseComplexity.UNKNOWN,
            queries=[query], budget={"max_queries": 2, "max_pages": 10},
            completion_contract=["factories"],
            canonical_company_name="ACME科技有限公司",
        )
        envelopes = SearchExecutor({"anysearch": adapter}).execute(plan)
        request = adapter.requests[0]
        self.assertEqual(request.topic, "factories")
        self.assertEqual(request.canonical_company_name, "ACME科技有限公司")
        self.assertEqual(request.expected_fields, ["factory_name", "operator", "capacity"])
        self.assertEqual(request.target_gap_ids, ["GAP-7"])
        envelope = envelopes[0]
        self.assertEqual(envelope.topic, "factories")
        self.assertEqual(envelope.expected_fields, ["factory_name", "operator", "capacity"])
        self.assertEqual(envelope.target_gap_ids, ["GAP-7"])

    def test_every_goal_family_has_a_contract(self) -> None:
        for family, _ in GOAL_FAMILIES:
            contract = contract_for(family)
            self.assertEqual(contract.goal_family, family)
            self.assertTrue(contract.expected_fields, f"{family} has no expected fields")
            self.assertTrue(contract.preferred_source_types, f"{family} has no preferred source types")

    def test_financial_and_energy_contracts_cover_required_fields(self) -> None:
        financial = GOAL_CONTRACTS["financials"].expected_fields
        for field in ("revenue", "profit", "gross_profit", "gross_margin", "operating_profit",
                      "total_assets", "total_liabilities", "operating_cash_flow", "investment",
                      "capex", "reporting_period", "currency", "scope", "yoy"):
            self.assertIn(field, financial)
        energy = GOAL_CONTRACTS["energy_consumption"].expected_fields
        for field in ("electricity_consumption", "energy_consumption", "load", "load_curve",
                      "transformer_capacity", "natural_gas", "steam", "compressed_air",
                      "roof_area", "energy_equipment"):
            self.assertIn(field, energy)


if __name__ == "__main__":
    unittest.main()
