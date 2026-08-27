import unittest

from energy_research_agent.automation.contracts import (
    CostMetrics,
    ResearchError,
    ResearchRequest,
    ResearchResult,
)
from energy_research_agent.automation.db import (
    AutomationDatabase,
    DuplicateTaskError,
    RunNotFoundError,
    TaskRepository,
)
from energy_research_agent.automation.enums import TaskStatus
from energy_research_agent.automation.state_machine import InvalidTransitionError
from energy_research_agent.domain.enums import ValidationStatus


def make_request(task_id: str = "TH_BESS_001", **overrides) -> ResearchRequest:
    payload = {
        "task_id": task_id,
        "requested_by": "user_001",
        "country": "Thailand",
        "product": "Residential BESS",
        "research_type": "market_entry",
        "topics": ["market_size", "policy"],
    }
    payload.update(overrides)
    return ResearchRequest.model_validate(payload)


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.db = AutomationDatabase("sqlite:///:memory:")
        self.session = self.db.session()
        self.repo = TaskRepository(self.session)

    def tearDown(self):
        self.session.close()
        self.db.engine.dispose()


class TestTasks(DbTestCase):
    def test_create_and_get_task_roundtrip(self):
        request = make_request()
        self.repo.create_task(request)
        row = self.repo.get_task("TH_BESS_001")
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "CREATED")
        self.assertEqual(row.request_payload["country"], "Thailand")
        self.assertEqual(row.requested_by, "user_001")

    def test_duplicate_task_id_rejected(self):
        self.repo.create_task(make_request())
        with self.assertRaises(DuplicateTaskError):
            self.repo.create_task(make_request())

    def test_idempotency_key_is_unique_and_searchable(self):
        self.repo.create_task(make_request(idempotency_key="key-1"))
        found = self.repo.find_by_idempotency_key("key-1")
        self.assertEqual(found.task_id, "TH_BESS_001")
        with self.assertRaises(DuplicateTaskError):
            self.repo.create_task(make_request(task_id="OTHER", idempotency_key="key-1"))


class TestRuns(DbTestCase):
    def setUp(self):
        super().setUp()
        self.request = make_request()
        self.repo.create_task(self.request)
        self.repo.create_run("RUN-001", self.request)

    def test_create_run_links_task(self):
        run = self.repo.get_run("RUN-001")
        self.assertEqual(run.task_id, "TH_BESS_001")
        self.assertEqual(run.country, "Thailand")
        task = self.repo.get_task("TH_BESS_001")
        self.assertEqual(task.active_run_id, "RUN-001")

    def test_legal_transition_updates_run_task_and_event(self):
        self.repo.update_run_status("RUN-001", TaskStatus.QUEUED, reason="accepted")
        run = self.repo.get_run("RUN-001")
        self.assertEqual(run.status, "QUEUED")
        self.assertEqual(self.repo.get_task("TH_BESS_001").status, "QUEUED")
        events = self.repo.list_events("RUN-001")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].from_status, "CREATED")
        self.assertEqual(events[0].to_status, "QUEUED")
        self.assertEqual(events[0].payload["reason"], "accepted")

    def test_illegal_transition_rejected_and_not_persisted(self):
        with self.assertRaises(InvalidTransitionError):
            self.repo.update_run_status("RUN-001", TaskStatus.PUBLISHED)
        self.assertEqual(self.repo.get_run("RUN-001").status, "CREATED")
        self.assertEqual(self.repo.list_events("RUN-001"), [])

    def test_validating_cannot_publish_via_repository(self):
        for target in (
            TaskStatus.QUEUED,
            TaskStatus.RESEARCHING,
            TaskStatus.EVIDENCE_COLLECTED,
            TaskStatus.VALIDATING,
        ):
            self.repo.update_run_status("RUN-001", target)
        with self.assertRaises(InvalidTransitionError):
            self.repo.update_run_status("RUN-001", TaskStatus.PUBLISHED)

    def test_duration_computed_on_finish(self):
        self.repo.update_run_status("RUN-001", TaskStatus.QUEUED)
        self.repo.update_run_status("RUN-001", TaskStatus.RESEARCHING, started=True)
        self.repo.update_run_status(
            "RUN-001", TaskStatus.FAILED, finished=True
        )
        run = self.repo.get_run("RUN-001")
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.duration_seconds)
        self.assertGreaterEqual(run.duration_seconds, 0.0)

    def test_missing_run_raises(self):
        with self.assertRaises(RunNotFoundError):
            self.repo.update_run_status("NOPE", TaskStatus.QUEUED)

    def test_finalize_run_persists_result_summary(self):
        result = ResearchResult(
            run_id="RUN-001",
            task_id="TH_BESS_001",
            status=TaskStatus.REVIEW_REQUIRED,
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            confidence=0.8,
            review_required=True,
            evidence_count=42,
            conflict_count=2,
            gap_count=1,
            cost_metrics=CostMetrics(input_tokens=1000, output_tokens=200),
            error=ResearchError(error_type="NONE", message=""),
        )
        self.repo.finalize_run(result)
        run = self.repo.get_run("RUN-001")
        self.assertEqual(run.validation_status, "PASS_WITH_WARNINGS")
        self.assertEqual(run.evidence_count, 42)
        self.assertEqual(run.input_tokens, 1000)
        self.assertTrue(run.review_required)
        self.assertEqual(run.result_payload["task_id"], "TH_BESS_001")


