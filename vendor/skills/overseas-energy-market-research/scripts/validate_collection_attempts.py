from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from _common import Issue, add_common_args, print_report, read_csv, require_columns, resolve_project_file, row_label
from collection_quantity_policy import load_project_policy, round_floor
from web_collection.journal import FIELDS, validate_journal_row, journal_stats

JOURNAL_CANDIDATES = ["13_Collection_Attempt_Journal.csv", "collection_attempt_journal.csv"]
TASKS_CANDIDATES = ["02_Web_Collection_Tasks.csv", "web_collection_tasks.csv"]

# 未解决时禁止任务置 completed 的阻断类错误
BLOCKING_ERROR_CLASSES = {"auth_required", "bridge_unavailable", "tool_unavailable", "insufficient_balance"}


def parse_nonnegative_int(value: str) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def validate(path: Path, require_actual: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    fieldnames, rows = read_csv(path)
    header_issues = require_columns(fieldnames, FIELDS)
    if header_issues:
        return header_issues

    project_root = path.parent.resolve()
    by_row_id: dict[str, dict[str, str]] = {}

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        for problem in validate_journal_row(row):
            issues.append(Issue("fail", label, "journal_row", problem))
        if row.get("attempt_id", "").strip():
            if row["attempt_id"] in by_row_id:
                issues.append(Issue("fail", label, "attempt_id", f"Duplicate attempt_id: {row['attempt_id']}"))
            by_row_id[row["attempt_id"]] = row

        status = row.get("status", "").strip()
        if status in {"success", "partial"}:
            raw_capture = row.get("raw_capture_path", "").strip()
            if raw_capture:
                capture_path = (project_root / raw_capture).resolve()
                if not capture_path.is_relative_to(project_root):
                    issues.append(Issue("fail", label, "raw_capture_path", "Raw capture must remain inside the project directory"))
                elif not capture_path.is_file():
                    issues.append(Issue("fail", label, "raw_capture_path", f"Raw capture file does not exist: {raw_capture}"))

    # ---- 对照任务表：防少搜 + 防假完成 ----
    tasks_path = project_root / "02_Web_Collection_Tasks.csv"
    if not tasks_path.is_file():
        issues.append(Issue("fail", "02_Web_Collection_Tasks.csv", "collection_plan", "Web collection task CSV is required for attempt audit"))
        return issues

    _, task_rows = read_csv(tasks_path)
    quantity_policy: dict | None = None
    manifest_path = project_root / "project_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            quantity_policy = load_project_policy(project_root, manifest)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            issues.append(Issue("fail", "project_manifest.json", "collection_quantity_policy", f"Cannot load frozen collection policy: {exc}"))

    attempts_by_task: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        task_id = row.get("task_id", "").strip()
        if task_id:
            attempts_by_task[task_id].append(row)

    for task_index, task in enumerate(task_rows, start=2):
        task_id = task.get("task_id", "").strip()
        rnd = task.get("round", "").strip()
        if rnd not in {"1", "2", "3"}:
            continue
        label = row_label(task_index, task)
        task_attempts = attempts_by_task.get(task_id, [])
        attempted = len(task_attempts)

        if attempted == 0:
            issues.append(Issue("fail", label, "attempt_journal", f"No collection attempts recorded for round {rnd} task {task_id}"))
            continue

        # 防少搜：attempted 至少达到 任务目标 与 政策 floor 中较低者（防止少搜/漏搜）
        target = parse_nonnegative_int(task.get("target_unique_sources", ""))
        floor = None
        if quantity_policy and task.get("goal_family", "").strip():
            try:
                floor = round_floor(task["goal_family"], rnd, quantity_policy)["min_unique_sources"]
            except (KeyError, ValueError):
                floor = None
        candidates = [value for value in (target, floor) if value is not None]
        minimum_attempts = min(candidates) if candidates else 1
        if attempted < minimum_attempts:
            issues.append(
                Issue(
                    "fail",
                    label,
                    "attempt_journal",
                    f"Round {rnd} task {task_id} has {attempted} attempt(s), below minimum {minimum_attempts} (target={target}, policy floor={floor})",
                )
            )

        # 防假完成：阻断类错误未解决（其后无成功 attempt）时，任务不得 completed
        task_status = task.get("status", "").strip().casefold()
        if task_status in {"completed", "done", "collected", "verified", "saturated"}:
            blocking_unresolved = False
            for attempt in task_attempts:
                if attempt.get("status", "").strip() == "failure" and attempt.get("error_class", "").strip() in BLOCKING_ERROR_CLASSES:
                    blocking_unresolved = True
                    break
            if blocking_unresolved:
                issues.append(
                    Issue(
                        "fail",
                        label,
                        "status",
                        f"Task {task_id} is completed but has unresolved blocking failures (auth_required/bridge_unavailable/tool_unavailable/insufficient_balance); login-state failures must not fake completion",
                    )
                )

        if require_actual:
            if task_status not in {"completed", "done", "collected", "verified", "saturated"}:
                issues.append(Issue("fail", label, "status", f"Final collection audit requires a completed status; got '{task.get('status', '')}'"))
            if target is not None and attempted < target:
                issues.append(Issue("fail", label, "attempt_journal", f"Final audit: task {task_id} attempted {attempted} times, below target {target}"))

    # ---- 汇总（计入报告输出）----
    stats = {"attempted": len(rows), "success": 0, "failure": 0, "partial": 0, "skipped": 0}
    for row in rows:
        status = row.get("status", "").strip()
        if status in stats:
            stats[status] += 1
    issues.append(
        Issue(
            "note",
            "journal_summary",
            "attempted/succeeded/failed",
            f"attempted={stats['attempted']} success={stats['success']} failure={stats['failure']} partial={stats['partial']} skipped={stats['skipped']}",
        )
    )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate collection attempt journal: anti-under-collection, anti-fake-completion, gap summary.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 13_Collection_Attempt_Journal.csv.")
    parser.add_argument("--file", help="Explicit attempt journal CSV path.")
    parser.add_argument("--require-actual", action="store_true", help="Final audit: require completed statuses and attempted >= declared targets.")
    add_common_args(parser)
    args = parser.parse_args()
    path = resolve_project_file(Path(args.project_dir).resolve(), args.file, JOURNAL_CANDIDATES)
    return print_report("Collection attempt journal validation", validate(path, require_actual=args.require_actual), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
