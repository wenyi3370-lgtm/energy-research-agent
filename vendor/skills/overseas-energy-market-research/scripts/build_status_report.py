from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from _common import read_csv, read_json


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    _, rows = read_csv(path)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Markdown status report for a research project.")
    parser.add_argument("--project-dir", default=".", help="Project directory.")
    parser.add_argument("--output", default="status_report.md", help="Output Markdown path relative to project dir unless absolute.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    manifest = read_json(project_dir / "project_manifest.json", {})
    source_fields, source_rows = read_csv(project_dir / "00_Source_Ledger.csv") if (project_dir / "00_Source_Ledger.csv").exists() else ([], [])
    gaps_fields, gap_rows = read_csv(project_dir / "11_Evidence_Issues.csv") if (project_dir / "11_Evidence_Issues.csv").exists() else ([], [])

    source_tiers = Counter(row.get("reliability_tier", "blank") or "blank" for row in source_rows)
    verification = Counter(row.get("verification_status", "blank") or "blank" for row in source_rows)

    lines = [
        "# Research Project Status",
        "",
        f"- Project: `{project_dir}`",
        f"- Region: {manifest.get('region', '')}",
        f"- Category: {manifest.get('category', '')}",
        f"- Language: {manifest.get('language', '')}",
        "",
        "## Artifact Counts",
        "",
        f"- Source ledger rows: {len(source_rows)}",
        f"- Model identifier rows: {count_rows(project_dir / '03_Model_Identifier_Check.csv')}",
        f"- Product parameter rows: {count_rows(project_dir / '04_Product_Parameters.csv')}",
        f"- Raw review rows: {count_rows(project_dir / '07_Raw_Reviews.csv')}",
        f"- Review coding rows: {count_rows(project_dir / '08_Review_Coding.csv')}",
        f"- Internal evidence issue rows: {len(gap_rows)}",
        f"- Model assumption rows: {count_rows(project_dir / '12_Model_Assumptions.csv')}",
        f"- Model result rows: {count_rows(project_dir / '13_Model_Results.csv')}",
        f"- Simulated modeling data rows: {count_rows(project_dir / '14_Simulated_Modeling_Data.csv')}",
        "",
        "## Source Tiers",
        "",
    ]
    for tier, count in sorted(source_tiers.items()):
        lines.append(f"- {tier}: {count}")
    lines.extend(["", "## Verification Status", ""])
    for status, count in sorted(verification.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Next Checks", "", "- Run approval, source, identifier, parameter, review, model, and deliverable validators before final handoff."])

    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote status report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
