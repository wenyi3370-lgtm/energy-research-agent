from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


LAYOUT_BY_FIGURE = {
    "trend-line": "trend_with_driver_panel",
    "line": "trend_with_driver_panel",
    "forecast": "trend_with_driver_panel",
    "bar_line": "trend_with_driver_panel",
    "timeline": "milestone_timeline",
    "scatter": "positioning_map",
    "scatter-positioning": "positioning_map",
    "heatmap": "evidence_matrix",
    "coverage-heatmap": "evidence_matrix",
    "radar": "capability_comparison",
    "evaluation-comparison": "capability_comparison",
    "donut": "composition_with_callouts",
    "waterfall": "value_bridge",
    "risk-matrix": "risk_matrix",
    "funnel": "funnel_with_gates",
    "lollipop": "ranked_evidence",
    "ranking-bar": "ranked_evidence",
    "bar": "comparison_with_commentary",
    "grouped-bar": "comparison_with_commentary",
    "diverging-bar": "sensitivity_tornado",
}

LAYOUT_VARIANTS = {
    "bar": ["comparison_with_commentary", "ranked_evidence", "small_multiples", "kpi_bridge"],
    "ranking-bar": ["ranked_evidence", "comparison_with_commentary", "small_multiples"],
    "lollipop": ["ranked_evidence", "priority_ladder", "comparison_with_commentary"],
    "line": ["trend_with_driver_panel", "trend_full_width", "scenario_band"],
    "forecast": ["scenario_band", "trend_with_driver_panel", "trend_full_width"],
    "narrative": ["executive_summary", "section_opener", "decision_tree", "action_roadmap"],
}


def load_manifests(charts_dir: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(charts_dir.glob("fig*.theme.json")):
        out.append((path, json.loads(path.read_text(encoding="utf-8-sig"))))
    return out


def _layout_for(ftype: str, index: int, requested: str = "") -> str:
    if requested:
        return requested
    variants = LAYOUT_VARIANTS.get(ftype)
    if variants:
        return variants[(index - 1) % len(variants)]
    return LAYOUT_BY_FIGURE.get(ftype, "mixed_evidence")


def _load_page_plan(path: Path | None) -> list[dict]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    pages = data.get("pages") if isinstance(data, dict) else data
    if not isinstance(pages, list):
        raise ValueError("Page plan must be a JSON list or an object containing pages[].")
    return pages


def build(charts_dir: Path, page_plan: Path | None = None) -> dict:
    manifests = load_manifests(charts_dir)
    by_name = {path.name: (path, data) for path, data in manifests}
    planned = _load_page_plan(page_plan)
    pages = []
    families = Counter()
    source_pages = planned or [
        {
            "section": (data.get("word_placement") or {}).get("section_heading") or "",
            "answer_first_title": (data.get("figure_contract") or {}).get("core_claim") or data.get("title") or "",
            "question": "",
            "so_what": (data.get("figure_contract") or {}).get("core_claim") or "",
            "evidence_manifest": path.name,
        }
        for path, data in manifests
    ]
    for index, planned_page in enumerate(source_pages, start=1):
        manifest_name = str(planned_page.get("evidence_manifest") or "")
        pair = by_name.get(Path(manifest_name).name) if manifest_name else None
        path, data = pair if pair else (None, {})
        contract = data.get("figure_contract") or {}
        placement = data.get("word_placement") or {}
        ftype = str(planned_page.get("figure_type") or contract.get("figure_type") or "narrative").lower()
        family = _layout_for(ftype, index, str(planned_page.get("layout_family") or ""))
        families[family] += 1
        claim = str(planned_page.get("answer_first_title") or contract.get("core_claim") or data.get("title") or "")
        evidence = planned_page.get("evidence")
        if not evidence and path:
            evidence = [{"manifest": str(path), "figure_type": ftype}]
        if not evidence:
            evidence = [{"kind": "narrative", "source": str(planned_page.get("source") or "approved report/workbook")}]
        pages.append(
            {
                "page_id": f"E{index:02d}",
                "section": planned_page.get("section") or placement.get("section_heading") or "",
                "answer_first_title": claim,
                "question": planned_page.get("question") or f"What evidence proves: {claim}",
                "evidence": evidence,
                "so_what": planned_page.get("so_what") or claim,
                "layout_family": family,
                "density_target": "high-but-readable",
                "native_objects": ["title", "body", "callout", "source", "simple_geometry"],
                "external_assets": [],
            }
        )
    return {
        "schema_version": 1,
        "workflow": "evidence-map-to-editable-ppt-v1",
        "model_compatibility": "text-only; no multimodal inspection required",
        "rules": {
            "one_conclusion_per_page": True,
            "evidence_graphic_must_prove_title": True,
            "avoid_repeated_card_grids": True,
            "max_same_layout_family_consecutive": 2,
            "fixed_font_sizes": True,
            "editable_core_information": True,
        },
        "layout_family_counts": dict(families),
        "pages": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic text-only presentation evidence and composition map.")
    parser.add_argument("--charts-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--page-plan", help="Optional JSON storyline with pages[]; required for a formal deck containing cover/agenda/action pages.")
    args = parser.parse_args()
    charts = Path(args.charts_dir).resolve()
    output = Path(args.output).resolve()
    result = build(charts, Path(args.page_plan).resolve() if args.page_plan else None)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
