"""Repository layer over the automation tables.

Every status write goes through :func:`assert_transition`, so the legal
transition table in ``automation.state_machine`` is enforced at the
persistence boundary even for callers that bypass the in-memory
``TaskStateMachine``. Each successful transition also appends a
``workflow_events`` row, giving every run a durable audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..contracts import ResearchRequest, ResearchResult
from ..enums import TaskStatus
from ..state_machine import assert_transition
from .models import (
    Base,
    ConflictResolutionRow,
    HumanReviewRow,
    ResearchRunRow,
    ResearchTaskRow,
    RunMetricRow,
    UserFeedbackRow,
    WorkflowEventRow,
)


class DuplicateTaskError(ValueError):
    """Raised when task_id or idempotency_key already exists."""


class RunNotFoundError(KeyError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize datetimes from the DB (naive on SQLite, aware on Postgres)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AutomationDatabase:
    """Engine/session factory; creates tables on first use."""

    def __init__(self, url: str = "sqlite:///:memory:") -> None:
        self.url = url
        self.engine: Engine = create_engine(url, future=True)
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._session_factory()


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- tasks ----------------------------------------------------------

    def create_task(self, request: ResearchRequest) -> ResearchTaskRow:
        row = ResearchTaskRow(
            task_id=request.task_id,
            idempotency_key=request.idempotency_key,
            requested_by=request.requested_by,
            priority=str(request.priority),
            status=str(TaskStatus.CREATED),
            request_payload=request.model_dump(mode="json"),
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateTaskError(
                f"task_id or idempotency_key already exists: {request.task_id}"
            ) from exc
        return row

    def get_task(self, task_id: str) -> ResearchTaskRow | None:
        return self.session.get(ResearchTaskRow, task_id)

    def find_by_idempotency_key(self, key: str) -> ResearchTaskRow | None:
        stmt = select(ResearchTaskRow).where(ResearchTaskRow.idempotency_key == key)
        return self.session.execute(stmt).scalar_one_or_none()

    # -- runs -----------------------------------------------------------

    def create_run(self, run_id: str, request: ResearchRequest) -> ResearchRunRow:
        row = ResearchRunRow(
            run_id=run_id,
            task_id=request.task_id,
            requested_by=request.requested_by,
            country=request.country,
            product=request.product,
            status=str(TaskStatus.CREATED),
        )
        self.session.add(row)
        task = self.get_task(request.task_id)
        if task is not None:
            task.active_run_id = run_id
        self.session.commit()
        return row

    def get_run(self, run_id: str) -> ResearchRunRow | None:
        return self.session.get(ResearchRunRow, run_id)

    def update_run_status(
        self,
        run_id: str,
        target: TaskStatus,
        *,
        reason: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> ResearchRunRow:
        row = self.get_run(run_id)
        if row is None:
            raise RunNotFoundError(run_id)
        source = TaskStatus(row.status)
        assert_transition(source, target)
        row.status = str(target)
        now = _utc_now()
        if started:
            # 每次进入执行态都刷新开始时间：重试后的 run 重新计时，
            # 避免陈旧 started_at 被僵尸检测误判为超时。
            row.started_at = now
        if finished:
            row.finished_at = now
            if row.started_at is not None:
                row.duration_seconds = (
                    _as_utc(row.finished_at) - _as_utc(row.started_at)
                ).total_seconds()
        self.record_event(
            run_id=run_id,
            task_id=row.task_id,
            event_type="STATUS_TRANSITION",
            from_status=str(source),
            to_status=str(target),
            payload={"reason": reason} if reason else None,
            commit=False,
        )
        task = self.get_task(row.task_id)
        if task is not None:
            task.status = str(target)
        self.session.commit()
        return row

    def finalize_run(self, result: ResearchResult) -> ResearchRunRow:
        """Persist the structured ResearchResult summary onto the run row."""
        row = self.get_run(result.run_id)
        if row is None:
            raise RunNotFoundError(result.run_id)
        row.validation_status = (
            str(result.validation_status) if result.validation_status else None
        )
        row.confidence = result.confidence
        row.risk_level = str(result.risk_level) if result.risk_level else None
        row.review_required = result.review_required
        row.evidence_count = result.evidence_count
        row.conflict_count = result.conflict_count
        row.gap_count = result.gap_count
        row.input_tokens = result.cost_metrics.input_tokens
        row.output_tokens = result.cost_metrics.output_tokens
        row.estimated_cost = result.cost_metrics.estimated_cost_usd
        row.artifact_manifest = [
            ref.model_dump(mode="json") for ref in result.artifact_manifest
        ]
        row.result_payload = result.model_dump(mode="json")
        if result.error is not None:
            row.error_type = result.error.error_type
            row.error_message = result.error.message
        self.session.commit()
        return row

    # -- events ---------------------------------------------------------

    def record_event(
        self,
        *,
        run_id: str | None,
        task_id: str,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        step: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> WorkflowEventRow:
        row = WorkflowEventRow(
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            step=step,
            payload=payload,
        )
        self.session.add(row)
        if commit:
            self.session.commit()
        return row

    def list_events(self, run_id: str) -> list[WorkflowEventRow]:
        stmt = (
            select(WorkflowEventRow)
            .where(WorkflowEventRow.run_id == run_id)
            .order_by(WorkflowEventRow.event_id)
        )
        return list(self.session.execute(stmt).scalars())

    # -- reviews --------------------------------------------------------

    def save_review(
        self,
        *,
        review_id: str,
        run_id: str,
        task_id: str,
        reviewer: str,
        decision: str,
        reason: str = "",
        original_value: dict[str, Any] | None = None,
        modified_value: dict[str, Any] | None = None,
    ) -> HumanReviewRow:
        row = HumanReviewRow(
            review_id=review_id,
            run_id=run_id,
            task_id=task_id,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
            original_value=original_value,
            modified_value=modified_value,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def list_reviews(self, run_id: str) -> list[HumanReviewRow]:
        stmt = (
            select(HumanReviewRow)
            .where(HumanReviewRow.run_id == run_id)
            .order_by(HumanReviewRow.created_at)
        )
        return list(self.session.execute(stmt).scalars())

    # -- metrics --------------------------------------------------------

    def upsert_metrics(self, run_id: str, **fields: Any) -> RunMetricRow:
        row = self.session.get(RunMetricRow, run_id)
        if row is None:
            row = RunMetricRow(run_id=run_id)
            self.session.add(row)
        for key, value in fields.items():
            if not hasattr(row, key):
                raise AttributeError(f"unknown run_metrics field: {key}")
            setattr(row, key, value)
        self.session.commit()
        return row

    def get_metrics(self, run_id: str) -> RunMetricRow | None:
        return self.session.get(RunMetricRow, run_id)

    # -- feedback -------------------------------------------------------

    def save_feedback(
        self,
        *,
        feedback_id: str,
        run_id: str,
        task_id: str,
        submitted_by: str,
        adoption_status: str | None = None,
        user_rating: int | None = None,
        manual_baseline_minutes: float | None = None,
        human_review_minutes: float | None = None,
        human_edit_count: int | None = None,
        comment: str | None = None,
    ) -> UserFeedbackRow:
        row = UserFeedbackRow(
            feedback_id=feedback_id,
            run_id=run_id,
            task_id=task_id,
            submitted_by=submitted_by,
            adoption_status=adoption_status,
            user_rating=user_rating,
            manual_baseline_minutes=manual_baseline_minutes,
            human_review_minutes=human_review_minutes,
            human_edit_count=human_edit_count,
            comment=comment,
        )
        self.session.add(row)
        self.session.commit()
        return row

    # -- conflict resolutions (冲突裁决) ----------------------------------

    def save_conflict_resolution(
        self,
        *,
        resolution_id: str,
        run_id: str,
        task_id: str,
        conflict_group_id: str,
        decision: str,
        selected_claim_id: str | None = None,
        reviewer: str,
        rationale: str = "",
    ) -> ConflictResolutionRow:
        row = ConflictResolutionRow(
            resolution_id=resolution_id,
            run_id=run_id,
            task_id=task_id,
            conflict_group_id=conflict_group_id,
            decision=decision,
            selected_claim_id=selected_claim_id,
            reviewer=reviewer,
            rationale=rationale,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def list_conflict_resolutions(self, run_id: str) -> list[ConflictResolutionRow]:
        stmt = (
            select(ConflictResolutionRow)
            .where(ConflictResolutionRow.run_id == run_id)
            .order_by(ConflictResolutionRow.created_at)
        )
        return list(self.session.execute(stmt).scalars())
