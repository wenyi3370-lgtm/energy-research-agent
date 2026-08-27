from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from build_presentation_evidence_map import build


SCRIPT_DIR = Path(__file__).resolve().parent


CASES = [
    ("lollipop", "priority ranking", {"category": "label", "value": "value", "xlabel": "Option", "ylabel": "Score"}, [("Residential", 4.7), ("Aggregator", 4.0), ("Fleet", 3.7), ("Public", 2.8)]),
    ("donut", "composition share", {"category": "label", "value": "value", "center_label": "Sources"}, [("Official", 16), ("Industry", 12), ("Media", 7), ("Community", 10)]),
    ("waterfall", "value bridge", {"category": "label", "value": "value", "xlabel": "Driver", "ylabel": "AUD/year"}, [("Arbitrage", 820), ("Solar export", 430), ("VPP", 510), ("Degradation", -190)]),
    ("diverging-bar", "sensitivity tornado", {"category": "label", "value": "value", "xlabel": "Variable", "ylabel": "Payback change"}, [("Hardware price", -2.2), ("Annual revenue", 3.3), ("Utilisation", 1.5), ("Degradation", -0.8)]),
    ("timeline", "time progression", {"date": "date", "label": "label"}, [("2022", "SA approval"), ("2024", "Grid rule"), ("2026", "Pilot scale"), ("2028", "Commercial gate")]),
    ("risk-matrix", "likelihood impact", {"label": "label", "likelihood": "likelihood", "impact": "impact"}, [("Certification", 0.7, 0.8), ("Warranty", 0.5, 0.9), ("Tariff", 0.6, 0.6), ("Demand", 0.35, 0.55)]),
    ("funnel", "stage narrowing", {"category": "label", "value": "value"}, [("Evidence pool", 120), ("Verified", 72), ("Decision grade", 38), ("Core claims", 18)]),
]


def write_rows(path: Path, encoding: dict, rows: list[tuple]) -> None:
    fields = list(dict.fromkeys(encoding.values()))
    fields = [field for field in fields if isinstance(field, str)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def run_case(root: Path, index: int, figure_type: str, relationship: str, encoding: dict, rows: list[tuple]) -> None:
    source = root / "data" / f"case_{index}.csv"
    write_rows(source, encoding, rows)
    spec = {
        "figure_id": f"fig{index}_{figure_type.replace('-', '_')}",
        "title": f"Text-only {figure_type} regression",
        "figure_class": "market-insight",
        "figure_type": figure_type,
        "visual_intent": relationship,
        "archetype": "single-evidence-chart",
        "role": "comparison",
        "core_claim": f"Confirmed fixture claim for {figure_type}.",
        "claim_confirmed": True,
        "panel_map": {"a": f"{relationship} evidence"},
        "source_data": str(source.relative_to(root)).replace("\\", "/"),
        "data_provenance": "observed",
        "statistics": {"metric_definition": relationship, "variability_definition": "not applicable", "baseline_definition": "fixture"},
        "encoding": {**encoding, "relationship": relationship},
        "figsize": [6.1417, 4.2],
        "dpi": 300,
        "minimum_font_size_pt": 8,
        "report_placement": {
            "section_heading": f"{index}、Fixture",
            "caption": f"Figure {index}: {figure_type}",
            "source_note": f"Data source: {source.name}.",
        },
        "output_stem": f"deliverables/charts/fig{index}_{figure_type.replace('-', '_')}",
    }
    spec_path = root / "specs" / f"case_{index}.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_figure_from_spec.py"), "--project-dir", str(root), "--spec", str(spec_path), "--mode", "final"],
        check=True,
    )
    manifest = root / f"deliverables/charts/fig{index}_{figure_type.replace('-', '_')}.theme.json"
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "register_figure_delivery.py"), str(manifest), "--project-dir", str(root), "--confirm-visual-inspected"],
        check=True,
    )


def execute(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(CASES, start=1):
        run_case(root, index, *case)
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "validate_figure_delivery.py"), str(root / "deliverables/charts"), "--project-dir", str(root), "--mode", "final"],
        check=True,
    )
    evidence_map = build(root / "deliverables/charts")
    families = {page["layout_family"] for page in evidence_map["pages"]}
    if len(families) < 4:
        raise AssertionError(f"Expected at least four layout families, got {families}")
    output = root / "presentation_project/evidence_map.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Text-only visual regression: PASS ({len(CASES)} chart types, {len(families)} layout families)")
    print(f"Artifacts: {root}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the text-only chart and evidence-map contract.")
    parser.add_argument("--work-dir")
    args = parser.parse_args()
    if args.work_dir:
        root = Path(args.work_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise SystemExit(f"Refusing to overwrite non-empty regression directory: {root}")
        execute(root)
    else:
        with tempfile.TemporaryDirectory(prefix="text_only_visual_regression_") as raw:
            execute(Path(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
