"""Goal Pipeline Trace (P0-12) and precise Gap Reason taxonomy (P0-13).

Every Goal Family records PLANNED -> SEARCHED -> RETRIEVED -> EXTRACTED ->
NORMALIZED -> VERIFIED -> SYNTHESIZED -> PUBLISHED counts so an empty chapter
can be blamed on the exact stage where the chain stopped. Gap reasons use the
stage taxonomy: PUBLIC_EVIDENCE_GAP is only allowed after searching and page
retrieval actually happened.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from enterprise_energy_research.adapters.base import SearchResultEnvelope
from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, DataGap, ResearchQuery

PIPELINE_STAGES = (
    "PLANNED", "SEARCHED", "RETRIEVED", "EXTRACTED",
    "NORMALIZED", "VERIFIED", "SYNTHESIZED", "PUBLISHED",
)

GAP_REASON_BY_STAGE = {
    "PLANNED": "NOT_SEARCHED",
    "SEARCHED": "SEARCH_FAILED",
    "RETRIEVED": "SEARCHED_NOT_FOUND",
    "EXTRACTED": "FOUND_NOT_RETRIEVED",
    "NORMALIZED": "RETRIEVED_NOT_EXTRACTED",
    "VERIFIED": "NORMALIZED_NOT_VERIFIED",
    "SYNTHESIZED": "VERIFIED_NOT_SYNTHESIZED",
    "PUBLISHED": "SYNTHESIZED_NOT_PUBLISHED",
}


class GoalPipelineEntry(BaseModel):
    goal_family: str
    queries: int = Field(default=0, ge=0)
    search_hits: int = Field(default=0, ge=0)
    search_failures: int = Field(default=0, ge=0)
    retrieved_pages: int = Field(default=0, ge=0)
    extracted_claims: int = Field(default=0, ge=0)
    normalized_claims: int = Field(default=0, ge=0)
    verified_claims: int = Field(default=0, ge=0)
    synthesis_findings: int = Field(default=0, ge=0)
    published_findings: int = Field(default=0, ge=0)
    stages: list[str] = Field(default_factory=list)
    stopping_stage: str | None = None


class GoalPipelineTrace(BaseModel):
    run_id: str
    goals: dict[str, GoalPipelineEntry] = Field(default_factory=dict)

    @classmethod
    def blank(cls, run_id: str, goal_families: list[str]) -> "GoalPipelineTrace":
        trace = cls(run_id=run_id)
        for family in goal_families:
            trace.goals[family] = GoalPipelineEntry(goal_family=family, stages=["PLANNED"])
        return trace

    def goal(self, family: str) -> GoalPipelineEntry:
        return self.goals.setdefault(family, GoalPipelineEntry(goal_family=family))

    def record_plan(self, queries: list[ResearchQuery]) -> None:
        for query in queries:
            entry = self.goal(query.topic)
            entry.queries += 1
            if "SEARCHED" not in entry.stages:
                entry.stages.append("SEARCHED")

    def record_envelope(self, envelope: SearchResultEnvelope, extracted: int, normalized: int, verified: int) -> None:
        entry = self.goal(envelope.topic or "unknown")
        entry.search_hits += len(envelope.hits)
        if envelope.status in {"error", "blocked"}:
            entry.search_failures += 1
        entry.retrieved_pages += sum(1 for hit in envelope.hits if hit.text)
        entry.extracted_claims += extracted
        entry.normalized_claims += normalized
        entry.verified_claims += verified
        if envelope.hits:
            if "RETRIEVED" not in entry.stages:
                entry.stages.append("RETRIEVED")
        if extracted:
            if "EXTRACTED" not in entry.stages:
                entry.stages.append("EXTRACTED")
        if normalized:
            if "NORMALIZED" not in entry.stages:
                entry.stages.append("NORMALIZED")
        if verified:
            if "VERIFIED" not in entry.stages:
                entry.stages.append("VERIFIED")

    def record_synthesis(self, goal_family: str, findings: int, published: int) -> None:
        entry = self.goal(goal_family)
        entry.synthesis_findings += findings
        entry.published_findings += published
        if findings:
            if "SYNTHESIZED" not in entry.stages:
                entry.stages.append("SYNTHESIZED")
        if published:
            if "PUBLISHED" not in entry.stages:
                entry.stages.append("PUBLISHED")

    def stopping_stage(self) -> None:
        for entry in self.goals.values():
            entry.stopping_stage = entry.stages[-1] if entry.stages else "PLANNED"

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "goal_pipeline_trace.json"
        path.write_text(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


class GapReasonClassifier:
    """Classify a DataGap's reason using pipeline trace evidence (P0-13).

    PUBLIC_EVIDENCE_GAP is granted only when the goal was actually searched
    and pages were actually retrieved and still nothing was found.
    """

    def classify(
        self,
        gap: DataGap,
        trace: GoalPipelineTrace,
        *,
        family: str | None = None,
    ) -> str:
        entry = trace.goals.get(family or gap.field_name) or next(
            (item for item in trace.goals.values() if item.goal_family == (family or gap.field_name)),
            None,
        )
        if entry is None:
            return "NOT_SEARCHED"
        if entry.queries == 0:
            return "NOT_SEARCHED"
        if entry.search_hits == 0:
            return "SEARCH_FAILED" if entry.search_failures else "SEARCHED_NOT_FOUND"
        if entry.retrieved_pages == 0:
            return "FOUND_NOT_RETRIEVED"
        if entry.extracted_claims == 0:
            return "RETRIEVED_NOT_EXTRACTED"
        if entry.normalized_claims == 0:
            return "EXTRACTED_NOT_NORMALIZED"
        if entry.verified_claims == 0:
            return "NORMALIZED_NOT_VERIFIED"
        if entry.synthesis_findings == 0:
            return "VERIFIED_NOT_SYNTHESIZED"
        if entry.published_findings == 0:
            return "SYNTHESIZED_NOT_PUBLISHED"
        # Searched + retrieved + extracted + verified + synthesized + published
        # yet the field is still missing: only now is it a public evidence gap.
        return "PUBLIC_EVIDENCE_GAP"
