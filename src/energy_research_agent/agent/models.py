"""Agent-layer domain models.

LLM owns uncertainty (understanding, planning, judging, recovery, synthesis);
code owns determinism (IDs, schemas, budgets, counting, audits). Every model in
this module is strict (``extra="forbid"``) and is the single contract between
the orchestrator, the skill adapters and the evidence plane.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from energy_research_agent.domain.enums import StrEnum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ResearchMode(StrEnum):
    ENTERPRISE = "ENTERPRISE"
    MARKET = "MARKET"
    HYBRID = "HYBRID"


class GoalClass(StrEnum):
    CORE_ENTERPRISE = "CORE_ENTERPRISE"
    CUSTOM_ENTERPRISE = "CUSTOM_ENTERPRISE"
    MARKET = "MARKET"
    POLICY = "POLICY"
    COMPETITION = "COMPETITION"
    CHANNEL = "CHANNEL"
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    ENGINEERING = "ENGINEERING"
    ECONOMICS = "ECONOMICS"
    STRATEGY = "STRATEGY"
    CUSTOM = "CUSTOM"


class PriorityLevel(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class GoalStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    SATISFIED = "SATISFIED"
    BLOCKED = "BLOCKED"
    EXHAUSTED = "EXHAUSTED"


class SkillName(StrEnum):
    ENTERPRISE_RESEARCH = "ENTERPRISE_RESEARCH"
    OVERSEAS_MARKET_RESEARCH = "OVERSEAS_MARKET_RESEARCH"


class FailureClass(StrEnum):
    MODEL_FAILURE = "MODEL_FAILURE"
    SKILL_FAILURE = "SKILL_FAILURE"
    ADAPTER_FAILURE = "ADAPTER_FAILURE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ARTIFACT_FAILED = "ARTIFACT_FAILED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MissionStatus(StrEnum):
    PARSED = "PARSED"
    PLANNED = "PLANNED"
    ROUTED = "ROUTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    EXHAUSTED = "EXHAUSTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SubjectType(StrEnum):
    ENTERPRISE = "enterprise"
    MARKET = "market"
    PRODUCT = "product"
    CUSTOM = "custom"


class SkillRunStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ResearchGoal(AgentStrictModel):
    """One bounded research question (§9). Dynamic/custom goals are first-class."""

    goal_id: str
    goal_name: str = Field(min_length=1)
    goal_description: str = Field(min_length=1)
    subject_id: str
    subject_name: str = Field(min_length=1)
    subject_type: SubjectType = SubjectType.ENTERPRISE
    goal_class: GoalClass
    scope: dict[str, Any] = Field(default_factory=dict)
    priority: PriorityLevel = PriorityLevel.P2
    required_evidence: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    assigned_skill: SkillName | None = None
    status: GoalStatus = GoalStatus.PLANNED
    evidence_refs: list[str] = Field(default_factory=list)
    gap_refs: list[str] = Field(default_factory=list)
    recovery_rounds: int = Field(default=0, ge=0)
    routing_reason: str | None = None

    def mark(self, status: GoalStatus) -> None:
        self.status = status


class ResearchMission(AgentStrictModel):
    """Top-level mission object (§8). The raw natural-language request is kept verbatim."""

    mission_id: str
    raw_request: str = Field(min_length=1)
    request_type: str = "research"
    primary_subject: str = Field(default="", description="Free-text subject; resolved later to a canonical id")
    canonical_entity_id: str | None = None
    geographies: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    time_scope: str | None = None
    decision_question: str | None = None
    audience: str | None = None
    mode: ResearchMode = ResearchMode.ENTERPRISE
    goals: list[ResearchGoal] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    evidence_version: int = Field(default=1, ge=1)
    status: MissionStatus = MissionStatus.PARSED
    parse_mode: str = "llm"
    # Deliverable references produced by the unified artifact plane (§37),
    # surfaced to the portal so users can reach Word/Excel/HTML/PPT outputs.
    artifact_refs: list[str] = Field(default_factory=list)
    # Why the mission ended in its terminal state: publication audit
    # findings plus blocked/failed goal evaluation reasons, so the portal
    # can show the real causes instead of an unexplained BLOCKED.
    review_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()


class RoutingDecision(AgentStrictModel):
    """One goal -> one skill decision, always carrying an auditable reason (§34)."""

    goal_id: str
    assigned_skill: SkillName
    routing_reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    mode: ResearchMode


class SkillPlan(AgentStrictModel):
    """Bounded execution contract handed to a ResearchSkillPort implementation."""

    skill_plan_id: str
    skill_name: SkillName
    mission_id: str
    goal_ids: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SkillAttempt(AgentStrictModel):
    """One executed strategy. ``executed`` is decided by code, not by the LLM (§24)."""

    attempt_id: str
    attempt_no: int = Field(ge=1)
    executed: bool = Field(
        default=False,
        description="True only when a genuinely different recovery strategy ran (§24 rules)",
    )
    strategy_summary: str = ""
    queries: list[str] = Field(default_factory=list)
    source_categories: list[str] = Field(default_factory=list)
    failure_class: FailureClass | None = None
    diagnostics: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class SkillRunResult(AgentStrictModel):
    """The only structured return the agent consumes from a skill (§16)."""

    skill_run_id: str
    skill_name: SkillName
    goal_ids: list[str] = Field(default_factory=list)
    status: SkillRunStatus
    evidence_exports: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    coverage_metrics: dict[str, Any] = Field(default_factory=dict)
    quality_metrics: dict[str, Any] = Field(default_factory=dict)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    attempts: list[SkillAttempt] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    failure_class: FailureClass | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @property
    def executed_attempts(self) -> list[SkillAttempt]:
        return [attempt for attempt in self.attempts if attempt.executed]


class GoalEvaluation(AgentStrictModel):
    """Post-execution judgment. Success is never self-declared (§63)."""

    goal_id: str
    status: GoalStatus
    satisfied_criteria: list[str] = Field(default_factory=list)
    unmet_criteria: list[str] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    required_evidence_missing: list[str] = Field(default_factory=list)
    evaluation_reason: str = Field(min_length=1)
    failure_class: FailureClass | None = None
    evaluated_at: datetime = Field(default_factory=utc_now)


class RecoveryPlan(AgentStrictModel):
    """A recovery round is a *different* strategy, never a repeated query (§22)."""

    recovery_plan_id: str
    goal_ids: list[str] = Field(min_length=1)
    failed_round: int = Field(ge=0)
    failure_reason: str = Field(min_length=1)
    failure_class: FailureClass | None = None
    new_strategy: str = Field(min_length=1)
    new_source_categories: list[str] = Field(default_factory=list)
    new_queries: list[str] = Field(default_factory=list)
    expected_evidence_delta: str = ""
    planned_skill: SkillName | None = None
    created_at: datetime = Field(default_factory=utc_now)


# Cross-domain findings are consumed by the frozen bundle and the narrative,
# so the canonical model lives in the domain plane; the agent re-exports it.
from energy_research_agent.domain.models import (  # noqa: E402
    CrossDomainFinding as CrossDomainFinding,
)



class AgentCostRecord(AgentStrictModel):
    """Per-stage cost telemetry (§65). No secrets are ever recorded."""

    stage: str
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    recorded_at: datetime = Field(default_factory=utc_now)


class MissionApproval(AgentStrictModel):
    """Human approval record. The agent can never approve itself (§27)."""

    approval_id: str
    mission_id: str
    approver: str = "human"
    decision: ApprovalStatus
    scope_summary: str = Field(min_length=1)
    message: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)
