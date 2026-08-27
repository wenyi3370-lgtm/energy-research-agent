"""PublicationQAReport (P0 refactor): QA is a SEPARATE artifact.

The report for the end user (HTML / Word / Excel / PPT) must never contain
renderer diagnostics, routing internals, or validation messages.  All of that
lives here, in ``publication_qa_report.json`` inside the artifact assets
directory — a machine-readable record for the research operator only.

A visual that cannot be rendered is recorded here with its outcome and the
safe fallback that was applied (diagram → structured table → prose); the
insight itself is never deleted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.ids import new_sortable_id


class QAVisualEntry(BaseModel):
    visual_id: str
    chapter_id: str
    outcome: Literal["rendered", "fallback_table", "failed", "dropped_to_prose"]
    visual_type: str | None = None
    reason: str | None = None
    png_status: str = "not_requested"


class QAImageEntry(BaseModel):
    image_id: str
    decision: Literal["published", "appendix_only", "rejected"]
    reason: str
    publication_priority: int | None = None


class QAFinding(BaseModel):
    code: str
    severity: Literal["info", "warn", "error"]
    message: str
    record_ids: list[str] = Field(default_factory=list)


class PublicationQAReport(BaseModel):
    schema_version: str = "1.0"
    report_id: str
    run_id: str
    freeze_id: str
    artifact_id: str
    status: Literal["pass", "warn", "fail"] = "pass"
    visual_entries: list[QAVisualEntry] = Field(default_factory=list)
    image_entries: list[QAImageEntry] = Field(default_factory=list)
    findings: list[QAFinding] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def record_visual(self, entry: QAVisualEntry) -> None:
        self.visual_entries.append(entry)
        if entry.outcome == "failed":
            self.status = "fail"
        elif entry.outcome == "fallback_table" and self.status != "fail":
            self.status = "warn"

    def record_image(self, entry: QAImageEntry) -> None:
        self.image_entries.append(entry)

    def record_finding(self, finding: QAFinding) -> None:
        self.findings.append(finding)
        if finding.severity == "error":
            self.status = "fail"
        elif finding.severity == "warn" and self.status == "pass":
            self.status = "warn"


# Gates whose failure means the evidence is ABSENT from public channels
# rather than fabricated or malformed.  Under conditional publication they
# are documented warnings: the caveat banner and the conditional-publication
# manifest already disclose the gap, and withholding the whole report would
# punish exactly the runs the conditional mode exists for.
CONDITIONAL_DOWNGRADE_CODES = frozenset({
    "product_image_coverage_failure",
    "word_product_image_gate",
    "dashboard_product_image_gate",
    "supplemental_requirement_coverage",
    "recommendation_lineage",
})


def downgrade_conditional_findings(report: PublicationQAReport, bundle) -> None:
    """Soften evidence-absent gates to warnings for conditional runs.

    Truthfulness checks (pixel verification, boilerplate, structural
    contracts) keep full severity; only codes in
    ``CONDITIONAL_DOWNGRADE_CODES`` are downgraded, and only when the run
    manifest carries ``publication_mode == "conditional"``.
    """
    scope = bundle.run_manifest.research_scope or {}
    if scope.get("publication_mode") != "conditional":
        return
    report.findings = [
        QAFinding(
            code=finding.code,
            severity="warn" if finding.code in CONDITIONAL_DOWNGRADE_CODES else finding.severity,
            message=(
                finding.message + "（条件发布：公开渠道证据缺失，已在报告中披露）"
                if finding.code in CONDITIONAL_DOWNGRADE_CODES and finding.severity == "error"
                else finding.message
            ),
            record_ids=finding.record_ids,
        )
        for finding in report.findings
    ]
    if any(finding.severity == "error" for finding in report.findings):
        report.status = "fail"
    elif any(finding.severity == "warn" for finding in report.findings):
        report.status = "warn"
    else:
        report.status = "pass"


def new_qa_report(run_id: str, freeze_id: str, artifact_id: str) -> PublicationQAReport:
    return PublicationQAReport(
        report_id=new_sortable_id("QA"),
        run_id=run_id,
        freeze_id=freeze_id,
        artifact_id=artifact_id,
    )


def write_qa_report(report: PublicationQAReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
