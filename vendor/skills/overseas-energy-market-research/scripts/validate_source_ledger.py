from __future__ import annotations

import argparse
import re
from pathlib import Path

from _common import Issue, add_common_args, is_url, print_report, read_csv, require_columns, resolve_project_file, row_label
from collection_quantity_policy import load_project_policy
from source_independence import canonical_source_key, normalize_taxonomy, root_domain_from_url


REQUIRED = [
    "source_id",
    "stage",
    "evidence_item",
    "value_class",
    "source_type",
    "collection_tool",
    "source_title",
    "source_url",
    "local_file_path",
    "access_date",
    "data_type",
    "global_region",
    "country",
    "province_state",
    "city_site",
    "reliability_tier",
    "evidence_row_ids",
    "verification_status",
]

ALLOWED_TOOLS = {"kimi-webbridge", "anysearch", "local file"}  # anysearch 2026-08-07 纳入
WEB_TOOLS = {"kimi-webbridge", "anysearch"}  # anysearch 2026-08-07 纳入双工具采集
VALUE_CLASSES = {"observed", "derived", "modeled_estimate", "scenario_assumption", "simulated", "pending_verification"}
INDEPENDENCE_FIELDS = ["publisher_group", "root_domain", "canonical_source_id", "source_relation_type"]


