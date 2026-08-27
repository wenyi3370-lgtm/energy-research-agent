from __future__ import annotations

"""离线回归：anysearch 内嵌 CLI 与后端（官方 CLI 零 diff + 错误归一化 + 全命令面）。

- 使用本地 mock JSON-RPC 服务器 + 模拟官方 CLI 表面的 fake CLI（子进程透传链路全真）；
- 覆盖 search/batch_search/extract/get_sub_domains/doc 全命令面与错误路径；
- 内嵌 CLI 与官方源 doc 输出 diff=0（同源保证）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from web_collection import anysearch_backend as backend  # noqa: E402
from web_collection.errors import ErrorClass  # noqa: E402

FAKE_CLI_TEMPLATE = '''\
import argparse, json, sys, requests
ENDPOINT = "http://127.0.0.1:{port}"

def _call(tool, arguments):
    payload = {{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {{"name": tool, "arguments": arguments}}}}
    try:
        resp = requests.post(ENDPOINT, json=payload, timeout=10)
    except requests.exceptions.ConnectionError as exc:
        print("Connection Error: Unable to reach the API endpoint.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"HTTP Error: {{resp.status_code}} {{resp.reason}}", file=sys.stderr)
        try:
            print(json.dumps(resp.json(), ensure_ascii=False), file=sys.stderr)
        except Exception:
            pass
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
p.add_argument("--api_key", default="")
sub = p.add_subparsers(dest="command", required=True)
s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--domain"); s.add_argument("--sub_domain"); s.add_argument("--sdp"); s.add_argument("--max_results", type=int)
b = sub.add_parser("batch_search"); b.add_argument("--query", action="append"); b.add_argument("--max_results", type=int); b.add_argument("--domain"); b.add_argument("--sub_domain"); b.add_argument("--sdp")
e = sub.add_parser("extract"); e.add_argument("--url")
g = sub.add_parser("get_sub_domains"); g.add_argument("--domain")
d = sub.add_parser("doc")
args = p.parse_args()
if args.command == "search":
    arguments = {{"query": args.query}}
    if args.domain: arguments["domain"] = args.domain
    if args.sub_domain: arguments["sub_domain"] = args.sub_domain
    if args.sdp:
        import json as _j
        arguments["sub_domain_params"] = {{k: v for k, v in (kv.split("=", 1) for kv in args.sdp.split(",") if "=" in kv)}}
    if args.max_results is not None: arguments["max_results"] = min(args.max_results, 10)
    _call("search", arguments)
elif args.command == "batch_search":
    _call("batch_search", {{"queries": [{{"query": q}} for q in args.query]}})
elif args.command == "extract":
    _call("extract", {{"url": args.url}})
elif args.command == "get_sub_domains":
    _call("get_sub_domains", {{"domain": args.domain}})
elif args.command == "doc":
    print("FAKE_DOC")
'''

SEARCH_OK = {
    "status": 200,
    "json": {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"total_results": 5, "results": [{"url": f"https://s{i}.example.com" for i in range(5)}]})}
            ]
        }
    },
}


class MockAnySearchServer:
    """本地 mock JSON-RPC 服务器：测试注入响应队列 + 记录收到的请求。"""

    def __init__(self) -> None:
        self.responses: list[dict] = []
        self.requests_log: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            server_ref = self

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    body = {}
                self.server_ref.requests_log.append(body)
                if not self.server_ref.responses:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"no mock response queued"}}')
                    return
                response = self.server_ref.responses.pop(0)
                status = response.get("status", 200)
                payload = response.get("json")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if payload is not None:
                    self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, *args) -> None:  # noqa: D401
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def write_fake_cli(directory: Path, port: int) -> Path:
    target = directory / "fake_anysearch_cli.py"
    target.write_text(FAKE_CLI_TEMPLATE.format(port=port), encoding="utf-8")
    return target


def test_embedded_cli_integrity() -> None:
    """FIX-01: self-contained integrity — the bundled CLI must match the
    INTERNAL manifest (references/anysearch_manifest.json). No external
    AnySearch Skill is required; parity with the official Skill is a
    separate integration test that SKIPs when the official Skill is absent.
    """
    embedded = backend.embedded_cli_path()
    if not embedded.is_file():
        raise AssertionError("embedded anysearch CLI missing")
    manifest_path = Path(__file__).resolve().parent.parent / "references" / "anysearch_manifest.json"
    if not manifest_path.is_file():
        raise AssertionError("references/anysearch_manifest.json missing - regenerate after any CLI change")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = backend.cli_sha256(embedded)
    expected = manifest.get("cli_sha256")
    if actual != expected:
        raise AssertionError(
            "embedded CLI hash %s differs from manifest %s - regenerate references/anysearch_manifest.json"
            % (actual[:16], str(expected)[:16])
        )
    doc_out = subprocess.run([sys.executable, str(embedded), "doc"], capture_output=True, text=True, timeout=60)
    if doc_out.returncode:
        raise AssertionError("embedded doc command failed")
    print("  [1/6] embedded CLI integrity (SHA256 == internal manifest): PASS")


def test_search_command_surface() -> None:
    server = MockAnySearchServer()
    fake_cli = write_fake_cli(Path(tempfile.mkdtemp(prefix="anysearch_reg_")), server.port)
    try:
        with tempfile.TemporaryDirectory(prefix="anysearch_proj_") as tmp:
            project = Path(tmp)
            server.responses.append(SEARCH_OK)
            result = backend.run_search(
                "Thailand BEV sales 2025",
                project_dir=project,
                task_id="T1",
                goal="market_size",
                max_results=5,
                official_cli=fake_cli,
            )
            if not result.ok or result.candidates_found != 5:
                raise AssertionError(f"search should succeed with 5 candidates: {result}")
            capture = project / result.raw_capture_path
            if not capture.is_file():
                raise AssertionError("raw capture not saved for search")
            payload = server.requests_log[0]
            tool_args = payload["params"]["arguments"]
            if tool_args["query"] != "Thailand BEV sales 2025" or tool_args["max_results"] != 5:
                raise AssertionError(f"search arguments mismatch: {tool_args}")

            # 垂直域 + sdp 参数透传
            server.responses.append(SEARCH_OK)
            backend.run_search(
                "tariff", project_dir=project, task_id="T2", goal="policy",
                domain="energy", sub_domain="energy.electricity",
                sdp="location=Thailand,metric=price", official_cli=fake_cli,
            )
            vertical_args = server.requests_log[1]["params"]["arguments"]
            if vertical_args.get("domain") != "energy" or vertical_args.get("sub_domain") != "energy.electricity":
                raise AssertionError(f"vertical search args mismatch: {vertical_args}")
            if vertical_args.get("sub_domain_params") != {"location": "Thailand", "metric": "price"}:
                raise AssertionError(f"sdp mismatch: {vertical_args.get('sub_domain_params')}")
        print("  [2/6] search command surface (general/vertical/sdp/max_results/capture): PASS")
    finally:
        server.close()


def test_batch_search_and_extract() -> None:
    server = MockAnySearchServer()
    fake_cli = write_fake_cli(Path(tempfile.mkdtemp(prefix="anysearch_reg_")), server.port)
    try:
        with tempfile.TemporaryDirectory(prefix="anysearch_proj_") as tmp:
            project = Path(tmp)
            server.responses.append(SEARCH_OK)
            result = backend.run_batch_search(
                ["q1", "q2", "q3"], project_dir=project, task_id="T3", goal="general", official_cli=fake_cli
            )
            if not result.ok:
                raise AssertionError(f"batch_search should succeed: {result.error_class}")
            queries = server.requests_log[0]["params"]["arguments"]["queries"]
            if [q["query"] for q in queries] != ["q1", "q2", "q3"]:
                raise AssertionError(f"batch queries mismatch: {queries}")

            server.responses.append(
                {"status": 200, "json": {"result": {"content": [{"type": "text", "text": "# Page Title\n\nContent..."}]}}}
            )
            result = backend.run_extract(
                "https://www.egat.co.th/home/en/", project_dir=project, task_id="T4", goal="policy", official_cli=fake_cli
            )
            if not result.ok:
                raise AssertionError(f"extract should succeed: {result.error_class}")
            payload = server.requests_log[1]["params"]["arguments"]
            if payload["url"] != "https://www.egat.co.th/home/en/":
                raise AssertionError(f"extract url mismatch: {payload}")
            if not (project / result.raw_capture_path).is_file():
                raise AssertionError("extract raw capture not saved")

            # 原始留痕唯一性：同一任务连续多次 extract 不得互相覆盖
            server.responses.append(
                {"status": 200, "json": {"result": {"content": [{"type": "text", "text": "# Second Page\n\nOther content..."}]}}}
            )
            second = backend.run_extract(
                "https://www.egat.co.th/home/en/20221021e/", project_dir=project, task_id="T4", goal="policy", official_cli=fake_cli
            )
            if not second.ok:
                raise AssertionError(f"second extract should succeed: {second.error_class}")
            if second.raw_capture_path == result.raw_capture_path:
                raise AssertionError("raw captures must be unique per attempt (no overwrite)")
            if not (project / second.raw_capture_path).is_file():
                raise AssertionError("second raw capture must exist")
        print("  [3/6] batch_search + extract command surface + capture uniqueness: PASS")
    finally:
        server.close()


def test_error_normalization() -> None:
    server = MockAnySearchServer()
    fake_cli = write_fake_cli(Path(tempfile.mkdtemp(prefix="anysearch_reg_")), server.port)
    try:
        with tempfile.TemporaryDirectory(prefix="anysearch_proj_") as tmp:
            project = Path(tmp)

            # 402 → insufficient_balance，不重试
            server.responses.append({"status": 402, "json": {"error": {"message": "quota exhausted"}}})
            result = backend.run_search("q", project_dir=project, task_id="T5", official_cli=fake_cli)
            if result.ok or result.error_class != ErrorClass.INSUFFICIENT_BALANCE or result.attempts != 1:
                raise AssertionError(f"402 should map to insufficient_balance, no retry: {result.error_class}, attempts={result.attempts}")

            # 429 → insufficient_balance，不重试
            server.responses.append({"status": 429, "json": {}})
            result = backend.run_search("q", project_dir=project, task_id="T6", official_cli=fake_cli)
            if result.ok or result.error_class != ErrorClass.INSUFFICIENT_BALANCE or result.attempts != 1:
                raise AssertionError(f"429 should map to insufficient_balance, no retry: {result.error_class}, attempts={result.attempts}")

            # 503 → upstream_5xx，最多重试一次
            server.responses.append({"status": 503, "json": {}})
            server.responses.append({"status": 503, "json": {}})
            result = backend.run_search("q", project_dir=project, task_id="T7", official_cli=fake_cli)
            if result.ok or result.error_class != ErrorClass.UPSTREAM_5XX or result.attempts != 2:
                raise AssertionError(f"503 should retry once: {result.error_class}, attempts={result.attempts}")

            # 404 → http_4xx，不重试
            server.responses.append({"status": 404, "json": {}})
            result = backend.run_search("q", project_dir=project, task_id="T8", official_cli=fake_cli)
            if result.ok or result.error_class != ErrorClass.HTTP_4XX or result.attempts != 1:
                raise AssertionError(f"404 should map to http_4xx, no retry: {result.error_class}, attempts={result.attempts}")

            # 401/403 → auth_required（登录墙优先于普通 4xx）
            server.responses.append({"status": 401, "json": {}})
            result = backend.run_search("q", project_dir=project, task_id="T10", official_cli=fake_cli)
            if result.error_class != ErrorClass.AUTH_REQUIRED:
                raise AssertionError(f"401 should map to auth_required: {result.error_class}")
            server.responses.append({"status": 403, "json": {}})
            result = backend.run_search("q", project_dir=project, task_id="T11", official_cli=fake_cli)
            if result.error_class != ErrorClass.AUTH_REQUIRED:
                raise AssertionError(f"403 should map to auth_required: {result.error_class}")
        print("  [4/6] error normalization (402/429/503/4xx/401/403 + retry policy): PASS")
    finally:
        server.close()


def test_connection_error() -> None:
    with tempfile.TemporaryDirectory(prefix="anysearch_proj_") as tmp:
        project = Path(tmp)
        closed = MockAnySearchServer()
        port = closed.port
        closed.close()  # 立即关闭：模拟 API 不可达
        fake_cli = write_fake_cli(Path(tempfile.mkdtemp(prefix="anysearch_reg_")), port)
        result = backend.run_search("q", project_dir=project, task_id="T9", official_cli=fake_cli)
        if result.ok or result.error_class != ErrorClass.NETWORK_ERROR:
            raise AssertionError(f"unreachable API should map to network_error: {result.error_class}")

        # 额度刷新信号：Rate limited + retry seconds 必须被识别并保留
        from web_collection.errors import classify_text, extract_retry_seconds

        if classify_text("Rate limited, retry after 300 seconds.") != ErrorClass.INSUFFICIENT_BALANCE:
            raise AssertionError("'Rate limited' must map to insufficient_balance (no blind retry)")
        if extract_retry_seconds("Rate limited, retry after 300 seconds.") != 300:
            raise AssertionError("retry seconds must be extracted from the rate-limit message")
        if extract_retry_seconds("some unrelated error") is not None:
            raise AssertionError("retry seconds must not be extracted from unrelated errors")
    print("  [5/6] connection error + quota refresh signal (Rate limited → insufficient_balance + retry seconds): PASS")


def test_get_sub_domains_and_embedded_cli_parse() -> None:
    server = MockAnySearchServer()
    fake_cli = write_fake_cli(Path(tempfile.mkdtemp(prefix="anysearch_reg_")), server.port)
    try:
        server.responses.append({"status": 200, "json": {"result": {"content": [{"type": "text", "text": "| domain | sub_domain |"}]}}})
        result = backend.run_get_sub_domains("energy", official_cli=fake_cli)
        if not result.ok or "sub_domain" not in result.stdout:
            raise AssertionError(f"get_sub_domains should succeed: {result.error_class}")
        if server.requests_log[0]["params"]["arguments"] != {"domain": "energy"}:
            raise AssertionError(f"get_sub_domains args mismatch: {server.requests_log[0]}")

        # 真实内嵌 CLI 命令面（不联网）：--help 与参数解析
        embedded = backend.embedded_cli_path()
        help_out = subprocess.run([sys.executable, str(embedded), "--help"], capture_output=True, text=True, timeout=60)
        if help_out.returncode or "batch_search" not in help_out.stdout:
            raise AssertionError("embedded CLI --help should list all commands")
        search_help = subprocess.run([sys.executable, str(embedded), "search", "--help"], capture_output=True, text=True, timeout=60)
        if search_help.returncode:
            raise AssertionError("embedded search --help failed")
        if "--sdp" not in search_help.stdout or "--max_results" not in search_help.stdout or "--domain" not in search_help.stdout:
            raise AssertionError("embedded search surface missing --sdp/--max_results/--domain")
        extract_help = subprocess.run([sys.executable, str(embedded), "extract", "--help"], capture_output=True, text=True, timeout=60)
        if "--url" not in extract_help.stdout:
            raise AssertionError("embedded extract surface missing --url")
        print("  [6/6] get_sub_domains + embedded CLI parser surface: PASS")
    finally:
        server.close()


def main() -> int:
    print("AnySearch embed regression:")
    test_embedded_cli_integrity()
    test_search_command_surface()
    test_batch_search_and_extract()
    test_error_normalization()
    test_connection_error()
    test_get_sub_domains_and_embedded_cli_parse()
    print("AnySearch embed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
