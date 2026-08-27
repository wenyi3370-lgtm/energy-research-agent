"""Agent service-layer tests: workflow rules around the state machine."""

import tempfile
import unittest
from pathlib import Path

from energy_research_agent.automation.contracts import (
    ArtifactRef,
    ResearchRequest,
    ReviewSubmission,
)
from energy_research_agent.automation.db import (
    AutomationDatabase,
    DuplicateTaskError,
    RunNotFoundError,
)
from energy_research_agent.automation.enums import ReviewDecision, TaskStatus
from energy_research_agent.automation.executor import ExecutionOutcome
from energy_research_agent.automation.feishu import FeishuNotifier, MockFeishuAdapter
from energy_research_agent.automation.service import (
    ResearchService,
    RetryExhaustedError,
)
from energy_research_agent.automation.state_machine import InvalidTransitionError
from energy_research_agent.domain.enums import (
    ArtifactStatus,
    ArtifactType,
    ValidationStatus,
)


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


class StubExecutor:
    """Deterministic executor double; no kernel involvement."""

    def __init__(
        self,
        outcome: ExecutionOutcome | None = None,
        freeze_outcome: ExecutionOutcome | None = None,
        validate_error: BaseException | None = None,
        publish_error: BaseException | None = None,
    ) -> None:
        self.outcome = outcome or ExecutionOutcome(validation_status=ValidationStatus.PASS)
        self.freeze_outcome = freeze_outcome or ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            artifacts=[
                ArtifactRef(
                    artifact_type=ArtifactType.EXCEL,
                    status=ArtifactStatus.PUBLISHED,
                    location="out/1.xlsx",
                )
            ],
        )
        self.validate_error = validate_error
        self.publish_error = publish_error
        self.research_calls = 0
        self.freeze_calls = 0
        self.repair_calls = 0
        self.on_research = None

    def research_and_validate(self, run_id, request, workdir):
        self.research_calls += 1
        if self.on_research is not None:
            self.on_research(run_id)
        if self.validate_error is not None:
            raise self.validate_error
        return self.outcome

    def freeze_and_publish(self, run_id, workdir):
        self.freeze_calls += 1
        if self.publish_error is not None:
            raise self.publish_error
        return self.freeze_outcome

    def repair_publication(self, run_id, workdir, *, failed_artifacts, attempt):
        self.repair_calls += 1
        return f"fixture repair {attempt}"


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AutomationDatabase(f"sqlite:///{Path(self.tmp.name) / 'svc.db'}")
        self.executor = StubExecutor()
        self.service = ResearchService(self.db, self.executor, Path(self.tmp.name))

    def tearDown(self):
        self.db.engine.dispose()
        self.tmp.cleanup()

    def _session(self):
        return self.db.session()


class TestSubmit(ServiceTestCase):
    def test_submit_creates_queued_run(self):
        result = self.service.submit(make_request())
        self.assertTrue(result.run_id.startswith("RUN-"))
        self.assertEqual(result.task_id, "TH_BESS_001")
        self.assertEqual(result.status, TaskStatus.QUEUED)
        with self._session() as session:
            from energy_research_agent.automation.db import TaskRepository

            repo = TaskRepository(session)
            task = repo.get_task("TH_BESS_001")
            self.assertEqual(task.status, "QUEUED")
            self.assertEqual(task.active_run_id, result.run_id)
            events = repo.list_events(result.run_id)
            self.assertEqual([(e.from_status, e.to_status) for e in events], [("CREATED", "QUEUED")])

    def test_submit_idempotent_by_key_returns_same_run(self):
        first = self.service.submit(make_request(idempotency_key="key-1"))
        replay = self.service.submit(make_request(idempotency_key="key-1"))
        self.assertEqual(replay.run_id, first.run_id)

    def test_submit_idempotent_key_wins_over_new_task_id(self):
        first = self.service.submit(make_request(idempotency_key="key-1"))
        replay = self.service.submit(make_request(task_id="OTHER", idempotency_key="key-1"))
        self.assertEqual(replay.run_id, first.run_id)
        self.assertEqual(replay.task_id, "TH_BESS_001")

    def test_submit_duplicate_task_id_raises(self):
        self.service.submit(make_request())
        with self.assertRaises(DuplicateTaskError):
            self.service.submit(make_request())

    def test_stop_all_cancels_prepared_queued_run(self):
        queued = self.service.submit(make_request())
        cancelled = self.service.cancel_running_runs()
        self.assertEqual([item.run_id for item in cancelled], [queued.run_id])
        self.assertEqual(cancelled[0].status, TaskStatus.FAILED)
        self.assertFalse(cancelled[0].error.retryable)


