from __future__ import annotations

"""离线端到端回归：统一采集流程（路由 + 台账 + 状态更新 + 过程机械校验）。

- 构造最小项目（manifest + 冻结政策快照 + 3 轮任务表）；
- mock anysearch（fake CLI + 本地 JSON-RPC 服务器）与 mock kimi bridge；
- 验证：防少搜（不足→FAIL，补满→PASS）、三轮全跑、防假完成（登录墙置 completed→FAIL）、
  台账字段与 raw capture 完整性。
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import now_iso, read_csv, write_csv  # noqa: E402
from collection_quantity_policy import (  # noqa: E402
    MANIFEST_FROZEN_AT_FIELD,
    MANIFEST_SHA256_FIELD,
    MANIFEST_SNAPSHOT_FIELD,
    MANIFEST_VERSION_FIELD,
    freeze_current_policy,
)
from web_collection.journal import CollectionJournal  # noqa: E402
from web_collection.router import TASK_FILE, run_task  # noqa: E402
from validate_collection_attempts import validate as validate_attempts  # noqa: E402

TASK_FIELDS = [
    "task_id", "stage", "platform", "market", "goal_family", "collection_goal",
    "target_brand", "exact_model", "identifier_type", "identifier_value",
    "starting_url_or_query", "required_tool", "output_file", "raw_capture_path",
    "planned_fields", "target_unique_sources", "actual_unique_sources",
    "target_records", "actual_records", "source_type_count", "platform_count",
    "primary_source_count", "coverage_requirement", "critical_claim_count",
    "dual_sourced_claim_count", "remaining_high_priority_count",
    "no_new_high_priority_batches", "count_evidence_refs",
    "platform_limit_evidence", "quantity_exception_type", "quantity_exception_refs",
    "round", "round_goal", "saturation_evidence", "status", "notes",
]

SEARCH_OK = {
    "status": 200,
    "json": {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"total_results": 5, "results": [{"url": f"https://s{i}.example.com"} for i in range(5)]})}
            ]
        }
    },
}
EXTRACT_OK = {
    "status": 200,
    "json": {"result": {"content": [{"type": "text", "text": "# Official Page\n\nCapacity: 5 MWh"}]}},
}

FAKE_CLI_TEMPLATE = '''\
import argparse, json, sys, requests
ENDPOINT = "http://127.0.0.1:{port}"
def _call(tool, arguments):
    payload = {{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {{"name": tool, "arguments": arguments}}}}
    try:
        resp = requests.post(ENDPOINT, json=payload, timeout=10)
    except requests.exceptions.ConnectionError:
        print("Connection Error: Unable to reach the API endpoint.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"HTTP Error: {{resp.status_code}}", file=sys.stderr)
        sys.exit(1)
    data = resp.json()
    if "error" in data:
        print(f"API Error: {{data['error'].get('message', '')}}", file=sys.stderr)
        sys.exit(1)
    content = data.get("result", {{}}).get("content", [])
    for item in content:
        if item.get("type") == "text":
            print(item.get("text", ""))
            return
    print(json.dumps(data.get("result", {{}}), ensure_ascii=False))

p = argparse.ArgumentParser(prog="anysearch")
sub = p.add_subparsers(dest="command", required=True)
s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--max_results", type=int)
e = sub.add_parser("extract"); e.add_argument("--url")
b = sub.add_parser("batch_search"); b.add_argument("--query", action="append")
g = sub.add_parser("get_sub_domains"); g.add_argument("--domain")
args = p.parse_args()
if args.command == "search":
    arguments = {{"query": args.query}}
    if args.max_results is not None: arguments["max_results"] = min(args.max_results, 10)
    _call("search", arguments)
elif args.command == "extract":
    _call("extract", {{"url": args.url}})
elif args.command == "batch_search":
    _call("batch_search", {{"queries": [{{"query": q}} for q in args.query]}})
elif args.command == "get_sub_domains":
    _call("get_sub_domains", {{"domain": args.domain}})
'''


class MockAnySearchServer:
    def __init__(self) -> None:
        self.responses: list[dict] = []
        self.requests_log: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            server_ref = self

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                self.server_ref.requests_log.append(json.loads(self.rfile.read(length).decode("utf-8")))
                response = self.server_ref.responses.pop(0) if self.server_ref.responses else {"status": 500, "json": {"error": {"message": "no mock"}}}
                self.send_response(response.get("status", 200))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response.get("json", {})).encode("utf-8"))

            def log_message(self, *args) -> None:  # noqa: D401
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class MockBridgeServer:
    def __init__(self) -> None:
        self.responses: list[dict] = []
        self.requests_log: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            server_ref = self

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                self.server_ref.requests_log.append(body)
                response = self.server_ref.responses.pop(0) if self.server_ref.responses else {"success": True}
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args) -> None:  # noqa: D401
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def build_project(directory: Path) -> tuple[Path, list[dict[str, str]]]:
    project = Path(directory).resolve()
    project.mkdir(parents=True, exist_ok=True)
    frozen = freeze_current_policy(project, now_iso())
    manifest = {
        "region": "Thailand",
        "category": "Battery Energy Storage",
        "target_markets": ["thailand"],
        "market_model_pairs": [{"market": "thailand", "exact_model": "Fixture BESS-5MWh"}],
        **frozen,
    }
    (project / "project_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def task(task_id: str, rnd: str, rnd_goal: str, tool: str, query: str, target: int) -> dict[str, str]:
        return {
            "task_id": task_id, "stage": "1", "platform": "web", "market": "thailand",
            "goal_family": "market_size_and_demand", "collection_goal": "market_size",
            "target_brand": "Fixture", "exact_model": "BESS-5MWh", "identifier_type": "", "identifier_value": "",
            "starting_url_or_query": query, "required_tool": tool, "output_file": f"out/{task_id}.csv",
            "raw_capture_path": "", "planned_fields": "capacity,price", "target_unique_sources": str(target),
            "actual_unique_sources": "", "target_records": str(target), "actual_records": "",
            "source_type_count": "", "platform_count": "", "primary_source_count": "",
            "coverage_requirement": "family_floor_and_all_high_priority", "critical_claim_count": "",
            "dual_sourced_claim_count": "", "remaining_high_priority_count": "",
            "no_new_high_priority_batches": "", "count_evidence_refs": "", "platform_limit_evidence": "",
            "quantity_exception_type": "", "quantity_exception_refs": "",
            "round": rnd, "round_goal": rnd_goal, "saturation_evidence": "", "status": "planned", "notes": "",
        }

    rows = [
        task("T-R1", "1", "coverage", "anysearch", "Thailand BESS market size 2026", 8),
        task("T-R2", "2", "depth", "anysearch", "https://www.example.com/official-report", 5),
        task("T-R3", "3", "triangulation", "kimi-webbridge", "https://www.example.com/portal", 2),
        task("T-AUTH", "3", "triangulation", "kimi-webbridge", "https://portal.example.com/secure", 2),
    ]
    write_csv(project / TASK_FILE, TASK_FIELDS, rows)
    return project, rows


def run_search_task(project: Path, task_row: dict[str, str], journal: CollectionJournal, fake_cli: Path, times: int) -> None:
    for _ in range(times):
        run_task(project, task_row, journal=journal, official_cli=fake_cli, allow_kimi=False)


def test_under_collection_blocked_then_saturated() -> None:
    server = MockAnySearchServer()
    try:
        with tempfile.TemporaryDirectory(prefix="wc_reg_") as tmp:
            fake_dir = Path(tempfile.mkdtemp(prefix="wc_cli_"))
            fake_cli = fake_dir / "fake_anysearch_cli.py"
            fake_cli.write_text(FAKE_CLI_TEMPLATE.format(port=server.port), encoding="utf-8")
            project, rows = build_project(tmp)
            journal = CollectionJournal(project)
            r1 = next(row for row in rows if row["task_id"] == "T-R1")

            # 只跑 1 次（少于 target=8 / policy floor=8）→ 防少搜 FAIL
            server.responses.append(SEARCH_OK)
            run_search_task(project, r1, journal, fake_cli, 1)
            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            r1_fails = [issue for issue in issues if issue.level == "fail" and "T-R1" in issue.message]
            if not any("below minimum" in issue.message for issue in r1_fails):
                raise AssertionError(f"under-collection must FAIL with 'below minimum', got: {[i.message for i in r1_fails]}")

            # 补满 8 次 → T-R1 不再有 fail（其他任务轮次未跑属预期，由 test 2 覆盖）
            server.responses.extend([SEARCH_OK] * 7)
            run_search_task(project, r1, journal, fake_cli, 7)
            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            r1_fails = [issue for issue in issues if issue.level == "fail" and "T-R1" in issue.message]
            if r1_fails:
                raise AssertionError(f"saturated R1 must pass, got fails: {[i.message for i in r1_fails]}")
            rows_after = journal.load()
            r1_attempts = [row for row in rows_after if row["task_id"] == "T-R1"]
            if len(r1_attempts) != 8:
                raise AssertionError(f"expected 8 R1 attempts, got {len(r1_attempts)}")
            if len({row["attempt_id"] for row in rows_after}) != len(rows_after):
                raise AssertionError("attempt_id uniqueness violated (same-second collision)")
            if not all(row["raw_capture_path"] for row in r1_attempts if row["status"] == "success"):
                raise AssertionError("success attempts must carry raw_capture_path")
        print("  [1/4] anti-under-collection (1 attempt → FAIL, 8 attempts → PASS, unique ids, captures): PASS")
    finally:
        server.close()


def test_full_three_rounds_and_status_updates() -> None:
    server = MockAnySearchServer()
    bridge = MockBridgeServer()
    import _kimi_webbridge as kimi

    kimi.BRIDGE_URL = f"http://127.0.0.1:{bridge.port}/command"
    healthy = mock.patch(
        "web_collection.kimi_adapter.check_health",
        return_value=__import__("web_collection.kimi_adapter", fromlist=["BridgeHealth"]).BridgeHealth(
            True, {"running": True, "extension_connected": True}, "none", ""
        ),
    )
    try:
        with tempfile.TemporaryDirectory(prefix="wc_reg_") as tmp:
            fake_dir = Path(tempfile.mkdtemp(prefix="wc_cli_"))
            fake_cli = fake_dir / "fake_anysearch_cli.py"
            fake_cli.write_text(FAKE_CLI_TEMPLATE.format(port=server.port), encoding="utf-8")
            project, rows = build_project(tmp)
            journal = CollectionJournal(project)

            # R1 已在前一测试独立验证；这里直接补满三轮
            server.responses.extend([SEARCH_OK] * 8)
            run_search_task(project, next(r for r in rows if r["task_id"] == "T-R1"), journal, fake_cli, 8)
            server.responses.extend([EXTRACT_OK] * 5)
            run_search_task(project, next(r for r in rows if r["task_id"] == "T-R2"), journal, fake_cli, 5)

            # R3 kimi：navigate+snapshot 成功（T-R3 两轮 + T-AUTH 一次成功；真实信封格式）
            bridge.responses.extend(
                [
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                ]
            )
            with healthy:
                for _ in range(2):
                    run_task(project, next(r for r in rows if r["task_id"] == "T-R3"), journal=journal)
                run_task(project, next(r for r in rows if r["task_id"] == "T-AUTH"), journal=journal)

            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            fails = [issue for issue in issues if issue.level == "fail"]
            if fails:
                raise AssertionError(f"full three rounds must pass, got: {[i.message for i in fails]}")

            # 02 CSV 状态更新为 completed
            _, task_rows = read_csv(project / TASK_FILE)
            for task in task_rows:
                if task["task_id"] in {"T-R1", "T-R2", "T-R3", "T-AUTH"}:
                    if task["status"] != "completed":
                        raise AssertionError(f"{task['task_id']} status should be completed, got {task['status']}")

            # journal 汇总（R1=8, R2=5, T-R3=2次run_task×2条=4, T-AUTH=1次×2条=2 → 19）
            summary = journal.summary()
            if summary["attempt_count"] != 8 + 5 + 4 + 2:
                raise AssertionError(f"unexpected attempt count: {summary['attempt_count']}")
        print("  [2/4] full R1/R2/R3 flow (anysearch + kimi + status updates + journal summary): PASS")
    finally:
        healthy.stop()
        kimi.BRIDGE_URL = "http://127.0.0.1:10086/command"
        server.close()
        bridge.close()


def test_fake_completion_blocked() -> None:
    bridge = MockBridgeServer()
    import _kimi_webbridge as kimi

    kimi.BRIDGE_URL = f"http://127.0.0.1:{bridge.port}/command"
    healthy = mock.patch(
        "web_collection.kimi_adapter.check_health",
        return_value=__import__("web_collection.kimi_adapter", fromlist=["BridgeHealth"]).BridgeHealth(
            True, {"running": True, "extension_connected": True}, "none", ""
        ),
    )
    try:
        with tempfile.TemporaryDirectory(prefix="wc_reg_") as tmp:
            project, rows = build_project(tmp)
            journal = CollectionJournal(project)
            auth_row = next(row for row in rows if row["task_id"] == "T-AUTH")

            # 登录墙：navigate 失败（信封格式，access_authentication）
            bridge.responses.append({"ok": True, "data": {"success": False, "message": "Please log in to continue"}})
            with healthy:
                outcome = run_task(project, auth_row, journal=journal)
            if outcome.status != "blocked":
                raise AssertionError(f"login-wall task must be blocked, got {outcome.status}")
            if outcome.attempts[0]["error_class"] != "auth_required":
                raise AssertionError(f"journal must record normalized auth_required, got {outcome.attempts[0]['error_class']}")

            # 模拟 Agent 造假：把 blocked 改成 completed → 防假完成 FAIL（聚焦 T-AUTH 消息）
            _, task_rows = read_csv(project / TASK_FILE)
            for task in task_rows:
                if task["task_id"] == "T-AUTH":
                    task["status"] = "completed"
            write_csv(project / TASK_FILE, TASK_FIELDS, task_rows)
            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            auth_fails = [issue for issue in issues if issue.level == "fail" and "T-AUTH" in issue.message]
            if not any("unresolved blocking" in issue.message or "fake completion" in issue.message for issue in auth_fails):
                raise AssertionError(f"fake completion must FAIL, got T-AUTH fails: {[i.message for i in auth_fails]}")

            # 改回 blocked → T-AUTH 不再有防假完成类 fail（其他任务未跑属预期）
            _, task_rows = read_csv(project / TASK_FILE)
            for task in task_rows:
                if task["task_id"] == "T-AUTH":
                    task["status"] = "blocked"
            write_csv(project / TASK_FILE, TASK_FIELDS, task_rows)
            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            auth_fails = [issue for issue in issues if issue.level == "fail" and "T-AUTH" in issue.message]
            if any("unresolved blocking" in issue.message for issue in auth_fails):
                raise AssertionError(f"blocked status must not trigger fake-completion fail: {[i.message for i in auth_fails]}")
        print("  [3/4] anti-fake-completion (login wall → blocked; forged completed → FAIL): PASS")
    finally:
        healthy.stop()
        kimi.BRIDGE_URL = "http://127.0.0.1:10086/command"
        bridge.close()


def test_http_fetch_fallback_and_ledger_imports() -> None:
    from web_collection.http_fetch import _is_login_wall, _html_to_markdown

    if not _is_login_wall("Please log in to view this page"):
        raise AssertionError("login wall detection failed")
    if _is_login_wall("Full market report with 10 tables"):
        raise AssertionError("false positive login wall")
    markdown = _html_to_markdown("<html><head><title>T</title></head><body><h1>H</h1><p>Body text.</p></body></html>")
    if "H" not in markdown or "Body text." not in markdown:
        raise AssertionError(f"html→markdown conversion broken: {markdown}")
    print("  [4/4] http_fetch helpers (login wall detection + markdown conversion): PASS")


def test_http_fetch_fallback_capture() -> None:
    """anysearch extract 失败 → http_fetch 回退成功 → 内容落盘 → validate PASS。"""
    from web_collection import http_fetch as fetch_module
    from web_collection.anysearch_backend import run_extract as backend_extract

    server = MockAnySearchServer()
    bridge = MockBridgeServer()
    import _kimi_webbridge as kimi

    kimi.BRIDGE_URL = f"http://127.0.0.1:{bridge.port}/command"
    healthy = mock.patch(
        "web_collection.kimi_adapter.check_health",
        return_value=__import__("web_collection.kimi_adapter", fromlist=["BridgeHealth"]).BridgeHealth(
            True, {"running": True, "extension_connected": True}, "none", ""
        ),
    )
    try:
        with tempfile.TemporaryDirectory(prefix="wc_reg_") as tmp:
            fake_dir = Path(tempfile.mkdtemp(prefix="wc_cli_"))
            fake_cli = fake_dir / "fake_anysearch_cli.py"
            fake_cli.write_text(FAKE_CLI_TEMPLATE.format(port=server.port), encoding="utf-8")
            project, rows = build_project(tmp)
            journal = CollectionJournal(project)

            # R1 补满 + R2 走 extract 失败→http_fetch 回退
            server.responses.extend([SEARCH_OK] * 8)
            run_search_task(project, next(r for r in rows if r["task_id"] == "T-R1"), journal, fake_cli, 8)

            fake_response = type(
                "R", (),
                {
                    "status_code": 200,
                    "headers": {"Content-Type": "text/html; charset=utf-8"},
                    "text": "<html><head><title>Official Report</title></head><body><h1>Grid Plan 2026</h1><p>Capacity target: 500 MW by 2030.</p></body></html>",
                },
            )()
            r2 = next(row for row in rows if row["task_id"] == "T-R2")
            with mock.patch.object(fetch_module.requests, "get", return_value=fake_response):
                # extract 失败（404）→ http_fetch 回退
                server.responses.append({"status": 404, "json": {}})
                for _ in range(5):
                    run_task(project, r2, journal=journal, official_cli=fake_cli, allow_kimi=False)

            # journal 中 http_fetch 行必须有存在的 raw_capture（markdown + 原始 HTML 双留痕）
            journal_rows = journal.load()
            fallback_rows = [row for row in journal_rows if row["action"] == "http_fetch"]
            if not fallback_rows:
                raise AssertionError("http_fetch fallback attempts must be journaled")
            if not all(row["status"] == "success" and row["raw_capture_path"] for row in fallback_rows):
                raise AssertionError("http_fetch success rows must carry raw_capture_path")
            capture = project / fallback_rows[0]["raw_capture_path"]
            if not capture.is_file():
                raise AssertionError(f"http_fetch capture missing: {capture}")
            content = capture.read_text(encoding="utf-8")
            if "Capacity target: 500 MW" not in content:
                raise AssertionError("http_fetch capture must contain converted markdown content")
            raw_captures = list((project / "raw_capture" / "market_size").glob("T-R2_http_fetch_*_raw.html"))
            if not raw_captures or "Grid Plan 2026" not in raw_captures[0].read_text(encoding="utf-8"):
                raise AssertionError("http_fetch raw HTML must be retained for traceability")

            # validate PASS（所有任务轮次都有 attempt 与 raw_capture）
            bridge.responses.extend(
                [
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                    {"ok": True, "data": {"success": True, "url": "https://www.example.com/portal", "tabId": "t1"}},
                    {"ok": True, "data": {"url": "https://www.example.com/portal", "title": "Portal", "tree": [{"role": "paragraph", "name": "Grid statistics 2026"}]}},
                ]
            )
            with healthy:
                for _ in range(2):
                    run_task(project, next(r for r in rows if r["task_id"] == "T-R3"), journal=journal)
                run_task(project, next(r for r in rows if r["task_id"] == "T-AUTH"), journal=journal)
            issues = validate_attempts(project / "13_Collection_Attempt_Journal.csv")
            fails = [issue for issue in issues if issue.level == "fail"]
            if fails:
                raise AssertionError(f"fallback flow must pass validation, got: {[i.message for i in fails]}")
        print("  [5/5] http_fetch fallback capture (extract 404 → fetch ok → md+html traceable → validate PASS): PASS")
    finally:
        healthy.stop()
        kimi.BRIDGE_URL = "http://127.0.0.1:10086/command"
        server.close()
        bridge.close()


def main() -> int:
    print("Web collection end-to-end regression:")
    test_under_collection_blocked_then_saturated()
    test_full_three_rounds_and_status_updates()
    test_fake_completion_blocked()
    test_http_fetch_fallback_and_ledger_imports()
    test_http_fetch_fallback_capture()
    print("Web collection end-to-end regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
