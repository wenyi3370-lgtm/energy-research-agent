from __future__ import annotations

import argparse
from pathlib import Path

from _common import Issue, add_common_args, is_url, print_report, read_csv, require_columns, resolve_project_file, row_label, split_ids


RAW_REQUIRED = [
    "review_id",
    "platform",
    "product_url",
    "review_url",
    "exact_model",
    "product_identifier",
    "asin",
    "sku",
    "crawl_date",
    "rating",
    "original_text",
    "collection_tool",
    "review_limit_note",
    "verification_status",
]

CODING_REQUIRED = [
    "theme_id",
    "theme",
    "raw_review_row_ids",
    "source_urls",
    "exact_model",
    "product_identifier",
    "frequency_count",
    "representative_quote",
    "summary_cn",
]

WEB_TOOLS = {"kimi-webbridge", "anysearch"}  # anysearch 2026-08-07 纳入


def validate_raw(path: Path, allow_empty: bool) -> tuple[list[Issue], set[str]]:
    fieldnames, rows = read_csv(path)
    issues = require_columns(fieldnames, RAW_REQUIRED)
    ids: set[str] = set()
    if issues:
        return issues, ids
    if not rows and not allow_empty:
        issues.append(Issue("fail", "file", "rows", "Raw review corpus is empty"))

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        if row.get("review_id"):
            ids.add(row["review_id"])
        else:
            issues.append(Issue("fail", label, "review_id", "Raw review row requires review_id"))

        if row.get("collection_tool") not in WEB_TOOLS:
            issues.append(Issue("fail", label, "collection_tool", "Review crawling must use kimi-webbridge or anysearch"))
        for field in ("platform", "exact_model", "crawl_date", "rating", "original_text", "verification_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))
        if not (row.get("product_identifier") or row.get("asin") or row.get("sku")):
            issues.append(Issue("fail", label, "product_identifier", "Review must be tied to exact product identifier, ASIN, or SKU"))
        for field in ("product_url", "review_url"):
            if row.get(field) and not is_url(row[field]):
                issues.append(Issue("fail", label, field, "URL must be http(s)"))
        if not row.get("product_url"):
            issues.append(Issue("fail", label, "product_url", "Raw review requires exact product URL"))
        if row.get("verification_status", "").lower() in {"unclear", "conflict", "待核实"} and not row.get("review_limit_note"):
            issues.append(Issue("warn", label, "review_limit_note", "Unclear review/model linkage should explain limitation"))
    return issues, ids


def validate_coding(path: Path, raw_ids: set[str]) -> list[Issue]:
    if not path.exists():
        return []
    fieldnames, rows = read_csv(path)
    issues = require_columns(fieldnames, CODING_REQUIRED)
    if issues:
        return issues
    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        for field in ("theme", "raw_review_row_ids", "source_urls", "exact_model", "frequency_count", "summary_cn"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))
        missing = [rid for rid in split_ids(row.get("raw_review_row_ids", "")) if rid not in raw_ids]
        if missing:
            issues.append(Issue("fail", label, "raw_review_row_ids", f"Unknown raw review IDs: {', '.join(missing)}"))
        urls = split_ids(row.get("source_urls", ""))
        if not urls or any(not is_url(url) for url in urls):
            issues.append(Issue("fail", label, "source_urls", "Coding row must contain valid source URL(s)"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate raw review corpus and review-coding traceability.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 07_Raw_Reviews.csv.")
    parser.add_argument("--raw-file", help="Explicit raw reviews CSV path.")
    parser.add_argument("--coding-file", help="Explicit review coding CSV path.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow empty raw corpus for early setup.")
    add_common_args(parser)
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    raw_path = resolve_project_file(project_dir, args.raw_file, ["07_Raw_Reviews.csv", "raw_reviews.csv"])
    coding_path = resolve_project_file(project_dir, args.coding_file, ["08_Review_Coding.csv", "review_coding.csv"])
    raw_issues, raw_ids = validate_raw(raw_path, args.allow_empty)
    issues = raw_issues + validate_coding(coding_path, raw_ids)
    return print_report("Review corpus validation", issues, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
