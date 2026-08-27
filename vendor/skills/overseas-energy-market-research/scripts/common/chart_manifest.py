# -*- coding: utf-8 -*-
"""Single chart-manifest writer (FIX round-2 P1-5).

All producers of `deliverables/charts/chart_manifest.json` (render_charts,
build_final_report_package, and any future caller) must use
`save_chart_manifest` so the manifest schema stays in one place.

Schema:
{
  "figure_pipeline_id": "embedded-figure-production-v1",
  "backend": "python",
  "mode": "draft" | "final",
  "charts": [{"name", "manifest", "rows_used"}, ...],
  "skipped": [{"chart", "reason"}, ...]
}
"""
from __future__ import annotations

import json
from pathlib import Path

PIPELINE_ID = "embedded-figure-production-v1"


def save_chart_manifest(
    path: Path,
    charts: list[dict],
    skipped: list[dict] | None = None,
    mode: str = "draft",
) -> Path:
    """Atomically write the chart manifest; returns the path."""
    manifest = {
        "figure_pipeline_id": PIPELINE_ID,
        "backend": "python",
        "mode": mode,
        "charts": charts,
        "skipped": skipped or [],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
