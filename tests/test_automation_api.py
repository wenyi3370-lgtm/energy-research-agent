"""Phase 2 API-layer tests: REST surface, structured errors, request IDs."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_energy_research.automation.api import create_app
from enterprise_energy_research.automation.executor import ExecutionOutcome
from enterprise_energy_research.automation.enums import ReviewDecision
from enterprise_energy_research.domain.enums import ArtifactStatus, ArtifactType, ValidationStatus
from test_automation_service import StubExecutor, make_request


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.executor = StubExecutor()
        self.app = create_app(
            database_url=f"sqlite:///{Path(self.tmp.name) / 'api.db'}",
            executor=self.executor,
            workdir=Path(self.tmp.name),
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        try:
            self.app.state.automation_db.engine.dispose()
        except AttributeError:
            pass
        self.tmp.cleanup()

    def submit(self, **overrides):
        resp = self.client.post(
            "/api/v1/research", json=make_request(**overrides).model_dump(mode="json")
        )
        self.assertEqual(resp.status_code, 201)
        return resp.json()


class TestSubmitAndStatus(ApiTestCase):
    def test_submit_returns_queued_then_background_executes(self):
        body = self.submit()
        self.assertTrue(body["run_id"].startswith("RUN-"))
        self.assertEqual(body["task_id"], "TH_BESS_001")
        self.assertEqual(body["status"], "QUEUED")
        # TestClient runs FastAPI background tasks before returning, so the
        # deterministic stub run is already PUBLISHED by the next call.
        status = self.client.get(f"/api/v1/research/{body['run_id']}").json()
        self.assertEqual(status["status"], "PUBLISHED")
        self.assertEqual(status["validation_status"], "PASS")

    def test_duplicate_task_id_is_409_structured(self):
        self.submit()
        resp = self.client.post(
            "/api/v1/research", json=make_request().model_dump(mode="json")
        )
        self.assertEqual(resp.status_code, 409)
        error = resp.json()["error"]
        self.assertEqual(error["type"], "DUPLICATE_TASK")
        self.assertIsNotNone(error["message"])

    def test_unknown_run_is_404_structured(self):
        resp = self.client.get("/api/v1/research/RUN-NOPE")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["type"], "RUN_NOT_FOUND")
        self.assertEqual(resp.json()["error"]["run_id"], "RUN-NOPE")

    def test_result_and_artifacts_endpoints(self):
        body = self.submit()
        result = self.client.get(f"/api/v1/research/{body['run_id']}/result")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["task_id"], "TH_BESS_001")
        artifacts = self.client.get(f"/api/v1/research/{body['run_id']}/artifacts")
        self.assertEqual(artifacts.status_code, 200)
        payload = artifacts.json()
        self.assertEqual(payload["run_id"], body["run_id"])
        self.assertEqual(len(payload["artifacts"]), 1)
        self.assertEqual(payload["artifacts"][0]["artifact_type"], "excel")

    def test_every_response_carries_request_id(self):
        body = self.submit()
        self.assertIn("X-Request-ID", self.client.get(f"/api/v1/research/{body['run_id']}").headers)
        self.assertIn("X-Request-ID", self.client.get("/health").headers)

    def test_health_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class TestReviewApi(ApiTestCase):
    def test_review_gate_flow(self):
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            review_required=True,
            review_reasons=["CONFLICT_01: price conflict"],
        )
        body = self.submit()
        status = self.client.get(f"/api/v1/research/{body['run_id']}").json()
        self.assertEqual(status["status"], "REVIEW_REQUIRED")
        resp = self.client.post(
            f"/api/v1/research/{body['run_id']}/review",
            json={
                "reviewer": "analyst_01",
                "decision": "APPROVE",
                "reason": "reviewed",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "PUBLISHED")

    def test_review_illegal_state_is_409(self):
        body = self.submit()  # stub auto-passes straight to PUBLISHED
        resp = self.client.post(
            f"/api/v1/research/{body['run_id']}/review",
            json={"reviewer": "analyst_01", "decision": "APPROVE"},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["type"], "INVALID_TRANSITION")

    def test_review_reject_is_terminal(self):
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS, review_required=True
        )
        body = self.submit()
        resp = self.client.post(
            f"/api/v1/research/{body['run_id']}/review",
            json={"reviewer": "analyst_01", "decision": "REJECT", "reason": "n/a"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "REJECTED")

    def test_review_validation_error_is_422(self):
        body = self.submit()
        resp = self.client.post(
            f"/api/v1/research/{body['run_id']}/review", json={"reviewer": ""}
        )
        self.assertEqual(resp.status_code, 422)


class TestRetryApi(ApiTestCase):
    def test_retry_requeues_failed_run(self):
        self.executor.validate_error = RuntimeError("search backend down")
        body = self.submit()
        status = self.client.get(f"/api/v1/research/{body['run_id']}").json()
        self.assertEqual(status["status"], "FAILED")
        self.assertTrue(status["error"]["retryable"])
        resp = self.client.post(f"/api/v1/research/{body['run_id']}/retry")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "QUEUED")
        # background re-execution with the still-failing stub -> FAILED again
        status = self.client.get(f"/api/v1/research/{body['run_id']}").json()
        self.assertEqual(status["status"], "FAILED")

    def test_retry_illegal_state_is_409(self):
        body = self.submit()  # PUBLISHED
        resp = self.client.post(f"/api/v1/research/{body['run_id']}/retry")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["type"], "INVALID_TRANSITION")

    def test_retry_exhausted_is_409(self):
        self.executor.validate_error = RuntimeError("still down")
        app = create_app(
            database_url=f"sqlite:///{Path(self.tmp.name) / 'api2.db'}",
            executor=self.executor,
            workdir=Path(self.tmp.name),
        )
        try:
            with TestClient(app) as client:
                body = client.post(
                    "/api/v1/research", json=make_request(task_id="RETRY_001").model_dump(mode="json")
                ).json()
                for _ in range(3):  # max_retries=3: three successful retries
                    resp = client.post(f"/api/v1/research/{body['run_id']}/retry")
                    self.assertEqual(resp.status_code, 200)
                resp = client.post(f"/api/v1/research/{body['run_id']}/retry")
        finally:
            app.state.automation_db.engine.dispose()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["type"], "RETRY_EXHAUSTED")


if __name__ == "__main__":
    unittest.main()
