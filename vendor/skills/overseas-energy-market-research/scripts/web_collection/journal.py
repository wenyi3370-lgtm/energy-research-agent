"""采集过程台账（13_Collection_Attempt_Journal.csv）。

每次采集动作（search / batch_search / extract / navigate / snapshot / fetch ...）
必须追加一行；验证器 validate_collection_attempts.py 据此做机械校验：
防少搜（每 R1/R2/R3 任务行必须有 attempt 且 attempted ≥ target）、
防假完成（未解决 auth_required / bridge_unavailable 的任务不得 completed）、
失败必须带 error_class + failure_reason、成功必须有存在的 raw_capture。
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Iterable

from _common import now_iso, read_csv

JOURNAL_FILE = "13_Collection_Attempt_Journal.csv"

FIELDS = [
    "attempt_id",
    "task_id",
    "round",
    "round_goal",
    "tool",
    "action",
    "query_or_url",
    "status",
    "error_class",
    "failure_reason",
    "result_count",
    "candidates_found",
    "raw_capture_path",
    "session",
    "timestamp",
]

STATUSES = {"success", "failure", "partial", "skipped"}
ALLOWED_TOOLS = {"anysearch", "kimi-webbridge", "http_fetch"}

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


class JournalWriteError(RuntimeError):
    """strict 模式下台账写入失败直接抛错，防止采集动作丢失审计痕迹。"""


def _safe_task_id(task_id: str) -> str:
    return _SAFE_ID.sub("-", str(task_id or "task")).strip("-") or "task"


class CollectionJournal:
    """项目内采集台账（追加式 CSV，attempt_id 防重复）。"""

    def __init__(self, project_dir: Path, *, strict: bool = False) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.path = self.project_dir / JOURNAL_FILE
        self.strict = strict
        self._known_ids: set[str] = set()
        if self.path.is_file():
            _, rows = read_csv(self.path)
            self._known_ids = {str(row.get("attempt_id", "")).strip() for row in rows if row.get("attempt_id", "").strip()}

    def append(
        self,
        *,
        task_id: str,
        round_number: str,
        round_goal: str,
        tool: str,
        action: str,
        query_or_url: str,
        status: str,
        error_class: str = "none",
        failure_reason: str = "",
        result_count: int | None = None,
        candidates_found: int | None = None,
        raw_capture_path: str = "",
        session: str = "",
    ) -> str:
        # 并发防御：append 前重读文件，纳入其他进程已写入的 attempt_id 与表头状态
        self._reload_existing()
        attempt_id = self.next_attempt_id(task_id)
        row = {
            "attempt_id": attempt_id,
            "task_id": str(task_id or "").strip(),
            "round": str(round_number or "").strip(),
            "round_goal": str(round_goal or "").strip(),
            "tool": str(tool or "").strip(),
            "action": str(action or "").strip(),
            "query_or_url": str(query_or_url or "").strip(),
            "status": str(status or "").strip(),
            "error_class": str(error_class or "none").strip(),
            "failure_reason": str(failure_reason or "").strip(),
            "result_count": "" if result_count is None else str(int(result_count)),
            "candidates_found": "" if candidates_found is None else str(int(candidates_found)),
            "raw_capture_path": str(raw_capture_path or "").strip(),
            "session": str(session or "").strip(),
            "timestamp": now_iso(),
        }
        self._known_ids.add(attempt_id)
        self._write_rows([row])
        return attempt_id

    def next_attempt_id(self, task_id: str) -> str:
        safe = _safe_task_id(task_id)
        stamp = now_iso().replace(":", "").replace("-", "").replace("T", "_").split(".")[0]
        # 同秒多次 append 时追加序号，保证 attempt_id 唯一且不会死循环
        sequence = 1
        while f"{safe}-{stamp}-{sequence}" in self._known_ids:
            sequence += 1
        return f"{safe}-{stamp}-{sequence}"

    def _reload_existing(self) -> None:
        """重读文件：跨进程追加时把新 attempt_id 纳入查重，避免同秒重复 ID。"""
        if not self.path.is_file():
            return
        try:
            _, rows = read_csv(self.path)
        except (OSError, Exception):  # noqa: BLE001 - 文件被并发写坏时保守处理
            return
        for row in rows:
            attempt_id = str(row.get("attempt_id", "")).strip()
            if attempt_id:
                self._known_ids.add(attempt_id)

    def _write_rows(self, rows: Iterable[dict[str, str]]) -> None:
        try:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            # 表头判断：文件不存在或为空时才写表头（并发下避免重复表头）
            needs_header = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                if needs_header:
                    writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            if self.strict:
                raise JournalWriteError(f"Cannot append to collection journal {self.path}: {exc}") from exc
            print(f"[journal] WARNING: cannot append to {self.path}: {exc} (strict=False, continuing)")

    def load(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        _, rows = read_csv(self.path)
        return rows

    def summary(self) -> dict[str, object]:
        """按 (task_id, round) 统计 attempted/succeeded/failed/partial/skipped 与缺口。"""
        rows = self.load()
        per_task: dict[tuple[str, str], dict[str, int]] = {}
        for row in rows:
            key = (str(row.get("task_id", "")).strip(), str(row.get("round", "")).strip())
            bucket = per_task.setdefault(key, {"attempted": 0, "success": 0, "failure": 0, "partial": 0, "skipped": 0})
            bucket["attempted"] += 1
            status = str(row.get("status", "")).strip()
            if status in bucket:
                bucket[status] += 1
        return {
            "journal_path": JOURNAL_FILE,
            "attempt_count": len(rows),
            "per_task_round": {
                f"{task}@{rnd}": counts for (task, rnd), counts in sorted(per_task.items())
            },
        }


def validate_journal_row(row: dict[str, str]) -> list[str]:
    """单行机械校验（供验证器复用）。"""
    problems: list[str] = []
    for field in ("attempt_id", "task_id", "tool", "action", "query_or_url", "status", "timestamp"):
        if not row.get(field, "").strip():
            problems.append(f"Required journal field is blank: {field}")
    tool = row.get("tool", "").strip()
    if tool and tool not in ALLOWED_TOOLS:
        problems.append(f"tool must be one of {sorted(ALLOWED_TOOLS)}; got '{tool}'")
    status = row.get("status", "").strip()
    if status and status not in STATUSES:
        problems.append(f"status must be one of {sorted(STATUSES)}; got '{status}'")
    if status == "failure":
        error_class = row.get("error_class", "").strip()
        reason = row.get("failure_reason", "").strip()
        if not error_class or error_class == "none":
            problems.append("failure attempts require a non-none error_class")
        if not reason:
            problems.append("failure attempts require failure_reason")
    if status in {"success", "partial"}:
        if not row.get("raw_capture_path", "").strip():
            problems.append("success/partial attempts require raw_capture_path")
    return problems


def journal_stats(rows: list[dict[str, str]], task_id: str, round_number: str | None = None) -> dict[str, int]:
    """指定任务（可选轮次）的 attempted/succeeded/failed 统计。"""
    stats = {"attempted": 0, "success": 0, "failure": 0, "partial": 0, "skipped": 0}
    for row in rows:
        if str(row.get("task_id", "")).strip() != task_id:
            continue
        if round_number is not None and str(row.get("round", "")).strip() != str(round_number):
            continue
        status = str(row.get("status", "")).strip()
        if status not in stats:
            continue
        stats["attempted"] += 1
        stats[status] += 1
    return stats
