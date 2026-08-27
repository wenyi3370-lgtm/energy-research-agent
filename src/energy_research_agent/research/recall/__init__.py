"""Shared, budget-bounded search recall layer.

The package intentionally stops at discovery.  Search snippets and
``FrontierEntry`` records are leads; only the existing extraction and
verification pipeline can turn hydrated pages into formal evidence.
"""

from .audit import RecallAudit
from .anomaly_hunter import AnomalyHunter
from .budget import DailyRecallBudgetPlanner, RecallBudgetPolicy
from .coverage import CoverageTracker
from .entity_miner import EntityEventMiner
from .models import (
    FrontierEntry,
    FrontierPriority,
    QueryPriority,
    RecallFunnel,
    RecallProfile,
    RecallQuerySpec,
    RecallStatus,
    SearchCoverageMatrix,
    SearchPass,
    SourceLane,
    UrlDispositionReason,
    UrlDispositionRecord,
)
from .query_expander import QueryExpander
from .recall_engine import RecallEngine
from .search_frontier import RecallConvergenceTracker, SearchFrontier

__all__ = [
    "AnomalyHunter", "CoverageTracker", "DailyRecallBudgetPlanner", "EntityEventMiner",
    "FrontierEntry", "FrontierPriority", "QueryExpander", "QueryPriority",
    "RecallAudit", "RecallBudgetPolicy", "RecallConvergenceTracker",
    "RecallEngine", "RecallFunnel", "RecallProfile", "RecallQuerySpec",
    "RecallStatus", "SearchCoverageMatrix", "SearchFrontier", "SearchPass",
    "SourceLane", "UrlDispositionReason", "UrlDispositionRecord",
]