class TestReviewsMetricsFeedback(DbTestCase):
    def setUp(self):
        super().setUp()
        self.repo.create_task(make_request())
        self.repo.create_run("RUN-001", make_request())

    def test_review_recorded_with_original_and_modified(self):
        self.repo.save_review(
            review_id="REV-1",
            run_id="RUN-001",
            task_id="TH_BESS_001",
            reviewer="analyst_01",
            decision="EDIT_AND_APPROVE",
            reason="market size conflict",
            original_value={"market_size_gwh": 1.2},
            modified_value={"market_size_gwh": 1.5},
        )
        reviews = self.repo.list_reviews("RUN-001")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].decision, "EDIT_AND_APPROVE")
        self.assertEqual(reviews[0].modified_value["market_size_gwh"], 1.5)

    def test_metrics_upsert(self):
        self.repo.upsert_metrics("RUN-001", research_duration=12.5, search_calls=30)
        self.repo.upsert_metrics("RUN-001", validation_duration=1.5)
        metrics = self.repo.get_metrics("RUN-001")
        self.assertEqual(metrics.research_duration, 12.5)
        self.assertEqual(metrics.search_calls, 30)
        self.assertEqual(metrics.validation_duration, 1.5)

    def test_metrics_rejects_unknown_field(self):
        with self.assertRaises(AttributeError):
            self.repo.upsert_metrics("RUN-001", not_a_field=1)

    def test_feedback_records_human_time_not_machine_time(self):
        self.repo.save_feedback(
            feedback_id="FB-1",
            run_id="RUN-001",
            task_id="TH_BESS_001",
            submitted_by="user_001",
            adoption_status="ADOPTED",
            user_rating=4,
            manual_baseline_minutes=480.0,
            human_review_minutes=35.0,
            human_edit_count=2,
        )
        from energy_research_agent.automation.db.models import UserFeedbackRow

        row = self.session.get(UserFeedbackRow, "FB-1")
        self.assertEqual(row.adoption_status, "ADOPTED")
        self.assertEqual(row.manual_baseline_minutes, 480.0)
        self.assertEqual(row.human_review_minutes, 35.0)

    def test_no_secret_columns_exist(self):
        from energy_research_agent.automation.db import models

        forbidden = {"api_key", "password", "secret", "token", "cookie"}
        for table in models.Base.metadata.tables.values():
            for column in table.columns:
                self.assertNotIn(column.name.lower(), forbidden, f"{table.name}.{column.name}")


if __name__ == "__main__":
    unittest.main()
