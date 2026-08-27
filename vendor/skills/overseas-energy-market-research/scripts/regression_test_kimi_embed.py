from __future__ import annotations

"""离线回归：kimi-webbridge 内嵌客户端（官方契约一致 + 生命周期 + 登录态 + 故障分类）。

- mock bridge 服务器记录请求，断言请求 body 与官方 SKILL.md curl 示例逐字段一致；
- 不碰真实 daemon / 浏览器（check_health 的二进制执行路径用 mock.patch 注入）。
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

import _kimi_webbridge as kimi  # noqa: E402
from web_collection import kimi_adapter  # noqa: E402

OFFICIAL_CURL_EXAMPLE = {
    "action": "navigate",
    "args": {"url": "https://example.com", "newTab": True, "group_title": "My task"},
    "session": "my-task",
}


class MockBridgeServer:
    """本地 mock bridge：记录收到的 command 请求，按队列返回响应。"""

    def __init__(self) -> None:
        self.requests_log: list[dict] = []
        self.responses: list[dict] = []

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


def _attach_bridge(server: MockBridgeServer) -> None:
    kimi.BRIDGE_URL = f"http://127.0.0.1:{server.port}/command"


def _detach_bridge() -> None:
    kimi.BRIDGE_URL = "http://127.0.0.1:10086/command"


def test_action_contract() -> None:
    if set(kimi.ACTION_CONTRACT) != {
        "navigate", "find_tab", "snapshot", "click", "fill", "evaluate",
        "screenshot", "network", "upload", "save_as_pdf", "list_tabs",
        "close_tab", "close_session",
    }:
        raise AssertionError(f"ACTION_CONTRACT must cover all 13 official actions: {sorted(kimi.ACTION_CONTRACT)}")
    if kimi.validate_action_args("fill", {"selector": "@e1"}):
        pass
    else:
        raise AssertionError("fill without value must be rejected")
    if kimi.validate_action_args("fill", {"selector": "@e1", "value": "x"}):
        raise AssertionError("fill with value must pass")
    if not kimi.validate_action_args("unknown_action", {}):
        raise AssertionError("unknown action must be rejected")
    print("  [1/7] action contract (13 actions + required-arg validation): PASS")


def test_command_payload_matches_official() -> None:
    server = MockBridgeServer()
    _attach_bridge(server)
    try:
        # navigate：请求 body 与官方 curl 示例逐字段一致；响应用真实 daemon 信封格式
        server.responses.append({"ok": True, "data": {"success": True, "url": "https://example.com", "tabId": "t1"}})
        result = kimi_adapter.run_action(
            "navigate", {"url": "https://example.com", "newTab": True, "group_title": "My task"},
            "my-task", timeout=10,
        )
        if not result.ok:
            raise AssertionError(f"navigate should succeed: {result.error_message}")
        sent = server.requests_log[0]
        expected = dict(OFFICIAL_CURL_EXAMPLE)
        if sent != expected:
            raise AssertionError(f"navigate payload must match official curl example field-by-field:\n sent={sent}\n expected={expected}")

        # snapshot：信封格式 + 真实树结构（role/name/children）
        server.responses.append(
            {
                "ok": True,
                "data": {
                    "url": "https://example.com",
                    "title": "Example Domain",
                    "tree": [{"role": "heading", "name": "Example Domain"}, {"role": "paragraph", "name": "This domain is for documentation."}],
                },
            }
        )
        result = kimi_adapter.run_action("snapshot", {}, "my-task", timeout=10)
        if not result.ok:
            raise AssertionError(f"snapshot should succeed: {result.error_message}")
        sent = server.requests_log[1]
        if sent != {"action": "snapshot", "args": {}, "session": "my-task"}:
            raise AssertionError(f"snapshot payload mismatch: {sent}")

        # screenshot：path 语义透传（信封格式；result 保留原始信封，data 为解包内容）
        server.responses.append({"ok": True, "data": {"format": "png", "path": "C:/tmp/shot.png", "sizeBytes": 100, "mimeType": "image/png"}})
        result = kimi_adapter.run_action("screenshot", {"path": "C:/tmp/shot.png"}, "my-task", timeout=10)
        sent = server.requests_log[2]
        if sent["args"] != {"path": "C:/tmp/shot.png"}:
            raise AssertionError(f"screenshot args mismatch: {sent['args']}")
        if result.result.get("data", {}).get("path") != "C:/tmp/shot.png":
            raise AssertionError(f"screenshot result path must pass through: {result.result}")

        # 双格式兼容：官方文档示例（顶层 success 字段）也必须被 unwrap 接受
        ok, payload = kimi_adapter.unwrap_result({"success": True, "url": "https://x", "tabId": "t"})
        if not ok or payload.get("url") != "https://x":
            raise AssertionError("documentation-format response must be unwrapped too")
        ok, payload = kimi_adapter.unwrap_result({"ok": True, "data": {"success": True, "url": "https://x", "tabId": "t"}})
        if not ok or payload.get("url") != "https://x":
            raise AssertionError("envelope-format response must be unwrapped")
        ok, payload = kimi_adapter.unwrap_result({"ok": False, "data": {"error": "boom"}})
        if ok:
            raise AssertionError("envelope ok=false must be treated as failure")
        if kimi_adapter.extract_tree_text([{"role": "heading", "name": "A", "children": [{"role": "StaticText", "name": "B"}]}]) != "A B":
            raise AssertionError("tree text extraction must recurse names")
        print("  [2/7] payload field-for-field identical + envelope unwrap (real v1.11 format) + tree text: PASS")
    finally:
        _detach_bridge()
        server.close()


def test_session_consistency() -> None:
    server = MockBridgeServer()
    _attach_bridge(server)
    try:
        for _ in range(3):
            server.responses.append({"success": True, "url": "https://a.com", "tabId": "t"})
            kimi_adapter.run_action("navigate", {"url": "https://a.com"}, "research-T1", timeout=10)
        for request in server.requests_log:
            if request["session"] != "research-t1":
                raise AssertionError(f"session must stay stable within a task (normalized): {request}")
        if kimi.normalize_session("Research   T1") != "research-t1":
            raise AssertionError("normalize_session must normalize to stable lowercase id")
        try:
            kimi.normalize_session("")
            raise AssertionError("empty session must be rejected")
        except ValueError:
            pass
        print("  [3/7] session consistency (one task = one session) + normalize: PASS")
    finally:
        _detach_bridge()
        server.close()


def test_health_classification() -> None:
    # binary 不存在 → not_installed
    missing = Path(tempfile.gettempdir()) / "no-such-webbridge-bin.exe"
    health = kimi_adapter.check_health(missing, auto_start=False)
    if health.healthy or health.failure_class != "not_installed":
        raise AssertionError(f"missing binary must classify as not_installed: {health.failure_class}")

    # 存在但不响应的 fake binary（_run_cli 被 mock，只验证分类逻辑）
    fake_binary = Path(tempfile.mkdtemp(prefix="kimi_reg_")) / "kimi-webbridge"
    fake_binary.write_text("", encoding="utf-8")

    def completed(stdout: str):
        return type("C", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    # daemon 未运行
    with mock.patch("_kimi_webbridge._run_cli", return_value=completed('{"running": false}')):
        health = kimi_adapter.check_health(fake_binary, auto_start=False)
        if health.healthy or health.failure_class != "daemon_stopped":
            raise AssertionError(f"stopped daemon must classify as daemon_stopped: {health.failure_class}")

    # 插件未连接
    with mock.patch("_kimi_webbridge._run_cli", return_value=completed('{"running": true, "extension_connected": false}')):
        health = kimi_adapter.check_health(fake_binary, auto_start=False)
        if health.healthy or health.failure_class != "extension_disconnected":
            raise AssertionError(f"disconnected extension must classify as extension_disconnected: {health.failure_class}")

    # 健康
    with mock.patch("_kimi_webbridge._run_cli", return_value=completed('{"running": true, "extension_connected": true}')):
        health = kimi_adapter.check_health(fake_binary, auto_start=False)
        if not health.healthy:
            raise AssertionError("healthy bridge must pass the hard gate")
    print("  [4/7] health classification (not_installed/daemon_stopped/extension_disconnected/healthy): PASS")


def test_failure_classification() -> None:
    server = MockBridgeServer()
    _attach_bridge(server)
    try:
        # 版本不匹配（信封格式）
        server.responses.append({"ok": False, "data": {"error": "Please update the Kimi WebBridge extension"}})
        result = kimi_adapter.run_action("navigate", {"url": "https://x.com"}, "s", timeout=10)
        if result.ok or result.error_class != "version_mismatch":
            raise AssertionError(f"version mismatch must classify: {result.error_class}")

        # 登录墙（信封 + data.success=false）
        server.responses.append({"ok": True, "data": {"success": False, "message": "Please log in to continue"}})
        result = kimi_adapter.run_action("snapshot", {}, "s", timeout=10)
        if result.ok or result.error_class != "access_authentication":
            raise AssertionError(f"login wall must classify as access_authentication: {result.error_class}")

        # 空响应（ok=true 但 data 无契约字段）→ 契约级失败，不得冒充成功
        server.responses.append({"ok": True, "data": {}})
        result = kimi_adapter.run_action("snapshot", {}, "s", timeout=10)
        if result.ok:
            raise AssertionError("empty snapshot must not be treated as success")

        # 误分类防御：URL 回声含 "login" 但错误字段无登录特征 → 不得归为访问认证
        failure_class, _ = kimi.classify_failure(
            {"success": False, "message": "network unreachable", "url": "https://example.com/login?next=/secure"}
        )
        if failure_class == "access_authentication":
            raise AssertionError(f"URL echo must not trigger access_authentication, got {failure_class}")
        failure_class, _ = kimi.classify_failure({"success": False, "error": "Please update the Kimi WebBridge extension"})
        if failure_class != "version_mismatch":
            raise AssertionError(f"message field must drive classification: {failure_class}")
        print("  [5/7] failure classification (version/access-auth/envelope/no-URL-echo-misclassification): PASS")
    finally:
        _detach_bridge()
        server.close()


def test_auth_check() -> None:
    server = MockBridgeServer()
    _attach_bridge(server)
    healthy = kimi_adapter.BridgeHealth(True, {"running": True, "extension_connected": True}, "none", "")
    try:
        # 登录墙：navigate 成功 + snapshot 只含登录提示（真实信封格式 + 树结构）
        server.responses.append({"ok": True, "data": {"success": True, "url": "https://portal.example.com", "tabId": "t"}})
        server.responses.append(
            {"ok": True, "data": {"url": "https://portal.example.com", "title": "Login", "tree": [{"role": "heading", "name": "Log in"}, {"role": "textbox", "name": "Password required"}]}}
        )
        with mock.patch("web_collection.kimi_adapter.check_health", return_value=healthy):
            auth = kimi_adapter.check_auth("https://portal.example.com", "s", timeout=10)
        if auth.state != "logged_out":
            raise AssertionError(f"login wall must yield logged_out, got {auth.state}: {auth.reason}")

        # 实质内容 → logged_in（project_dir 传入 → 证据落盘，raw_capture_path 非空）
        server.responses.append({"ok": True, "data": {"success": True, "url": "https://portal.example.com", "tabId": "t"}})
        server.responses.append(
            {"ok": True, "data": {"url": "https://portal.example.com", "title": "Dashboard", "tree": [{"role": "paragraph", "name": "Welcome back. Your energy dashboard shows 1,234 kWh."}]}}
        )
        capture_project = Path(tempfile.mkdtemp(prefix="kimi_auth_cap_"))
        with mock.patch("web_collection.kimi_adapter.check_health", return_value=healthy):
            auth = kimi_adapter.check_auth(
                "https://portal.example.com", "s", timeout=10, project_dir=capture_project, task_id="A1", goal="policy"
            )
        if auth.state != "logged_in":
            raise AssertionError(f"substantive content must yield logged_in, got {auth.state}: {auth.reason}")
        if not auth.raw_capture_path or not (capture_project / auth.raw_capture_path).is_file():
            raise AssertionError(f"auth_check must persist evidence with raw_capture_path: {auth.raw_capture_path}")
        print("  [6/7] auth check (login wall → logged_out, substantive → logged_in, evidence persisted): PASS")
    finally:
        _detach_bridge()
        server.close()


def test_daemon_lifecycle_passthrough() -> None:
    fake_binary = Path(tempfile.mkdtemp(prefix="kimi_reg_")) / "kimi-webbridge"
    fake_binary.write_text("", encoding="utf-8")
    fake_completed = type("C", (), {"returncode": 0, "stdout": "fake log line\nsecond line\n", "stderr": ""})()
    with mock.patch("subprocess.run", return_value=fake_completed) as run:
        output = kimi.daemon_logs(fake_binary, lines=100)
        if output != "fake log line\nsecond line\n":
            raise AssertionError("daemon_logs must return stdout verbatim")
        command = run.call_args.args[0]
        if command[-3:] != ["logs", "-n", "100"]:
            raise AssertionError(f"logs passthrough args mismatch: {command}")
        kimi.daemon_logs(fake_binary, previous=True)
        if run.call_args.args[0][-2:] != ["logs", "--prev"]:
            raise AssertionError("logs --prev passthrough failed")
        # follow 模式必须明确拒绝（subprocess.run 下会永不退出）
        try:
            kimi.daemon_logs(fake_binary, follow=True)
            raise AssertionError("daemon_logs(follow=True) must raise NotImplementedError")
        except NotImplementedError:
            pass
        print("  [7/7] daemon lifecycle passthrough (logs -n/--prev; follow rejected): PASS")


def main() -> int:
    print("Kimi WebBridge embed regression:")
    test_action_contract()
    test_command_payload_matches_official()
    test_session_consistency()
    test_health_classification()
    test_failure_classification()
    test_auth_check()
    test_daemon_lifecycle_passthrough()
    print("Kimi WebBridge embed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
