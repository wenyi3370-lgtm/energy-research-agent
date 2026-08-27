from __future__ import annotations

import json
from datetime import date
from pathlib import Path


GAP_AUDIT_FIELDS = {
    "related_task_ids",
    "rounds_completed",
    "count_evidence_refs",
    "gap_evidence_path",
    "remaining_high_priority_count",
    "exception_approval_status",
    "exception_approved_by",
    "exception_approval_date",
    "exception_approval_message",
}


def split_refs(value: str) -> list[str]:
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


def task_scope(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("market", "").strip().casefold(),
        row.get("exact_model", "").strip().casefold(),
        row.get("goal_family", "").strip().casefold(),
        row.get("collection_goal", "").strip().casefold(),
    )


def safe_project_file(project_root: Path, value: str) -> Path | None:
    relative = Path(str(value).strip())
    if not str(value).strip() or relative.is_absolute():
        return None
    resolved = (project_root / relative).resolve()
    return resolved if resolved.is_relative_to(project_root) else None


def json_string_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def validate_market_gap_exception(
    project_root: Path,
    task_row: dict[str, str],
    task_rows_by_id: dict[str, dict[str, str]],
    gap_row: dict[str, str],
    source_ledger: dict[str, dict[str, str]],
    gap_policy: dict,
    completed_statuses: set[str],
) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    issue_id = gap_row.get("issue_id", "").strip()
    required_rounds = {str(item) for item in gap_policy["required_rounds"]}

    if gap_row.get("data_domain", "").strip().casefold() != "market":
        problems.append(("quantity_exception_refs", f"Gap {issue_id} must use data_domain=market"))
    if gap_row.get("issue_type", "").strip().casefold() != str(gap_policy["required_issue_type"]).strip().casefold():
        problems.append(("quantity_exception_refs", f"Gap {issue_id} must use issue_type={gap_policy['required_issue_type']}"))
    for field in gap_policy["required_gap_fields"]:
        if not gap_row.get(str(field), "").strip():
            problems.append(("quantity_exception_refs", f"Gap {issue_id} requires nonblank {field}"))

    related_ids = set(split_refs(gap_row.get("related_task_ids", "")))
    current_task_id = task_row.get("task_id", "").strip()
    if current_task_id not in related_ids:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} must link the current task ID {current_task_id}"))
    unknown_tasks = sorted(related_ids - set(task_rows_by_id))
    if unknown_tasks:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} links unknown task IDs: {unknown_tasks}"))

    linked_rows = [task_rows_by_id[task_id] for task_id in sorted(related_ids & set(task_rows_by_id))]
    current_scope = task_scope(task_row)
    wrong_scope = [row.get("task_id", "") for row in linked_rows if task_scope(row) != current_scope]
    if wrong_scope:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} links tasks outside the same scoped goal: {wrong_scope}"))
    linked_rounds = {row.get("round", "").strip() for row in linked_rows if task_scope(row) == current_scope}
    if linked_rounds != required_rounds:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} must link completed R1/R2/R3 tasks; found rounds {sorted(linked_rounds)}"))
    incomplete = [
        row.get("task_id", "")
        for row in linked_rows
        if row.get("status", "").strip().casefold() not in completed_statuses
    ]
    if incomplete:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} links tasks not in a completed status: {incomplete}"))

    declared_rounds = set(split_refs(gap_row.get("rounds_completed", "")))
    if declared_rounds != required_rounds:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} rounds_completed must be exactly {sorted(required_rounds)}"))

    expected_count_refs = {
        row.get("count_evidence_refs", "").strip()
        for row in linked_rows
        if row.get("count_evidence_refs", "").strip()
    }
    declared_count_refs = set(split_refs(gap_row.get("count_evidence_refs", "")))
    if declared_count_refs != expected_count_refs or len(expected_count_refs) != len(required_rounds):
        problems.append(("quantity_exception_refs", f"Gap {issue_id} must link each R1/R2/R3 task count-evidence JSON exactly"))
    for ref in sorted(declared_count_refs):
        path = safe_project_file(project_root, ref)
        if path is None or not path.exists():
            problems.append(("quantity_exception_refs", f"Gap {issue_id} has invalid count-evidence path: {ref}"))

    remaining_text = gap_row.get("remaining_high_priority_count", "").strip()
    try:
        remaining_count = int(remaining_text)
    except ValueError:
        remaining_count = -1
    if gap_policy["require_zero_remaining_high_priority"] and remaining_count != 0:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} requires remaining_high_priority_count=0"))

    expected_approval = str(gap_policy["approval_status"]).strip().casefold()
    if gap_row.get("exception_approval_status", "").strip().casefold() != expected_approval:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} requires exception_approval_status={expected_approval}"))
    for field in ("exception_approved_by", "exception_approval_date", "exception_approval_message"):
        if not gap_row.get(field, "").strip():
            problems.append(("quantity_exception_refs", f"Gap {issue_id} requires nonblank {field}"))
    approval_date = gap_row.get("exception_approval_date", "").strip()
    if approval_date:
        try:
            date.fromisoformat(approval_date[:10])
        except ValueError:
            problems.append(("quantity_exception_refs", f"Gap {issue_id} exception_approval_date must start with YYYY-MM-DD"))

    evidence_value = gap_row.get("gap_evidence_path", "").strip()
    evidence_path = safe_project_file(project_root, evidence_value)
    if evidence_path is None or not evidence_path.exists():
        problems.append(("quantity_exception_refs", f"Gap {issue_id} requires an existing project-relative gap_evidence_path"))
        return problems
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON is unreadable: {exc}"))
        return problems
    if not isinstance(evidence, dict):
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON must be an object"))
        return problems
    if str(evidence.get("issue_id", "")).strip() != issue_id:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON issue_id does not match"))
    evidence_task_list = json_string_list(evidence.get("related_task_ids"))
    if evidence_task_list is None:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON related_task_ids must be an array"))
        evidence_task_list = []
    evidence_task_ids = set(evidence_task_list)
    if evidence_task_ids != related_ids:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON related_task_ids do not match the CSV"))

    round_entries = evidence.get("rounds", []) if isinstance(evidence.get("rounds"), list) else []
    round_map = {
        str(item.get("round", "")).strip(): item
        for item in round_entries
        if isinstance(item, dict) and str(item.get("round", "")).strip()
    }
    if len(round_entries) != len(required_rounds) or len(round_map) != len(round_entries) or set(round_map) != required_rounds:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON must contain exactly R1/R2/R3 entries"))
    for round_number in sorted(required_rounds):
        entry = round_map.get(round_number, {})
        task_id = str(entry.get("task_id", "")).strip()
        if task_id not in related_ids or task_rows_by_id.get(task_id, {}).get("round", "").strip() != round_number:
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} evidence must link its matching task"))
        attempted_queries = json_string_list(entry.get("attempted_queries"))
        attempted_source_list = json_string_list(entry.get("attempted_source_ids"))
        failure_reasons = json_string_list(entry.get("failure_reasons"))
        raw_refs = json_string_list(entry.get("raw_capture_refs"))
        for field, value in (
            ("attempted_queries", attempted_queries),
            ("attempted_source_ids", attempted_source_list),
            ("failure_reasons", failure_reasons),
            ("raw_capture_refs", raw_refs),
        ):
            if value is None:
                problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} {field} must be an array"))
        attempted_queries = attempted_queries or []
        attempted_sources = set(attempted_source_list or [])
        failure_reasons = failure_reasons or []
        raw_refs = raw_refs or []
        if len(attempted_queries) < int(gap_policy["minimum_queries_per_round"]):
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} has too few attempted queries"))
        if len(attempted_sources) < int(gap_policy["minimum_attempted_sources_per_round"]):
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} has too few attempted source IDs"))
        unknown_sources = sorted(attempted_sources - set(source_ledger))
        if unknown_sources:
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} uses unknown attempted source IDs: {unknown_sources}"))
        if len(failure_reasons) < int(gap_policy["minimum_failure_reasons_per_round"]):
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} has too few failure reasons"))
        if len(raw_refs) < int(gap_policy["minimum_raw_capture_refs_per_round"]):
            problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} has too few raw capture references"))
        for ref in raw_refs:
            raw_path = safe_project_file(project_root, ref)
            if raw_path is None or not raw_path.exists():
                problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} has invalid raw capture reference: {ref}"))
            elif not raw_path.is_file() or raw_path.stat().st_size == 0:
                problems.append(("quantity_exception_refs", f"Gap {issue_id} R{round_number} raw capture is empty or not a file: {ref}"))

    remaining_list = json_string_list(evidence.get("remaining_high_priority_ids"))
    if remaining_list is None:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence JSON remaining_high_priority_ids must be an array"))
        remaining_list = []
    remaining_ids = set(remaining_list)
    if gap_policy["require_zero_remaining_high_priority"] and remaining_ids:
        problems.append(("quantity_exception_refs", f"Gap {issue_id} evidence still has high-priority discoveries: {sorted(remaining_ids)}"))
    if remaining_count >= 0 and remaining_count != len(remaining_ids):
        problems.append(("quantity_exception_refs", f"Gap {issue_id} remaining-high-priority count does not match evidence JSON"))
    return problems
