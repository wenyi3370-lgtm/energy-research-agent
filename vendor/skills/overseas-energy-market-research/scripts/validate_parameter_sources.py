from __future__ import annotations

import argparse
from pathlib import Path

from _common import Issue, add_common_args, is_url, print_report, read_csv, require_columns, resolve_project_file, row_label


REQUIRED = [
    "parameter_id",
    "brand",
    "exact_model",
    "parameter_group",
    "parameter_name",
    "raw_value",
    "unit",
    "source_priority",
    "source_url",
    "local_file_path",
    "local_file_location",
    "access_or_extraction_date",
    "identifier",
    "verification_status",
    "web_source_reason",
]

LOCAL_REASON_VALUES = {
    "no local file",
    "local file incomplete",
    "parameter absent",
    "official contradiction",
    "user approved web search",
}


def validate(path: Path, local_files_provided: bool) -> list[Issue]:
    fieldnames, rows = read_csv(path)
    issues = require_columns(fieldnames, REQUIRED)
    if issues:
        return issues

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        priority = row.get("source_priority", "").strip().lower()

        for field in ("brand", "exact_model", "parameter_name", "raw_value", "unit", "source_priority", "access_or_extraction_date", "identifier", "verification_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))

        if priority == "local file":
            if not row.get("local_file_path"):
                issues.append(Issue("fail", label, "local_file_path", "Local parameter evidence requires local_file_path"))
            if not row.get("local_file_location"):
                issues.append(Issue("fail", label, "local_file_location", "Local parameter evidence requires sheet/page/section/table location"))
        elif priority in {"official web", "marketplace", "retailer", "review site", "forum", "other"}:
            if not is_url(row.get("source_url", "")):
                issues.append(Issue("fail", label, "source_url", "Web parameter evidence requires URL"))
            reason = row.get("web_source_reason", "").strip().lower()
            if local_files_provided and reason not in LOCAL_REASON_VALUES:
                issues.append(Issue("fail", label, "web_source_reason", "Web-sourced parameter requires reason when local files were provided"))
        else:
            issues.append(Issue("fail", label, "source_priority", "Use local file, official web, marketplace, retailer, review site, forum, or other"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate product parameter source priority and evidence.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 04_Product_Parameters.csv.")
    parser.add_argument("--file", help="Explicit product parameters CSV path.")
    parser.add_argument("--local-files-provided", choices=["yes", "no"], default="yes", help="Whether user provided local parameter files.")
    add_common_args(parser)
    args = parser.parse_args()

    path = resolve_project_file(Path(args.project_dir).resolve(), args.file, ["04_Product_Parameters.csv", "product_parameters.csv"])
    issues = validate(path, local_files_provided=args.local_files_provided == "yes")
    return print_report("Parameter source validation", issues, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
