"""Application service orchestrating repository, state machine and executor (Phase 2).

:class:`ResearchService` is the single entry point behind the FastAPI
layer; it never imports FastAPI itself so it stays testable in plain
unittest and reusable by n8n-side workers. It owns the workflow rules:

- ``submit`` is idempotent by ``idempotency_key`` and rejects duplicate
  ``task_id``.
- status changes always go through ``TaskRepository.update_run_status``,
  which enforces ``LEGAL_TRANSITIONS`` at the persistence boundary.
- the human gate sits between validation and freeze: the run may only
  reach FROZEN after REVIEW_REQUIRED -> APPROVED (or validation auto-pass
  -> APPROVED), and ``executor.freeze_and_publish`` is invoked only from
  APPROVED.
- every failure is captured as a structured ``ResearchError`` and the run
  moves to FAILED; retries are bounded by ``max_retries``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..domain.enums import ValidationStatus
from ..domain.ids import new_sortable_id
from .contracts import (
    ArtifactRef,
    ResearchError,
    ResearchRequest,
    ResearchResult,
    ReviewSubmission,
)
from .db import AutomationDatabase, DuplicateTaskError, RunNotFoundError, TaskRepository
from .db.models import ResearchRunRow, UserFeedbackRow
from .enums import ReviewDecision, TaskStatus
from .executor import ExecutionOutcome, ResearchExecutor
from .feishu.notifier import FeishuNotifier
from .observability import log_event, run_span
from .retry import RetryPolicy
from .review import ReviewGateResult, ReviewPolicy
from .roi import RoiRunRow
from .state_machine import InvalidTransitionError, assert_transition


class RetryExhaustedError(ValueError):
    """Raised when a run has consumed all allowed retries."""


class ConflictNotFoundError(KeyError):
    """Raised when a conflict group id does not exist in the run's evidence."""


class ConflictResolutionError(ValueError):
    """Raised when a conflict resolution request is invalid."""


class StaleRunError(RuntimeError):
    """Raised when a RESEARCHING run has shown no progress for too long.

    The typical cause is the hosting process being killed mid-run (e.g. a
    container rebuild); the run is marked FAILED and becomes retryable.
    """


