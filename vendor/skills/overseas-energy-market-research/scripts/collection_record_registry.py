from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from _common import read_csv
from market_gap_exception import safe_project_file, split_refs, task_scope


REQUIRED_FIELDS = {
    "record_id",
    "record_ref",
    "owner_task_id",
    "supporting_task_ids",
    "market",
    "exact_model",
    "goal_family",
    "collection_goal",
    "round",
    "source_ids",
    "canonical_record_key",
    "content_sha256",
    "novelty_type",
    "parent_record_id",
    "duplicate_of_record_id",
    "material_new_fields",
    "counts_toward_floor",
    "status",
    "created_date",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class RegistryResult:
    by_ref: dict[str, dict[str, str]]
    by_id: dict[str, dict[str, str]]
    countable_refs: set[str]
    problems: list[tuple[str, str]]


def parse_bool(value: str) -> bool | None:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def canonical_payload(
    row: dict[str, str],
    excluded_fields: set[str],
    excluded_prefixes: tuple[str, ...],
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw_field, raw_value in row.items():
        field = str(raw_field).strip().casefold()
        if field in excluded_fields or any(field.startswith(prefix) for prefix in excluded_prefixes):
            continue
        value = " ".join(str(raw_value).split()).casefold()
        if value:
            payload[field] = value
    return payload


def content_sha256(
    row: dict[str, str],
    excluded_fields: set[str],
    excluded_prefixes: tuple[str, ...],
) -> tuple[str, dict[str, str]]:
    payload = canonical_payload(row, excluded_fields, excluded_prefixes)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def resolve_record_ref(
    project_root: Path,
    value: str,
    csv_cache: dict[Path, list[dict[str, str]]] | None = None,
) -> tuple[dict[str, str] | None, str | None]:
    if "#" not in value:
        return None, "must use relative.csv#row_number"
    relative_text, row_text = value.rsplit("#", 1)
    try:
        row_number = int(row_text)
    except ValueError:
        return None, "row number must be an integer"
    record_path = safe_project_file(project_root, relative_text)
    if record_path is None or record_path.suffix.casefold() != ".csv" or not record_path.is_file():
        return None, "must reference an existing project-local CSV"
    if csv_cache is not None and record_path in csv_cache:
        rows = csv_cache[record_path]
    else:
        _, rows = read_csv(record_path)
        if csv_cache is not None:
            csv_cache[record_path] = rows
    if row_number < 2 or row_number > len(rows) + 1:
        return None, "row number is out of range"
    return rows[row_number - 2], None


def registry_scope(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("market", "").strip().casefold(),
        row.get("exact_model", "").strip().casefold(),
        row.get("goal_family", "").strip().casefold(),
        row.get("collection_goal", "").strip().casefold(),
    )


def validate_record_registry(
    project_root: Path,
    task_rows_by_id: dict[str, dict[str, str]],
    source_ledger: dict[str, dict[str, str]],
    policy: dict,
    source_dimension_policy: dict | None = None,
) -> RegistryResult:
    problems: list[tuple[str, str]] = []
    registry_path = project_root / str(policy["file_name"])
    if not registry_path.is_file():
        return RegistryResult({}, {}, set(), [("record_registry", f"Missing {policy['file_name']}")])
    fields, rows = read_csv(registry_path)
    missing = sorted(REQUIRED_FIELDS - set(fields))
    if missing:
        return RegistryResult({}, {}, set(), [("record_registry", f"Registry header is missing fields: {missing}")])

    excluded_fields = {str(item).strip().casefold() for item in policy["excluded_hash_fields"]}
    excluded_prefixes = tuple(str(item).strip().casefold() for item in policy["excluded_hash_field_prefixes"])
    allowed_novelty = {str(item).strip().casefold() for item in policy["allowed_novelty_types"]}
    countable_novelty = {str(item).strip().casefold() for item in policy["countable_novelty_types"]}
    countable_statuses = {str(item).strip().casefold() for item in policy["countable_statuses"]}
    by_id: dict[str, dict[str, str]] = {}
    by_ref: dict[str, dict[str, str]] = {}
    resolved_rows: dict[str, dict[str, str]] = {}
    countable_refs: set[str] = set()
    countable_hashes: dict[str, str] = {}
    csv_cache: dict[Path, list[dict[str, str]]] = {}

    for index, row in enumerate(rows, start=2):
        label = row.get("record_id", "").strip() or f"row-{index}"
        record_id = row.get("record_id", "").strip()
        record_ref = row.get("record_ref", "").strip()
        owner_id = row.get("owner_task_id", "").strip()
        novelty = row.get("novelty_type", "").strip().casefold()
        status = row.get("status", "").strip().casefold()
        countable = parse_bool(row.get("counts_toward_floor", ""))
        canonical_key = row.get("canonical_record_key", "").strip().casefold()
        declared_hash = row.get("content_sha256", "").strip().casefold()

        for field in (
            "record_id",
            "record_ref",
            "owner_task_id",
            "market",
            "goal_family",
            "collection_goal",
            "round",
            "source_ids",
            "canonical_record_key",
            "content_sha256",
            "novelty_type",
            "counts_toward_floor",
            "status",
            "created_date",
        ):
            if not row.get(field, "").strip():
                problems.append((label, f"Required registry field is blank: {field}"))
        if record_id:
            if record_id in by_id:
                problems.append((label, f"Duplicate record_id: {record_id}"))
            else:
                by_id[record_id] = row
        if record_ref:
            if policy["require_unique_record_ref"] and record_ref in by_ref:
                problems.append((label, f"record_ref is already registered by {by_ref[record_ref].get('record_id')}: {record_ref}"))
            else:
                by_ref[record_ref] = row
        if owner_id not in task_rows_by_id:
            problems.append((label, f"Unknown owner_task_id: {owner_id}"))
        elif policy["require_owner_scope_match"]:
            owner = task_rows_by_id[owner_id]
            if registry_scope(row) != task_scope(owner) or row.get("round", "").strip() != owner.get("round", "").strip():
                problems.append((label, "Registry market/model/goal/round must match owner_task_id"))
        if row.get("round", "").strip() not in {"1", "2", "3"}:
            problems.append((label, "Registry round must be 1, 2, or 3"))
        supporting_ids = set(split_refs(row.get("supporting_task_ids", "")))
        unknown_supporting = sorted(supporting_ids - set(task_rows_by_id))
        if unknown_supporting:
            problems.append((label, f"Unknown supporting_task_ids: {unknown_supporting}"))
        if owner_id and owner_id in supporting_ids:
            problems.append((label, "owner_task_id cannot also appear in supporting_task_ids"))

        source_ids = set(split_refs(row.get("source_ids", "")))
        unknown_sources = sorted(source_ids - set(source_ledger))
        if unknown_sources:
            problems.append((label, f"Unknown source_ids: {unknown_sources}"))
        if novelty not in allowed_novelty:
            problems.append((label, f"Unknown novelty_type: {novelty}"))
        if countable is None:
            problems.append((label, "counts_toward_floor must be true or false"))
        elif countable:
            if record_ref:
                countable_refs.add(record_ref)
            if novelty not in countable_novelty:
                problems.append((label, f"Countable records must use one of {sorted(countable_novelty)}"))
            if status not in countable_statuses:
                problems.append((label, f"Countable records must use one of statuses {sorted(countable_statuses)}"))
        elif novelty in {"duplicate", "supporting_only"}:
            pass
        if not canonical_key:
            problems.append((label, "canonical_record_key cannot be blank"))

        resolved, ref_error = resolve_record_ref(project_root, record_ref, csv_cache)
        if ref_error:
            problems.append((label, f"Invalid record_ref {record_ref}: {ref_error}"))
        elif resolved is not None:
            resolved_rows[record_id] = resolved
            computed_hash, payload = content_sha256(resolved, excluded_fields, excluded_prefixes)
            if not payload:
                problems.append((label, "Referenced row has no substantive fields after hash exclusions"))
            if not SHA256_RE.fullmatch(declared_hash):
                problems.append((label, "content_sha256 must be 64 lowercase hexadecimal characters"))
            elif declared_hash != computed_hash:
                problems.append((label, f"content_sha256 does not match the referenced row; expected {computed_hash}"))
            if countable and policy["require_unique_countable_content_hash"]:
                prior_id = countable_hashes.get(computed_hash)
                if prior_id:
                    problems.append((label, f"Countable content duplicates record {prior_id}"))
                else:
                    countable_hashes[computed_hash] = record_id
            if (
                source_dimension_policy
                and source_dimension_policy["require_review_record_platform_match"]
                and countable
                and row.get("goal_family", "").strip().casefold()
                == str(source_dimension_policy["review_goal_family"]).strip().casefold()
            ):
                platform_field = str(source_dimension_policy["platform_id_field"])
                record_platform_field = str(source_dimension_policy["review_record_platform_field"])
                source_platforms = {
                    source_ledger[source_id].get(platform_field, "").strip().casefold()
                    for source_id in source_ids
                    if source_id in source_ledger and source_ledger[source_id].get(platform_field, "").strip()
                }
                record_platform = resolved.get(record_platform_field, "").strip().casefold()
                if len(source_platforms) != 1:
                    problems.append((label, "A counted review record must resolve to exactly one source platform_id"))
                elif record_platform not in source_platforms:
                    problems.append(
                        (
                            label,
                            f"Review row {record_platform_field} '{record_platform}' must match source platform_id '{next(iter(source_platforms))}'",
                        )
                    )

    for record_id, row in by_id.items():
        label = record_id
        novelty = row.get("novelty_type", "").strip().casefold()
        countable = parse_bool(row.get("counts_toward_floor", "")) is True
        parent_id = row.get("parent_record_id", "").strip()
        duplicate_id = row.get("duplicate_of_record_id", "").strip()
        if novelty == "material_enrichment":
            if parent_id not in by_id:
                problems.append((label, "material_enrichment requires a valid parent_record_id"))
                continue
            parent = by_id[parent_id]
            if registry_scope(row) != registry_scope(parent):
                problems.append((label, "material_enrichment parent must belong to the same scoped goal"))
            try:
                if int(parent.get("round", "0")) >= int(row.get("round", "0")):
                    problems.append((label, "material_enrichment parent must come from an earlier round"))
            except ValueError:
                problems.append((label, "Registry round values must be integers"))
            new_fields = split_refs(row.get("material_new_fields", ""))
            if not new_fields:
                problems.append((label, "material_enrichment requires material_new_fields"))
            current_payload = resolved_rows.get(record_id, {})
            parent_payload = resolved_rows.get(parent_id, {})
            for field in new_fields:
                if not current_payload.get(field, "").strip():
                    problems.append((label, f"material_new_field is blank or absent in the current row: {field}"))
                elif current_payload.get(field, "").strip().casefold() == parent_payload.get(field, "").strip().casefold():
                    problems.append((label, f"material_new_field did not change from the parent row: {field}"))
        elif parent_id:
            problems.append((label, "parent_record_id is allowed only for material_enrichment"))

        if novelty == "duplicate":
            if countable:
                problems.append((label, "duplicate records cannot count toward a floor"))
            if duplicate_id not in by_id:
                problems.append((label, "duplicate requires a valid duplicate_of_record_id"))
            elif row.get("content_sha256", "").strip().casefold() != by_id[duplicate_id].get("content_sha256", "").strip().casefold():
                problems.append((label, "duplicate content hash must match duplicate_of_record_id"))
        elif duplicate_id:
            problems.append((label, "duplicate_of_record_id is allowed only for duplicate records"))

    if policy["require_material_enrichment_for_reused_canonical_key"]:
        groups: dict[tuple[tuple[str, str, str, str], str], list[dict[str, str]]] = {}
        for row in by_id.values():
            if parse_bool(row.get("counts_toward_floor", "")) is not True:
                continue
            key = (registry_scope(row), row.get("canonical_record_key", "").strip().casefold())
            groups.setdefault(key, []).append(row)
        for rows_with_key in groups.values():
            rows_with_key.sort(
                key=lambda item: (
                    int(item.get("round", "0")) if item.get("round", "").isdigit() else 0,
                    item.get("record_id", ""),
                )
            )
            for later in rows_with_key[1:]:
                if later.get("novelty_type", "").strip().casefold() != "material_enrichment":
                    problems.append((later.get("record_id", ""), "A reused canonical_record_key can count only as material_enrichment"))

    return RegistryResult(by_ref, by_id, countable_refs, problems)
