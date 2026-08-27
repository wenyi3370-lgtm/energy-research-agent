"""anysearch 后端：官方 CLI 零 diff 副本的子进程透传。

设计原则：
- CLI（scripts/anysearch/anysearch_cli.py）是官方 3.0.1 原样拷贝，本层只负责
  调用、原始输出落盘（raw_capture）、错误归一化，**不重解析**；
- 搜索结果条数提取是 best-effort（解析失败记 parse_failure 但保留原始输出）；
- 双路径：默认内嵌 CLI；--official-cli 可显式走官方 skill 的 CLI（行为逐字节一致）；
- 错误归一化：402/429→insufficient_balance；4xx→http_4xx；503→upstream_5xx
  （最多重试一次）；网络/超时→network_error/timeout。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from web_collection.errors import (
    ErrorClass,
    classify_text,
    extract_http_status,
    extract_retry_seconds,
    normalize_http_status,
    retry_allowed,
)

# 默认不再硬编码本机代理：容器/无代理机器上注入 127.0.0.1:7897 会让每次
# 搜索立即 ConnectionError（全部采集 network_error 归零）。需要代理的环境通过
# ANYSEARCH_PROXY 显式开启（如 http://127.0.0.1:7897）。
PROXY_HOST = os.environ.get("ANYSEARCH_PROXY", "").strip()

KNOWN_OFFICIAL_SKILL_DIRS = [
    Path.home() / ".claude" / "skills" / "anysearch",
    Path.home() / ".agents" / "skills" / "anysearch",
    Path.home() / ".codex" / "skills" / "anysearch",
]

_RESULT_COUNT_PATTERNS = [
    re.compile(r'"total_results"\s*:\s*(\d+)'),
    re.compile(r'"result_count"\s*:\s*(\d+)'),
    re.compile(r"Search Results \((\d+) results"),
    re.compile(r"(\d+)\s+results"),
]

# 额度耗尽时 API 返回 HTTP 200、CLI 退出码 0，正文只有这句话。不能按退出码
# 判成功：必须拦成 insufficient_balance，否则 journal 记 success、raw_capture
# 存满额度提示、台账登记空转（真实失败被当 500 次成功采集）。
# 用精确话术而非泛词（quota/402），避免误伤正常搜索结果中的政策/价格文本。
_QUOTA_EXHAUSTED_PATTERN = re.compile(
    r"reached your (?:api key['\u2019]?s? )?(?:total free|daily|free)?\s*quota", re.IGNORECASE
)


@dataclass
class AnySearchResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error_class: str = ErrorClass.NONE
    error_message: str = ""
    candidates_found: int | None = None
    raw_capture_path: str = ""
    cli_used: str = ""
    attempts: int = 1
    detail: dict[str, Any] = field(default_factory=dict)


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def embedded_cli_path() -> Path:
    return skill_root() / "anysearch" / "anysearch_cli.py"


def official_cli_path(explicit: str | os.PathLike | None = None) -> Path | None:
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        return candidate if candidate.is_file() else None
    env_dir = os.environ.get("ANYSEARCH_SKILL_DIR", "").strip()
    candidates = ([Path(env_dir)] if env_dir else []) + KNOWN_OFFICIAL_SKILL_DIRS
    for directory in candidates:
        candidate = directory / "scripts" / "anysearch_cli.py"
        if candidate.is_file():
            return candidate
    return None


def resolve_cli(official_cli: str | os.PathLike | None = None) -> Path:
    if official_cli:
        resolved = official_cli_path(official_cli)
        if resolved is None:
            raise FileNotFoundError(f"--official-cli path does not exist: {official_cli}")
        return resolved
    embedded = embedded_cli_path()
    if embedded.is_file():
        return embedded
    resolved = official_cli_path()
    if resolved is not None:
        return resolved
    raise FileNotFoundError(
        f"anysearch CLI not found: embedded at {embedded} is missing and no official skill is installed. "
        "Install the anysearch skill or restore scripts/anysearch/."
    )


def cli_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def embedded_cli_sha256() -> str | None:
    path = embedded_cli_path()
    return cli_sha256(path) if path.is_file() else None


def proxy_env() -> dict[str, str]:
    """按需设置代理环境变量（仅当调用方未设置时）。

    仅当 ANYSEARCH_PROXY 显式给出时才注入代理；否则继承当前环境（多数部署/容器
    无代理，注入不存在的本机代理会把每次搜索变成 ConnectionError）。
    本地回环地址（127.0.0.1/localhost）始终排除代理：避免本机 mock 服务器、
    本地桥接服务被代理软件劫持（返回 502）。
    """
    env = dict(os.environ)
    if PROXY_HOST:
        env.setdefault("HTTP_PROXY", PROXY_HOST)
        env.setdefault("HTTPS_PROXY", PROXY_HOST)
    no_proxy_parts = [part for part in env.get("NO_PROXY", "").split(",") if part.strip()]
    no_proxy_parts += ["127.0.0.1", "localhost"]
    env["NO_PROXY"] = ",".join(dict.fromkeys(no_proxy_parts))
    return env


def _invoke(
    args: list[str],
    *,
    official_cli: str | os.PathLike | None = None,
    timeout: int = 90,
    use_proxy: bool = True,
) -> subprocess.CompletedProcess[str]:
    cli = resolve_cli(official_cli)
    env = proxy_env() if use_proxy else dict(os.environ)
    return subprocess.run(
        [sys.executable, str(cli), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def _best_effort_result_count(stdout: str) -> int | None:
    """best-effort 提取候选数；失败返回 None（由调用方决定是否记 parse_failure）。"""
    if not stdout.strip():
        return None
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        for key in ("total_results", "result_count", "count"):
            value = parsed.get(key)
            if isinstance(value, int):
                return value
    for pattern in _RESULT_COUNT_PATTERNS:
        match = pattern.search(stdout)
        if match:
            return int(match.group(1))
    return None


def _normalize(
    completed: subprocess.CompletedProcess[str],
    *,
    candidates_found: int | None,
    raw_capture_path: str,
    cli_path: Path,
) -> AnySearchResult:
    if completed.returncode == 0:
        # 退出码 0 不代表成功：额度耗尽响应仍返回 0，先拦成失败。
        if _QUOTA_EXHAUSTED_PATTERN.search(completed.stdout or ""):
            return AnySearchResult(
                ok=False,
                stdout=completed.stdout,
                stderr=completed.stderr,
                error_class=ErrorClass.INSUFFICIENT_BALANCE,
                error_message=(completed.stdout.strip() or "free quota exhausted")[:2000],
                candidates_found=candidates_found,
                raw_capture_path=raw_capture_path,
                cli_used=str(cli_path),
            )
        return AnySearchResult(
            ok=True,
            stdout=completed.stdout,
            stderr=completed.stderr,
            candidates_found=candidates_found,
            raw_capture_path=raw_capture_path,
            cli_used=str(cli_path),
        )
    status_code = extract_http_status(completed.stderr)
    if status_code is not None:
        error_class = normalize_http_status(status_code, completed.stderr)
    else:
        # stderr 与 stdout 都扫描（修复短路：classify_text 返回 none 时继续扫 stdout）
        error_class = classify_text(completed.stderr)
        if error_class == ErrorClass.NONE:
            error_class = classify_text(completed.stdout)
        if error_class == ErrorClass.NONE:
            error_class = ErrorClass.NETWORK_ERROR
    message = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
    retry_seconds = extract_retry_seconds(message)
    if retry_seconds is not None:
        message = f"{message} [anysearch quota refresh: retry after {retry_seconds}s]"
    return AnySearchResult(
        ok=False,
        stdout=completed.stdout,
        stderr=completed.stderr,
        error_class=error_class,
        error_message=message[:2000],
        candidates_found=candidates_found,
        raw_capture_path=raw_capture_path,
        cli_used=str(cli_path),
        detail={"status_code": status_code, "retry_seconds": retry_seconds},
    )


def save_raw_capture(project_dir: Path, goal: str, task_id: str, filename: str, content: str) -> str:
    """原始输出落盘 raw_capture/<goal>/ 并返回项目相对路径。"""
    project_root = Path(project_dir).resolve()
    safe_goal = re.sub(r"[^A-Za-z0-9._-]+", "_", goal or "general") or "general"
    directory = project_root / "raw_capture" / safe_goal
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    target = directory / safe_name
    target.write_text(content, encoding="utf-8")
    return target.relative_to(project_root).as_posix()


def run_search(
    query: str,
    *,
    project_dir: Path,
    task_id: str,
    goal: str = "general",
    max_results: int | None = None,
    domain: str | None = None,
    sub_domain: str | None = None,
    sdp: str | None = None,
    official_cli: str | os.PathLike | None = None,
    round_number: str = "",
    timeout: int = 90,
) -> AnySearchResult:
    """search 透传（含一次 503/网络/超时重试）。"""
    args = ["search", query]
    if max_results is not None:
        args += ["--max_results", str(max(1, min(int(max_results), 10)))]
    if domain:
        args += ["--domain", domain]
    if sub_domain:
        args += ["--sub_domain", sub_domain]
    if sdp:
        args += ["--sdp", sdp]
    return _run_with_retry(
        args,
        project_dir=project_dir,
        task_id=task_id,
        goal=goal,
        action="search",
        official_cli=official_cli,
        timeout=timeout,
        count_from_stdout=True,
    )


def run_batch_search(
    queries: list[str],
    *,
    project_dir: Path,
    task_id: str,
    goal: str = "general",
    max_results: int | None = None,
    domain: str | None = None,
    sub_domain: str | None = None,
    sdp: str | None = None,
    official_cli: str | os.PathLike | None = None,
    timeout: int = 120,
) -> AnySearchResult:
    args = ["batch_search"]
    for query in queries[:5]:
        args += ["--query", query]
    if max_results is not None:
        args += ["--max_results", str(max(1, min(int(max_results), 10)))]
    if domain:
        args += ["--domain", domain]
    if sub_domain:
        args += ["--sub_domain", sub_domain]
    if sdp:
        args += ["--sdp", sdp]
    return _run_with_retry(
        args,
        project_dir=project_dir,
        task_id=task_id,
        goal=goal,
        action="batch_search",
        official_cli=official_cli,
        timeout=timeout,
        count_from_stdout=False,
    )


def run_extract(
    url: str,
    *,
    project_dir: Path,
    task_id: str,
    goal: str = "general",
    official_cli: str | os.PathLike | None = None,
    timeout: int = 120,
) -> AnySearchResult:
    args = ["extract", "--url", url]
    return _run_with_retry(
        args,
        project_dir=project_dir,
        task_id=task_id,
        goal=goal,
        action="extract",
        official_cli=official_cli,
        timeout=timeout,
        count_from_stdout=False,
    )


def run_get_sub_domains(
    domain: str,
    *,
    official_cli: str | os.PathLike | None = None,
    timeout: int = 60,
) -> AnySearchResult:
    args = ["get_sub_domains", "--domain", domain]
    cli = resolve_cli(official_cli)
    try:
        completed = _invoke(args, official_cli=official_cli, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return AnySearchResult(ok=False, error_class=ErrorClass.TIMEOUT, error_message=str(exc), cli_used=str(cli))
    except OSError as exc:
        return AnySearchResult(ok=False, error_class=ErrorClass.NETWORK_ERROR, error_message=str(exc), cli_used=str(cli))
    return _normalize(completed, candidates_found=None, raw_capture_path="", cli_path=cli)


def run_doc(official_cli: str | os.PathLike | None = None) -> str:
    cli = resolve_cli(official_cli)
    completed = _invoke(["doc"], official_cli=official_cli, timeout=60, use_proxy=False)
    return completed.stdout if completed.returncode == 0 else ""


def _run_with_retry(
    args: list[str],
    *,
    project_dir: Path,
    task_id: str,
    goal: str,
    action: str,
    official_cli: str | os.PathLike | None,
    timeout: int,
    count_from_stdout: bool,
) -> AnySearchResult:
    cli = resolve_cli(official_cli)
    retries_used = 0
    raw_capture_path = ""
    while True:
        try:
            completed = _invoke(args, official_cli=official_cli, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            result = AnySearchResult(
                ok=False,
                error_class=ErrorClass.TIMEOUT,
                error_message=str(exc),
                cli_used=str(cli),
                attempts=retries_used + 1,
            )
        except OSError as exc:
            result = AnySearchResult(
                ok=False,
                error_class=ErrorClass.NETWORK_ERROR,
                error_message=str(exc),
                cli_used=str(cli),
                attempts=retries_used + 1,
            )
        else:
            candidates = _best_effort_result_count(completed.stdout) if count_from_stdout else None
            if completed.returncode == 0:
                # 文件名带微秒时间戳：同一任务多次动作不得互相覆盖（原始留痕唯一性）
                from datetime import datetime

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                raw_capture_path = save_raw_capture(
                    project_dir, goal, task_id, f"{task_id}_{action}_{stamp}.md", completed.stdout
                )
            result = _normalize(
                completed, candidates_found=candidates, raw_capture_path=raw_capture_path, cli_path=cli
            )
            result.attempts = retries_used + 1
        if result.ok or not retry_allowed(result.error_class, retries_used):
            return result
        retries_used += 1
