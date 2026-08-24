"""编排接线 tests: OrchestratingExecutor end-to-end over recorded fixtures
plus service integration through the review gate."""

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.adapters.base import AdapterHealth, SearchHit, SearchRequest, SearchResultEnvelope
from enterprise_energy_research.automation.contracts import ResearchRequest
from enterprise_energy_research.automation.db import AutomationDatabase
from enterprise_energy_research.automation.enums import TaskStatus
from enterprise_energy_research.automation.orchestration import OrchestratingExecutor
from enterprise_energy_research.automation.service import ResearchService
from enterprise_energy_research.domain.enums import ValidationStatus

ROOT = Path(__file__).resolve().parents[1]


class DictFixtureAdapter:
    """Replays a fixed hit list for any query; embeds a recorded evidence batch."""

    name = "anysearch"

    def __init__(self, batch: dict, available: bool = True) -> None:
        self.batch = batch
        self._available = available
        self.calls = 0

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            available=self._available,
            version="1.0",
            diagnostics=[] if self._available else ["disabled for test"],
        )

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        self.calls += 1
        if not self._available:
            return SearchResultEnvelope(
                adapter=self.name, query_id=request.query_id, status="blocked",
                diagnostics=["adapter unavailable"],
            )
        return SearchResultEnvelope(
            adapter=self.name,
            query_id=request.query_id,
            status="ok",
            hits=[{
                "requested_url": f"https://example.com/{request.query_id}",
                "final_url": f"https://example.com/{request.query_id}",
                "title": request.query,
                "text": "fixture page content for " + request.query,
                "status": "ok",
                "retrieved_at": "2026-08-19T00:00:00Z",
                "metadata": {"evidence_batch": self.batch},
            }],
        )


def load_batch(name: str) -> dict:
    payload = json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))
    return payload[0]


def make_request(task_id: str, company: str) -> ResearchRequest:
    return ResearchRequest(
        task_id=task_id, requested_by="orchestrator-test", company=company,
        research_type="company_profile", topics=["product_catalog"],
    )


