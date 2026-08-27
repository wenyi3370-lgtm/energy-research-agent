"""联网采集统一 CLI。

用法示例：
  python scripts/web_collection/cli.py doctor
  python scripts/web_collection/cli.py search "Thailand BEV sales 2025" --project-dir . --task-id T1
  python scripts/web_collection/cli.py extract <url> --project-dir . --task-id T2 --goal policy
  python scripts/web_collection/cli.py batch-search --query q1 --query q2 --project-dir . --task-id T3
  python scripts/web_collection/cli.py browse <url> --session research --project-dir . --task-id T4
  python scripts/web_collection/cli.py auth-check <url> --session research --project-dir . --task-id T5
  python scripts/web_collection/cli.py journal-summary --project-dir .
所有命令输出统一 JSON（便于主代理处理）；search/extract/browse 自动写采集台账与原始捕获。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接运行 python web_collection/cli.py（scripts/ 下既有脚本都依赖 _common 等顶层模块）
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from web_collection import kimi_adapter
from web_collection.anysearch_backend import (
    embedded_cli_sha256,
    official_cli_path,
    run_batch_search,
    run_extract,
    run_get_sub_domains,
    run_search,
)
from web_collection.errors import normalize_kimi_error_class
from web_collection.journal import CollectionJournal

from _common import now_iso  # noqa: E402
from _kimi_webbridge import default_bridge_binary, daemon_logs, get_status  # noqa: E402


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _modeling_chain_sync() -> dict[str, object]:
    """建模链 24 文档（+ math-figure-generator 3 个 references 附件）与官方源哈希对比。"""
    import hashlib

    chain_dir = Path(__file__).resolve().parents[2] / "references" / "modeling_chain"
    comparisons: list[tuple[Path, Path]] = []  # (embedded, official)
    for path in sorted(chain_dir.glob("*.md")):
        if path.name == "README_embedded.md":
            continue
        name = path.name[:-3]
        comparisons.append((path, Path.home() / ".claude" / "skills" / name / "SKILL.md"))
    # math-figure-generator 附件（官方子目录 references/）
    for filename in ("chart-patterns.md", "color-systems.md", "layout-guide.md"):
        comparisons.append(
            (
                chain_dir / "references" / filename,
                Path.home() / ".claude" / "skills" / "math-figure-generator" / "references" / filename,
            )
        )
    out_of_sync: list[str] = []
    checked = 0
    official_missing: list[str] = []
    for embedded, official in comparisons:
        if not official.is_file():
            official_missing.append(embedded.name)
            continue
        checked += 1
        if hashlib.sha256(embedded.read_bytes()).hexdigest() != hashlib.sha256(official.read_bytes()).hexdigest():
            out_of_sync.append(embedded.name)
    return {
        "embedded_dir": str(chain_dir),
        "documents_checked": checked,
        "official_missing_optional": official_missing,
        "out_of_sync": out_of_sync,  # 空列表 = in_sync
        "action": "re-copy changed docs from official skills (zero diff)" if out_of_sync else "no action",
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: dict[str, object] = {}
    # 1. anysearch 内嵌 CLI
    embedded = embedded_cli_sha256()
    checks["anysearch_embedded_cli"] = "present" if embedded else "MISSING"
    checks["anysearch_embedded_cli_sha256"] = embedded
    official = official_cli_path(args.official_cli)
    if official is not None:
        import hashlib

        checks["anysearch_official_cli"] = str(official)
        checks["anysearch_official_cli_sha256"] = hashlib.sha256(official.read_bytes()).hexdigest()
        checks["anysearch_sync"] = "in_sync" if embedded and embedded == checks["anysearch_official_cli_sha256"] else "OUT_OF_SYNC (re-copy from official skill)"
    else:
        checks["anysearch_official_cli"] = "not installed (optional)"
    # 2. kimi-webbridge daemon + 插件
    binary = default_bridge_binary()
    checks["kimi_bridge_binary"] = str(binary) if binary.exists() else "MISSING (~/.kimi-webbridge/bin/)"
    if binary.exists():
        try:
            status = get_status(binary)
            checks["kimi_status"] = status
            checks["kimi_ready"] = bool(status.get("running") and status.get("extension_connected"))
            if not status.get("extension_connected"):
                checks["kimi_action"] = "open the browser with the Kimi WebBridge extension enabled (https://www.kimi.com/zh-cn/features/webbridge)"
        except Exception as exc:  # noqa: BLE001
            checks["kimi_status"] = {"error": str(exc)}
            checks["kimi_ready"] = False
    # 3. 依赖
    import importlib.util

    checks["dependencies"] = {
        module: bool(importlib.util.find_spec(module))
        for module in ("requests", "bs4", "markitdown", "yaml")
    }
    # 4. 建模链文档与官方源同步（差异 1：版本冻结的同步机制）
    checks["modeling_chain_sync"] = _modeling_chain_sync()
    # 5. 台账
    project = Path(args.project_dir or ".").resolve()
    journal = CollectionJournal(project)
    checks["journal"] = {"path": journal.path.name, "rows": len(journal.load())}
    checks["checked_at"] = now_iso()
    _emit({"doctor": checks})
    # doctor 只做诊断：任何环境状态都返回 0（调用方读 JSON 判断）
    return 0


def _journal(project_dir: str) -> CollectionJournal:
    return CollectionJournal(Path(project_dir or ".").resolve())


def cmd_search(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    result = run_search(
        args.query,
        project_dir=Path(args.project_dir or ".").resolve(),
        task_id=args.task_id or "adhoc",
        goal=args.goal,
        max_results=args.max_results,
        domain=args.domain,
        sub_domain=args.sub_domain,
        sdp=args.sdp,
        official_cli=args.official_cli,
    )
    journal.append(
        task_id=args.task_id or "adhoc",
        round_number=args.round,
        round_goal=args.round_goal,
        tool="anysearch",
        action="search",
        query_or_url=args.query,
        status="success" if result.ok else "failure",
        error_class=result.error_class,
        failure_reason=result.error_message,
        candidates_found=result.candidates_found,
        raw_capture_path=result.raw_capture_path,
    )
    _emit(
        {
            "command": "search",
            "ok": result.ok,
            "candidates_found": result.candidates_found,
            "raw_capture_path": result.raw_capture_path,
            "cli_used": result.cli_used,
            "attempts": result.attempts,
            "error_class": result.error_class if not result.ok else None,
            "error_message": result.error_message if not result.ok else None,
            "stdout": result.stdout[:2000],
        }
    )
    return 0 if result.ok else 1


def cmd_extract(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    result = run_extract(
        args.url,
        project_dir=Path(args.project_dir or ".").resolve(),
        task_id=args.task_id or "adhoc",
        goal=args.goal,
        official_cli=args.official_cli,
    )
    journal.append(
        task_id=args.task_id or "adhoc",
        round_number=args.round,
        round_goal=args.round_goal,
        tool="anysearch",
        action="extract",
        query_or_url=args.url,
        status="success" if result.ok else "failure",
        error_class=result.error_class,
        failure_reason=result.error_message,
        raw_capture_path=result.raw_capture_path,
    )
    _emit(
        {
            "command": "extract",
            "ok": result.ok,
            "raw_capture_path": result.raw_capture_path,
            "cli_used": result.cli_used,
            "attempts": result.attempts,
            "error_class": result.error_class if not result.ok else None,
            "error_message": result.error_message if not result.ok else None,
        }
    )
    return 0 if result.ok else 1


def cmd_batch_search(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    result = run_batch_search(
        args.query,
        project_dir=Path(args.project_dir or ".").resolve(),
        task_id=args.task_id or "adhoc",
        goal=args.goal,
        max_results=args.max_results,
        domain=args.domain,
        sub_domain=args.sub_domain,
        sdp=args.sdp,
        official_cli=args.official_cli,
    )
    journal.append(
        task_id=args.task_id or "adhoc",
        round_number=args.round,
        round_goal=args.round_goal,
        tool="anysearch",
        action="batch_search",
        query_or_url=" | ".join(args.query),
        status="success" if result.ok else "failure",
        error_class=result.error_class,
        failure_reason=result.error_message,
        raw_capture_path=result.raw_capture_path,
    )
    _emit(
        {
            "command": "batch_search",
            "ok": result.ok,
            "queries": len(args.query),
            "raw_capture_path": result.raw_capture_path,
            "cli_used": result.cli_used,
            "attempts": result.attempts,
            "error_class": result.error_class if not result.ok else None,
            "error_message": result.error_message if not result.ok else None,
        }
    )
    return 0 if result.ok else 1


def cmd_browse(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    project = Path(args.project_dir or ".").resolve()
    if args.action == "snapshot":
        nav = kimi_adapter.run_action("navigate", {"url": args.url, "newTab": True, "group_title": args.group_title or "research"}, args.session, project_dir=project, task_id=args.task_id or "adhoc", goal=args.goal)
        journal.append(task_id=args.task_id or "adhoc", round_number=args.round, round_goal=args.round_goal, tool="kimi-webbridge", action="navigate", query_or_url=args.url, status="success" if nav.ok else "failure", error_class=normalize_kimi_error_class(nav.error_class), failure_reason=nav.error_message, raw_capture_path=nav.raw_capture_path, session=args.session)
        if not nav.ok:
            _emit({"command": "browse", "ok": False, "error_class": nav.error_class, "error_message": nav.error_message})
            return 1
        shot = kimi_adapter.run_action("snapshot", {}, args.session, project_dir=project, task_id=args.task_id or "adhoc", goal=args.goal)
        journal.append(task_id=args.task_id or "adhoc", round_number=args.round, round_goal=args.round_goal, tool="kimi-webbridge", action="snapshot", query_or_url=args.url, status="success" if shot.ok else "failure", error_class=normalize_kimi_error_class(shot.error_class), failure_reason=shot.error_message, raw_capture_path=shot.raw_capture_path, session=args.session)
        _emit({"command": "browse", "ok": shot.ok, "action": "snapshot", "raw_capture_path": shot.raw_capture_path, "error_class": shot.error_class if not shot.ok else None, "error_message": shot.error_message if not shot.ok else None})
        return 0 if shot.ok else 1
    if args.action == "screenshot":
        shot = kimi_adapter.run_action("screenshot", {"path": args.output or ""} if args.output else {}, args.session, project_dir=project, task_id=args.task_id or "adhoc", goal=args.goal)
        journal.append(task_id=args.task_id or "adhoc", round_number=args.round, round_goal=args.round_goal, tool="kimi-webbridge", action="screenshot", query_or_url=args.url, status="success" if shot.ok else "failure", error_class=normalize_kimi_error_class(shot.error_class), failure_reason=shot.error_message, raw_capture_path=shot.raw_capture_path, session=args.session)
        _emit({"command": "browse", "ok": shot.ok, "action": "screenshot", "result": shot.result, "error_class": shot.error_class if not shot.ok else None, "error_message": shot.error_message if not shot.ok else None})
        return 0 if shot.ok else 1
    if args.action == "pdf":
        shot = kimi_adapter.run_action("save_as_pdf", {"path": args.output or ""} if args.output else {}, args.session, project_dir=project, task_id=args.task_id or "adhoc", goal=args.goal)
        journal.append(task_id=args.task_id or "adhoc", round_number=args.round, round_goal=args.round_goal, tool="kimi-webbridge", action="save_as_pdf", query_or_url=args.url, status="success" if shot.ok else "failure", error_class=normalize_kimi_error_class(shot.error_class), failure_reason=shot.error_message, raw_capture_path=shot.raw_capture_path, session=args.session)
        _emit({"command": "browse", "ok": shot.ok, "action": "pdf", "result": shot.result, "error_class": shot.error_class if not shot.ok else None, "error_message": shot.error_message if not shot.ok else None})
        return 0 if shot.ok else 1
    _emit({"command": "browse", "ok": False, "error_message": f"unknown browse action: {args.action}"})
    return 1


def cmd_auth_check(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    auth = kimi_adapter.check_auth(
        args.url, args.session, project_dir=Path(args.project_dir or ".").resolve(),
        task_id=args.task_id or "adhoc", goal=args.goal,
    )
    auth_error = "auth_required" if auth.state == "logged_out" else ("unknown" if auth.state == "unknown" else "none")
    journal.append(
        task_id=args.task_id or "adhoc",
        round_number=args.round,
        round_goal=args.round_goal,
        tool="kimi-webbridge",
        action="auth_check",
        query_or_url=args.url,
        status="success" if auth.state == "logged_in" else "failure",
        error_class=auth_error,
        failure_reason=auth.reason,
        raw_capture_path=auth.raw_capture_path,
        session=args.session,
    )
    _emit({"command": "auth-check", "state": auth.state, "reason": auth.reason, "raw_capture_path": auth.raw_capture_path})
    return 0 if auth.state == "logged_in" else 1


def cmd_journal_summary(args: argparse.Namespace) -> int:
    journal = _journal(args.project_dir)
    _emit(journal.summary())
    return 0


def _add_common_subargs(sub: argparse.ArgumentParser) -> None:
    """每个子命令都接受 --project-dir/--official-cli（用户直觉把选项写在子命令后）。"""
    sub.add_argument("--project-dir", default=".", help="项目目录（写台账/raw_capture 的根）")
    sub.add_argument("--official-cli", default=None, help="显式指定官方 anysearch CLI 路径（双路径兜底）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="web-collection", description="统一联网采集 CLI（anysearch 透传 + kimi-webbridge 编排 + 采集台账）")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_p = sub.add_parser("doctor", help="环境体检（CLI/哈希同步/插件/依赖/台账）")
    _add_common_subargs(doctor_p)
    doctor_p.set_defaults(func=cmd_doctor)

    search_p = sub.add_parser("search", help="anysearch 搜索")
    _add_common_subargs(search_p)
    search_p.add_argument("query")
    search_p.add_argument("--max-results", type=int)
    search_p.add_argument("--domain")
    search_p.add_argument("--sub-domain")
    search_p.add_argument("--sdp")
    search_p.add_argument("--goal", default="general")
    search_p.add_argument("--task-id")
    search_p.add_argument("--round", default="")
    search_p.add_argument("--round-goal", default="")
    search_p.set_defaults(func=cmd_search)

    extract_p = sub.add_parser("extract", help="anysearch 网页正文提取（Markdown）")
    _add_common_subargs(extract_p)
    extract_p.add_argument("url")
    extract_p.add_argument("--goal", default="general")
    extract_p.add_argument("--task-id")
    extract_p.add_argument("--round", default="")
    extract_p.add_argument("--round-goal", default="")
    extract_p.set_defaults(func=cmd_extract)

    batch_p = sub.add_parser("batch-search", help="anysearch 批量搜索（≤5）")
    _add_common_subargs(batch_p)
    batch_p.add_argument("--query", action="append", required=True)
    batch_p.add_argument("--max-results", type=int)
    batch_p.add_argument("--domain")
    batch_p.add_argument("--sub-domain")
    batch_p.add_argument("--sdp")
    batch_p.add_argument("--goal", default="general")
    batch_p.add_argument("--task-id")
    batch_p.add_argument("--round", default="")
    batch_p.add_argument("--round-goal", default="")
    batch_p.set_defaults(func=cmd_batch_search)

    browse_p = sub.add_parser("browse", help="kimi-webbridge 浏览器动作（snapshot/screenshot/pdf）")
    _add_common_subargs(browse_p)
    browse_p.add_argument("url")
    browse_p.add_argument("--session", required=True)
    browse_p.add_argument("--action", choices=["snapshot", "screenshot", "pdf"], default="snapshot")
    browse_p.add_argument("--output", help="screenshot/pdf 输出路径")
    browse_p.add_argument("--group-title")
    browse_p.add_argument("--goal", default="general")
    browse_p.add_argument("--task-id")
    browse_p.add_argument("--round", default="")
    browse_p.add_argument("--round-goal", default="")
    browse_p.set_defaults(func=cmd_browse)

    auth_p = sub.add_parser("auth-check", help="kimi-webbridge 登录态检查")
    _add_common_subargs(auth_p)
    auth_p.add_argument("url")
    auth_p.add_argument("--session", required=True)
    auth_p.add_argument("--task-id")
    auth_p.add_argument("--round", default="")
    auth_p.add_argument("--round-goal", default="")
    auth_p.add_argument("--goal", default="general")
    auth_p.set_defaults(func=cmd_auth_check)

    journal_p = sub.add_parser("journal-summary", help="台账统计")
    _add_common_subargs(journal_p)
    journal_p.set_defaults(func=cmd_journal_summary)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
