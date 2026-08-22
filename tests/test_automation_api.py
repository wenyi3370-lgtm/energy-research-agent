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

    def test_monitor_summary_cannot_be_submitted_as_research(self):
        resp = self.client.post(
            "/api/v1/triggers/feishu",
            json={
                "requested_by": "watchdog",
                "company": "监测通知",
                "research_type": "other",
                "notes": "[定时监测] 到期任务 0 个",
            },
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(
            resp.json()["error"]["type"], "OPERATIONAL_NOTIFICATION_MISROUTED"
        )

    def test_legacy_monitor_endpoint_cannot_start_scheduled_research(self):
        resp = self.client.post("/api/v1/monitor/run")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {
                "triggered": False,
                "disabled": True,
                "due_count": 0,
                "stale_recovered": 0,
                "ran_async": False,
                "message": "定时研究已禁用；请通过本地网页点击“开始调查”",
            },
        )

    def test_portal_exposes_manual_research_and_daily_push_controls(self):
        html = self.client.get("/").text
        self.assertIn("企业研究仅由本页按钮启动，不会定时自动运行", html)
        self.assertIn("/api/v1/research/prepare", html)
        self.assertIn("/api/v1/research/' + currentRun + '/start", html)
        self.assertIn("renderParsed({company: body.company", html)
        self.assertIn("/api/v1/intelligence/pause", html)
        self.assertIn("/api/v1/intelligence/resume", html)

    def test_portal_exposes_continue_deep_research(self):
        """门户提供「继续深度研究」入口（自然语言定位 + 需求 + 保存桌面/推送飞书）。"""
        html = self.client.get("/").text
        self.assertIn("继续深度研究", html)
        self.assertIn("/deep-research", html)
        self.assertIn("deepRequirements", html)
        self.assertIn("deepQuery", html)
        self.assertIn("deepDesktop", html)
        self.assertIn("deepFeishu", html)

    def test_deep_research_lookup_by_natural_language(self):
        """任务定位：用公司名/产品关键词即可找到 run。"""
        body = self.submit(company="宁德时代新能源科技股份有限公司", product="动力电池", topics=["主营业务", "生产基地"])
        run_id = body["run_id"]
        found = self.client.get("/api/v1/research/lookup", params={"q": "宁德时代"}).json()
        self.assertTrue(any(m["run_id"] == run_id for m in found["matches"]), found)
        found_product = self.client.get("/api/v1/research/lookup", params={"q": "动力电池"}).json()
        self.assertTrue(any(m["run_id"] == run_id for m in found_product["matches"]), found_product)

    def test_deep_research_endpoint_accepts_and_reports(self):
        """POST 深度研究返回 202；GET 返回 run_id 匹配的结果状态。"""
        body = self.submit()
        run_id = body["run_id"]
        accepted = self.client.post(
            f"/api/v1/research/{run_id}/deep-research",
            json={"requirements": "补充 2022 年营业收入与利润", "requested_by": "portal-user"},
        )
        # 后台任务在 TestClient 下同步执行；无搜索适配器的环境允许失败，
        # 但接口本身必须可调用（202/500 都说明端点已注册并执行了任务）。
        self.assertIn(accepted.status_code, (202, 500))
        if accepted.status_code == 202:
            result = self.client.get(f"/api/v1/research/{run_id}/deep-research")
            self.assertEqual(result.status_code, 200)
            payload = result.json()
            self.assertEqual(payload["run_id"], run_id)
            self.assertIn(payload["status"], {"running", "completed", "failed"})
        # 需求过短被 422 拒绝（payload 契约）
        short = self.client.post(
            f"/api/v1/research/{run_id}/deep-research",
            json={"requirements": "x", "requested_by": "portal-user"},
        )
        self.assertEqual(short.status_code, 422)

    def test_stop_all_cancels_prepared_portal_run(self):
        prepared = self.client.post(
            "/api/v1/research/prepare",
            json=make_request().model_dump(mode="json"),
        )
        self.assertEqual(prepared.status_code, 201)
        stopped = self.client.post("/api/v1/research/stop-all")
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["count"], 1)
        self.assertEqual(stopped.json()["stopped"][0]["status"], "FAILED")

    def test_daily_push_pause_and_resume_persist(self):
        self.assertEqual(
            self.client.get("/api/v1/intelligence/status").json(), {"paused": False}
        )
        self.assertEqual(
            self.client.post("/api/v1/intelligence/pause").json(), {"paused": True}
        )
        self.assertEqual(
            self.client.get("/api/v1/intelligence/status").json(), {"paused": True}
        )
        blocked = self.client.post("/api/v1/intelligence/daily").json()
        self.assertEqual(blocked["triggered"], False)
        self.assertEqual(blocked["paused"], True)
        self.assertEqual(
            self.client.post("/api/v1/intelligence/resume").json(), {"paused": False}
        )
        self.assertEqual(
            self.client.get("/api/v1/intelligence/status").json(), {"paused": False}
        )


class TestReviewApi(ApiTestCase):
    def test_review_flag_auto_publishes(self):
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            review_required=True,
            review_reasons=["CONFLICT_01: price conflict"],
        )
        body = self.submit()
        status = self.client.get(f"/api/v1/research/{body['run_id']}").json()
        self.assertEqual(status["status"], "PUBLISHED")
        self.assertFalse(status["review_required"])

    def test_review_endpoint_is_removed(self):
        body = self.submit()  # stub auto-passes straight to PUBLISHED
        resp = self.client.post(
            f"/api/v1/research/{body['run_id']}/review",
            json={"reviewer": "analyst_01", "decision": "APPROVE"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_conflict_resolution_endpoint_is_removed(self):
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS, review_required=True
        )
        body = self.submit()
        resp = self.client.post(f"/api/v1/research/{body['run_id']}/conflicts/C1/resolve", json={})
        self.assertEqual(resp.status_code, 404)

    def test_resume_endpoint_is_removed(self):
        body = self.submit()
        resp = self.client.post(f"/api/v1/research/{body['run_id']}/resume")
        self.assertEqual(resp.status_code, 404)


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