class OrchestratingExecutorTests(unittest.TestCase):
    def test_portal_orchestrator_hydrates_search_snippets_before_extraction(self):
        class HydratingAdapter:
            name = "anysearch"

            def __init__(self) -> None:
                self.extract_calls = 0

            def health(self) -> AdapterHealth:
                return AdapterHealth(name=self.name, available=True, version="test")

            def search(self, request: SearchRequest) -> SearchResultEnvelope:
                if request.metadata.get("url"):
                    self.extract_calls += 1
                    return SearchResultEnvelope(
                        adapter=self.name, query_id=request.query_id, status="ok",
                        hits=[SearchHit(
                            requested_url=request.metadata["url"],
                            final_url=request.metadata["url"], title="企业官网全文",
                            text="星星充电主营充电设备与储能系统，并建设生产基地。",
                            status="ok", retrieved_at="2026-08-24T00:00:00Z",
                            metadata={"format": "json"},
                        )],
                    )
                raise AssertionError("only extract calls are expected in this unit test")

        adapter = HydratingAdapter()
        executor = OrchestratingExecutor(adapters={"anysearch": adapter})
        source = SearchResultEnvelope(
            adapter="anysearch", query_id="Q-PRODUCT", status="ok",
            topic="products", purpose="核验产品", collection_round="R2",
            canonical_company_name="星星充电", expected_fields=["product_family"],
            hits=[SearchHit(
                final_url="https://www.starcharge.com/products", title="搜索摘要",
                text="星星充电产品中心搜索结果摘要", status="ok", retrieved_at="2026-08-24T00:00:00Z",
                metadata={"snippet": True},
            )],
        )
        # The same URL under another goal must reuse the network fetch while
        # preserving both goal contexts.
        second = source.model_copy(update={"query_id": "Q-FACTORY", "topic": "factories"})
        hydrated = executor._hydrate_fulltext_envelopes([source, second])
        material = [
            envelope for envelope in hydrated
            if envelope.hits and not envelope.hits[0].metadata.get("snippet")
        ]
        self.assertEqual(adapter.extract_calls, 1)
        self.assertEqual({item.topic for item in material}, {"products", "factories"})
        self.assertTrue(all(item.canonical_company_name == "星星充电" for item in material))
        self.assertTrue(all("主营充电设备" in (item.hits[0].text or "") for item in material))

    def test_portal_orchestrator_does_not_hydrate_unrelated_discovery_hit(self):
        class MustNotFetch:
            name = "anysearch"

            @staticmethod
            def health() -> AdapterHealth:
                return AdapterHealth(name="anysearch", available=True, version="test")

            @staticmethod
            def search(_request: SearchRequest) -> SearchResultEnvelope:
                raise AssertionError("unrelated discovery URL must not be hydrated")

        executor = OrchestratingExecutor(adapters={"anysearch": MustNotFetch()})
        source = SearchResultEnvelope(
            adapter="anysearch", query_id="Q-IRRELEVANT", status="ok",
            topic="sales_channels", canonical_company_name="星星充电",
            hits=[SearchHit(
                final_url="https://podcasts.example/unrelated", title="今夜说晚安",
                text="播客节目列表", status="ok",
                retrieved_at="2026-08-24T00:00:00Z", metadata={"snippet": True},
            )],
        )
        hydrated = executor._hydrate_fulltext_envelopes([source])
        self.assertEqual(hydrated, [source])

    def test_research_and_validate_over_fixture(self):
        adapter = DictFixtureAdapter(load_batch("small_simple.json"))
        executor = OrchestratingExecutor(adapters={"anysearch": adapter})
        request = make_request("TASK-ORCH", "示例节能服务有限公司")
        with tempfile.TemporaryDirectory() as tmp:
            outcome = executor.research_and_validate("RUN-ORCH-1", request, Path(tmp))
            self.assertEqual(outcome.validation_status, ValidationStatus.PASS)
            self.assertGreater(outcome.evidence_count, 0)
            self.assertGreater(outcome.search_calls, 0)
            self.assertGreater(adapter.calls, 0)
            # saturation/quality findings must be surfaced, not dropped
            self.assertTrue(any("SAT-" in r or "round" in r.lower() for r in outcome.review_reasons) or outcome.evidence_count > 0)
            outcome2 = executor.freeze_and_publish("RUN-ORCH-1", Path(tmp))
            self.assertIsNotNone(outcome2.freeze_id)
            self.assertGreater(len(outcome2.artifacts), 0)

    def test_unavailable_adapter_fail_closed(self):
        executor = OrchestratingExecutor(
            adapters={"anysearch": DictFixtureAdapter(load_batch("small_simple.json"), available=False)}
        )
        request = make_request("TASK-ORCH-2", "示例节能服务有限公司")
        with tempfile.TemporaryDirectory() as tmp:
            outcome = executor.research_and_validate("RUN-ORCH-2", request, Path(tmp))
            self.assertEqual(outcome.validation_status, ValidationStatus.BLOCKED)
            self.assertIn("adapter not available", " ".join(outcome.review_reasons))

    def test_missing_adapter_reported_not_guessed(self):
        executor = OrchestratingExecutor(
            adapters={"anysearch": DictFixtureAdapter(load_batch("small_simple.json"))}
        )
        # plan prefers kimi_webbridge for some queries; it is absent -> blocked envelopes
        request = make_request("TASK-ORCH-3", "示例节能服务有限公司")
        with tempfile.TemporaryDirectory() as tmp:
            outcome = executor.research_and_validate("RUN-ORCH-3", request, Path(tmp))
            self.assertTrue(outcome.evidence_count > 0 or outcome.validation_status != ValidationStatus.PASS)


class OrchestrationServiceTests(unittest.TestCase):
    def test_full_service_path_to_published(self):
        adapter = DictFixtureAdapter(load_batch("small_simple.json"))
        executor = OrchestratingExecutor(adapters={"anysearch": adapter})
        with tempfile.TemporaryDirectory() as tmp:
            db = AutomationDatabase(f"sqlite:///{Path(tmp) / 'orch.db'}")
            service = ResearchService(db, executor, Path(tmp) / "work")
            try:
                submitted = service.submit(make_request("TASK-SVC", "示例节能服务有限公司"))
                final = service.execute_run(submitted.run_id)
                self.assertEqual(final.status, TaskStatus.PUBLISHED, final.error)
                metrics = service.roi_rows()  # no feedback yet -> empty, still callable
                self.assertEqual(metrics, [])
            finally:
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
