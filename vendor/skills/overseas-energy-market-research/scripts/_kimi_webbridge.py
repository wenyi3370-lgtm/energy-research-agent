from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BRIDGE_URL = "http://127.0.0.1:10086/command"

# --- 只读 action 契约表（官方 kimi-webbridge SKILL.md 3.0.1，仅数据不实现逻辑）---
# 每个 action 的必填/可选参数与返回字段来自官方文档；调用方按此构造 args，
# 并经 command() 原样 POST 到 daemon（payload 与官方 curl 示例逐字段一致）。
ACTION_CONTRACT: dict[str, dict[str, list[str]]] = {
    "navigate": {
        "required_args": ["url"],
        "optional_args": ["newTab", "group_title"],
        "returns": ["success", "url", "tabId"],
        "note": "First call opens a tab; set group_title to a user-language label",
    },
    "find_tab": {
        "required_args": ["url"],
        "optional_args": ["active"],
        "returns": ["success", "url", "tabId"],
        "note": "Select an already-open tab as the current one",
    },
    "snapshot": {
        "required_args": [],
        "optional_args": [],
        "returns": ["url", "title", "tree"],
        "note": "Accessibility tree with @e refs; prefer over CSS selectors",
    },
    "click": {
        "required_args": ["selector"],
        "optional_args": [],
        "returns": ["success", "tag", "text"],
        "note": "Synthetic el.click(); selector is @e ref or CSS",
    },
    "fill": {
        "required_args": ["selector", "value"],
        "optional_args": [],
        "returns": ["success", "tag", "mode"],
        "note": "Works on input/textarea AND [contenteditable]",
    },
    "evaluate": {
        "required_args": ["code"],
        "optional_args": [],
        "returns": ["type", "value"],
        "note": "Supports async/await; wrap in IIFE to avoid const redeclaration",
    },
    "screenshot": {
        "required_args": [],
        "optional_args": ["format", "quality", "selector", "path"],
        "returns": ["format", "path", "sizeBytes", "mimeType"],
        "note": "Returns a file path, not base64",
    },
    "network": {
        "required_args": ["cmd"],
        "optional_args": ["filter", "requestId"],
        "returns": ["requests"],
        "note": "cmd is start|stop|list|detail",
    },
    "upload": {
        "required_args": ["selector", "files"],
        "optional_args": [],
        "returns": ["success", "fileCount"],
        "note": "files is an array of paths",
    },
    "save_as_pdf": {
        "required_args": [],
        "optional_args": ["paper_format", "landscape", "scale", "print_background", "path"],
        "returns": ["path", "sizeBytes", "mimeType", "pageTitle"],
        "note": "Renders the current page; returns a file path",
    },
    "list_tabs": {
        "required_args": [],
        "optional_args": [],
        "returns": ["success", "tabs"],
        "note": "tabs: [{tabId, url, title, active, groupTitle}]",
    },
    "close_tab": {
        "required_args": [],
        "optional_args": [],
        "returns": ["success", "closed"],
        "note": "Close the current tab in the session",
    },
    "close_session": {
        "required_args": [],
        "optional_args": [],
        "returns": ["success", "closed"],
        "note": "Close all tabs in the session; closed is the count",
    },
}

# --- 故障分类（来自官方 SKILL.md 失败处理与 playbook 的分类）---
FAILURE_VERSION_MISMATCH = "version_mismatch"
FAILURE_EXTENSION_DISCONNECTED = "extension_disconnected"
FAILURE_TIMEOUT = "timeout"
FAILURE_ACCESS_AUTH = "access_authentication"
FAILURE_CHALLENGE = "challenge"
FAILURE_EMPTY_SNAPSHOT = "empty_snapshot"
FAILURE_WRONG_CURRENT_TAB = "wrong_current_tab"
FAILURE_SYNTHETIC_EVENT = "synthetic_event_limitation"
FAILURE_DAEMON_STOPPED = "daemon_stopped"
FAILURE_NOT_INSTALLED = "not_installed"
FAILURE_UNKNOWN = "unknown"