def validate(path: Path) -> list[Issue]:
    fieldnames, rows = read_csv(path)
    try:
        quantity_policy = load_project_policy(path.parent)
    except ValueError as exc:
        return [Issue("fail", "project_manifest.json", "collection_quantity_policy", str(exc))]
    independence_policy = quantity_policy.get("source_independence")
    dimension_policy = quantity_policy.get("source_dimension_derivation")
    qualification_policy = quantity_policy.get("primary_source_qualification")
    dimension_fields = [str(dimension_policy["platform_id_field"])] if dimension_policy else []
    required_fields = REQUIRED + (INDEPENDENCE_FIELDS if independence_policy else []) + dimension_fields
    issues = require_columns(fieldnames, required_fields)
    if issues:
        return issues

    ledger = {
        row.get("source_id", "").strip(): row
        for row in rows
        if row.get("source_id", "").strip()
    }
    if len(ledger) != len([row for row in rows if row.get("source_id", "").strip()]):
        issues.append(Issue("fail", "source_ledger", "source_id", "Duplicate source_id values are not allowed"))

    allowed_source_types = {
        normalize_taxonomy(item) for item in (independence_policy or {}).get("allowed_source_types", [])
    }
    allowed_relation_types = {
        normalize_taxonomy(item) for item in (independence_policy or {}).get("allowed_relation_types", [])
    }
    derivative_relation_types = {
        normalize_taxonomy(item) for item in (independence_policy or {}).get("derivative_relation_types", [])
    }
    platform_field = str((dimension_policy or {}).get("platform_id_field", "platform_id"))
    platform_pattern = re.compile(str((dimension_policy or {}).get("platform_id_pattern", r"^.*$")))
    root_platforms: dict[str, set[str]] = {}
    allowed_tiers = {
        str(item).strip().casefold()
        for item in (qualification_policy or {}).get("allowed_reliability_tiers", [])
        if str(item).strip()
    }
    tiers_by_source_type = {
        normalize_taxonomy(source_type): {str(tier).strip().casefold() for tier in tiers if str(tier).strip()}
        for source_type, tiers in (qualification_policy or {}).get("allowed_tiers_by_source_type", {}).items()
    }

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        tool = row.get("collection_tool", "").strip()
        source_type = row.get("source_type", "").strip().lower()
        data_type = row.get("data_type", "").strip().lower()
        platform_id = row.get(platform_field, "").strip().casefold()
        reliability_tier = row.get("reliability_tier", "").strip().casefold().replace(" ", "")

        if not row.get("source_id"):
            issues.append(Issue("fail", label, "source_id", "Required value is blank"))

        if tool not in ALLOWED_TOOLS:
            issues.append(Issue("fail", label, "collection_tool", "Must be kimi-webbridge, anysearch, or local file"))

        if tool in WEB_TOOLS:
            if not is_url(row.get("source_url", "")):
                issues.append(Issue("fail", label, "source_url", "Web-collected evidence requires an http(s) URL"))

        if dimension_policy:
            if not platform_id:
                issues.append(Issue("fail", label, platform_field, "Policy v6+ requires a stable platform_id for every source-ledger row"))
            elif not platform_pattern.fullmatch(platform_id):
                issues.append(Issue("fail", label, platform_field, "platform_id must match the frozen lowercase controlled-ID pattern"))
            if tool == "local file" and platform_id and platform_id != str(dimension_policy["local_platform_id"]).casefold():
                issues.append(Issue("fail", label, platform_field, f"Local-file sources must use platform_id '{dimension_policy['local_platform_id']}'"))

        if independence_policy:
            normalized_source_type = normalize_taxonomy(row.get("source_type", ""))
            relation_type = normalize_taxonomy(row.get("source_relation_type", ""))
            canonical_id = row.get("canonical_source_id", "").strip()
            if normalized_source_type not in allowed_source_types:
                issues.append(Issue("fail", label, "source_type", f"Use a controlled source type from the frozen policy; got '{row.get('source_type', '')}'"))
            if relation_type not in allowed_relation_types:
                issues.append(Issue("fail", label, "source_relation_type", f"Use a controlled relation type from the frozen policy; got '{row.get('source_relation_type', '')}'"))
            if not row.get("publisher"):
                issues.append(Issue("fail", label, "publisher", "Policy v2+ requires the named publisher"))
            if not row.get("publisher_group"):
                issues.append(Issue("fail", label, "publisher_group", "Policy v2+ requires the accountable publisher/owner group"))
            if tool in WEB_TOOLS:
                expected_root = root_domain_from_url(row.get("source_url", ""))
                actual_root = row.get("root_domain", "").strip().casefold()
                if not actual_root:
                    issues.append(Issue("fail", label, "root_domain", "Web evidence requires a registrable root domain"))
                elif actual_root != expected_root:
                    issues.append(Issue("fail", label, "root_domain", f"Expected root domain '{expected_root}' from source_url"))
                elif dimension_policy and platform_id:
                    root_platforms.setdefault(actual_root, set()).add(platform_id)
                    if dimension_policy["require_web_platform_id_equals_root_domain"] and platform_id != actual_root:
                        issues.append(Issue("fail", label, platform_field, f"Web platform_id must equal verified root_domain '{actual_root}'"))
            if relation_type in derivative_relation_types:
                if not canonical_id:
                    issues.append(Issue("fail", label, "canonical_source_id", f"Relation type '{relation_type}' requires the original source ID"))
                elif canonical_id == row.get("source_id", "").strip():
                    issues.append(Issue("fail", label, "canonical_source_id", "A derivative source cannot identify itself as the original"))
                elif canonical_id not in ledger:
                    issues.append(Issue("fail", label, "canonical_source_id", f"Unknown original source ID: {canonical_id}"))
            elif canonical_id and canonical_id != row.get("source_id", "").strip():
                issues.append(Issue("fail", label, "canonical_source_id", "Original/independent analysis must leave canonical_source_id blank or self-reference"))

        if qualification_policy:
            normalized_source_type = normalize_taxonomy(row.get("source_type", ""))
            if reliability_tier not in allowed_tiers:
                issues.append(Issue("fail", label, "reliability_tier", f"Use a controlled reliability tier; got '{row.get('reliability_tier', '')}'"))
            elif reliability_tier not in tiers_by_source_type.get(normalized_source_type, set()):
                issues.append(
                    Issue(
                        "fail",
                        label,
                        "reliability_tier",
                        f"Source type '{normalized_source_type}' cannot be classified as {reliability_tier}",
                    )
                )

        if tool == "local file" or "local" in source_type:
            if not row.get("local_file_path"):
                issues.append(Issue("fail", label, "local_file_path", "Local-file evidence requires local_file_path"))
            elif (
                qualification_policy
                and qualification_policy["require_existing_local_file_for_tier0"]
                and reliability_tier == "tier0"
            ):
                local_path = Path(row.get("local_file_path", "").strip())
                resolved_local = local_path if local_path.is_absolute() else (path.parent / local_path)
                if not resolved_local.resolve().is_file():
                    issues.append(Issue("fail", label, "local_file_path", "Tier 0 local evidence must resolve to an existing file"))

        for field in ("source_title", "access_date", "data_type", "reliability_tier", "verification_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))

        if row.get("value_class") not in VALUE_CLASSES:
            issues.append(Issue("fail", label, "value_class", "Use observed, derived, modeled_estimate, scenario_assumption, simulated, or pending_verification"))

        if not any(row.get(field) for field in ("global_region", "country", "province_state", "city_site")):
            issues.append(Issue("fail", label, "geography", "At least one geography field is required"))

        if any(token in data_type for token in ("conclusion", "summary", "insight", "review-derived")):
            if not row.get("evidence_row_ids"):
                issues.append(Issue("fail", label, "evidence_row_ids", "Derived conclusions must reference evidence row IDs"))

        if row.get("value_class") in {"modeled_estimate", "scenario_assumption", "simulated"} and not row.get("evidence_row_ids"):
            issues.append(Issue("fail", label, "evidence_row_ids", "Estimates and assumptions must reference supporting evidence or assumption rows"))

    if independence_policy:
        for source_id in sorted(ledger):
            if canonical_source_key(source_id, ledger).startswith("cycle:"):
                issues.append(Issue("fail", source_id, "canonical_source_id", "Canonical-source relation contains a cycle"))

    if dimension_policy:
        if dimension_policy["require_root_domain_platform_consistency"]:
            for root_domain, platform_ids in sorted(root_platforms.items()):
                if len(platform_ids) > 1:
                    issues.append(Issue("fail", root_domain, platform_field, f"One root domain cannot impersonate multiple platforms: {sorted(platform_ids)}"))
        if dimension_policy["require_canonical_platform_consistency"]:
            for source_id, row in sorted(ledger.items()):
                canonical_id = row.get("canonical_source_id", "").strip()
                if canonical_id and canonical_id != source_id and canonical_id in ledger:
                    platform_id = row.get(platform_field, "").strip().casefold()
                    canonical_platform = ledger[canonical_id].get(platform_field, "").strip().casefold()
                    if platform_id and canonical_platform and platform_id != canonical_platform:
                        issues.append(Issue("fail", source_id, platform_field, f"Derivative/mirror source must inherit canonical platform_id '{canonical_platform}'"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate source ledger traceability and collection-tool constraints.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 00_Source_Ledger.csv.")
    parser.add_argument("--file", help="Explicit source ledger CSV path.")
    add_common_args(parser)
    args = parser.parse_args()

    path = resolve_project_file(Path(args.project_dir).resolve(), args.file, ["00_Source_Ledger.csv", "source_ledger.csv"])
    return print_report("Source ledger validation", validate(path), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
