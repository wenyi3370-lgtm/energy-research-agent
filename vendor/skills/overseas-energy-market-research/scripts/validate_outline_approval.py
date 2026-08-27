from __future__ import annotations

import argparse
from pathlib import Path

from _common import Issue, add_common_args, print_report, read_csv, read_json, require_columns, resolve_project_file


REQUIRED = [
    "approval_id",
    "outline_version",
    "outline_path",
    "scope_summary",
    "reviewer",
    "approval_status",
    "approval_date",
    "approval_message",
    "scope_change_requires_reapproval",
    "notes",
]


def validate(project_dir: Path, path: Path | None = None) -> list[Issue]:
    approval_path = path or project_dir / "00_Research_Approval.csv"
    fieldnames, rows = read_csv(approval_path)
    issues = require_columns(fieldnames, REQUIRED)
    if issues:
        return issues

    manifest = read_json(project_dir / "project_manifest.json", {})
    current_version = str(manifest.get("outline_version") or "").strip()
    if not current_version:
        issues.append(Issue("fail", "manifest", "outline_version", "project_manifest.json must define the current outline_version"))
        return issues

    matches = [row for row in rows if row.get("outline_version", "").strip() == current_version]
    if not matches:
        issues.append(Issue("fail", "approval", "outline_version", f"No approval row for current outline version {current_version}"))
        return issues

    approved = [row for row in matches if row.get("approval_status", "").strip().lower() == "approved"]
    if not approved:
        issues.append(Issue("fail", "approval", "approval_status", f"Current outline version {current_version} is not approved"))
        return issues

    row = approved[-1]
    for field in ("approval_id", "outline_path", "scope_summary", "reviewer", "approval_date", "approval_message"):
        if not row.get(field):
            issues.append(Issue("fail", row.get("approval_id") or "approval", field, "Approved outline row requires a value"))

    outline_path = Path(row.get("outline_path", ""))
    if not outline_path.is_absolute():
        outline_path = project_dir / outline_path
    if not outline_path.exists():
        issues.append(Issue("fail", row.get("approval_id") or "approval", "outline_path", f"Approved outline file does not exist: {outline_path}"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate explicit human approval for the current research outline.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--file")
    add_common_args(parser)
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    path = resolve_project_file(project_dir, args.file, ["00_Research_Approval.csv"])
    return print_report("Outline approval validation", validate(project_dir, path), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
