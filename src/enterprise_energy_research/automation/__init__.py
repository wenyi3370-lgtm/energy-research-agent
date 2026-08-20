"""Automation layer: service contracts, state machine, and orchestration.

This subpackage is additive. It must not weaken the existing domain
boundaries: publishers never browse, validation gates precede freeze,
and frozen evidence stays immutable.
"""

from .contracts import (
    ArtifactRef,
    ConflictResolutionPayload,
    CostMetrics,
    FeedbackPayload,
    FeishuFormPayload,
    ResearchError,
    ResearchRequest,
    ResearchResult,
    ReviewSubmission,
)
from .enums import (
    AdoptionStatus,
    Priority,
    ResearchType,
    ReviewDecision,
    RiskLevel,
    TaskStatus,
)
from .executor import ExecutionOutcome, ResearchExecutor, SyntheticKernelExecutor
from .feishu import FeishuAdapter, FeishuMessage, FeishuNotifier, MockFeishuAdapter
from .observability import CountingGateway, GatewayUsage, log_event, run_span
from .orchestration import OrchestratingExecutor
from .retry import RetryPolicy, is_transient
from .review import ReviewGateResult, ReviewPolicy
from .roi import RoiCalculator, RoiResult, RoiRunRow
from .service import (
    ConflictNotFoundError,
    ConflictResolutionError,
    ResearchService,
    RetryExhaustedError,
)
from .state_machine import (
    InvalidTransitionError,
    TaskStateMachine,
    TransitionRecord,
    assert_transition,
    is_terminal,
)

__all__ = [
    "AdoptionStatus",
    "ArtifactRef",
    "ConflictNotFoundError",
    "ConflictResolutionError",
    "ConflictResolutionPayload",
    "CostMetrics",
    "CountingGateway",
    "ExecutionOutcome",
    "FeedbackPayload",
    "FeishuAdapter",
    "FeishuFormPayload",
    "FeishuMessage",
    "FeishuNotifier",
    "GatewayUsage",
    "InvalidTransitionError",
    "MockFeishuAdapter",
    "OrchestratingExecutor",
    "Priority",
    "ResearchError",
    "ResearchExecutor",
    "ResearchRequest",
    "ResearchResult",
    "ResearchService",
    "ResearchType",
    "RetryExhaustedError",
    "RetryPolicy",
    "ReviewDecision",
    "ReviewGateResult",
    "ReviewPolicy",
    "ReviewSubmission",
    "RiskLevel",
    "RoiCalculator",
    "RoiResult",
    "RoiRunRow",
    "SyntheticKernelExecutor",
    "TaskStateMachine",
    "TaskStatus",
    "TransitionRecord",
    "assert_transition",
    "is_terminal",
    "is_transient",
    "log_event",
    "run_span",
]
