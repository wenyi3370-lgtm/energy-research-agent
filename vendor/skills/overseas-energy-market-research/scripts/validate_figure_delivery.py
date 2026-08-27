from __future__ import annotations

import argparse
import json
from pathlib import Path

from figure_production import (
    FIGURE_TYPE_LIMIT,
    VISUAL_FAMILY_LIMIT,
    canonical_figure_type,
    validate_figure_manifest,
    visual_family,
)

BAR_TYPES = {"bar", "ranking-bar", "grouped-bar", "diverging-bar"}


def discover_manifests(targets: list[str], project_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for raw in targets:
        target = Path(raw)
        if not target.is_absolute():
            target = project_dir / target
        if target.is_dir():
            paths.extend(sorted(target.glob("*.theme.json")))
        else:
            paths.append(target)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate embedded SVG/PNG figure bundles and theme manifests.")
    parser.add_argument("targets", nargs="+", help="Manifest files or directories containing *.theme.json")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    manifests = discover_manifests(args.targets, project_dir)
    reports = []
    fail_count = 0
    if not manifests:
        reports.append(
            {
                "manifest": "",
                "status": "failed",
                "issues": [{"level": "fail", "field": "targets", "message": "No figure manifests found"}],
            }
        )
        fail_count = 1
    for path in manifests:
        issues = validate_figure_manifest(path, project_dir=project_dir, final=args.mode == "final")
        fails = [issue for issue in issues if issue["level"] == "fail"]
        fail_count += len(fails)
        reports.append(
            {
                "manifest": str(path),
                "status": "ok" if not fails else "failed",
                "issues": issues,
            }
        )
    # Every final set, regardless of size, must respect the per-type quota.
    # Sizeable sets additionally need portfolio-level family diversity.
    if args.mode == "final" and manifests:
        types = []
        for path in manifests:
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                types.append(canonical_figure_type((data.get("figure_contract") or {}).get("figure_type")))
            except Exception:
                continue
        families = set(types)
        counts = {figure_type: types.count(figure_type) for figure_type in families}
        repeated = {figure_type: count for figure_type, count in counts.items() if count > FIGURE_TYPE_LIMIT}
        if repeated:
            fail_count += 1
            detail = ", ".join(f"{figure_type}={count}" for figure_type, count in sorted(repeated.items()))
            reports.append({"manifest": "portfolio", "status": "failed", "issues": [{"level": "fail", "field": "chart_type_quota", "message": f"Each chart type may appear at most {FIGURE_TYPE_LIMIT} times; found {detail}."}]})
        visual_families = [visual_family(figure_type) for figure_type in types]
        family_counts = {family: visual_families.count(family) for family in set(visual_families)}
        family_repeated = {family: count for family, count in family_counts.items() if count > VISUAL_FAMILY_LIMIT}
        if family_repeated:
            fail_count += 1
            detail = ", ".join(f"{family}={count}" for family, count in sorted(family_repeated.items()))
            reports.append({"manifest": "portfolio", "status": "failed", "issues": [{"level": "fail", "field": "visual_family_quota", "message": f"Visually similar grammars are counted together; each visual family may appear at most {VISUAL_FAMILY_LIMIT} times. Found {detail}. Bar, ranking-bar, grouped-bar, lollipop and dot-plot all belong to single-axis-comparison."}]})
        if len(manifests) >= 6:
            bar_count = sum(t in BAR_TYPES for t in types)
            if bar_count / max(1, len(types)) > 0.60:
                fail_count += 1
                reports.append({"manifest": "portfolio", "status": "failed", "issues": [{"level": "fail", "field": "chart_variety", "message": f"Bar-family charts are {bar_count}/{len(types)} (>60%); use semantic alternatives such as line, lollipop, donut, waterfall, timeline, heatmap, scatter or risk matrix."}]})
            if len(families) < 3:
                fail_count += 1
                reports.append({"manifest": "portfolio", "status": "failed", "issues": [{"level": "fail", "field": "chart_families", "message": f"Only {len(families)} chart families found; final report requires at least 3."}]})
    result = {"status": "ok" if fail_count == 0 else "failed", "fail_count": fail_count, "figures": reports}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Figure delivery validation: {result['status'].upper()}")
        for report in reports:
            print(f"- {report['status'].upper()}: {report['manifest']}")
            for issue in report["issues"]:
                print(f"  [{issue['level']}] {issue['field']}: {issue['message']}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
