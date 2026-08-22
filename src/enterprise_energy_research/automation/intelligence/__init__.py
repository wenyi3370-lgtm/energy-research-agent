"""每日战略情报模块（V2G & 储能董事长日报）。"""

from .collector import DAILY_QUERIES, IntelligenceCollector, IntelligenceExtraction
from .freshness import (
    FreshnessGateResult,
    apply_freshness_gate,
    are_same_event,
    content_sha256,
    current_intelligence_time,
    filter_last_24_hours,
    parse_event_date,
    parse_exact_publication_time,
)
from .models import DailyBrief, IntelligenceItem, RawIntelligenceItem
from .scorer import deduplicate, score_item, select_top
from .service import IntelligenceService

__all__ = [
    "DAILY_QUERIES",
    "DailyBrief",
    "FreshnessGateResult",
    "IntelligenceCollector",
    "IntelligenceExtraction",
    "IntelligenceItem",
    "IntelligenceService",
    "RawIntelligenceItem",
    "apply_freshness_gate",
    "are_same_event",
    "content_sha256",
    "deduplicate",
    "current_intelligence_time",
    "filter_last_24_hours",
    "parse_event_date",
    "parse_exact_publication_time",
    "score_item",
    "select_top",
]
