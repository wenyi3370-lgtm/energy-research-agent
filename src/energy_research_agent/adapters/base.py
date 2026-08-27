from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from energy_research_agent.domain.enums import ArtifactType
from energy_research_agent.domain.models import ArtifactBinding, FrozenResearchBundle


class AdapterError(RuntimeError):
    pass


class AdapterHealth(BaseModel):
    name: str
    available: bool
    version: str = "unknown"
    diagnostics: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query_id: str
    query: str
    entity_id: str
    purpose: str
    preferred_source_levels: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=100)
    requires_browser: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Research goal context (P0-2): the extractor must know WHY a page is
    # being retrieved, not just that a page arrived.
    topic: str | None = None
    collection_round: str | None = None
    round_goal: str | None = None
    trigger: str | None = None
    target_gap_ids: list[str] = Field(default_factory=list)
    target_conflict_ids: list[str] = Field(default_factory=list)
    target_claim_ids: list[str] = Field(default_factory=list)
    canonical_company_name: str | None = None
    canonical_company_aliases: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)
    goal_domain: str = "general_enterprise_research"
    subject_role: str = "target_enterprise"
    evidence_lane: str = "target"
    evidence_use: str = "target_fact"
    requirement_text: str | None = None


class SearchHit(BaseModel):
    requested_url: str | None = None
    final_url: str | None = None
    title: str | None = None
    text: str | None = None
    status: Literal["ok", "partial", "blocked", "error"]
    retrieved_at: str
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResultEnvelope(BaseModel):
    adapter: str
    query_id: str
    hits: list[SearchHit] = Field(default_factory=list)
    status: Literal["ok", "partial", "blocked", "error"]
    diagnostics: list[str] = Field(default_factory=list)
    # Research goal context echoed by the executor so the extractor stage
    # sees the same goal the planner declared (P0-2).
    topic: str | None = None
    purpose: str | None = None
    collection_round: str | None = None
    round_goal: str | None = None
    trigger: str | None = None
    target_gap_ids: list[str] = Field(default_factory=list)
    target_conflict_ids: list[str] = Field(default_factory=list)
    target_claim_ids: list[str] = Field(default_factory=list)
    canonical_company_name: str | None = None
    canonical_company_aliases: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)
    goal_domain: str = "general_enterprise_research"
    subject_role: str = "target_enterprise"
    evidence_lane: str = "target"
    evidence_use: str = "target_fact"
    requirement_text: str | None = None


class ArtifactResult(BaseModel):
    adapter: str
    artifact_id: str
    artifact_type: ArtifactType
    path: Path | None = None
    content_sha256: str | None = None
    used_claim_ids: list[str] = Field(default_factory=list)
    used_image_ids: list[str] = Field(default_factory=list)
    used_chart_ids: list[str] = Field(default_factory=list)
    status: Literal["published", "skipped", "failed"]
    diagnostics: list[str] = Field(default_factory=list)


@runtime_checkable
class SearchAdapter(Protocol):
    name: str
    def health(self) -> AdapterHealth: ...
    def search(self, request: SearchRequest) -> SearchResultEnvelope: ...


@runtime_checkable
class ArtifactAdapter(Protocol):
    name: str
    artifact_type: ArtifactType
    def health(self) -> AdapterHealth: ...
    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult: ...


class KimiWebBridgeAdapter(SearchAdapter, Protocol):
    """Port for browser/authenticated public-source research."""


class AnySearchAdapter(SearchAdapter, Protocol):
    """Port for broad public-source discovery and extraction."""


class ExcelMasterAdapter(ArtifactAdapter, Protocol):
    """Port for Excel Master workbook publication."""


class PPTMasterAdapter(ArtifactAdapter, Protocol):
    """Port for PPT Master presentation publication."""


class FrontendDesignAdapter(ArtifactAdapter, Protocol):
    """Port for standalone enterprise and product HTML publication."""
