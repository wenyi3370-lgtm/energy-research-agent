from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from energy_research_agent.domain.models import StrictModel


class RecallProfile(str, Enum):
    DEEP_RESEARCH = "DEEP_RESEARCH"
    DAILY_INTELLIGENCE = "DAILY_INTELLIGENCE"


class SourceLane(str, Enum):
    CORPORATE_OFFICIAL = "corporate_official"
    GOVERNMENT_REGULATORY = "government_regulatory"
    TENDER_PROCUREMENT = "tender_procurement"
    INDUSTRY_ASSOCIATION = "industry_association"
    MEDIA_DISCOVERY = "media_discovery"
    CUSTOMER_PARTNER = "customer_partner"
    TECHNICAL_DOCUMENT = "technical_document"
    FINANCIAL_DISCLOSURE = "financial_disclosure"


class SearchPass(str, Enum):
    PRIMARY = "PRIMARY"
    FRONTIER = "FRONTIER"
    SOURCE_PATROL = "SOURCE_PATROL"
    RECOVERY = "RECOVERY"
    UPDATE = "UPDATE"
    ENTERPRISE_SEED = "ENTERPRISE_SEED"
    ENTERPRISE_FRONTIER = "ENTERPRISE_FRONTIER"
    ANOMALY = "ANOMALY"


class QueryPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class FrontierPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RecallStatus(str, Enum):
    RECALL_SATURATED = "RECALL_SATURATED"
    BOUNDED_COMPLETE = "BOUNDED_COMPLETE"
    RECALL_BUDGET_EXHAUSTED = "RECALL_BUDGET_EXHAUSTED"
    PARTIAL_SOURCE_COVERAGE = "PARTIAL_SOURCE_COVERAGE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class FrontierStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    SEARCHED = "SEARCHED"
    CLASSIFIED = "CLASSIFIED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"


class UrlDispositionReason(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_URL = "DUPLICATE_URL"
    SEARCH_RESULT_PAGE = "SEARCH_RESULT_PAGE"
    LISTING_ROOT = "LISTING_ROOT"
    HYDRATION_FAILED = "HYDRATION_FAILED"
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    TIME_OUT_OF_WINDOW = "TIME_OUT_OF_WINDOW"
    MISSING_SOURCE = "MISSING_SOURCE"
    SAME_EVENT_DUPLICATE = "SAME_EVENT_DUPLICATE"


class RecallQuerySpec(StrictModel):
    query_id: str
    topic: str
    query: str
    search_pass: SearchPass
    source_lane: SourceLane
    language: str = "zh-CN"
    priority: QueryPriority = QueryPriority.P1
    requested_results: int = Field(default=4, ge=0, le=100)
    desired_results: int = Field(default=4, ge=1, le=100)
    seed_query: bool = False
    query_variant: str = ""
    parent_frontier_id: str | None = None
    deferred: bool = False
    defer_reason: str = ""


class FrontierEntry(StrictModel):
    frontier_id: str
    run_id: str
    entry_type: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    origin_query_id: str
    origin_url: str
    origin_source_id: str = ""
    parent_frontier_id: str | None = None
    discovery_round: int = Field(default=1, ge=1)
    discovery_reason: str = ""
    priority: FrontierPriority = FrontierPriority.P2
    expansion_allowed: bool = False
    expansion_depth: int = Field(default=0, ge=0)
    max_expansion_depth: int = Field(default=1, ge=0)
    suggested_topics: list[str] = Field(default_factory=list)
    generated_queries: list[str] = Field(default_factory=list)
    status: FrontierStatus = FrontierStatus.DISCOVERED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    defer_reason: str = ""
    promote_reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UrlDispositionRecord(StrictModel):
    query_id: str
    url: str
    reason: UrlDispositionReason
    canonical_url: str = ""
    detail: str = ""
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QueryRecallAudit(StrictModel):
    query_id: str
    topic: str
    search_pass: str
    source_lane: str
    language: str
    priority: str
    requested_results: int = 0
    returned_results: int = 0
    unique_urls: int = 0
    duplicate_urls: int = 0
    listing_root_skipped: int = 0
    search_page_skipped: int = 0
    hydration_attempted: int = 0
    hydration_success: int = 0
    hydration_failed: int = 0
    extracted_items: int = 0
    frontier_entries_discovered: int = 0
    filtered_items: int = 0
    filter_reasons: dict[str, int] = Field(default_factory=dict)


class LaneCoverage(StrictModel):
    attempted: int = 0
    hits: int = 0


class TopicCoverage(StrictModel):
    topic: str
    corporate_official: LaneCoverage = Field(default_factory=LaneCoverage)
    government_regulatory: LaneCoverage = Field(default_factory=LaneCoverage)
    tender_procurement: LaneCoverage = Field(default_factory=LaneCoverage)
    industry_association: LaneCoverage = Field(default_factory=LaneCoverage)
    media_discovery: LaneCoverage = Field(default_factory=LaneCoverage)
    customer_partner: LaneCoverage = Field(default_factory=LaneCoverage)
    technical_document: LaneCoverage = Field(default_factory=LaneCoverage)
    financial_disclosure: LaneCoverage = Field(default_factory=LaneCoverage)


class SearchCoverageMatrix(StrictModel):
    schema_version: str = "1.0"
    profile: RecallProfile
    topics: list[TopicCoverage] = Field(default_factory=list)
    chinese_query_count: int = 0
    english_query_count: int = 0
    unique_domain_count: int = 0
    official_domain_count: int = 0
    government_domain_count: int = 0
    media_domain_count: int = 0
    tender_domain_count: int = 0
    coverage_complete: bool = False
    status: RecallStatus = RecallStatus.PARTIAL_SOURCE_COVERAGE


class RecallFunnel(StrictModel):
    seed_query_count: int = 0
    expanded_query_count: int = 0
    source_patrol_query_count: int = 0
    frontier_followup_query_count: int = 0
    total_query_count: int = 0
    search_hits: int = 0
    unique_urls: int = 0
    hydration_attempts: int = 0
    hydration_successes: int = 0
    extraction_attempts: int = 0
    extraction_successes: int = 0
    candidate_items: int = 0
    freshness_accepted: int = 0
    freshness_rejected: int = 0
    same_event_deduped: int = 0
    in_scope_items: int = 0
    final_selected: int = 0
    unknown_publication_time_count: int = 0
    secondary_source_count: int = 0
    original_source_count: int = 0
    unique_domains: int = 0
    budget_used: int = 0
    budget_remaining: int = 0
    stop_reason: str = ""


class SourcePatrolAudit(StrictModel):
    source_id: str
    source_attempted: bool = False
    listing_pages_opened: int = 0
    article_links_discovered: int = 0
    article_pages_hydrated: int = 0


class RecallRunResult(StrictModel):
    profile: RecallProfile
    status: RecallStatus
    query_specs: list[RecallQuerySpec] = Field(default_factory=list)
    deferred_queries: list[RecallQuerySpec] = Field(default_factory=list)
    frontier_entries: list[FrontierEntry] = Field(default_factory=list)
    url_dispositions: list[UrlDispositionRecord] = Field(default_factory=list)
    query_audits: list[QueryRecallAudit] = Field(default_factory=list)
    source_patrol: list[SourcePatrolAudit] = Field(default_factory=list)
    coverage: SearchCoverageMatrix
    funnel: RecallFunnel = Field(default_factory=RecallFunnel)
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
