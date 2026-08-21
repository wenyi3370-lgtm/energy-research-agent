"""Visual layer (P0 refactor): business-driven VisualSpec + VisualManifest.

A VisualSpec carries the *business question* the figure answers
(``decision_question`` / ``business_thesis``), the information semantics
(``semantic_pattern``) and the concrete visual type chosen by the Visual
Router.  Rendering belongs to
:mod:`enterprise_energy_research.artifacts.diagram_design_adapter`; routing
belongs to :mod:`enterprise_energy_research.artifacts.visual_router`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# Visual types supported by the diagram-design editorial design system.
VisualType = Literal[
    "line", "bar", "radar", "quadrant", "scatter", "treemap", "timeline",
    "process", "data_flow", "sankey", "gantt", "pyramid", "tree", "fishbone",
    "architecture", "journey", "kpi_cards", "table",
]

# Information-semantics patterns: chapter thesis → semantics → visual type.
SemanticPattern = Literal[
    "time_series", "category_comparison", "multi_dimension_score",
    "opportunity_priority", "two_metric_distribution", "part_to_whole",
    "technology_evolution", "operational_process", "value_flow",
    "implementation_roadmap", "hierarchy_or_conversion", "verified_relationship",
    "root_cause", "system_architecture", "customer_journey", "data_handoff",
    "quantitative_facts", "none",
]


class VisualDatum(BaseModel):
    """One data row in a visual.

    ``series``/``period`` support multi-series and time-based charts;
    ``x``/``y`` support quadrant/scatter; ``weight`` supports treemap/sankey.
    """

    label: str
    value: float | int | str | None = None
    unit: str | None = None
    note: str | None = None
    series: str | None = None
    period: str | None = None
    x: float | int | None = None
    y: float | int | None = None
    weight: float | int | None = None
    status: str | None = None


class VisualNode(BaseModel):
    """A node in diagram-type visuals (tree/fishbone/architecture/journey)."""

    id: str
    label: str
    kind: str = "backend"  # focal | backend | store | external | input | security | optional
    sublabel: str | None = None
    parent: str | None = None


class VisualStage(BaseModel):
    """A stage/task/segment in process/data_flow/sankey/gantt/timeline."""

    id: str
    label: str
    from_label: str | None = None
    to_label: str | None = None
    weight: float | int | None = None  # flow quantity (sankey) / segment size
    start: str | None = None  # gantt start (YYYY-MM-DD or label)
    end: str | None = None  # gantt end
    note: str | None = None
    kind: str = "backend"


class VisualSpec(BaseModel):
    """Business-driven visual specification (source of truth for both HTML and Word)."""

    visual_id: str
    chapter_id: str
    decision_question: str
    business_thesis: str
    visual_type: VisualType = "table"
    semantic_pattern: SemanticPattern = "none"
    title: str
    subtitle: str | None = None
    data_binding: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    transformation: str = "直接映射冻结证据，不新增假设。"
    assumption_status: Literal["evidence", "analytical_inference", "to_be_confirmed"] = "evidence"
    verified: bool = True
    destination: Literal["html", "word", "both"] = "both"
    editorial_priority: int = Field(default=3, ge=1, le=5)
    items: list[VisualDatum] = Field(default_factory=list)
    nodes: list[VisualNode] = Field(default_factory=list)
    stages: list[VisualStage] = Field(default_factory=list)
    axes: dict[str, Any] = Field(default_factory=dict)
    source_note: str = ""
    confidence: str | None = None


class VisualManifest(BaseModel):
    schema_version: str = "2.0"
    freeze_id: str
    theme: str = "enterprise-consulting-diagram-design"
    visual_system: str = "diagram-design"
    visuals: list[VisualSpec]


def write_visual_manifest(manifest: VisualManifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_visual_manifest(path: Path) -> VisualManifest:
    return VisualManifest.model_validate_json(path.read_text(encoding="utf-8"))