_ACCESS_AUTH_TOKENS = ("login", "sign in", "password", "登录", "密码", "authenticate", "log in", "sign-in", "登录页")
_CHALLENGE_TOKENS = ("captcha", "challenge", "验证码", "人机验证")
_VERSION_TOKENS = ("version mismatch", "incompatible", "升级", "更新插件", "update", "version")
_TIMEOUT_TOKENS = ("timeout", "timed out", "超时")


def validate_action_args(action: str, args: dict[str, Any]) -> list[str]:
    """按只读契约表机械校验必填参数（不执行任何 action）。"""
    contract = ACTION_CONTRACT.get(action)
    if contract is None:
        return [f"Unknown kimi-webbridge action: {action}"]
    problems = []
    for required in contract["required_args"]:
        if required not in args or args[required] in (None, ""):
            problems.append(f"{action} requires arg '{required}'")
    return problems


def classify_failure(result: dict[str, Any], status: dict[str, Any] | None = None) -> tuple[str, str]:
    """把失败的 command 返回/桥接状态归一为 (failure_class, reason)。

    分类依据：官方 SKILL.md 失败处理与 references/kimi-webbridge-operations.md。
    登录墙/挑战/版本不匹配等必须显式分类，不得冒充成功。
    注意：只扫描 message/error 字段，避免 URL/args/session 回声（如含 "login" 的 URL）
    造成误分类。
    """
    if status:
        if not status.get("running"):
            return FAILURE_DAEMON_STOPPED, "Kimi WebBridge daemon is not running"
        if not status.get("extension_connected"):
            return FAILURE_EXTENSION_DISCONNECTED, "Kimi WebBridge browser extension is not connected"
    error_fields: list[str] = []
    for key in ("message", "error", "msg", "error_message", "reason"):
        value = result.get(key)
        if isinstance(value, str):
            error_fields.append(value)
        elif isinstance(value, dict):
            error_fields.append(json.dumps(value, ensure_ascii=False))
    lowered = " ".join(error_fields).casefold()
    if not lowered:
        # 无错误字段：按结果结构做保守推断
        snapshot = result.get("tree")
        if action_is_snapshot_like(result) and not snapshot:
            return FAILURE_EMPTY_SNAPSHOT, "Snapshot returned no accessibility tree"
        return FAILURE_UNKNOWN, "Unclassified bridge failure; inspect the raw result"
    for token in _VERSION_TOKENS:
        if token in lowered:
            return FAILURE_VERSION_MISMATCH, f"Daemon/extension version mismatch or upgrade needed (token: {token})"
    for token in _CHALLENGE_TOKENS:
        if token in lowered:
            return FAILURE_CHALLENGE, f"Site presented a captcha/challenge (token: {token})"
    for token in _ACCESS_AUTH_TOKENS:
        if token in lowered:
            return FAILURE_ACCESS_AUTH, f"Authentication or login wall detected (token: {token})"
    for token in _TIMEOUT_TOKENS:
        if token in lowered:
            return FAILURE_TIMEOUT, f"Command timed out (token: {token})"
    return FAILURE_UNKNOWN, "Unclassified bridge failure; inspect the raw result"


def action_is_snapshot_like(result: dict[str, Any]) -> bool:
    return "tree" in result or "title" in result


def normalize_session(session: str) -> str:
    """任务级 session 名称规范：非空、稳定、小写连字符风格。"""
    cleaned = " ".join(str(session or "").split()).casefold().replace(" ", "-")
    if not cleaned:
        raise ValueError("A stable task-level session name is required (one task = one session)")
    return cleaned


class BridgePreflightError(RuntimeError):
    def __init__(self, message: str, status: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status or {}


def default_bridge_binary() -> Path:
    base = Path.home() / ".kimi-webbridge" / "bin"
    windows_binary = base / "kimi-webbridge.exe"
    return windows_binary if windows_binary.exists() else base / "kimi-webbridge"


def _run_cli(binary: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(binary), *args], text=True, capture_output=True)


