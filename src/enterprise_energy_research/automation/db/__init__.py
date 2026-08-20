"""Automation persistence layer (control-plane tables only)."""

from .models import (
    Base,
    HumanReviewRow,
    ResearchRunRow,
    ResearchTaskRow,
    RunMetricRow,
    UserFeedbackRow,
    WorkflowEventRow,
)
from .repository import (
    AutomationDatabase,
    DuplicateTaskError,
    RunNotFoundError,
    TaskRepository,
)

__all__ = [
    "AutomationDatabase",
    "Base",
    "DuplicateTaskError",
    "HumanReviewRow",
    "ResearchRunRow",
    "ResearchTaskRow",
    "RunMetricRow",
    "RunNotFoundError",
    "TaskRepository",
    "UserFeedbackRow",
    "WorkflowEventRow",
]
