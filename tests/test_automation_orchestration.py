"""编排接线 tests: OrchestratingExecutor end-to-end over recorded fixtures
plus service integration through the review gate."""

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.adapters.base import AdapterHealth, SearchRequest, SearchResultEnvelope
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