class TestExecuteRun(ServiceTestCase):
    def test_full_path_to_published(self):
        result = self.service.submit(make_request())
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS, evidence_count=5, gap_count=1
        )
        self.executor.freeze_outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            evidence_count=5,
            gap_count=1,
            artifacts=[
                ArtifactRef(
                    artifact_type=ArtifactType.EXCEL,
                    status=ArtifactStatus.PUBLISHED,
                    location="out/1.xlsx",
                )
            ],
        )
        final = self.service.execute_run(result.run_id)
        self.assertEqual(final.status, TaskStatus.PUBLISHED)
        self.assertEqual(self.executor.freeze_calls, 1)
        self.assertEqual(self.executor.research_calls, 1)
        self.assertEqual(len(final.artifact_manifest), 1)
        with self._session() as session:
            from energy_research_agent.automation.db import TaskRepository

            repo = TaskRepository(session)
            chain = [
                (e.from_status, e.to_status)
                for e in repo.list_events(result.run_id)
                if e.event_type == "STATUS_TRANSITION"
            ]
        expected = [
            ("CREATED", "QUEUED"),
            ("QUEUED", "RESEARCHING"),
            ("RESEARCHING", "EVIDENCE_COLLECTED"),
            ("EVIDENCE_COLLECTED", "VALIDATING"),
            ("VALIDATING", "APPROVED"),
            ("APPROVED", "FROZEN"),
            ("FROZEN", "PUBLISHING"),
            ("PUBLISHING", "PUBLISHED"),
        ]
        self.assertEqual(chain, expected)
        self.assertIsNotNone(final.finished_at)
        self.assertEqual(final.validation_status, ValidationStatus.PASS)
        self.assertEqual(final.evidence_count, 5)

    def test_validation_blocked_lands_in_blocked(self):
        result = self.service.submit(make_request())
        self.executor.outcome = ExecutionOutcome(validation_status=ValidationStatus.BLOCKED)
        final = self.service.execute_run(result.run_id)
        self.assertEqual(final.status, TaskStatus.BLOCKED)
        self.assertEqual(self.executor.freeze_calls, 0)
        self.assertIsNotNone(final.finished_at)

    def test_review_flag_is_auto_adjudicated_and_publishes(self):
        result = self.service.submit(make_request())
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            review_required=True,
            review_reasons=["CONFLICT_01: price conflict"],
        )
        approved = self.service.execute_run(result.run_id)
        self.assertEqual(approved.status, TaskStatus.PUBLISHED)
        self.assertFalse(approved.review_required)
        self.assertIn("CONFLICT_01", approved.review_reasons[0])
        self.assertEqual(self.executor.freeze_calls, 1)
        with self._session() as session:
            from energy_research_agent.automation.db import TaskRepository

            reviews = TaskRepository(session).list_reviews(result.run_id)
        self.assertEqual(reviews, [])

    def test_edit_and_approve_requires_modified_value(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ReviewSubmission(
                reviewer="analyst_01",
                decision=ReviewDecision.EDIT_AND_APPROVE,
                reason="edit",
            )

    def test_review_reject_is_unavailable_after_auto_publish(self):
        result = self.service.submit(make_request())
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS, review_required=True
        )
        self.service.execute_run(result.run_id)
        with self.assertRaises(InvalidTransitionError):
            self.service.submit_review(
                result.run_id,
                ReviewSubmission(reviewer="analyst_01", decision=ReviewDecision.REJECT, reason="not actionable"),
            )

    def test_review_research_again_is_unavailable_after_auto_publish(self):
        result = self.service.submit(make_request())
        self.executor.outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS, review_required=True
        )
        self.service.execute_run(result.run_id)
        with self.assertRaises(InvalidTransitionError):
            self.service.submit_review(
                result.run_id,
                ReviewSubmission(reviewer="analyst_01", decision=ReviewDecision.RESEARCH_AGAIN, reason="more sources needed"),
            )

    def test_review_on_non_gate_state_raises(self):
        result = self.service.submit(make_request())
        with self.assertRaises(InvalidTransitionError):
            self.service.submit_review(
                result.run_id,
                ReviewSubmission(reviewer="analyst_01", decision=ReviewDecision.APPROVE),
            )