def _as_utc(value: datetime) -> datetime:
    """Normalize datetimes from the DB (naive on SQLite, aware on Postgres)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ResearchService:
    """Workflow orchestration for automated research tasks/runs.

    One service instance owns one ``AutomationDatabase``; sessions are
    short-lived per call, so the same service can be shared by API workers
    and background executors.
    """

    def __init__(
        self,
        db: AutomationDatabase,
        executor: ResearchExecutor,
        workdir: Path,
        max_retries: int = 3,
        *,
        review_policy: ReviewPolicy | None = None,
        retry_policy: RetryPolicy | None = None,
        notifier: FeishuNotifier | None = None,
    ) -> None:
        self.db = db
        self.executor = executor
        self.workdir = Path(workdir)
        self.max_retries = max_retries
        self.review_policy = review_policy or ReviewPolicy()
        self.retry_policy = retry_policy or RetryPolicy()
        self.notifier = notifier or FeishuNotifier()

    # -- submission ------------------------------------------------------

    def submit(self, request: ResearchRequest) -> ResearchResult:
        """Create a task + first run in QUEUED; idempotent by key.

        If ``idempotency_key`` was already accepted, the existing task's
        active run status is returned (replay semantics). A fresh
        ``task_id`` with no key colliding with an existing task raises
        :class:`DuplicateTaskError`.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            if request.idempotency_key:
                existing = repo.find_by_idempotency_key(request.idempotency_key)
                if existing is not None:
                    return self._result_for_task(repo, existing)
            if repo.get_task(request.task_id) is not None:
                raise DuplicateTaskError(f"task_id already exists: {request.task_id}")
            repo.create_task(request)
            run_id = new_sortable_id("RUN")
            repo.create_run(run_id, request)
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="accepted by service")
            return self._build_result(repo.get_run(run_id))
        finally:
            session.close()

    # -- execution ---------------------------------------------------------

    def execute_run(self, run_id: str) -> ResearchResult:
        """Run the deterministic workflow until a gate, terminal state or failure.

        Research -> evidence -> validation always ends at one of:
        BLOCKED (finished), REVIEW_REQUIRED (human gate per the review
        policy) or APPROVED -> freeze -> publish -> PUBLISHED. Failures
        move the run to FAILED with a structured error and never leave it
        wedged mid-state.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            request = ResearchRequest.model_validate(
                self._require_task(repo, row.task_id).request_payload
            )
            # Re-execution means "research from scratch": drop any evidence
            # left by a previous FAILED/BLOCKED attempt (never reachable for
            # PUBLISHED/REJECTED runs, which cannot be re-executed).
            run_dir = self.workdir / run_id
            if run_dir.exists():
                import shutil

                shutil.rmtree(run_dir)
            repo.update_run_status(
                run_id, TaskStatus.RESEARCHING, reason="worker started", started=True
            )
            try:
                with run_span("research", run_id=run_id):
                    outcome = self.executor.research_and_validate(
                        run_id, request, self.workdir
                    )
                repo.update_run_status(run_id, TaskStatus.EVIDENCE_COLLECTED, reason="evidence ingested")
                repo.update_run_status(run_id, TaskStatus.VALIDATING, reason="validation gate")
                if outcome.validation_status == ValidationStatus.BLOCKED:
                    repo.update_run_status(run_id, TaskStatus.BLOCKED, reason="validation blocked", finished=True)
                    return self._settle(repo, run_id, outcome, TaskStatus.BLOCKED)
                gate = self._gate(outcome, request)
                if outcome.review_required or gate.review_required:
                    reasons = list(outcome.review_reasons)
                    reasons.extend(reason for reason in gate.reasons if reason not in reasons)
                    outcome.review_reasons = reasons
                    outcome.review_required = True
                    repo.update_run_status(run_id, TaskStatus.REVIEW_REQUIRED, reason="human review gate")
                    return self._settle(repo, run_id, outcome, TaskStatus.REVIEW_REQUIRED)
                repo.update_run_status(run_id, TaskStatus.APPROVED, reason="validation auto-pass")
                return self._freeze_and_publish(repo, run_id)
            except Exception as exc:  # noqa: BLE001 - a run must never wedge mid-state
                return self._fail(repo, run_id, exc)
        finally:
            session.close()

    def _gate(self, outcome: ExecutionOutcome, request: ResearchRequest) -> ReviewGateResult:
        """Apply the configured Review Policy rules on top of the executor flag."""
        return self.review_policy.evaluate(outcome, request)

    def _freeze_and_publish(self, repo: TaskRepository, run_id: str) -> ResearchResult:
        """Freeze -> publish -> audit; only ever invoked from APPROVED."""
        try:
            with run_span("publishing", run_id=run_id):
                outcome = self.executor.freeze_and_publish(run_id, self.workdir)
            repo.update_run_status(run_id, TaskStatus.FROZEN, reason="evidence frozen")
            repo.update_run_status(run_id, TaskStatus.PUBLISHING, reason="publishing artifacts")
            repo.update_run_status(run_id, TaskStatus.PUBLISHED, finished=True)
            return self._settle(repo, run_id, outcome, TaskStatus.PUBLISHED)
        except Exception as exc:  # noqa: BLE001 - publish failures must land in FAILED
            return self._fail(repo, run_id, exc)

    # -- review gate --------------------------------------------------------

    def submit_review(self, run_id: str, review: ReviewSubmission) -> ResearchResult:
        """Apply a human decision at the REVIEW_REQUIRED gate.

        APPROVE/EDIT_AND_APPROVE continue to freeze+publish; REJECT is
        terminal; RESEARCH_AGAIN re-queues the run. Any decision on a run
        that is not REVIEW_REQUIRED raises :class:`InvalidTransitionError`.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            target = {
                ReviewDecision.APPROVE: TaskStatus.APPROVED,
                ReviewDecision.EDIT_AND_APPROVE: TaskStatus.APPROVED,
                ReviewDecision.REJECT: TaskStatus.REJECTED,
                ReviewDecision.RESEARCH_AGAIN: TaskStatus.RETRYING,
            }[review.decision]
            assert_transition(TaskStatus(row.status), target)
            repo.save_review(
                review_id=new_sortable_id("REV"),
                run_id=run_id,
                task_id=row.task_id,
                reviewer=review.reviewer,
                decision=str(review.decision),
                reason=review.reason,
                original_value=review.original_value,
                modified_value=review.modified_value,
            )
            if review.decision in (ReviewDecision.APPROVE, ReviewDecision.EDIT_AND_APPROVE):
                repo.update_run_status(
                    run_id, TaskStatus.APPROVED, reason=f"review decision: {review.decision}"
                )
                return self._freeze_and_publish(repo, run_id)
            if review.decision == ReviewDecision.REJECT:
                repo.update_run_status(
                    run_id,
                    TaskStatus.REJECTED,
                    reason=review.reason or "rejected by reviewer",
                    finished=True,
                )
                result = self.get_status(run_id)
                self._notify(result)
                return result
            repo.update_run_status(run_id, TaskStatus.RETRYING, reason="research again per review")
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="re-queued after review")
            return self.get_status(run_id)
        finally:
            session.close()

    # -- retry ---------------------------------------------------------------

    def retry(self, run_id: str) -> ResearchResult:
        """Re-queue a FAILED/BLOCKED run; bounded by ``max_retries``.

        Retry count is derived from the durable ``workflow_events`` audit
        trail (STATUS_TRANSITION -> RETRYING), so it survives restarts.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            assert_transition(TaskStatus(row.status), TaskStatus.RETRYING)
            retries = sum(
                1
                for event in repo.list_events(run_id)
                if event.event_type == "STATUS_TRANSITION"
                and event.to_status == str(TaskStatus.RETRYING)
            )
            if retries >= self.max_retries:
                raise RetryExhaustedError(
                    f"run {run_id} exhausted retries: {retries}/{self.max_retries}"
                )
            repo.update_run_status(run_id, TaskStatus.RETRYING, reason="retry scheduled")
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="re-queued for retry")
            return self.get_status(run_id)
        finally:
            session.close()

    # -- conflict adjudication (冲突裁决) -------------------------------------

    def list_conflicts(self, run_id: str) -> list[dict]:
        """List the run's evidence conflicts (from its immutable evidence store)."""
        store = self._evidence_store(run_id)
        if store is None:
            return []
        return [conflict.model_dump(mode="json") for conflict in store.list(run_id, "conflict")]

    def resolve_conflict(
        self,
        run_id: str,
        conflict_group_id: str,
        *,
        decision: str,
        reviewer: str,
        rationale: str = "",
        selected_claim_id: str | None = None,
    ) -> ResearchResult:
        """Adjudicate a BLOCKING conflict, then move the run to QUEUED.

        The resolution is recorded durably (``conflict_resolutions`` table)
        and mirrored into the run's workdir snapshot so the re-validation
        during freeze treats this group as resolved. The reviewer must pick
        a claim for ``select_authoritative``; the run must be BLOCKED.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            current = TaskStatus(row.status)
            if current != TaskStatus.BLOCKED:
                raise InvalidTransitionError(current, TaskStatus.RETRYING)
            conflict = self._find_conflict(run_id, conflict_group_id)
            if conflict is None:
                raise ConflictNotFoundError(conflict_group_id)
            if decision == "select_authoritative":
                if not selected_claim_id:
                    raise ConflictResolutionError(
                        "select_authoritative requires selected_claim_id"
                    )
                if selected_claim_id not in conflict.claim_ids:
                    raise ConflictResolutionError(
                        f"selected_claim_id {selected_claim_id} is not part of "
                        f"conflict group {conflict_group_id}"
                    )
            elif decision not in ("coexist", "superseded"):
                raise ConflictResolutionError(f"unknown decision: {decision}")
            repo.save_conflict_resolution(
                resolution_id=new_sortable_id("RSL"),
                run_id=run_id,
                task_id=row.task_id,
                conflict_group_id=conflict_group_id,
                decision=decision,
                selected_claim_id=selected_claim_id,
                reviewer=reviewer,
                rationale=rationale,
            )
            self._write_resolved_conflict(run_id, conflict_group_id)
            repo.update_run_status(
                run_id, TaskStatus.RETRYING, reason=f"conflict {conflict_group_id} adjudicated"
            )
            repo.update_run_status(run_id, TaskStatus.QUEUED, reason="awaiting resume after adjudication")
            return self.get_status(run_id)
        finally:
            session.close()

    def resume(self, run_id: str) -> ResearchResult:
        """Continue a conflict-adjudicated run without redoing research.

        Walks QUEUED -> ... -> APPROVED over the preserved evidence and lets
        the executor freeze + publish. Only allowed when the run carries at
        least one recorded conflict resolution and sits in QUEUED.
        """
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            if TaskStatus(row.status) != TaskStatus.QUEUED:
                raise InvalidTransitionError(TaskStatus(row.status), TaskStatus.RESEARCHING)
            if not repo.list_conflict_resolutions(run_id):
                raise ConflictResolutionError(
                    f"run {run_id} has no recorded conflict resolutions; nothing to resume"
                )
            repo.update_run_status(run_id, TaskStatus.RESEARCHING, reason="resume after adjudication")
            repo.update_run_status(run_id, TaskStatus.EVIDENCE_COLLECTED, reason="evidence preserved from blocked run")
            repo.update_run_status(run_id, TaskStatus.VALIDATING, reason="re-validating with resolved conflicts")
            repo.update_run_status(run_id, TaskStatus.APPROVED, reason="conflicts adjudicated by reviewer")
            return self._freeze_and_publish(repo, run_id)
        finally:
            session.close()

    def recover_stale_runs(self, *, max_minutes: int = 120) -> list[ResearchResult]:
        """Mark RESEARCHING runs with no progress for too long as FAILED (僵尸任务检测).

        A run stuck in RESEARCHING beyond ``max_minutes`` since ``started_at``
        almost certainly lost its executor (host process killed mid-run, e.g.
        container rebuild). Recovering it un-wedges the state: it becomes
        FAILED + retryable and triggers the usual Feishu notification, so the
        operator can retry instead of staring at a hanging run.
        """
        from datetime import timedelta

        from sqlalchemy import select

        from .db.models import ResearchRunRow

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)
        session = self.db.session()
        recovered: list[ResearchResult] = []
        try:
            rows = session.execute(
                select(ResearchRunRow).where(
                    ResearchRunRow.status == str(TaskStatus.RESEARCHING),
                    ResearchRunRow.started_at.is_not(None),
                )
            ).scalars().all()
            repo = TaskRepository(session)
            for row in rows:
                started_at = _as_utc(row.started_at)
                if started_at >= cutoff:
                    continue
                result = self._fail(
                    repo,
                    row.run_id,
                    StaleRunError(
                        f"run {row.run_id} showed no progress since "
                        f"{started_at:%Y-%m-%d %H:%M} UTC; the executor process was "
                        "likely interrupted (e.g. container restart)"
                    ),
                )
                recovered.append(result)
            return recovered
        finally:
            session.close()

    # -- internals -------------------------------------------------------------

    def _evidence_store(self, run_id: str):
        from ..evidence.store import EvidenceStore

        path = self.workdir / run_id / "evidence.sqlite3"
        if not path.is_file():
            return None
        return EvidenceStore(path)

    def _find_conflict(self, run_id: str, conflict_group_id: str):
        store = self._evidence_store(run_id)
        if store is None:
            return None
        for conflict in store.list(run_id, "conflict"):
            if conflict.conflict_group_id == conflict_group_id:
                return conflict
        return None

    def _write_resolved_conflict(self, run_id: str, conflict_group_id: str) -> None:
        run_dir = self.workdir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "resolved_conflicts.json"
        ids = []
        if path.is_file():
            ids = list(json.loads(path.read_text(encoding="utf-8")).get("conflict_group_ids", []))
        if conflict_group_id not in ids:
            ids.append(conflict_group_id)
        path.write_text(
            json.dumps({"conflict_group_ids": ids}, ensure_ascii=False), encoding="utf-8"
        )

    # -- reads ---------------------------------------------------------------

    def get_status(self, run_id: str) -> ResearchResult:
        session = self.db.session()
        try:
            return self._build_result(self._require_run(TaskRepository(session), run_id))
        finally:
            session.close()

    def get_result(self, run_id: str) -> ResearchResult:
        """Full structured result (last finalized summary, live status)."""
        session = self.db.session()
        try:
            return self._build_result(self._require_run(TaskRepository(session), run_id))
        finally:
            session.close()

    def get_artifacts(self, run_id: str) -> list[ArtifactRef]:
        session = self.db.session()
        try:
            row = self._require_run(TaskRepository(session), run_id)
            return [
                ArtifactRef.model_validate(ref) for ref in (row.artifact_manifest or [])
            ]
        finally:
            session.close()

    def submit_feedback(
        self,
        run_id: str,
        *,
        submitted_by: str,
        adoption_status: str | None = None,
        user_rating: int | None = None,
        manual_baseline_minutes: float | None = None,
        human_review_minutes: float | None = None,
        human_edit_count: int | None = None,
        comment: str | None = None,
    ) -> ResearchResult:
        """Record requester feedback (Phase 11 ROI input); validated against the run."""
        session = self.db.session()
        try:
            repo = TaskRepository(session)
            row = self._require_run(repo, run_id)
            repo.save_feedback(
                feedback_id=new_sortable_id("FB"),
                run_id=run_id,
                task_id=row.task_id,
                submitted_by=submitted_by,
                adoption_status=adoption_status,
                user_rating=user_rating,
                manual_baseline_minutes=manual_baseline_minutes,
                human_review_minutes=human_review_minutes,
                human_edit_count=human_edit_count,
                comment=comment,
            )
            return self._build_result(self._require_run(repo, run_id))
        finally:
            session.close()

    def roi_rows(self) -> list[RoiRunRow]:
        """Join durable feedback + metrics into ROI inputs (never fabricates)."""
        session = self.db.session()
        try:
            runs = {row.run_id: row for row in session.query(ResearchRunRow).all()}
            rows: list[RoiRunRow] = []
            for feedback in session.query(UserFeedbackRow).all():
                run = runs.get(feedback.run_id)
                if run is None:
                    continue
                rows.append(RoiRunRow(
                    run_id=feedback.run_id,
                    task_id=feedback.task_id,
                    manual_baseline_minutes=feedback.manual_baseline_minutes or 0.0,
                    human_review_minutes=feedback.human_review_minutes or 0.0,
                    human_edit_count=feedback.human_edit_count or 0,
                    machine_total_seconds=run.duration_seconds or 0.0,
                    adoption_status=feedback.adoption_status,
                ))
            return rows
        finally:
            session.close()

    # -- internals -------------------------------------------------------------

    @staticmethod
    def _require_run(repo: TaskRepository, run_id: str) -> object:
        row = repo.get_run(run_id)
        if row is None:
            raise RunNotFoundError(run_id)
        return row

    @staticmethod
    def _require_task(repo: TaskRepository, task_id: str) -> object:
        row = repo.get_task(task_id)
        if row is None:
            raise RunNotFoundError(f"task not found: {task_id}")
        return row

    def _result_for_task(self, repo: TaskRepository, task_row: object) -> ResearchResult:
        """Idempotent replay: current status of the task's active run."""
        run_id = task_row.active_run_id
        if run_id is None:
            raise RunNotFoundError(f"task has no active run: {task_row.task_id}")
        return self._build_result(self._require_run(repo, run_id))

    def _settle(
        self, repo: TaskRepository, run_id: str, outcome: ExecutionOutcome, status: TaskStatus
    ) -> ResearchResult:
        """Persist the outcome summary + metrics at a gate/terminal state."""
        row = self._require_run(repo, run_id)
        result = self._result_from_outcome(row, outcome)
        result.status = status
        repo.finalize_run(result)
        self._store_metrics(repo, run_id, outcome)
        result = self._build_result(self._require_run(repo, run_id))
        self._notify(result)
        return result

    def _store_metrics(
        self, repo: TaskRepository, run_id: str, outcome: ExecutionOutcome
    ) -> None:
        """Persist ROI/observability counters (Phase 10/11); tokens default 0."""
        repo.upsert_metrics(
            run_id,
            evidence_count=outcome.evidence_count,
            verified_claim_count=outcome.verified_claim_count,
            conflict_count=outcome.conflict_count,
            gap_count=outcome.gap_count,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            tool_calls=outcome.llm_calls,
            search_calls=outcome.search_calls,
        )

    def _fail(self, repo: TaskRepository, run_id: str, exc: BaseException) -> ResearchResult:
        error = ResearchError(
            error_type=type(exc).__name__,
            message=str(exc) or type(exc).__name__,
            retryable=self.retry_policy.should_retry(exc, attempts_used=0),
        )
        repo.update_run_status(
            run_id, TaskStatus.FAILED, reason=f"failed: {error.error_type}", finished=True
        )
        row = self._require_run(repo, run_id)
        result = ResearchResult(
            run_id=run_id,
            task_id=row.task_id,
            status=TaskStatus.FAILED,
            error=error,
        )
        repo.finalize_run(result)
        result = self._build_result(self._require_run(repo, run_id))
        self._notify(result)
        return result

    def _notify(self, result: ResearchResult) -> None:
        """Surface gate/terminal transitions to Feishu (Phase 7), never raises."""
        if self.notifier is None:
            return
        try:
            self.notifier.notify(result)
        except Exception as exc:  # noqa: BLE001 - notifications must not break the run
            log_event("notify.error", run_id=result.run_id, error=str(exc))

    @staticmethod
    def _result_from_outcome(row: object, outcome: ExecutionOutcome) -> ResearchResult:
        return ResearchResult(
            run_id=row.run_id,
            task_id=row.task_id,
            status=TaskStatus(row.status),
            created_at=_as_utc(row.created_at),
            validation_status=outcome.validation_status,
            confidence=outcome.confidence,
            risk_level=outcome.risk_level,
            review_required=outcome.review_required,
            review_reasons=list(outcome.review_reasons),
            evidence_count=outcome.evidence_count,
            conflict_count=outcome.conflict_count,
            gap_count=outcome.gap_count,
            artifact_manifest=list(outcome.artifacts),
        )

    def _build_result(self, row: object) -> ResearchResult:
        """Rehydrate the last finalized summary with live status/timestamps."""
        result: ResearchResult
        if row.result_payload:
            result = ResearchResult.model_validate(row.result_payload)
        else:
            result = ResearchResult(
                run_id=row.run_id,
                task_id=row.task_id,
                status=TaskStatus(row.status),
            )
        result.status = TaskStatus(row.status)
        if row.started_at is not None:
            result.started_at = _as_utc(row.started_at)
        if row.finished_at is not None:
            result.finished_at = _as_utc(row.finished_at)
        return result
