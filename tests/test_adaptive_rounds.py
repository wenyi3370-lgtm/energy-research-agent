"""P1-1 / P1-2 regression: adaptive rounds driven by REAL gaps and conflicts,
evidence ingestion before the next round, and EvidenceDelta-driven saturation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from energy_research_agent.adapters.base import AdapterHealth, SearchHit, SearchResultEnvelope
from energy_research_agent.domain.enums import EnterpriseComplexity
from energy_research_agent.research.evidence_delta import DeltaSaturation, EvidenceDelta, EvidenceSnapshot
from energy_research_agent.research.production_runner import AdaptiveResearchRunner


def claim_dict(entity_key: str, field: str, value: str) -> dict:
    return {
        "entity_key": entity_key, "field_name": field, "value": value,
        "value_type": "string", "raw_text": f"{field}={value}",
        "context_text": f"页面披露 {field} 为 {value}", "qualifier": "exact",
    }


IDENTITY_BATCH = {
    "source_url": "https://www.acme-corp.com/about",
    "source_title": "ACME 简介",
    "publisher": "ACME",
    "source_kind": "official_company",
    "extraction_method": "model_structured",
    "retrieval_adapter": "anysearch",
    "is_search_snippet": False,
    "entities": [{
        "entity_key": "acme", "canonical_name": "ACME科技有限公司", "entity_type": "company",
        "official_website": "https://www.acme-corp.com",
    }],
    "claims": [
        claim_dict("acme", "canonical_company_name", "ACME科技有限公司"),
        claim_dict("acme", "core_business", "储能系统研发制造"),
    ],
    "factories": [], "products": [], "images": [],
}

REVENUE_100_BATCH = {
    "source_url": "https://stats.example-industry.org/acme",
    "source_title": "行业协会数据",
    "publisher": "行业协会",
    "source_kind": "industry_association",
    "extraction_method": "model_structured",
    "retrieval_adapter": "anysearch",
    "is_search_snippet": False,
    "entities": [{
        "entity_key": "acme", "canonical_name": "ACME科技有限公司", "entity_type": "company",
    }],
    "claims": [claim_dict("acme", "revenue", "100亿元")],
    "factories": [], "products": [], "images": [],
}

REVENUE_120_BATCH = {
    "source_url": "https://db.example-market.org/acme",
    "source_title": "商业数据库",
    "publisher": "商业数据库",
    "source_kind": "commercial_database",
    "extraction_method": "model_structured",
    "retrieval_adapter": "anysearch",
    "is_search_snippet": False,
    "entities": [{
        "entity_key": "acme", "canonical_name": "ACME科技有限公司", "entity_type": "company",
    }],
    "claims": [claim_dict("acme", "revenue", "120亿元")],
    "factories": [], "products": [], "images": [],
}

TRIANGULATION_BATCH = {
    "source_url": "https://report.example-gov.org/acme",
    "source_title": "政府公开数据",
    "publisher": "政府机构",
    "source_kind": "government",
    "extraction_method": "model_structured",
    "retrieval_adapter": "anysearch",
    "is_search_snippet": False,
    "entities": [{
        "entity_key": "acme", "canonical_name": "ACME科技有限公司", "entity_type": "company",
    }],
    "claims": [claim_dict("acme", "revenue", "100亿元")],
    "factories": [], "products": [], "images": [],
}


class ScenarioAdapter:
    name = "anysearch"

    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list = []

    def health(self) -> AdapterHealth:
        return AdapterHealth(name=self.name, available=True)

    def search(self, request):
        self.requests.append(request)
        hits = self.handler(request)
        return SearchResultEnvelope(
            adapter=self.name, query_id=request.query_id, status="ok" if hits else "partial",
            hits=[
                SearchHit(
                    requested_url=batch["source_url"], final_url=batch["source_url"],
                    title=batch.get("source_title"), text="页面正文",
                    status="ok", retrieved_at="2026-08-20T00:00:00Z",
                    metadata={"evidence_batch": batch},
                )
                for batch in hits
            ],
        )


class QuietKimi:
    name = "kimi_webbridge"

    def health(self) -> AdapterHealth:
        return AdapterHealth(name=self.name, available=True)

    def navigate_to(self, url, *, new_tab=False):
        return {"url": url}

    def evaluate(self, code):
        return {}

    def search(self, request):
        return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="partial", hits=[])


class AdaptiveRoundTests(unittest.TestCase):
    def _runner(self, handler, budget: dict | None = None):
        budget = budget or {"max_queries": 6, "max_pages": 30}
        return AdaptiveResearchRunner(
            # The scenario serves BOTH approved adapters: browser-routed topics
            # (kimi_webbridge) receive the same recorded responses.
            {
                "anysearch": ScenarioAdapter(handler),
                "kimi_webbridge": ScenarioAdapter(handler),
            },
            enterprise_rules={},
            fetcher=None,
            enable_image_archiving=False,
            enable_publication=False,
            minimum_substantive_claims=20,
        ), budget

    def _run(self, handler, budget: dict | None = None):
        runner, budget = self._runner(handler, budget)
        with tempfile.TemporaryDirectory() as temp:
            report = runner.run(
                "ACME", EnterpriseComplexity.ENTERPRISE_NORMAL, budget, Path(temp),
            )
            return report, runner

    # ---- gap-driven R2 -----------------------------------------------------

    def test_production_runner_executes_gap_driven_r2(self) -> None:
        def handler(request):
            # R1: nothing found anywhere -> critical company_identity gap.
            if request.trigger != "gap":
                return []
            return [IDENTITY_BATCH]

        report, runner = self._run(handler)
        rounds = {item.round: item for item in report.rounds}
        self.assertIn("R2", rounds)
        self.assertEqual(rounds["R2"].trigger, "gap")
        self.assertTrue(rounds["R1"].new_gap_ids)

    def test_r2_queries_reference_real_gap_ids(self) -> None:
        def handler(request):
            if request.trigger != "gap":
                return []
            return [IDENTITY_BATCH]

        report, runner = self._run(handler)
        r2 = next(item for item in report.rounds if item.round == "R2")
        gap_ids = next(item for item in report.rounds if item.round == "R1").new_gap_ids
        self.assertTrue(gap_ids)
        self.assertTrue(all(item["target_gap_ids"] for item in r2.round_queries))
        referenced = {gap_id for item in r2.round_queries for gap_id in item["target_gap_ids"]}
        self.assertTrue(referenced.issubset(set(gap_ids)))

    def test_r2_driven_only_by_searchable_gaps(self) -> None:
        def handler(request):
            if request.topic == "company_identity":
                return [IDENTITY_BATCH]
            return []

        # identity results produce requires_site_due_diligence gaps (NOT
        # searchable); the empty product families produce SEARCHED_NOT_FOUND
        # gaps (searchable).  R2 must be driven by the latter only.
        report, runner = self._run(handler, {"max_queries": 20, "max_pages": 30})
        r2 = next((item for item in report.rounds if item.round == "R2"), None)
        self.assertIsNotNone(r2)
        # every R2 query targets a real searchable gap.  The shared Recall
        # layer may expose additional source-lane goals alongside products.
        self.assertTrue(all(item["target_gap_ids"] for item in r2.round_queries))
        self.assertTrue(any(item["topic"].startswith("product") for item in r2.round_queries))
        energy_gap_ids = {
            gap.gap_id for gap in runner.cumulative.gaps
            if gap.reason == "requires_site_due_diligence"
        }
        referenced = {gap_id for item in r2.round_queries for gap_id in item["target_gap_ids"]}
        self.assertFalse(referenced & energy_gap_ids, "site-due-diligence gaps must not drive R2")

    def test_new_r2_evidence_is_ingested_before_next_round(self) -> None:
        def handler(request):
            if request.topic == "company_identity":
                return [IDENTITY_BATCH]
            if request.trigger == "gap":
                # R2 depth introduces conflicting revenue values from two
                # independent sources: merged evidence must reach R3 planning.
                return [REVENUE_100_BATCH, REVENUE_120_BATCH]
            if request.trigger == "conflict":
                return [TRIANGULATION_BATCH]
            return []

        report, runner = self._run(handler, {"max_queries": 12, "max_pages": 40})
        rounds = {item.round: item for item in report.rounds}
        self.assertIn("R3", rounds)  # only possible if R2 claims were merged before R3 planning
        values = {
            str(claim.value) for claim in runner.cumulative.claims if claim.field_name == "revenue"
        }
        self.assertIn("120亿元", values)
        self.assertIn("100亿元", values)

    # ---- conflict-driven R3 ------------------------------------------------

    def test_production_runner_executes_conflict_driven_r3(self) -> None:
        def handler(request):
            if request.topic == "company_identity":
                return [IDENTITY_BATCH]
            if request.trigger == "gap":
                return [REVENUE_100_BATCH, REVENUE_120_BATCH]
            if request.trigger == "conflict":
                return [TRIANGULATION_BATCH]
            return []

        report, runner = self._run(handler, {"max_queries": 12, "max_pages": 40})
        rounds = {item.round: item for item in report.rounds}
        self.assertIn("R3", rounds)
        self.assertEqual(rounds["R3"].trigger, "conflict")

    def test_r3_queries_reference_real_conflict_ids(self) -> None:
        def handler(request):
            if request.topic == "company_identity":
                return [IDENTITY_BATCH]
            if request.trigger == "gap":
                return [REVENUE_100_BATCH, REVENUE_120_BATCH]
            if request.trigger == "conflict":
                return [TRIANGULATION_BATCH]
            return []

        report, runner = self._run(handler, {"max_queries": 12, "max_pages": 40})
        r3 = next(item for item in report.rounds if item.round == "R3")
        # The conflicts that TRIGGERED R3 are the ones present after R2.
        r2 = next(item for item in report.rounds if item.round == "R2")
        conflict_ids = set(r2.snapshot_after["conflicts"])
        self.assertTrue(conflict_ids)
        referenced = {
            conflict_id for item in r3.round_queries for conflict_id in item["target_conflict_ids"]
        }
        self.assertTrue(referenced.issubset(conflict_ids))

    def test_r3_not_generated_without_triangulation_need(self) -> None:
        def handler(request):
            if request.topic == "company_identity":
                return [IDENTITY_BATCH]
            if request.trigger == "gap":
                return [IDENTITY_BATCH]
            return []

        report, runner = self._run(handler, {"max_queries": 12, "max_pages": 40})
        self.assertNotIn("R3", {item.round for item in report.rounds})

    def test_recall_budget_cannot_consume_baseline_evidence_budget(self) -> None:
        """Recall is additive; all legacy R1 goals retain the full page pool."""
        runner, _ = self._runner(lambda _request: [], {"max_queries": 180, "max_pages": 240})
        plans = []

        def capture_execute(_executor, plan):
            plans.append(plan)
            return []

        with tempfile.TemporaryDirectory() as temp, patch(
            "energy_research_agent.research.executor.SearchExecutor.execute",
            new=capture_execute,
        ):
            runner.run(
                "ACME", EnterpriseComplexity.ENTERPRISE_NORMAL,
                {"max_queries": 180, "max_pages": 240}, Path(temp),
            )

        recall_plans = [
            plan for plan in plans
            if plan.queries and all(query.query_id.startswith("RQ-E-") for query in plan.queries)
        ]
        evidence_plans = [
            plan for plan in plans
            if plan.queries and all(not query.query_id.startswith("RQ-E-") for query in plan.queries)
            and any(query.collection_round == "R1" for query in plan.queries)
        ]
        self.assertEqual(len(recall_plans), 1)
        self.assertEqual(recall_plans[0].budget["max_pages"], 48)
        self.assertTrue(evidence_plans)
        baseline = evidence_plans[0]
        self.assertEqual(baseline.budget["max_pages"], 240)
        topics = {query.topic for query in baseline.queries}
        self.assertTrue({
            "financials", "factories", "capacity", "production_lines",
            "products", "product_series", "product_models", "product_parameters",
        }.issubset(topics))


class FulltextPassTests(unittest.TestCase):
    def test_fulltext_pass_fetches_real_pages_via_anysearch_extract(self) -> None:
        from energy_research_agent.adapters.base import AdapterHealth, SearchHit
        from energy_research_agent.research.production_runner import AdaptiveResearchRunner

        class FakeAnySearch:
            name = "anysearch"

            def __init__(self) -> None:
                self.requests: list = []

            def health(self) -> AdapterHealth:
                return AdapterHealth(name=self.name, available=True)

            def search(self, request):
                self.requests.append(request)
                if request.metadata.get("url"):
                    return SearchResultEnvelope(
                        adapter=self.name, query_id=request.query_id, status="ok",
                        hits=[SearchHit(
                            requested_url=request.metadata["url"], final_url=request.metadata["url"],
                            title="全文页", text="公司全称ACME科技有限公司，成立于2010年。",
                            status="ok", retrieved_at="2026-08-21T00:00:00Z",
                            metadata={"format": "json"},
                        )],
                    )
                return SearchResultEnvelope(
                    adapter=self.name, query_id=request.query_id, status="ok",
                    hits=[SearchHit(
                        final_url="https://www.acme-corp.com/about", title="结果", text="snippet",
                        status="ok", retrieved_at="2026-08-21T00:00:00Z",
                        metadata={"format": "json", "snippet": True},
                    )],
                )

        adapter = FakeAnySearch()
        runner = AdaptiveResearchRunner({"anysearch": adapter})
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="Q1", status="ok", topic="company_identity",
            hits=[SearchHit(
                final_url="https://www.acme-corp.com/about", title="结果", text="snippet",
                status="ok", retrieved_at="2026-08-21T00:00:00Z",
                metadata={"format": "json", "snippet": True},
            )],
        )
        extended = runner._fulltext_pass([envelope], [])
        fulltext = [item for item in extended if item.hits and "ACME科技有限公司" in (item.hits[0].text or "")]
        self.assertTrue(fulltext, "full-text pages were not fetched via AnySearch extract")
        self.assertFalse(fulltext[0].hits[0].metadata.get("snippet"))
        extract_requests = [request for request in adapter.requests if request.metadata.get("url")]
        self.assertEqual(extract_requests[0].metadata["url"], "https://www.acme-corp.com/about")


class EvidenceDeltaTests(unittest.TestCase):
    def test_delta_never_defaults_to_empty_pass(self) -> None:
        assessment = DeltaSaturation.assess([])
        self.assertEqual(assessment.status, "SATURATION_BLOCKED")

    def test_delta_saturation_requires_real_quiet_rounds(self) -> None:
        before = EvidenceSnapshot(label="before")
        after = EvidenceSnapshot(label="after", claims=["c1"], verified_claims=["c1"])
        productive = EvidenceDelta.compute(before, after)
        assessment = DeltaSaturation.assess([productive])
        self.assertEqual(assessment.status, "SATURATION_PARTIAL")

    def test_delta_counts_new_evidence_precisely(self) -> None:
        before = EvidenceSnapshot(label="before", claims=["c1"])
        after = EvidenceSnapshot(label="after", claims=["c1", "c2"], verified_claims=["c2"],
                                 products=["p1"], images=["i1"], gaps=["g1"])
        delta = EvidenceDelta.compute(before, after)
        self.assertEqual(delta.new_claims, ["c2"])
        self.assertEqual(delta.new_verified_claims, ["c2"])
        self.assertEqual(delta.new_products, ["p1"])
        self.assertEqual(delta.new_images, ["i1"])
        self.assertEqual(delta.new_gaps, ["g1"])
        self.assertTrue(delta.computable)


if __name__ == "__main__":
    unittest.main()
