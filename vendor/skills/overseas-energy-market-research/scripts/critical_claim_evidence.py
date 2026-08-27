from __future__ import annotations

import hashlib
from pathlib import Path

from collection_record_registry import parse_bool, resolve_record_ref
from market_gap_exception import split_refs
from source_independence import evaluate_claim_independence


def normalize_claim_text(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def claim_sha256(value: str) -> str:
    return hashlib.sha256(normalize_claim_text(value).encode("utf-8")).hexdigest()


def validate_critical_claims(
    claims: list[object],
    task_id: str,
    audit_source_ids: set[str],
    audit_record_refs: set[str],
    project_root: Path,
    registry_by_ref: dict[str, dict[str, str]],
    source_ledger: dict[str, dict[str, str]],
    record_file_cache: dict[Path, list[dict[str, str]]],
    policy: dict,
    independence_policy: dict | None,
) -> tuple[int, int, list[str]]:
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    valid_dual_claims = 0
    disallowed_fields = {str(item).strip().casefold() for item in policy["disallowed_evidence_fields"]}
    minimum_bindings = int(policy["minimum_evidence_bindings_per_claim"])

    for index, claim in enumerate(claims, start=1):
        prefix = f"Critical claim #{index}"
        claim_problem_count = len(problems)
        if not isinstance(claim, dict):
            problems.append(f"{prefix} must be an object")
            continue
        claim_id = str(claim.get("claim_id", "")).strip()
        claim_text = str(claim.get("claim_text", "")).strip()
        declared_hash = str(claim.get("claim_sha256", "")).strip().casefold()
        if not claim_id:
            problems.append(f"{prefix} requires claim_id")
        elif policy["require_unique_claim_id"] and claim_id in seen_ids:
            problems.append(f"Duplicate critical claim_id: {claim_id}")
        else:
            seen_ids.add(claim_id)
        if not claim_text:
            problems.append(f"{prefix} requires nonblank claim_text")
        expected_hash = claim_sha256(claim_text)
        if declared_hash != expected_hash:
            problems.append(f"{prefix} claim_sha256 must match normalized claim_text; expected {expected_hash}")
        elif policy["require_unique_claim_hash"] and declared_hash in seen_hashes:
            problems.append(f"Duplicate critical claim content hash: {declared_hash}")
        else:
            seen_hashes.add(declared_hash)

        source_items = claim.get("source_ids", [])
        if not isinstance(source_items, list):
            problems.append(f"{prefix} source_ids must be an array")
            source_items = []
        claim_sources = {str(item).strip() for item in source_items if str(item).strip()}
        unknown_claim_sources = sorted(claim_sources - audit_source_ids)
        if unknown_claim_sources:
            problems.append(f"{prefix} uses unlisted source IDs: {unknown_claim_sources}")

        bindings = claim.get("evidence_bindings", [])
        if not isinstance(bindings, list):
            problems.append(f"{prefix} evidence_bindings must be an array")
            bindings = []
        if len(bindings) < minimum_bindings:
            problems.append(f"{prefix} requires at least {minimum_bindings} evidence bindings")
        binding_refs: set[str] = set()
        binding_sources: set[str] = set()
        for binding_index, binding in enumerate(bindings, start=1):
            binding_prefix = f"{prefix} binding #{binding_index}"
            if not isinstance(binding, dict):
                problems.append(f"{binding_prefix} must be an object")
                continue
            record_ref = str(binding.get("record_ref", "")).strip()
            if not record_ref:
                problems.append(f"{binding_prefix} requires record_ref")
                continue
            if record_ref in binding_refs:
                problems.append(f"{prefix} cannot bind the same record_ref twice: {record_ref}")
            binding_refs.add(record_ref)
            if policy["require_binding_record_in_task_audit"] and record_ref not in audit_record_refs:
                problems.append(f"{binding_prefix} record_ref is not counted by the task: {record_ref}")
            registry_row = registry_by_ref.get(record_ref)
            if registry_row is None:
                problems.append(f"{binding_prefix} record_ref is not registered: {record_ref}")
                continue
            if policy["require_binding_owned_by_task"] and registry_row.get("owner_task_id", "").strip() != task_id:
                problems.append(f"{binding_prefix} record_ref is owned by another task: {record_ref}")
            if policy["require_binding_countable"] and parse_bool(registry_row.get("counts_toward_floor", "")) is not True:
                problems.append(f"{binding_prefix} record_ref is not countable: {record_ref}")
            binding_sources.update(split_refs(registry_row.get("source_ids", "")))

            evidence_fields = binding.get("evidence_fields", [])
            if not isinstance(evidence_fields, list):
                problems.append(f"{binding_prefix} evidence_fields must be an array")
                evidence_fields = []
            normalized_fields = [str(item).strip().casefold() for item in evidence_fields if str(item).strip()]
            if policy["require_nonempty_evidence_fields"] and not normalized_fields:
                problems.append(f"{binding_prefix} requires at least one substantive evidence field")
            if len(normalized_fields) != len(set(normalized_fields)):
                problems.append(f"{binding_prefix} evidence_fields cannot contain duplicates")
            invalid_fields = sorted(set(normalized_fields) & disallowed_fields)
            if invalid_fields:
                problems.append(f"{binding_prefix} uses metadata-only evidence fields: {invalid_fields}")
            resolved, ref_error = resolve_record_ref(project_root, record_ref, record_file_cache)
            if ref_error:
                problems.append(f"{binding_prefix} has invalid record_ref: {ref_error}")
                continue
            assert resolved is not None
            resolved_by_name = {str(field).strip().casefold(): value for field, value in resolved.items()}
            for field in normalized_fields:
                if field not in resolved_by_name:
                    problems.append(f"{binding_prefix} evidence field does not exist: {field}")
                elif not str(resolved_by_name[field]).strip():
                    problems.append(f"{binding_prefix} evidence field is blank: {field}")

        if policy["require_claim_sources_equal_binding_sources"] and claim_sources != binding_sources:
            problems.append(
                f"{prefix} source_ids must exactly equal sources from bound registry records; "
                f"expected {sorted(binding_sources)}"
            )

        if independence_policy:
            independent, _, reasons = evaluate_claim_independence(claim_sources, source_ledger, independence_policy)
            if not independent:
                problems.append(f"{prefix} lacks independent triangulation: {'; '.join(reasons)}")
        elif len(claim_sources) < 2:
            problems.append(f"{prefix} requires at least two sources")
        if len(problems) == claim_problem_count:
            valid_dual_claims += 1

    return len(claims), valid_dual_claims, problems
