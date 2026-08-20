"""Automation-layer enumerations.

Defined in Phase 1 as part of the machine-readable contract; the legal
transition table for :class:`TaskStatus` is implemented by the
TaskStateMachine in Phase 3 and must reference these members.
"""

from __future__ import annotations

from ..domain.enums import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle states of an automated research task/run."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RESEARCHING = "RESEARCHING"
    EVIDENCE_COLLECTED = "EVIDENCE_COLLECTED"
    VALIDATING = "VALIDATING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ResearchType(StrEnum):
    """Business-level research task categories."""

    MARKET_ENTRY = "market_entry"
    MARKET_MONITOR = "market_monitor"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    POLICY_REGULATION = "policy_regulation"
    COMPANY_PROFILE = "company_profile"
    PRODUCT_RESEARCH = "product_research"
    CHANNEL_RESEARCH = "channel_research"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewDecision(StrEnum):
    """Allowed human-review outcomes at the REVIEW_REQUIRED gate."""

    APPROVE = "APPROVE"
    EDIT_AND_APPROVE = "EDIT_AND_APPROVE"
    RESEARCH_AGAIN = "RESEARCH_AGAIN"
    REJECT = "REJECT"


class AdoptionStatus(StrEnum):
    """How the requester ultimately used the delivered research (ROI)."""

    ADOPTED = "ADOPTED"
    PARTIALLY_ADOPTED = "PARTIALLY_ADOPTED"
    REJECTED = "REJECTED"
