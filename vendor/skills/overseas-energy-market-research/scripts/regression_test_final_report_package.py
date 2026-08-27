# -*- coding: utf-8 -*-
"""FIX round-2 P1-6: final report package regression — REAL assembly.

Constructs a minimal valid research project (init + one minimal row per
required evidence table + a confirmed claim registry) and genuinely runs
`build_final_report_package.py`. Asserts:

- DOCX / XLSX / PPTX exist and are non-empty;
- `deliverables/charts/chart_manifest.json` exists and is valid JSON;
- `deliverables/word_production_manifest.json` exists;
- no ImportError / signature mismatch (the old chain imported a
  `save_manifest` that never existed and called chart builders with the
  wrong signature — this test would have failed).

Self-contained, offline, deterministic. Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from sync_csv_to_excel import REQUIRED_NONEMPTY_CSVS  # noqa: E402

BUILDERS = ["market_trend", "price_capacity_scatter", "parameter_availability_heatmap",
            "channel_coverage_heatmap", "pain_point_pareto", "capability_radar"]


def _default_value(col: str) -> str:
    c = col.lower()
    if "source" in c and "id" in c:
        return "S001"
    if "id" in c:
        return "T1"
    if "record" in c:
        return "R1"
    if "url" in c:
        return "https://example.com"
    if "date" in c or "access" in c:
        return "2026-08-11"
    if "country" in c:
        return "Thailand"
    if "region" in c:
        return "Southeast Asia"
    if "unit" in c:
        return "MWh"
    if "currency" in c:
        return "USD"
    if "tax" in c:
        return "exclusive"
    if "metric" in c:
        return "installed_capacity"
    if "year" in c:
        return "2026"
    if any(k in c for k in ("rate", "value", "count", "number", "score", "level",
                            "capacity", "power", "price", "cost", "priority",
                            "frequency", "status", "stage")):
        return "1"
    return "x"


def build_minimal_project(project: Path) -> None:
    init = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "init_research_project.py"),
         "--project-dir", str(project), "--region", "Thailand",
         "--category", "BESS", "--language", "zh-CN", "--stages", "0-8"],
        capture_output=True, text=True, timeout=300,
    )
    if init.returncode != 0:
        raise AssertionError("init failed: %s" % init.stdout[-400:])
    for name in sorted(REQUIRED_NONEMPTY_CSVS):
        path = project / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        with path.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([_default_value(c) for c in header])
    claims = {name: {"core_claim": "fixture claim for %s" % name, "claim_confirmed": True}
              for name in BUILDERS}
    (project / "intermediate" / "charts").mkdir(parents=True, exist_ok=True)
    (project / "intermediate" / "charts" / "claims.json").write_text(
        json.dumps(claims, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="final_pkg_") as tmp:
        project = Path(tmp) / "proj"
        project.mkdir(parents=True)
        build_minimal_project(project)

        build = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "build_final_report_package.py"),
             "--project-dir", str(project), "--region", "Thailand",
             "--category", "BESS", "--prefix", "测试报告"],
            capture_output=True, text=True, timeout=600,
        )
        if build.returncode != 0:
            raise AssertionError("build_final_report_package failed (rc=%s): %s"
                                 % (build.returncode, (build.stderr or build.stdout)[-500:]))
        if "ImportError" in build.stderr:
            raise AssertionError("ImportError in final package build: %s" % build.stderr[-400:])

        deliverables = project / "deliverables"
        for name in ("测试报告.docx", "测试报告.xlsx", "测试报告.pptx"):
            path = deliverables / name
            if not path.exists() or path.stat().st_size < 1024:
                raise AssertionError("output missing or empty: %s" % name)

        chart_manifest = deliverables / "charts" / "chart_manifest.json"
        if not chart_manifest.is_file():
            raise AssertionError("chart_manifest.json not generated")
        data = json.loads(chart_manifest.read_text(encoding="utf-8"))
        if "charts" not in data or "mode" not in data:
            raise AssertionError("chart_manifest schema invalid: %s" % list(data))

        word_manifest = deliverables / "word_production_manifest.json"
        if not word_manifest.is_file():
            raise AssertionError("word_production_manifest.json not generated")

        print("  [1/1] final report package (DOCX+XLSX+PPTX+manifests) real assembly: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
