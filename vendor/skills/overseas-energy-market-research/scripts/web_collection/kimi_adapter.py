"""kimi-webbridge 流程编排层（薄封装，action payload 一律走 command() 透传）。

不实现任何 action 协议逻辑；只做：
- 健康检查硬门禁（ensure_ready：daemon running + extension_connected）；
- 按只读契约表校验参数（validate_action_args）；
- navigate → snapshot 等动作的流程编排与原始捕获落盘；
- 登录态检查（check_auth：登录墙特征 + 无实质内容判断）；
- 失败分类（classify_failure），插件未连接 → bridge_unavailable 显式失败。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import _kimi_webbridge as kimi
from _kimi_webbridge import (
    ACTION_CONTRACT,
    BridgePreflightError,
    classify_failure,
    command,
    default_bridge_binary,
    ensure_ready,
    normalize_session,
    validate_action_args,
)

_SNAPSHOT_LOGIN_TOKENS = ("log in", "login", "sign in", "password", "登录", "密码", "authenticate", "sign-in")
_SNAPSHOT_EMPTY_TOKENS = ("captcha", "challenge", "验证码")


def unwrap_result(result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """解开 daemon 响应信封（真实 v1.11.x 返回 {ok, data}；文档示例为顶层字段）。

    两种格式都兼容：真实 daemon 的信封优先，官方 SKILL.md 示例（success 顶层）兜底。
    """
    if not isinstance(result, dict):
        return True, {}
    if "data" in result or "ok" in result:
        ok = bool(result.get("ok", True))
        data = result.get("data")
        if isinstance(data, dict):
            return ok, data
        if ok and isinstance(data, (str, list, int, float, bool)):
            return True, {"_value": data}
        return ok, {}
    return bool(result.get("success", True)), result


def extract_tree_text(tree: Any) -> str:
    """递归提取无障碍树中的可读文本（role/name 节点）。"""
    if isinstance(tree, str):
        return tree
    if isinstance(tree, list):
        return " ".join(part for item in tree for part in [extract_tree_text(item)] if part)
    if isinstance(tree, dict):
        parts: list[str] = []
        name = tree.get("name")
        if isinstance(name, str) and name.strip():
            parts.append(name.strip())
        children = tree.get("children")
        if children:
            parts.append(extract_tree_text(children))
        return " ".join(part for part in parts if part)
    return ""


@dataclass
class BridgeHealth:
    healthy: bool
    status: dict[str, Any]
    failure_class: str
    failure_reason: str


@dataclass
class AuthState:
    state: str  # logged_in | logged_out | unknown
    reason: str
    snapshot_tree: str = ""
    raw_capture_path: str = ""


@dataclass
class KimiActionResult:
    ok: bool
    action: str
    result: dict[str, Any]
    error_class: str = "none"
    error_message: str = ""
    raw_capture_path: str = ""


def check_health(binary: Path | None = None, auto_start: bool = True) -> BridgeHealth:
    """健康检查硬门禁。未就绪时返回明确分类，不抛异常（调用方决定流程）。"""
    selected = binary or default_bridge_binary()
    try:
        status = ensure_ready(selected, auto_start=auto_start)
    except BridgePreflightError as exc:
        if exc.status:
            failure_class, reason = classify_failure({}, exc.status)
        elif "not found" in str(exc).casefold() or "install" in str(exc).casefold():
            failure_class, reason = "not_installed", str(exc)
        else:
            failure_class, reason = "unknown", str(exc)
        return BridgeHealth(healthy=False, status=exc.status, failure_class=failure_class, failure_reason=reason)
    except FileNotFoundError as exc:
        return BridgeHealth(
            healthy=False,
            status={},
            failure_class="not_installed",
            failure_reason=str(exc),
        )
    return BridgeHealth(healthy=True, status=status, failure_class="none", failure_reason="")


def run_action(
    action: str,
    args: dict[str, Any],
    session: str,
    *,
    project_dir: Path | None = None,
    task_id: str = "",
    goal: str = "general",
    timeout: int = 60,
) -> KimiActionResult:
    """执行单个 action：参数契约校验 → command() 透传 → 失败分类 → 原始捕获落盘。"""
    normalized = normalize_session(session)
    validation = validate_action_args(action, args)
    if validation:
        return KimiActionResult(ok=False, action=action, result={}, error_class="parse_failure", error_message="; ".join(validation))
    try:
        result = command(action, args, normalized, timeout=timeout)
    except BridgePreflightError as exc:
        failure_class, reason = classify_failure({}, exc.status)
        return KimiActionResult(ok=False, action=action, result={}, error_class=failure_class, error_message=reason)
    except TimeoutError as exc:
        return KimiActionResult(ok=False, action=action, result={}, error_class="timeout", error_message=str(exc))
    except Exception as exc:  # noqa: BLE001 - 保留现场，归类 unknown 而不是误标 timeout
        return KimiActionResult(ok=False, action=action, result={}, error_class="unknown", error_message=f"{type(exc).__name__}: {exc}")
    envelope_ok, payload = unwrap_result(result)
    if not envelope_ok:
        failure_class, reason = classify_failure(payload or result)
        return KimiActionResult(ok=False, action=action, result=result, error_class=failure_class, error_message=reason)
    success = bool(payload.get("success", True))
    if not success:
        failure_class, reason = classify_failure(payload)
        return KimiActionResult(ok=False, action=action, result=result, error_class=failure_class, error_message=reason)
    # 契约级成功判定：响应必须至少包含契约返回字段之一，否则视为异常响应
    # （空响应/空快照不得冒充成功）
    contract = ACTION_CONTRACT.get(action, {})
    expected_returns = contract.get("returns", [])
    if expected_returns and not any(key in payload for key in expected_returns):
        failure_class = "empty_snapshot" if action == "snapshot" else "unknown"
        return KimiActionResult(
            ok=False,
            action=action,
            result=result,
            error_class=failure_class,
            error_message=f"Response lacks any contract return field ({expected_returns}): empty/invalid bridge response",
        )
    raw_capture_path = ""
    if project_dir is not None:
        raw_capture_path = _save_bridge_capture(project_dir, goal, task_id, action, result)
    return KimiActionResult(ok=True, action=action, result=result, raw_capture_path=raw_capture_path)


def _save_bridge_capture(project_dir: Path, goal: str, task_id: str, action: str, result: dict[str, Any]) -> str:
    import json
    from datetime import datetime

    project_root = Path(project_dir).resolve()
    directory = project_root / "raw_capture" / _safe_goal(goal)
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", task_id or "task")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = directory / f"{safe}_{action}_{stamp}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return target.relative_to(project_root).as_posix()


def check_auth(
    url: str,
    session: str,
    *,
    binary: Path | None = None,
    timeout: int = 60,
    project_dir: Path | None = None,
    task_id: str = "",
    goal: str = "general",
) -> AuthState:
    """登录态检查：navigate 到 URL → snapshot → 登录墙/实质内容判断。

    登录失败/登录墙 → logged_out；无法判断 → unknown。绝不把登录墙当成功。
    传入 project_dir 时把 snapshot 证据落盘（成功与失败都留痕，供台账引用）。
    """
    health = check_health(binary)
    if not health.healthy:
        return AuthState("unknown", f"bridge unavailable: {health.failure_reason}")
    normalized = normalize_session(session)
    try:
        nav = command("navigate", {"url": url, "newTab": True}, normalized, timeout=timeout)
    except BridgePreflightError as exc:
        return AuthState("unknown", f"navigate failed: {str(exc)}")
    nav_ok, nav_payload = unwrap_result(nav)
    if not nav_ok or not nav_payload.get("success", True):
        failure_class, reason = classify_failure(nav_payload or nav)
        return AuthState("unknown", f"navigate failed: {failure_class}: {reason}")
    try:
        snapshot = command("snapshot", {}, normalized, timeout=timeout)
    except BridgePreflightError as exc:
        return AuthState("unknown", f"snapshot failed: {str(exc)}")
    snap_ok, snap_payload = unwrap_result(snapshot)
    tree_text = extract_tree_text(snap_payload.get("tree")) if snap_payload else ""
    if not snap_ok:
        failure_class, reason = classify_failure(snap_payload or snapshot)
        return AuthState("unknown", f"snapshot failed: {failure_class}: {reason}")
    lowered = tree_text.casefold()
    if any(token in lowered for token in _SNAPSHOT_LOGIN_TOKENS) and len(tree_text) < 2000:
        state = AuthState("logged_out", "snapshot shows a login wall without substantive content", snapshot_tree=tree_text[:500])
    elif any(token in lowered for token in _SNAPSHOT_EMPTY_TOKENS):
        state = AuthState("unknown", "snapshot shows a challenge/captcha; cannot confirm login state", snapshot_tree=tree_text[:500])
    elif not tree_text.strip():
        state = AuthState("unknown", "snapshot returned no content", snapshot_tree="")
    else:
        state = AuthState("logged_in", "snapshot contains substantive content", snapshot_tree=tree_text[:500])
    if project_dir is not None:
        state.raw_capture_path = _save_auth_capture(project_dir, goal, task_id, url, state, snapshot)
    return state


def _save_auth_capture(project_dir: Path, goal: str, task_id: str, url: str, state: AuthState, snapshot: dict[str, Any]) -> str:
    """登录态检查证据落盘（原始 snapshot 信封 + 判定结果），供台账与审计引用。"""
    import json
    from datetime import datetime

    project_root = Path(project_dir).resolve()
    directory = project_root / "raw_capture" / _safe_goal(goal)
    directory.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", task_id or "task")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    payload = {
        "url": url,
        "auth_state": state.state,
        "reason": state.reason,
        "snapshot_tree": state.snapshot_tree,
        "raw_snapshot": snapshot,
    }
    target = directory / f"{safe}_auth_check_{stamp}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target.relative_to(project_root).as_posix()


def _safe_goal(goal: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", goal or "general") or "general"
