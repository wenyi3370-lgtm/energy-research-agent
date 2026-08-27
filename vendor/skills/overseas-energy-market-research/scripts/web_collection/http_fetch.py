"""静态网页/PDF/结构化数据抓取回退适配器。

定位：anysearch extract 失败（或 anysearch 不可用）时的静态回退路径；
动态页/需要登录的页面不在此处理，必须走 kimi-webbridge。
规则：503 重试一次、4xx 不重试、402/429→insufficient_balance、登录墙→auth_required。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from web_collection.errors import ErrorClass, normalize_http_status, retry_allowed

DEFAULT_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_LOGIN_TOKENS = ("log in", "login", "sign in", "password", "登录", "密码", "authenticate")


@dataclass
class FetchResult:
    ok: bool
    content_type: str = ""
    text: str = ""
    raw_text: str = ""  # 原始响应文本（HTML/JSON），用于原始留痕
    error_class: str = ErrorClass.NONE
    error_message: str = ""
    attempts: int = 1
    status_code: int | None = None


def _is_login_wall(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(token in lowered for token in _LOGIN_TOKENS)


def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "nav", "footer", "form"]):
        node.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    lines: list[str] = []
    if title:
        lines.append(f"# {title}")
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        text = heading.get_text(strip=True)
        if text:
            level = int(heading.name[1])
            lines.append(f"{'#' * level} {text}")
    for paragraph in soup.find_all("p"):
        text = paragraph.get_text(strip=True)
        if text:
            lines.append(text)
    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if rows:
            lines.append("")
            for row in rows:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
    return "\n\n".join(lines).strip()


def fetch_url(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    """静态抓取：HTML→Markdown、JSON→原样文本、PDF→文本占位提示（PDF 走 markitdown 转换）。"""
    retries_used = 0
    while True:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.exceptions.Timeout as exc:
            result = FetchResult(ok=False, error_class=ErrorClass.TIMEOUT, error_message=str(exc), attempts=retries_used + 1)
        except requests.exceptions.RequestException as exc:
            result = FetchResult(ok=False, error_class=ErrorClass.NETWORK_ERROR, error_message=str(exc), attempts=retries_used + 1)
        else:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().casefold()
            status_code = response.status_code
            if status_code != 200:
                error_class = normalize_http_status(status_code, response.text[:2000])
                result = FetchResult(
                    ok=False,
                    content_type=content_type,
                    error_class=error_class,
                    error_message=f"HTTP {status_code}",
                    attempts=retries_used + 1,
                    status_code=status_code,
                )
            elif content_type.endswith("json"):
                result = FetchResult(
                    ok=True, content_type=content_type, text=response.text, raw_text=response.text,
                    attempts=retries_used + 1, status_code=status_code,
                )
            elif content_type.endswith("pdf") or url.casefold().endswith(".pdf"):
                result = FetchResult(
                    ok=False,
                    content_type=content_type,
                    error_class=ErrorClass.PARSE_FAILURE,
                    error_message="PDF requires markitdown conversion (see convert_pdf_to_markdown)",
                    attempts=retries_used + 1,
                    status_code=status_code,
                )
            else:
                text = _html_to_markdown(response.text)
                if _is_login_wall(text) and len(text) < 500:
                    result = FetchResult(
                        ok=False,
                        content_type=content_type,
                        text=text,
                        raw_text=response.text,
                        error_class=ErrorClass.AUTH_REQUIRED,
                        error_message="Static fetch hit a login wall; route to kimi-webbridge for authenticated browsing",
                        attempts=retries_used + 1,
                        status_code=status_code,
                    )
                else:
                    result = FetchResult(
                        ok=True, content_type=content_type, text=text, raw_text=response.text,
                        attempts=retries_used + 1, status_code=status_code,
                    )
        if result.ok or not retry_allowed(result.error_class, retries_used):
            return result
        retries_used += 1


def convert_pdf_to_markdown(pdf_path: Path) -> str:
    """PDF → Markdown（markitdown，已在 requirements.txt）。"""
    try:
        from markitdown import MarkItDown

        converter = MarkItDown()
        result = converter.convert(str(pdf_path))
        return result.text_content or ""
    except ImportError as exc:
        raise RuntimeError("markitdown is required for PDF conversion; install requirements.txt") from exc
