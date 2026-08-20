"""Automation-layer persistence (Phase 4).

These tables belong to the automation/control plane only. The evidence
plane keeps its own append-only SQLite store (``evidence/store.py``);
nothing here duplicates or mutates evidence records.

Column choice stays portable (String/Integer/Float/Boolean/DateTime/JSON)
so the same models run on SQLite for dev/tests and PostgreSQL for
deployment via the same ``database_url``.

Security rule: no API keys, passwords, cookies or tokens are ever stored
in these tables. Request/result payloads are research metadata only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ResearchTaskRow(Base):
    __tablename__ = "research_tasks"

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(128), index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)
    active_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResearchRunRow(Base):
    __tablename__ = "research_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("research_tasks.task_id"), index=True
    )
    requested_by: Mapped[str] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    gap_count: Mapped[int] = mapped_column(Integer, default=0)

    validation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)

    human_review_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_edit_count: Mapped[int] = mapped_column(Integer, default=0)

    artifact_manifest: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HumanReviewRow(Base):
    __tablename__ = "human_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(2048), default="")
    original_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    modified_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunMetricRow(Base):
    __tablename__ = "run_metrics"

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("research_runs.run_id"), primary_key=True
    )
    total_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    research_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_review_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    publishing_duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_llm_cost: Mapped[float] = mapped_column(Float, default=0.0)

    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    search_calls: Mapped[int] = mapped_column(Integer, default=0)

    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_claim_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    gap_count: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserFeedbackRow(Base):
    __tablename__ = "user_feedback"

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    submitted_by: Mapped[str] = mapped_column(String(128))
    adoption_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_baseline_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_review_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_edit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConflictResolutionRow(Base):
    """Human adjudication of a BLOCKING evidence conflict (冲突裁决, audit trail).

    The resolution itself lives here (automation control plane); the frozen
    evidence stays immutable. ``selected_claim_id`` is the authoritative
    claim chosen by the reviewer for ``select_authoritative`` decisions.
    """

    __tablename__ = "conflict_resolutions"

    resolution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    conflict_group_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(32))  # coexist | select_authoritative | superseded
    selected_claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    rationale: Mapped[str] = mapped_column(String(2048), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
