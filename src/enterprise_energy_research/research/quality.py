from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, ConflictGroup, DataGap, ImageEvidence, Product, ProductDetection, Source

from .saturation import SaturationAssessment


class ResearchQualityReport(BaseModel):
    schema_version: str = "1.0"
    goal_coverage: float = Field(ge=0.0, le=1.0)
    source_diversity: int = Field(ge=0)
    official_source_ratio: float = Field(ge=0.0, le=1.0)
    verified_claim_ratio: float = Field(ge=0.0, le=1.0)
    triangulated_claim_ratio: float = Field(ge=0.0, le=1.0)
    catalog_coverage: float = Field(ge=0.0, le=1.0)
    parameter_coverage: float = Field(ge=0.0, le=1.0)
    image_coverage: float = Field(ge=0.0, le=1.0)
    critical_gap_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    saturation_status: str
    diagnostics: list[str] = Field(default_factory=list)


class ResearchQualityCalculator:
    """Compute release metrics from evidence records, never from search-call counts."""

    @staticmethod
    def assess(
        *,
        saturation: SaturationAssessment,
        sources: Iterable[Source],
        claims: Iterable[Claim],
        products: Iterable[Product],
        images: Iterable[ImageEvidence],
        gaps: Iterable[DataGap],
        conflicts: Iterable[ConflictGroup],
        product_detection: ProductDetection | None = None,
    ) -> ResearchQualityReport:
        source_rows, claim_rows = list(sources), list(claims)
        product_rows, image_rows = list(products), list(images)
        gap_rows, conflict_rows = list(gaps), list(conflicts)
        verified = [row for row in claim_rows if row.verification_status == VerificationStatus.VERIFIED]
        official = [row for row in source_rows if row.source_level.value == "SOURCE_A"]
        origins_by_claim_key: dict[tuple, set[str]] = defaultdict(set)
        for claim in verified:
            source = next((item for item in source_rows if item.source_id == claim.source_id), None)
            if source:
                origins_by_claim_key[(claim.entity_id, claim.field_name, str(claim.value), claim.scope, claim.as_of_date)].add(source.source_domain)
        triangulated = sum(len(origins_by_claim_key[(row.entity_id, row.field_name, str(row.value), row.scope, row.as_of_date)]) >= 2 for row in verified)
        verified_products = [row for row in product_rows if row.verification_status == VerificationStatus.VERIFIED]
        verified_images = [row for row in image_rows if row.verification_status == VerificationStatus.VERIFIED]
        archived_images = [row for row in verified_images if row.local_asset_ref]
        saturated_goals = sum(status == "SATURATED" for status in saturation.goal_status.values())
        goal_count = len(saturation.goal_status)
        diagnostics = list(saturation.findings)
        return ResearchQualityReport(
            goal_coverage=saturated_goals / goal_count if goal_count else 0.0,
            source_diversity=len({row.source_domain for row in source_rows}),
            official_source_ratio=len(official) / len(source_rows) if source_rows else 0.0,
            verified_claim_ratio=len(verified) / len(claim_rows) if claim_rows else 0.0,
            triangulated_claim_ratio=triangulated / len(verified) if verified else 0.0,
            catalog_coverage=product_detection.catalog_coverage_ratio if product_detection else 0.0,
            parameter_coverage=sum(bool(row.parameters) for row in verified_products) / len(verified_products) if verified_products else 0.0,
            image_coverage=len(archived_images) / len(verified_images) if verified_images else 0.0,
            critical_gap_count=sum(row.importance == "critical" and row.status.value == "OPEN" for row in gap_rows),
            conflict_count=sum(row.status.value == "OPEN" for row in conflict_rows),
            saturation_status=saturation.status,
            diagnostics=diagnostics,
        )


def write_research_quality(report: ResearchQualityReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "research_quality.json"
    path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
