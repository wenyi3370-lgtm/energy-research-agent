"""统一路由与单轮任务执行。

路由规则（与 kimi-webbridge-collection-playbooks.md 一致）：
- anysearch：搜索/垂直域/批量搜索 + 静态页提取；extract 失败 → http_fetch 静态回退；
- http_fetch：仅静态；登录墙 → auth_required → 升级 kimi-webbridge；
- kimi-webbridge：动态/认证/交互（硬门禁：插件必须已连接）。
每次动作必经 journal；任务状态按结果置 completed / partial / blocked。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _common import is_url, now_iso, read_csv, write_csv
from _kimi_webbridge import normalize_session
from web_collection.anysearch_backend import run_batch_search, run_extract, run_search
from web_collection.errors import ErrorClass, normalize_kimi_error_class
from web_collection.http_fetch import FetchResult, fetch_url
from web_collection.journal import CollectionJournal
from web_collection import kimi_adapter

TASK_FILE = "02_Web_Collection_Tasks.csv"
COMPLETED_STATUSES = {"completed", "done", "collected", "verified", "saturated"}


def save_fetch_capture(project_root: Path, goal: str, task_id: str, url: str, result: FetchResult) -> str:
    """http_fetch 回退内容双留痕：markdown 主文件 + 原始 HTML/JSON 副文件（唯一时间戳）。"""
    import re
    from datetime import datetime

    safe_goal = re.sub(r"[^A-Za-z0-9._-]+", "_", goal or "general") or "general"
    directory = project_root / "raw_capture" / safe_goal
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", task_id or "task")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    markdown_target = directory / f"{safe}_http_fetch_{stamp}.md"
    markdown_target.write_text(
        f"# http_fetch raw capture\n\nURL: {url}\n\n---\n\n{result.text or ''}",
        encoding="utf-8",
    )
    if result.raw_text and result.raw_text != result.text:
        extension = "json" if "json" in (result.content_type or "") else "html"
        raw_target = directory / f"{safe}_http_fetch_{stamp}_raw.{extension}"
        raw_target.write_text(result.raw_text, encoding="utf-8")
    return markdown_target.relative_to(project_root).as_posix()


@dataclass
class RunOutcome:
    task_id: str
    status: str  # completed | partial | blocked
    attempts: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


def _read_tasks(project_dir: Path) -> tuple[list[str], list[dict[str, str]]]:
    path = project_dir / TASK_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{TASK_FILE} does not exist in {project_dir}")
    return read_csv(path)


def update_task_status(project_dir: Path, task_id: str, status: str, note: str) -> None:
    path = project_dir / TASK_FILE
    fieldnames, rows = read_csv(path)
    updated = False
    for row in rows:
        if row.get("task_id", "").strip() == task_id:
            row["status"] = status
            prior = row.get("notes", "").strip()
            row["notes"] = f"{prior}; {note}".strip("; ") if prior else note
            updated = True
            break
    if not updated:
        raise ValueError(f"run_task: task_id {task_id} not found in {TASK_FILE}; status not updated")
    write_csv(path, fieldnames, rows)


def run_task(
    project_dir: Path,
    task_row: dict[str, str],
    *,
    journal: CollectionJournal | None = None,
    official_cli: str | Path | None = None,
    kimi_binary: Path | None = None,
    strict_journal: bool = False,
    allow_kimi: bool = True,
) -> RunOutcome:
    """执行一个采集任务的单轮动作（R1/R2/R3 由任务行 round 决定）。"""
    project_root = Path(project_dir).resolve()
    selected_journal = journal or CollectionJournal(project_root, strict=strict_journal)
    task_id = task_row.get("task_id", "").strip()
    round_number = task_row.get("round", "").strip()
    round_goal = task_row.get("round_goal", "").strip()
    tool = task_row.get("required_tool", "").strip()
    goal = task_row.get("collection_goal", "").strip()
    query_or_url = task_row.get("starting_url_or_query", "").strip()
    # session 用归一化后的小写稳定名（与 daemon 实际收到的一致，台账对账可匹配）
    session = normalize_session(f"research-{task_id}")

    attempts: list[dict[str, Any]] = []

    def record(**kwargs: Any) -> dict[str, Any]:
        row = {
            "task_id": task_id,
            "round_number": round_number,
            "round_goal": round_goal,
            "tool": kwargs.pop("tool", tool),
            "session": session,
        }
        row.update(kwargs)
        attempt_id = selected_journal.append(
            task_id=task_id,
            round_number=round_number,
            round_goal=round_goal,
            tool=row["tool"],
            action=row["action"],
            query_or_url=row["query_or_url"],
            status=row["status"],
            error_class=row.get("error_class", "none"),
            failure_reason=row.get("failure_reason", ""),
            result_count=row.get("result_count"),
            candidates_found=row.get("candidates_found"),
            raw_capture_path=row.get("raw_capture_path", ""),
            session=session,
        )
        row["attempt_id"] = attempt_id
        attempts.append(row)
        return row

    if tool == "kimi-webbridge":
        outcome = _run_kimi_task(
            record, task_id, goal, query_or_url, project_root, kimi_binary, allow_kimi
        )
    elif tool == "anysearch":
        outcome = _run_anysearch_task(
            record, task_id, goal, query_or_url, project_root, official_cli
        )
    else:
        record(
            action="route",
            query_or_url=query_or_url,
            status="failure",
            error_class=ErrorClass.PARSE_FAILURE,
            failure_reason=f"Unsupported required_tool: {tool}",
        )
        outcome = RunOutcome(task_id=task_id, status="blocked", attempts=attempts, note=f"unsupported tool {tool}")

    update_task_status(project_root, task_id, outcome.status, outcome.note)
    outcome.attempts = attempts
    return outcome


def _run_anysearch_task(
    record,
    task_id: str,
    goal: str,
    query_or_url: str,
    project_root: Path,
    official_cli: str | Path | None,
) -> RunOutcome:
    action = "extract" if is_url(query_or_url) else "search"
    if action == "extract":
        result = run_extract(
            query_or_url,
            project_dir=project_root,
            task_id=task_id,
            goal=goal,
            official_cli=official_cli,
        )
        record(
            action="extract",
            query_or_url=query_or_url,
            status="success" if result.ok else "failure",
            error_class=result.error_class,
            failure_reason=result.error_message,
            raw_capture_path=result.raw_capture_path,
        )
        if result.ok:
            return RunOutcome(task_id=task_id, status="completed", note="extract ok")
        if result.error_class in {ErrorClass.HTTP_4XX, ErrorClass.NETWORK_ERROR, ErrorClass.PARSE_FAILURE, ErrorClass.TOOL_UNAVAILABLE}:
            fallback = fetch_url(query_or_url)
            fallback_capture = ""
            if fallback.ok:
                fallback_capture = save_fetch_capture(project_root, goal, task_id, query_or_url, fallback)
            record(
                action="http_fetch",
                query_or_url=query_or_url,
                status="success" if fallback.ok else "failure",
                error_class=fallback.error_class,
                failure_reason=fallback.error_message,
                tool="http_fetch",
                raw_capture_path=fallback_capture,
            )
            if fallback.ok:
                return RunOutcome(task_id=task_id, status="completed", note="anysearch extract failed; http_fetch ok")
            if fallback.error_class == ErrorClass.AUTH_REQUIRED:
                return RunOutcome(
                    task_id=task_id,
                    status="blocked",
                    note="login wall detected; route to kimi-webbridge with authenticated session",
                )
        return RunOutcome(
            task_id=task_id,
            status="blocked",
            note=f"extract failed: {result.error_class}: {result.error_message[:200]}",
        )

    result = run_search(
        query_or_url,
        project_dir=project_root,
        task_id=task_id,
        goal=goal,
        max_results=10,
        official_cli=official_cli,
    )
    record(
        action="search",
        query_or_url=query_or_url,
        status="success" if result.ok else "failure",
        error_class=result.error_class,
        failure_reason=result.error_message,
        candidates_found=result.candidates_found,
        raw_capture_path=result.raw_capture_path,
    )
    if result.ok:
        return RunOutcome(task_id=task_id, status="completed", note="search ok")
    return RunOutcome(
        task_id=task_id,
        status="blocked",
        note=f"search failed: {result.error_class}: {result.error_message[:200]}",
    )


def _run_kimi_task(
    record,
    task_id: str,
    goal: str,
    query_or_url: str,
    project_root: Path,
    kimi_binary: Path | None,
    allow_kimi: bool,
) -> RunOutcome:
    if not allow_kimi:
        record(
            action="route",
            query_or_url=query_or_url,
            status="skipped",
            failure_reason="kimi-webbridge disabled by caller",
        )
        return RunOutcome(task_id=task_id, status="blocked", note="kimi-webbridge disabled")

    health = kimi_adapter.check_health(kimi_binary)
    if not health.healthy:
        record(
            action="health_check",
            query_or_url=query_or_url,
            status="failure",
            error_class=ErrorClass.BRIDGE_UNAVAILABLE,
            failure_reason=f"{health.failure_class}: {health.failure_reason}",
        )
        return RunOutcome(
            task_id=task_id,
            status="blocked",
            note=f"bridge unavailable: {health.failure_class}. Open the browser with the extension enabled or start the daemon.",
        )

    if goal == "auth_check":
        auth = kimi_adapter.check_auth(
            query_or_url, session, binary=kimi_binary, project_dir=project_root, task_id=task_id, goal=goal
        )
        auth_error = ErrorClass.AUTH_REQUIRED if auth.state == "logged_out" else ("unknown" if auth.state == "unknown" else "none")
        record(
            action="auth_check",
            query_or_url=query_or_url,
            status="success" if auth.state == "logged_in" else "failure",
            error_class=auth_error,
            failure_reason=auth.reason,
            raw_capture_path=auth.raw_capture_path,
        )
        status = "completed" if auth.state == "logged_in" else "blocked"
        return RunOutcome(task_id=task_id, status=status, note=f"auth state: {auth.state}")

    nav = kimi_adapter.run_action("navigate", {"url": query_or_url, "newTab": True, "group_title": task_id}, f"research-{task_id}", project_dir=project_root, task_id=task_id, goal=goal)
    record(
        action="navigate",
        query_or_url=query_or_url,
        status="success" if nav.ok else "failure",
        error_class=normalize_kimi_error_class(nav.error_class),
        failure_reason=nav.error_message,
        raw_capture_path=nav.raw_capture_path,
    )
    if not nav.ok:
        return RunOutcome(
            task_id=task_id,
            status="blocked",
            note=f"navigate failed: {nav.error_class}: {nav.error_message[:200]}",
        )
    snapshot = kimi_adapter.run_action("snapshot", {}, f"research-{task_id}", project_dir=project_root, task_id=task_id, goal=goal)
    record(
        action="snapshot",
        query_or_url=query_or_url,
        status="success" if snapshot.ok else "failure",
        error_class=normalize_kimi_error_class(snapshot.error_class),
        failure_reason=snapshot.error_message,
        raw_capture_path=snapshot.raw_capture_path,
    )
    if not snapshot.ok:
        return RunOutcome(
            task_id=task_id,
            status="blocked",
            note=f"snapshot failed: {snapshot.error_class}: {snapshot.error_message[:200]}",
        )
    return RunOutcome(task_id=task_id, status="completed", note="navigate+snapshot ok")