class TestFailuresAndRetry(ServiceTestCase):
    def test_value_error_failure_is_not_retryable(self):
        self.executor.validate_error = ValueError("fixture schema rejected")
        result = self.service.submit(make_request())
        final = self.service.execute_run(result.run_id)
        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertIsNotNone(final.finished_at)
        self.assertEqual(final.error.error_type, "ValueError")
        self.assertFalse(final.error.retryable)

    def test_runtime_error_failure_is_retryable(self):
        self.executor.validate_error = RuntimeError("anysearch unreachable")
        result = self.service.submit(make_request())
        final = self.service.execute_run(result.run_id)
        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertTrue(final.error.retryable)

    def test_explicit_failure_terminates_immediately_and_notifies(self):
        adapter = MockFeishuAdapter()
        self.service.notifier = FeishuNotifier(adapter)
        self.executor.validate_error = RuntimeError("upstream failed")
        result = self.service.submit(make_request())

        final = self.service.execute_run(result.run_id)

        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertIsNotNone(final.finished_at)
        self.assertEqual(self.executor.research_calls, 1)
        self.assertEqual(self.executor.freeze_calls, 0)
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].status, "FAILED")
        self.assertIn("upstream failed", adapter.sent[0].text)

    def test_watchdog_failure_cannot_be_revived_by_late_executor_return(self):
        from datetime import datetime, timedelta, timezone
        from energy_research_agent.automation.db import TaskRepository

        def terminate_as_stale(run_id):
            with self._session() as session:
                row = TaskRepository(session).get_run(run_id)
                row.started_at = datetime.now(timezone.utc) - timedelta(hours=3)
                session.commit()
            recovered = self.service.recover_stale_runs(max_minutes=120)
            self.assertEqual([item.run_id for item in recovered], [run_id])

        self.executor.on_research = terminate_as_stale
        submitted = self.service.submit(make_request())

        final = self.service.execute_run(submitted.run_id)

        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertEqual(self.executor.freeze_calls, 0)
        with self._session() as session:
            row = TaskRepository(session).get_run(submitted.run_id)
            self.assertEqual(row.status, "FAILED")

    def test_publish_failure_lands_in_failed(self):
        self.executor.publish_error = RuntimeError("disk full")
        result = self.service.submit(make_request())
        final = self.service.execute_run(result.run_id)
        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertEqual(final.error.error_type, "RuntimeError")

    def test_required_artifact_qa_failure_cannot_publish_run(self):
        self.executor.freeze_outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            artifacts=[ArtifactRef(
                artifact_type=ArtifactType.WORD,
                status=ArtifactStatus.FAILED,
                location="out/failed.docx",
            )],
        )
        result = self.service.submit(make_request())

        final = self.service.execute_run(result.run_id)

        self.assertEqual(final.status, TaskStatus.FAILED)
        self.assertEqual(final.error.error_type, "RequiredArtifactPublicationError")
        self.assertIn("word", final.error.message.lower())
        self.assertEqual(self.executor.freeze_calls, 11)
        self.assertEqual(self.executor.repair_calls, 10)

    def test_recoverable_first_publication_failure_retries_before_notifying(self):
        adapter = MockFeishuAdapter()
        self.service.notifier = FeishuNotifier(adapter)
        failed = ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            artifacts=[ArtifactRef(
                artifact_type=ArtifactType.WORD,
                status=ArtifactStatus.FAILED,
                location="out/first.docx",
            )],
        )
        recovered = ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            artifacts=[ArtifactRef(
                artifact_type=ArtifactType.WORD,
                status=ArtifactStatus.PUBLISHED,
                location="out/recovered.docx",
            )],
        )
        outcomes = iter((failed, recovered))

        def publish_with_recovery(run_id, workdir):
            self.executor.freeze_calls += 1
            return next(outcomes)

        self.executor.freeze_and_publish = publish_with_recovery
        submitted = self.service.submit(make_request())

        final = self.service.execute_run(submitted.run_id)

        self.assertEqual(final.status, TaskStatus.PUBLISHED)
        self.assertEqual(self.executor.freeze_calls, 2)
        self.assertEqual(self.executor.repair_calls, 1)
        self.assertTrue(any("auto-recovery succeeded" in item for item in final.review_reasons))
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].status, "PUBLISHED")

    def test_manual_retry_after_artifact_failure_reuses_existing_evidence(self):
        self.executor.freeze_outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            artifacts=[ArtifactRef(
                artifact_type=ArtifactType.WORD,
                status=ArtifactStatus.FAILED,
                location="out/failed.docx",
            )],
        )
        submitted = self.service.submit(make_request())
        run_dir = Path(self.tmp.name) / submitted.run_id
        def leave_evidence(run_id):
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "evidence.sqlite3").touch()

        self.executor.on_research = leave_evidence
        failed = self.service.execute_run(submitted.run_id)
        self.assertEqual(failed.status, TaskStatus.FAILED)
        self.assertEqual(self.executor.research_calls, 1)
        self.assertEqual(self.executor.freeze_calls, 11)

        queued = self.service.retry(submitted.run_id)
        self.assertEqual(queued.status, TaskStatus.QUEUED)
        self.assertTrue((run_dir / "publication_retry.json").is_file())
        self.executor.freeze_outcome = ExecutionOutcome(
            validation_status=ValidationStatus.PASS,
            artifacts=[ArtifactRef(
                artifact_type=ArtifactType.WORD,
                status=ArtifactStatus.PUBLISHED,
                location="out/recovered.docx",
            )],
        )

        recovered = self.service.execute_run(submitted.run_id)

        self.assertEqual(recovered.status, TaskStatus.PUBLISHED)
        self.assertEqual(self.executor.research_calls, 1)
        self.assertEqual(self.executor.freeze_calls, 12)
        self.assertFalse((run_dir / "publication_retry.json").exists())

    def test_retry_requeues_until_exhausted(self):
        self.executor.validate_error = RuntimeError("search backend down")
        service = ResearchService(self.db, self.executor, Path(self.tmp.name), max_retries=1)
        result = service.submit(make_request())
        service.execute_run(result.run_id)
        first = service.retry(result.run_id)
        self.assertEqual(first.status, TaskStatus.QUEUED)
        self.assertIsNone(first.error)
        self.assertIsNone(first.started_at)
        self.assertIsNone(first.finished_at)
        service.execute_run(result.run_id)
        with self.assertRaises(RetryExhaustedError):
            service.retry(result.run_id)

    def test_successful_retry_does_not_retain_previous_error(self):
        self.executor.validate_error = RuntimeError("temporary search failure")
        submitted = self.service.submit(make_request())
        failed = self.service.execute_run(submitted.run_id)
        self.assertIsNotNone(failed.error)

        queued = self.service.retry(submitted.run_id)
        self.assertIsNone(queued.error)
        self.executor.validate_error = None
        published = self.service.execute_run(submitted.run_id)

        self.assertEqual(published.status, TaskStatus.PUBLISHED)
        self.assertIsNone(published.error)
        with self._session() as session:
            from energy_research_agent.automation.db import TaskRepository

            row = TaskRepository(session).get_run(submitted.run_id)
            self.assertIsNone(row.error_type)
            self.assertIsNone(row.error_message)

    def test_retry_only_from_failed_or_blocked(self):
        result = self.service.submit(make_request())
        with self.assertRaises(InvalidTransitionError):
            self.service.retry(result.run_id)

    def test_failed_run_cannot_be_reviewed(self):
        self.executor.validate_error = RuntimeError("boom")
        result = self.service.submit(make_request())
        self.service.execute_run(result.run_id)
        with self.assertRaises(InvalidTransitionError):
            self.service.submit_review(
                result.run_id,
                ReviewSubmission(reviewer="analyst_01", decision=ReviewDecision.APPROVE),
            )


