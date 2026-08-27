from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from _common import Issue, read_csv
from validate_collection_tasks import validate as validate_collection_tasks
from validate_deliverables import parse_stages, validate as validate_deliverables
from validate_model_identifiers import validate as validate_model_identifiers
from validate_parameter_sources import validate as validate_parameter_sources
from validate_review_corpus import validate_coding, validate_raw
from validate_source_ledger import validate as validate_source_ledger
from validate_outline_approval import validate as validate_outline_approval
from validate_model_integrity import validate as validate_model_integrity


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    _, rows = read_csv(path)
    return len(rows)


def safe_issues(label: str, func) -> list[tuple[str, Issue]]:
    try:
        return [(label, issue) for issue in func()]
    except FileNotFoundError as exc:
        return [(label, Issue("fail", "file", label, f"Missing file: {exc}"))]


def collect_issues(project_dir: Path, *, local_files_provided: bool, allow_empty_reviews: bool, strict_final_files: bool) -> list[tuple[str, Issue]]:
    issues: list[tuple[str, Issue]] = []
    issues.extend(safe_issues("outline_approval", lambda: validate_outline_approval(project_dir)))
    issues.extend(safe_issues("collection_tasks", lambda: validate_collection_tasks(project_dir / "02_Web_Collection_Tasks.csv")))
    issues.extend(safe_issues("source_ledger", lambda: validate_source_ledger(project_dir / "00_Source_Ledger.csv")))
    issues.extend(safe_issues("model_identifiers", lambda: validate_model_identifiers(project_dir / "03_Model_Identifier_Check.csv")))
    issues.extend(safe_issues("parameter_sources", lambda: validate_parameter_sources(project_dir / "04_Product_Parameters.csv", local_files_provided)))

    def review_check() -> list[Issue]:
        raw_issues, raw_ids = validate_raw(project_dir / "07_Raw_Reviews.csv", allow_empty=allow_empty_reviews)
        return raw_issues + validate_coding(project_dir / "08_Review_Coding.csv", raw_ids)

    issues.extend(safe_issues("review_corpus", review_check))
    issues.extend(safe_issues("model_integrity", lambda: validate_model_integrity(project_dir, allow_empty=allow_empty_reviews)))
    issues.extend(safe_issues("deliverables", lambda: validate_deliverables(project_dir, parse_stages("0-8"), strict_final_files)))
    return issues


def status_counts(project_dir: Path, filename: str, field: str) -> Counter:
    path = project_dir / filename
    if not path.exists():
        return Counter()
    _, rows = read_csv(path)
    return Counter(row.get(field, "") or "blank" for row in rows)


def build_markdown(project_dir: Path, issues: list[tuple[str, Issue]], *, local_files_provided: bool, allow_empty_reviews: bool) -> str:
    fail_count = sum(1 for _, issue in issues if issue.level == "fail")
    warn_count = sum(1 for _, issue in issues if issue.level == "warn")
    rows = {
        "collection_tasks": count_rows(project_dir / "02_Web_Collection_Tasks.csv"),
        "source_ledger": count_rows(project_dir / "00_Source_Ledger.csv"),
        "model_identifiers": count_rows(project_dir / "03_Model_Identifier_Check.csv"),
        "product_parameters": count_rows(project_dir / "04_Product_Parameters.csv"),
        "raw_reviews": count_rows(project_dir / "07_Raw_Reviews.csv"),
        "review_coding": count_rows(project_dir / "08_Review_Coding.csv"),
        "integrated_matrix": count_rows(project_dir / "09_Integrated_Matrix.csv"),
        "evidence_issues": count_rows(project_dir / "11_Evidence_Issues.csv"),
        "model_assumptions": count_rows(project_dir / "12_Model_Assumptions.csv"),
        "model_results": count_rows(project_dir / "13_Model_Results.csv"),
        "simulated_modeling_data": count_rows(project_dir / "14_Simulated_Modeling_Data.csv"),
        "collection_record_registry": count_rows(project_dir / "15_Collection_Record_Registry.csv"),
    }

    lines = [
        "# Evidence Audit Report",
        "",
        f"- Project: `{project_dir}`",
        f"- Overall status: {'FAIL' if fail_count else 'OK'}",
        f"- Failures: {fail_count}",
        f"- Warnings: {warn_count}",
        f"- Local parameter files provided: {'yes' if local_files_provided else 'no'}",
        f"- Empty review corpus allowed for this audit: {'yes' if allow_empty_reviews else 'no'}",
        "",
        "## Row Counts",
        "",
    ]
    for key, value in rows.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Verification Status", ""])
    for filename, field in [
        ("00_Source_Ledger.csv", "verification_status"),
        ("03_Model_Identifier_Check.csv", "match_status"),
        ("04_Product_Parameters.csv", "verification_status"),
        ("07_Raw_Reviews.csv", "verification_status"),
    ]:
        counts = status_counts(project_dir, filename, field)
        lines.append(f"### {filename}")
        if counts:
            for status, count in sorted(counts.items()):
                lines.append(f"- {status}: {count}")
        else:
            lines.append("- no rows")
        lines.append("")

    lines.extend(["## Issues", ""])
    if not issues:
        lines.append("- No validator issues found.")
    else:
        lines.append("| Validator | Level | Row | Field | Message |")
        lines.append("|---|---:|---|---|---|")
        for validator, issue in issues:
            message = issue.message.replace("|", "\\|")
            lines.append(f"| {validator} | {issue.level} | {issue.row} | {issue.field} | {message} |")

    lines.extend(
        [
            "",
            "## Handoff Notes",
            "",
            "- Any row marked `待核实`, `unclear`, or `conflict` must not support a final strategic conclusion unless caveated.",
            "- Review-derived conclusions require saved raw review rows and source URLs.",
            "- Web-sourced product parameters require a reason when local parameter files were available.",
            "- Modeled estimates must remain labeled and trace to assumptions, formulas, and supporting evidence.",
            "- The final workbook must keep the complete URL ledger in the last sheet and omit internal evidence-issue sheets.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a consolidated evidence audit report.")
    parser.add_argument("--project-dir", default=".", help="Research project directory.")
    parser.add_argument("--output", default="evidence_audit_report.md", help="Output Markdown path relative to project dir unless absolute.")
    parser.add_argument("--local-files-provided", choices=["yes", "no"], default="yes")
    parser.add_argument("--allow-empty-reviews", action="store_true")
    parser.add_argument("--strict-final-files", action="store_true")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    issues = collect_issues(
        project_dir,
        local_files_provided=args.local_files_provided == "yes",
        allow_empty_reviews=args.allow_empty_reviews,
        strict_final_files=args.strict_final_files,
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    output.write_text(
        build_markdown(project_dir, issues, local_files_provided=args.local_files_provided == "yes", allow_empty_reviews=args.allow_empty_reviews),
        encoding="utf-8",
    )
    print(f"Wrote evidence audit: {output}")
    return 1 if any(issue.level == "fail" for _, issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
