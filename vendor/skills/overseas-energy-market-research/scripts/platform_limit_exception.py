from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from market_gap_exception import json_string_list, safe_project_file, split_refs, task_scope


def nonnegative_int(value: object) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_platform_limit_exception(
    project_root: Path,
    task_row: dict[str, str],
    task_rows_by_id: dict[str, dict[str, str]],
    source_ledger: dict[str, dict[str, str]],
    policy: dict,
    completed_statuses: set[str],
) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    task_id = task_row.get("task_id", "").strip()
    required_family = str(policy["required_goal_family"]).strip()
    required_round = str(policy["required_round"]).strip()
    required_rounds = {str(item) for item in policy["required_rounds"]}

    if task_row.get("goal_family", "").strip().casefold() != required_family.casefold():
        problems.append(("quantity_exception_type", f"platform_limit is allowed only for {required_family}"))
    if task_row.get("round", "").strip() != required_round:
        problems.append(("quantity_exception_type", f"platform_limit is allowed only in round {required_round}"))

    target_records = nonnegative_int(task_row.get("target_records"))
    actual_records = nonnegative_int(task_row.get("actual_records"))
    if target_records is None or actual_records is None:
        problems.append(("platform_limit_evidence", "platform_limit requires valid target_records and actual_records"))
    elif actual_records >= target_records:
        problems.append(("platform_limit_evidence", "platform_limit is unnecessary unless actual_records is below target_records"))

    evidence_value = task_row.get("platform_limit_evidence", "").strip()
    evidence_path = safe_project_file(project_root, evidence_value)
    if evidence_path is None or evidence_path.suffix.casefold() != ".json" or not evidence_path.is_file():
        problems.append(("platform_limit_evidence", "platform_limit_evidence must be an existing project-relative JSON file"))
        return problems
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(("platform_limit_evidence", f"Platform-limit evidence JSON is unreadable: {exc}"))
        return problems
    if not isinstance(evidence, dict):
        problems.append(("platform_limit_evidence", "Platform-limit evidence JSON must be an object"))
        return problems

    evidence_id = str(evidence.get("evidence_id", "")).strip()
    if not evidence_id:
        problems.append(("platform_limit_evidence", "Platform-limit evidence JSON requires evidence_id"))
    if str(evidence.get("task_id", "")).strip() != task_id:
        problems.append(("platform_limit_evidence", "Platform-limit evidence task_id must match the R2 task"))
    exception_refs = split_refs(task_row.get("quantity_exception_refs", ""))
    if not evidence_id or exception_refs != [evidence_id]:
        problems.append(("quantity_exception_refs", "platform_limit quantity_exception_refs must contain exactly the evidence_id"))

    related_list = json_string_list(evidence.get("related_task_ids"))
    if related_list is None:
        problems.append(("platform_limit_evidence", "related_task_ids must be an array"))
        related_list = []
    related_ids = set(related_list)
    if len(related_list) != len(related_ids):
        problems.append(("platform_limit_evidence", "related_task_ids cannot contain duplicates"))
    if task_id not in related_ids:
        problems.append(("platform_limit_evidence", f"related_task_ids must include the current task {task_id}"))
    unknown_tasks = sorted(related_ids - set(task_rows_by_id))
    if unknown_tasks:
        problems.append(("platform_limit_evidence", f"related_task_ids contain unknown task IDs: {unknown_tasks}"))
    linked_rows = [task_rows_by_id[item] for item in related_ids if item in task_rows_by_id]
    wrong_scope = [row.get("task_id", "") for row in linked_rows if task_scope(row) != task_scope(task_row)]
    if wrong_scope:
        problems.append(("platform_limit_evidence", f"related_task_ids include tasks outside the same scoped goal: {wrong_scope}"))
    linked_rounds = {row.get("round", "").strip() for row in linked_rows if task_scope(row) == task_scope(task_row)}
    if len(related_ids) != len(required_rounds) or linked_rounds != required_rounds:
        problems.append(("platform_limit_evidence", "related_task_ids must contain exactly the completed R1/R2/R3 tasks"))
    incomplete = [
        row.get("task_id", "")
        for row in linked_rows
        if row.get("status", "").strip().casefold() not in completed_statuses
    ]
    if incomplete:
        problems.append(("platform_limit_evidence", f"Platform-limit evidence links incomplete tasks: {incomplete}"))

    audit_value = task_row.get("count_evidence_refs", "").strip()
    audit_path = safe_project_file(project_root, audit_value)
    if audit_path is None or not audit_path.is_file():
        problems.append(("platform_limit_evidence", "The R2 count-evidence JSON must exist before platform-limit validation"))
        return problems
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(("platform_limit_evidence", f"The R2 count-evidence JSON is unreadable: {exc}"))
        return problems
    if not isinstance(audit, dict):
        problems.append(("platform_limit_evidence", "The R2 count-evidence JSON must be an object"))
        return problems
    if str(audit.get("task_id", "")).strip() != task_id:
        problems.append(("platform_limit_evidence", "The R2 count-evidence task_id does not match"))
    audit_record_list = json_string_list(audit.get("record_refs"))
    audit_platform_list = json_string_list(audit.get("platforms"))
    audit_source_list = json_string_list(audit.get("unique_source_ids"))
    if audit_record_list is None or audit_platform_list is None or audit_source_list is None:
        problems.append(("platform_limit_evidence", "The R2 count-evidence record_refs, platforms, and unique_source_ids must be arrays"))
        audit_record_list = audit_record_list or []
        audit_platform_list = audit_platform_list or []
        audit_source_list = audit_source_list or []
    audit_records = set(audit_record_list)
    audit_platforms = set(audit_platform_list)
    audit_sources = set(audit_source_list)

    entries = evidence.get("platform_limits")
    if not isinstance(entries, list):
        problems.append(("platform_limit_evidence", "platform_limits must be an array"))
        entries = []
    if len(entries) < int(policy["minimum_platform_entries"]):
        problems.append(("platform_limit_evidence", f"platform_limits requires at least {policy['minimum_platform_entries']} platform entries"))

    platform_names: list[str] = []
    urls: list[str] = []
    all_record_refs: list[str] = []
    all_raw_refs: list[str] = []
    accessible_sum = 0
    for index, entry in enumerate(entries, start=1):
        label = f"platform_limits[{index}]"
        if not isinstance(entry, dict):
            problems.append(("platform_limit_evidence", f"{label} must be an object"))
            continue
        platform = str(entry.get("platform", "")).strip()
        url = str(entry.get("url", "")).strip()
        access_date = str(entry.get("access_date", "")).strip()
        blocker_reason = str(entry.get("blocker_reason", "")).strip()
        if not platform:
            problems.append(("platform_limit_evidence", f"{label} requires platform"))
        else:
            platform_names.append(platform)
        if not is_http_url(url):
            problems.append(("platform_limit_evidence", f"{label} requires a valid HTTP(S) URL"))
        else:
            urls.append(url)
        try:
            date.fromisoformat(access_date[:10])
        except ValueError:
            problems.append(("platform_limit_evidence", f"{label} access_date must start with YYYY-MM-DD"))
        if not blocker_reason:
            problems.append(("platform_limit_evidence", f"{label} requires blocker_reason"))

        source_list = json_string_list(entry.get("source_ids"))
        method_list = json_string_list(entry.get("attempted_methods"))
        raw_list = json_string_list(entry.get("raw_capture_refs"))
        record_list = json_string_list(entry.get("record_refs"))
        for field, value in (
            ("source_ids", source_list),
            ("attempted_methods", method_list),
            ("raw_capture_refs", raw_list),
            ("record_refs", record_list),
        ):
            if value is None:
                problems.append(("platform_limit_evidence", f"{label} {field} must be an array"))
        source_list = source_list or []
        method_list = method_list or []
        raw_list = raw_list or []
        record_list = record_list or []
        if len(set(source_list)) < int(policy["minimum_source_ids_per_platform"]):
            problems.append(("platform_limit_evidence", f"{label} has too few source IDs"))
        unknown_sources = sorted(set(source_list) - set(source_ledger))
        if unknown_sources:
            problems.append(("platform_limit_evidence", f"{label} uses unknown source IDs: {unknown_sources}"))
        if not set(source_list).issubset(audit_sources):
            problems.append(("platform_limit_evidence", f"{label} source IDs must be in the R2 count audit"))
        source_urls = {source_ledger[item].get("source_url", "").strip() for item in source_list if item in source_ledger}
        if url and url not in source_urls:
            problems.append(("platform_limit_evidence", f"{label} URL must match one of its source-ledger rows"))
        if len(set(method_list)) < int(policy["minimum_attempt_methods_per_platform"]):
            problems.append(("platform_limit_evidence", f"{label} has too few distinct attempted methods"))
        if len(set(raw_list)) < int(policy["minimum_raw_capture_refs_per_platform"]):
            problems.append(("platform_limit_evidence", f"{label} has too few raw capture references"))
        for ref in raw_list:
            raw_path = safe_project_file(project_root, ref)
            if raw_path is None or not raw_path.is_file() or raw_path.stat().st_size == 0:
                problems.append(("platform_limit_evidence", f"{label} has an invalid or empty raw capture: {ref}"))
        all_raw_refs.extend(raw_list)

        visible = nonnegative_int(entry.get("visible_total_count"))
        accessible = nonnegative_int(entry.get("accessible_unique_count"))
        collected_raw = nonnegative_int(entry.get("collected_raw_count"))
        duplicates = nonnegative_int(entry.get("duplicate_removed_count"))
        if None in {visible, accessible, collected_raw, duplicates}:
            problems.append(("platform_limit_evidence", f"{label} count fields must be nonnegative integers"))
        else:
            assert visible is not None and accessible is not None and collected_raw is not None and duplicates is not None
            if visible < accessible:
                problems.append(("platform_limit_evidence", f"{label} visible_total_count cannot be below accessible_unique_count"))
            if collected_raw < accessible or collected_raw - duplicates != accessible:
                problems.append(("platform_limit_evidence", f"{label} raw/dedup/access counts do not reconcile"))
            if len(set(record_list)) != accessible or len(record_list) != len(set(record_list)):
                problems.append(("platform_limit_evidence", f"{label} record_refs must be unique and equal accessible_unique_count"))
            accessible_sum += accessible
        all_record_refs.extend(record_list)

    if len(platform_names) != len(set(platform_names)):
        problems.append(("platform_limit_evidence", "Platform names must be unique"))
    if len(urls) != len(set(urls)):
        problems.append(("platform_limit_evidence", "Platform evidence URLs must be unique"))
    if set(platform_names) != audit_platforms:
        problems.append(("platform_limit_evidence", "Platform evidence entries must exactly match the R2 count-audit platforms"))
    if len(all_raw_refs) != len(set(all_raw_refs)):
        problems.append(("platform_limit_evidence", "Raw capture references cannot be reused across platform entries"))
    if len(all_record_refs) != len(set(all_record_refs)):
        problems.append(("platform_limit_evidence", "Record references cannot overlap across platform entries"))
    if set(all_record_refs) != audit_records:
        problems.append(("platform_limit_evidence", "Platform-limit record_refs must exactly match the R2 count audit"))

    combined_accessible = nonnegative_int(evidence.get("combined_accessible_unique_count"))
    combined_valid = nonnegative_int(evidence.get("combined_collected_valid_count"))
    if combined_accessible is None or combined_valid is None:
        problems.append(("platform_limit_evidence", "Combined platform-limit counts must be nonnegative integers"))
    else:
        if combined_accessible != accessible_sum:
            problems.append(("platform_limit_evidence", "combined_accessible_unique_count does not equal the platform sum"))
        if combined_valid != len(set(all_record_refs)):
            problems.append(("platform_limit_evidence", "combined_collected_valid_count does not equal the unique record references"))
        if policy["require_collected_equals_accessible_max"] and combined_valid != combined_accessible:
            problems.append(("platform_limit_evidence", "Collected valid reviews must equal the accessible platform maximum"))
        if actual_records is not None and combined_valid != actual_records:
            problems.append(("platform_limit_evidence", "Platform-limit valid count must equal task actual_records"))

    remaining_list = json_string_list(evidence.get("remaining_high_priority_ids"))
    if remaining_list is None:
        problems.append(("platform_limit_evidence", "remaining_high_priority_ids must be an array"))
        remaining_list = []
    if policy["require_zero_remaining_high_priority"] and remaining_list:
        problems.append(("platform_limit_evidence", "Platform-limit evidence still has unresolved high-priority discoveries"))

    approval = evidence.get("approval")
    if not isinstance(approval, dict):
        problems.append(("platform_limit_evidence", "Platform-limit evidence requires an approval object"))
        approval = {}
    expected_status = str(policy["approval_status"]).strip().casefold()
    if str(approval.get("status", "")).strip().casefold() != expected_status:
        problems.append(("platform_limit_evidence", f"Approval status must be {expected_status}"))
    for field in ("approved_by", "approval_date", "approval_message"):
        if not str(approval.get(field, "")).strip():
            problems.append(("platform_limit_evidence", f"Approval requires nonblank {field}"))
    approval_date = str(approval.get("approval_date", "")).strip()
    if approval_date:
        try:
            date.fromisoformat(approval_date[:10])
        except ValueError:
            problems.append(("platform_limit_evidence", "approval_date must start with YYYY-MM-DD"))
    return problems