class TestReads(ServiceTestCase):
    def test_get_status_result_artifacts(self):
        result = self.service.submit(make_request())
        self.service.execute_run(result.run_id)
        status = self.service.get_status(result.run_id)
        self.assertEqual(status.status, TaskStatus.PUBLISHED)
        payload = self.service.get_result(result.run_id)
        self.assertEqual(payload.task_id, "TH_BESS_001")
        artifacts = self.service.get_artifacts(result.run_id)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].artifact_type, ArtifactType.EXCEL)

    def test_missing_run_raises(self):
        with self.assertRaises(RunNotFoundError):
            self.service.get_status("NOPE")


class TestSyntheticKernelExecutorSmoke(unittest.TestCase):
    """Real-kernel smoke: fixture research path + full service run."""

    ROOT = Path(__file__).resolve().parents[1]

    def test_fixture_research_and_validate_produces_outcome(self):
        import json

        from energy_research_agent.automation.executor import SyntheticKernelExecutor
        from energy_research_agent.domain.models import ExtractedEvidenceBatch

        payload = json.loads(
            (self.ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8")
        )
        batches = [ExtractedEvidenceBatch.model_validate(item) for item in payload]
        executor = SyntheticKernelExecutor(fixture_batches={"TASK-FIXTURE": batches})
        request = make_request(task_id="TASK-FIXTURE", company="示例制造公司")
        with tempfile.TemporaryDirectory() as tmp:
            outcome = executor.research_and_validate("RUN-SMOKE", request, Path(tmp))
            self.assertEqual(outcome.validation_status, ValidationStatus.PASS)
            self.assertGreater(outcome.evidence_count, 0)
            self.assertFalse(outcome.review_required)
            from energy_research_agent.evidence.store import EvidenceStore

            store = EvidenceStore(Path(tmp) / "RUN-SMOKE" / "evidence.sqlite3")
            self.assertGreater(len(store.list("RUN-SMOKE", "entity")), 0)

    def test_service_full_path_publishes_when_fixture_artifact_qa_passes(self):
        import json

        from energy_research_agent.automation.executor import SyntheticKernelExecutor
        from energy_research_agent.domain.models import ExtractedEvidenceBatch

        payload = json.loads(
            (self.ROOT / "tests" / "fixtures" / "small_simple.json").read_text(encoding="utf-8")
        )
        batches = [ExtractedEvidenceBatch.model_validate(item) for item in payload]
        executor = SyntheticKernelExecutor(fixture_batches={"TASK-REAL": batches})
        with tempfile.TemporaryDirectory() as tmp:
            db = AutomationDatabase(f"sqlite:///{Path(tmp) / 'real.db'}")
            service = ResearchService(db, executor, Path(tmp))
            result = service.submit(make_request(task_id="TASK-REAL", company="简单企业"))
            final = service.execute_run(result.run_id)
            db.engine.dispose()
        self.assertEqual(final.status, TaskStatus.PUBLISHED)
        self.assertIsNone(final.error)


if __name__ == "__main__":
    unittest.main()