def _parse_status(output: str) -> dict[str, Any]:
    for line in reversed([line.strip() for line in output.splitlines() if line.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise BridgePreflightError("Kimi WebBridge status did not return valid JSON.")


def get_status(binary: Path) -> dict[str, Any]:
    if not binary.exists():
        raise BridgePreflightError(f"Kimi WebBridge binary not found: {binary}")
    completed = _run_cli(binary, "status")
    if completed.returncode:
        raise BridgePreflightError(
            "Kimi WebBridge status failed.\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return _parse_status(completed.stdout)


def ensure_ready(binary: Path, auto_start: bool = True) -> dict[str, Any]:
    status = get_status(binary)
    if not status.get("running") and auto_start:
        started = _run_cli(binary, "start")
        if started.returncode:
            raise BridgePreflightError(
                "Kimi WebBridge daemon could not be started.\n"
                f"STDOUT:\n{started.stdout}\nSTDERR:\n{started.stderr}",
                status,
            )
        status = get_status(binary)
    if not status.get("running"):
        raise BridgePreflightError(
            "Kimi WebBridge daemon is not running. Follow kimi-webbridge/references/operations.md.",
            status,
        )
    if not status.get("extension_connected"):
        raise BridgePreflightError(
            "Kimi WebBridge browser extension is not connected. Open a browser with the extension enabled, "
            "or install it from https://www.kimi.com/zh-cn/features/webbridge, then retry.",
            status,
        )
    return status


def command(action: str, args: dict[str, Any], session: str, timeout: int = 60) -> dict[str, Any]:
    payload = json.dumps(
        {"action": action, "args": args, "session": session},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        BRIDGE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BridgePreflightError(f"Kimi WebBridge command failed: {exc}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BridgePreflightError("Kimi WebBridge command returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise BridgePreflightError("Kimi WebBridge command returned an unexpected response.")
    return result


# --- daemon 生命周期（官方 CLI 子命令透传，行为与官方一致）---

def daemon_start(binary: Path | None = None) -> subprocess.CompletedProcess[str]:
    selected = binary or default_bridge_binary()
    if not selected.exists():
        raise BridgePreflightError(
            f"Kimi WebBridge binary not found: {selected}. Install from "
            "https://www.kimi.com/features/webbridge (中文: https://www.kimi.com/zh-cn/features/webbridge)."
        )
    return _run_cli(selected, "start")


def daemon_stop(binary: Path | None = None) -> subprocess.CompletedProcess[str]:
    selected = binary or default_bridge_binary()
    if not selected.exists():
        raise BridgePreflightError(f"Kimi WebBridge binary not found: {selected}")
    return _run_cli(selected, "stop")


def daemon_restart(binary: Path | None = None) -> subprocess.CompletedProcess[str]:
    selected = binary or default_bridge_binary()
    if not selected.exists():
        raise BridgePreflightError(f"Kimi WebBridge binary not found: {selected}")
    return _run_cli(selected, "restart")


def daemon_logs(
    binary: Path | None = None,
    *,
    lines: int = 100,
    follow: bool = False,
    previous: bool = False,
) -> str:
    """查看 daemon 日志（官方 `logs -n N` / `-f` / `--prev` 透传）。

    注意：follow（-f）模式永不退出，与 subprocess.run 的超时模型冲突，
    明确禁止（调用方应改用 logs -n 取最近日志）。
    """
    if follow:
        raise NotImplementedError(
            "daemon_logs(follow=True) is not supported: follow mode never exits under subprocess.run; use daemon_logs(lines=N) instead"
        )
    selected = binary or default_bridge_binary()
    if not selected.exists():
        raise BridgePreflightError(f"Kimi WebBridge binary not found: {selected}")
    command = [str(selected), "logs"]
    if previous:
        command.append("--prev")
    else:
        command.extend(["-n", str(max(1, int(lines)))])
    completed = subprocess.run(command, text=True, capture_output=True, timeout=30)
    if completed.returncode:
        raise BridgePreflightError(
            "kimi-webbridge logs failed.\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed.stdout
