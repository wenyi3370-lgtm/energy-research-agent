"""归一化错误分类（联网采集执行层）。

规则（与 kimi-webbridge-collection-playbooks.md 一致）：
- 402/429 归一化为 insufficient_balance（不盲目重试）；
- 其他 4xx 归一化为 http_4xx（不盲目重试）；
- 503 归一化为 upstream_5xx（最多重试一次）；
- 网络/超时归一化为 network_error / timeout；
- 登录墙/认证归一化为 auth_required；
- kimi 插件未连接/daemon 未运行归一化为 bridge_unavailable；
- 采集工具不可用（CLI 缺失）归一化为 tool_unavailable；
- 解析失败归一化为 parse_failure（原始输出必须保留，不得冒充成功）。
"""
from __future__ import annotations

import re
from typing import Any


class ErrorClass:
    INSUFFICIENT_BALANCE = "insufficient_balance"
    AUTH_REQUIRED = "auth_required"
    HTTP_4XX = "http_4xx"
    UPSTREAM_5XX = "upstream_5xx"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    PARSE_FAILURE = "parse_failure"
    BRIDGE_UNAVAILABLE = "bridge_unavailable"
    TOOL_UNAVAILABLE = "tool_unavailable"
    NONE = "none"


ERROR_CLASSES = frozenset(
    {
        ErrorClass.INSUFFICIENT_BALANCE,
        ErrorClass.AUTH_REQUIRED,
        ErrorClass.HTTP_4XX,
        ErrorClass.UPSTREAM_5XX,
        ErrorClass.NETWORK_ERROR,
        ErrorClass.TIMEOUT,
        ErrorClass.PARSE_FAILURE,
        ErrorClass.BRIDGE_UNAVAILABLE,
        ErrorClass.TOOL_UNAVAILABLE,
        ErrorClass.NONE,
    }
)

# 503 类错误最多重试一次（RETRYABLE_5XX 为 True 且仍有重试次数时）
RETRYABLE_CLASSES = frozenset({ErrorClass.UPSTREAM_5XX, ErrorClass.NETWORK_ERROR, ErrorClass.TIMEOUT})
MAX_RETRIES = 1

_BALANCE_TOKENS = ("402", "429", "insufficient", "balance", "quota", "credit", "余额", "积分", "rate limited")
_AUTH_TOKENS = ("login", "sign in", "log in", "password", "authenticate", "登录", "密码", "unauthorized", "forbidden", "auth")


class CollectionError(RuntimeError):
    """带归一化错误分类的采集异常。"""

    def __init__(
        self,
        error_class: str,
        message: str,
        *,
        retryable: bool = False,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.retryable = retryable
        self.detail = detail or {}


def normalize_http_status(status_code: int | None, body_text: str = "") -> str:
    """HTTP 状态码 → 归一化错误类。"""
    if status_code in (402, 429):
        return ErrorClass.INSUFFICIENT_BALANCE
    if status_code in (401, 403):
        # 认证/授权失败优先归为登录墙类（与"绝不假装采集完成"一致）
        return ErrorClass.AUTH_REQUIRED
    if status_code is not None and 400 <= status_code < 500:
        return ErrorClass.HTTP_4XX
    if status_code == 503:
        return ErrorClass.UPSTREAM_5XX
    if status_code is not None and status_code >= 500:
        return ErrorClass.UPSTREAM_5XX
    lowered = body_text.casefold()
    if any(token in lowered for token in _BALANCE_TOKENS):
        return ErrorClass.INSUFFICIENT_BALANCE
    if any(token in lowered for token in _AUTH_TOKENS):
        return ErrorClass.AUTH_REQUIRED
    return ErrorClass.NETWORK_ERROR


def classify_text(text: str) -> str:
    """把工具输出/错误文本归一化为错误类（无状态码时的启发式）。"""
    lowered = (text or "").casefold()
    if any(token in lowered for token in _BALANCE_TOKENS):
        return ErrorClass.INSUFFICIENT_BALANCE
    if any(token in lowered for token in _AUTH_TOKENS):
        return ErrorClass.AUTH_REQUIRED
    if "connection error" in lowered or "unable to reach" in lowered or "connection refused" in lowered:
        return ErrorClass.NETWORK_ERROR
    if "timed out" in lowered or "timeout" in lowered or "超时" in lowered:
        return ErrorClass.TIMEOUT
    if "503" in lowered or "502" in lowered or "service unavailable" in lowered or "bad gateway" in lowered:
        return ErrorClass.UPSTREAM_5XX
    return ErrorClass.NONE


_RATE_LIMITED_PATTERN = re.compile(r"rate limited[^\d]{0,40}?(\d+)\s*(?:seconds?|秒)")


def extract_retry_seconds(text: str) -> int | None:
    """从 'Rate limited, retry after 300 seconds.' 提取重试秒数（官方额度刷新信号）。"""
    match = _RATE_LIMITED_PATTERN.search((text or "").casefold())
    if match:
        return int(match.group(1))
    return None


def retry_allowed(error_class: str, retries_used: int) -> bool:
    """503/网络/超时类错误且未用尽重试次数时允许重试一次。"""
    return error_class in RETRYABLE_CLASSES and retries_used < MAX_RETRIES


def extract_http_status(text: str) -> int | None:
    """从工具 stderr/stdout 中提取 HTTP 状态码（如 'HTTP Error: 503'）。"""
    lowered = (text or "").casefold()
    marker = "http error:"
    index = lowered.find(marker)
    if index < 0:
        return None
    tail = lowered[index + len(marker):].strip().splitlines()[0]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return int(digits) if digits else None


_KIMI_TO_UNIFIED = {
    "access_authentication": ErrorClass.AUTH_REQUIRED,
    "challenge": ErrorClass.AUTH_REQUIRED,
    "extension_disconnected": ErrorClass.BRIDGE_UNAVAILABLE,
    "daemon_stopped": ErrorClass.BRIDGE_UNAVAILABLE,
    "not_installed": ErrorClass.BRIDGE_UNAVAILABLE,
    "version_mismatch": ErrorClass.TOOL_UNAVAILABLE,
    "empty_snapshot": ErrorClass.PARSE_FAILURE,
    "synthetic_event_limitation": ErrorClass.PARSE_FAILURE,
    "wrong_current_tab": ErrorClass.PARSE_FAILURE,
    "timeout": ErrorClass.TIMEOUT,
}


def normalize_kimi_error_class(failure_class: str) -> str:
    """把 _kimi_webbridge 的故障分类归一为统一 ErrorClass（台账用统一类）。"""
    return _KIMI_TO_UNIFIED.get(str(failure_class or "").strip(), str(failure_class or "").strip() or ErrorClass.NONE)
