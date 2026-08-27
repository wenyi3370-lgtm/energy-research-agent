"""Deterministic task state machine for automated research runs (Phase 3).

Business status transitions are workflow rules, not agent decisions:
only the transitions declared in :data:`LEGAL_TRANSITIONS` are allowed,
and any attempt to jump illegally (e.g. VALIDATING → PUBLISHED, which
would bypass the freeze and review gates) raises
:class:`InvalidTransitionError`.

State semantics:

- CREATED / QUEUED: task accepted, waiting for a worker.
- RESEARCHING: planner/search/extraction in progress (agentic zone).
- EVIDENCE_COLLECTED: batches ingested, kernel normalization done.
- VALIDATING: CoreValidator + delivery-quality gates running.
- REVIEW_REQUIRED: human-in-the-loop gate; only a reviewer can move on.
- APPROVED: validation and (if required) human review passed; freeze allowed.
- REJECTED: terminal; reviewer or policy rejected the run.
- FROZEN: immutable evidence freeze created; publishers may consume it.
- PUBLISHING / PUBLISHED: artifact build and delivery; PUBLISHED is terminal.
- RETRYING: a bounded retry is scheduled/underway after FAILED/BLOCKED.
- FAILED: retryable failure; may only continue via RETRYING.
- BLOCKED: policy/validation block; requires intervention before RETRYING.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ..domain.models import StrictModel, utc_now
from .enums import TaskStatus

LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.FAILED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RESEARCHING, TaskStatus.FAILED, TaskStatus.BLOCKED}),
    TaskStatus.RESEARCHING: frozenset(
        {TaskStatus.EVIDENCE_COLLECTED, TaskStatus.RETRYING, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    TaskStatus.EVIDENCE_COLLECTED: frozenset(
        {TaskStatus.VALIDATING, TaskStatus.RETRYING, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    # Per the review-gate contract: VALIDATING may never reach PUBLISHED
    # directly; it must pass through REVIEW_REQUIRED/APPROVED (or BLOCKED).
    TaskStatus.VALIDATING: frozenset(
        {TaskStatus.REVIEW_REQUIRED, TaskStatus.APPROVED, TaskStatus.BLOCKED}
    ),
    TaskStatus.REVIEW_REQUIRED: frozenset(
        {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.RETRYING}
    ),
    TaskStatus.APPROVED: frozenset({TaskStatus.FROZEN, TaskStatus.FAILED}),
    TaskStatus.REJECTED: frozenset(),
    TaskStatus.FROZEN: frozenset({TaskStatus.PUBLISHING, TaskStatus.FAILED}),
    TaskStatus.PUBLISHING: frozenset(
        {TaskStatus.PUBLISHED, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    TaskStatus.PUBLISHED: frozenset(),
    TaskStatus.RETRYING: frozenset(
        {TaskStatus.QUEUED, TaskStatus.RESEARCHING, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.RETRYING}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.RETRYING}),
}

TERMINAL_STATES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.PUBLISHED, TaskStatus.REJECTED}
)


class InvalidTransitionError(ValueError):
    """Raised when a transition is not in :data:`LEGAL_TRANSITIONS`."""

    def __init__(self, source: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"illegal task transition: {source} -> {target}")
        self.source = source
        self.target = target


class TransitionRecord(StrictModel):
    from_status: TaskStatus
    to_status: TaskStatus
    at: datetime = Field(default_factory=utc_now)
    reason: str | None = None


def is_terminal(status: TaskStatus) -> bool:
    return status in TERMINAL_STATES


def assert_transition(source: TaskStatus, target: TaskStatus) -> None:
    """Validate a single transition; pure function for DB-driven services."""
    if target not in LEGAL_TRANSITIONS[source]:
        raise InvalidTransitionError(source, target)


class TaskStateMachine:
    """In-memory state machine with a full transition audit trail."""

    def __init__(self, initial: TaskStatus = TaskStatus.CREATED) -> None:
        self._state = initial
        self._history: list[TransitionRecord] = []

    @property
    def state(self) -> TaskStatus:
        return self._state

    @property
    def history(self) -> tuple[TransitionRecord, ...]:
        return tuple(self._history)

    def can_transition(self, target: TaskStatus) -> bool:
        return target in LEGAL_TRANSITIONS[self._state]

    def transition(self, target: TaskStatus, *, reason: str | None = None) -> TransitionRecord:
        assert_transition(self._state, target)
        record = TransitionRecord(
            from_status=self._state, to_status=target, reason=reason
        )
        self._state = target
        self._history.append(record)
        return record
