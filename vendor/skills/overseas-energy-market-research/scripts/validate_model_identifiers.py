from __future__ import annotations

import argparse
import re
from pathlib import Path

from _common import Issue, add_common_args, has_any, is_asin, is_url, print_report, read_csv, require_columns, resolve_project_file, row_label


REQUIRED = [
    "model_id",
    "brand",
    "exact_model",
    "asin",
    "sku",
    "model_code",
    "product_url",
    "page_title",
    "identifier_source_url",
    "checked_date",
    "match_status",
    "conflict_note",
]

AMAZON_RE = re.compile(r"amazon\.", re.IGNORECASE)


def validate(path: Path) -> list[Issue]:
    fieldnames, rows = read_csv(path)
    issues = require_columns(fieldnames, REQUIRED)
    if issues:
        return issues

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        product_url = row.get("product_url", "")
        source_url = row.get("identifier_source_url", "")
        match_status = row.get("match_status", "").strip().lower()

        for field in ("brand", "exact_model", "checked_date", "match_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))

        if product_url and not is_url(product_url):
            issues.append(Issue("fail", label, "product_url", "Product URL must be http(s) URL"))
        if source_url and not is_url(source_url):
            issues.append(Issue("fail", label, "identifier_source_url", "Identifier source URL must be http(s) URL"))

        if product_url and AMAZON_RE.search(product_url):
            asin = row.get("asin", "").upper()
            if not asin:
                issues.append(Issue("fail", label, "asin", "Amazon product rows require ASIN"))
            elif not is_asin(asin):
                issues.append(Issue("fail", label, "asin", "ASIN should be 10 uppercase letters/digits"))
            elif asin not in product_url.upper():
                issues.append(Issue("warn", label, "product_url", "ASIN is not visible in product_url; verify ASIN URL manually"))

        if product_url and not AMAZON_RE.search(product_url):
            if not has_any(row, ("sku", "model_code", "asin")):
                issues.append(Issue("fail", label, "sku/model_code", "Non-Amazon product rows require SKU, model_code, or another identifier"))

        if not product_url:
            issues.append(Issue("fail", label, "product_url", "Model-level evidence requires exact product URL or row should be excluded"))

        if match_status in {"conflict", "待核实", "unclear"} and not row.get("conflict_note"):
            issues.append(Issue("fail", label, "conflict_note", "Conflict or unclear match status requires conflict_note"))

        # regional_equivalence / pending_verification are counted as valid
        # statuses by build_evidence_audit; keep the gate enum in sync.
        if match_status not in {"exact_match", "conflict", "excluded", "待核实", "unclear",
                                "regional_equivalence", "pending_verification"}:
            issues.append(Issue("warn", label, "match_status", "Recommended values: exact_match, conflict, excluded, 待核实, unclear, regional_equivalence, pending_verification"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ASIN/SKU/model identifier consistency.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 03_Model_Identifier_Check.csv.")
    parser.add_argument("--file", help="Explicit model identifier CSV path.")
    add_common_args(parser)
    args = parser.parse_args()

    path = resolve_project_file(Path(args.project_dir).resolve(), args.file, ["03_Model_Identifier_Check.csv", "model_identifier.csv"])
    return print_report("Model identifier validation", validate(path), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
