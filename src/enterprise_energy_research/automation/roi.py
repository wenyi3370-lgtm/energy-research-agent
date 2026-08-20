"""ROI accounting: human effort vs machine time separation (Phase 11).

Business ROI is measured with *human minutes* as the unit of value: how
much manual analyst time the workflow removes versus how much human
oversight it still requires. Machine wall-clock duration is tracked
separately (``run_metrics``) and never blended with human time.

Every number here comes from durable rows: ``user_feedback`` (submitted by
the requester) and ``run_metrics`` (recorded by the workflow). The audit
rule stands: ROI numbers are never fabricated — an aggregate only reports
what was actually collected.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..domain.models import StrictModel


class RoiRunRow(StrictModel):
    """One run's ROI inputs, pulled from run_metrics + user_feedback."""

    run_id: str
    task_id: str = ""
    manual_baseline_minutes: float = Field(default=0.0, ge=0.0)
    human_review_minutes: float = Field(default=0.0, ge=0.0)
    human_edit_count: int = Field(default=0, ge=0)
    machine_total_seconds: float = Field(default=0.0, ge=0.0)
    adoption_status: str | None = None


class RoiResult(StrictModel):
    """Per-run ROI outcome."""

    run_id: str
    manual_baseline_minutes: float
    human_minutes: float
    machine_minutes: float
    minutes_saved: float
    roi_ratio: float  # minutes_saved per human minute spent (1.0 = break-even)
    adopted: bool | None = None

    @property
    def roi_comment(self) -> str:
        if self.minutes_saved <= 0:
            return "no measurable saving yet; review human time and baseline"
        return f"{self.roi_ratio:.1f}x human-time return; {self.minutes_saved:.0f} min saved"


class RoiCalculator:
    """Pure functions over the durable ROI rows."""

    @staticmethod
    def per_run(row: RoiRunRow) -> RoiResult:
        human_minutes = row.human_review_minutes
        minutes_saved = row.manual_baseline_minutes - human_minutes
        roi_ratio = minutes_saved / human_minutes if human_minutes > 0 else 0.0
        return RoiResult(
            run_id=row.run_id,
            manual_baseline_minutes=row.manual_baseline_minutes,
            human_minutes=round(human_minutes, 1),
            machine_minutes=round(row.machine_total_seconds / 60.0, 1),
            minutes_saved=round(minutes_saved, 1),
            roi_ratio=round(roi_ratio, 2),
            adopted=True if row.adoption_status == "ADOPTED" else
            False if row.adoption_status == "REJECTED" else None,
        )

    @staticmethod
    def aggregate(rows: list[RoiRunRow]) -> dict[str, Any]:
        """Monthly/period summary over collected feedback (never extrapolates)."""
        per_run = [RoiCalculator.per_run(row) for row in rows]
        baseline = sum(item.manual_baseline_minutes for item in per_run)
        human = sum(item.human_minutes for item in per_run)
        saved = sum(item.minutes_saved for item in per_run)
        adopted = sum(1 for item in per_run if item.adopted is True)
        return {
            "runs_with_feedback": len(per_run),
            "total_baseline_minutes": round(baseline, 1),
            "total_human_minutes": round(human, 1),
            "total_minutes_saved": round(saved, 1),
            "aggregate_roi_ratio": round(saved / human, 2) if human > 0 else 0.0,
            "adopted_runs": adopted,
            "estimated_monthly_saved_hours": round(saved / 60.0, 1),
            "per_run": [item.model_dump(mode="json") for item in per_run],
        }
