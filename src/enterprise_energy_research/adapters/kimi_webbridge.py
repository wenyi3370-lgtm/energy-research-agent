from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise_energy_research.vendor import embedded_skill_root

from .base import AdapterHealth, SearchHit, SearchRequest, SearchResultEnvelope


class KimiWebBridgeSearchAdapter:
    name = "kimi_webbridge"

    def __init__(self, session: str, *, daemon_url: str = "http://127.0.0.1:10086", skill_root: Path | None = None) -> None:
        self.session = session
        self.daemon_url = daemon_url.rstrip("/")
        self.skill_root = skill_root or embedded_skill_root("kimi-webbridge")
        self.command_timeout_seconds = max(
            5, min(30, int(os.environ.get("KIMI_WEBBRIDGE_TIMEOUT_SECONDS", "15")))
        )
        # Per-run usage telemetry (P0-14): routing alone is not usage.
        from enterprise_energy_research.research.image_discovery import KimiUsageTelemetry
        self.usage = KimiUsageTelemetry()
        # The daemon's single-tab actions (snapshot/evaluate) act on the
        # session's CURRENT tab.  Concurrent research workers sharing one
        # session would otherwise interleave navigate/snapshot and hit
        # "No tab with given id" races, so serialize every browser
        # transaction per adapter instance.
        self._op_lock = threading.Lock()

    @staticmethod
    def _binary() -> Path | None:
        home = Path.home()
        for candidate in (home / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe", home / ".kimi-webbridge" / "bin" / "kimi-webbridge"):
            if candidate.is_file():
                return candidate
        found = shutil.which("kimi-webbridge")
        return Path(found) if found else None

    def health(self) -> AdapterHealth:
        required = (self.skill_root / "SKILL.md", self.skill_root / "references" / "operations.md")
        missing = [str(path.relative_to(self.skill_root)) for path in required if not path.is_file()]
        if missing:
            return AdapterHealth(name=self.name, available=False, diagnostics=["Embedded Kimi WebBridge instructions are incomplete: " + ", ".join(missing)])
        # 方式 1：本地二进制 status（宿主机/Windows 场景）
        binary = self._binary()
        if binary:
            try:
                result = subprocess.run([str(binary), "status"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
                payload = json.loads(result.stdout.strip().splitlines()[0])
                available = bool(payload.get("running") and payload.get("extension_connected"))
                diagnostics: list[str] = []
                if not payload.get("running"):
                    diagnostics.append("daemon is not running")
                if payload.get("running") and not payload.get("extension_connected"):
                    diagnostics.append("browser extension is not connected")
                return AdapterHealth(name=self.name, available=available,
                                     version=str(payload.get("version", "unknown")), diagnostics=diagnostics)
            except Exception:  # noqa: BLE001 - fall through to HTTP probe
                pass
        # 方式 2：HTTP 探测 daemon（容器场景：Windows .exe 不可执行，
        # 通过 host.docker.internal 访问宿主机 daemon）
        try:
            payload = self._command("list_tabs", {})
            # daemon 可达即视为可用（list_tabs 成功 = daemon 运行 + 扩展已连）
            return AdapterHealth(
                name=self.name, available=True, version="daemon",
                diagnostics=["daemon reachable via " + self.daemon_url],
            )
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(
                name=self.name, available=False,
                diagnostics=[f"daemon unreachable ({self.daemon_url}): {str(exc)[:120]}"],
            )

    def _command(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"action": action, "args": args, "session": self.session}).encode("utf-8")
        request = urllib.request.Request(f"{self.daemon_url}/command", data=body, headers={"Content-Type": "application/json"}, method="POST")
        # The daemon is loopback-only.  Always bypass HTTP(S)_PROXY here so an
        # optional outbound proxy cannot accidentally capture local bridge
        # control traffic.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=self.command_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok") is False:
            raise OSError(str(payload.get("error") or "Kimi WebBridge command failed"))
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def navigate_to(self, url: str, *, new_tab: bool = False) -> dict[str, Any]:
        """Open a REAL target page (deep research), not a search-result page."""
        self.usage.kimi_pages_visited += 1
        if url and not url.startswith(("http://", "https://")):
            raise ValueError(f"target page must be an absolute URL: {url}")
        return self._command("navigate", {
            "url": url,
            "newTab": new_tab,
            "group_title": "企业产业与能源调研",
        })

    def evaluate(self, code: str) -> dict[str, Any]:
        """Run JS in the current page and return the value (DOM inspection)."""
        self.usage.kimi_dom_inspections += 1
        payload = self._command("evaluate", {"code": code})
        if isinstance(payload, dict) and "value" in payload:
            return payload["value"] if isinstance(payload["value"], dict) else {"value": payload["value"]}
        return payload

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        health = self.health()
        if not health.available:
            self.usage.kimi_status = "BLOCKED"
            self.usage.reason = "browser daemon/extension unavailable: " + "; ".join(health.diagnostics)
            return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="blocked", diagnostics=health.diagnostics)
        self.usage.kimi_status = "AVAILABLE"
        self.usage.kimi_queries += 1
        url = request.metadata.get("url") or ("https://www.bing.com/search?q=" + urllib.parse.quote(request.query))
        is_target_page = bool(request.metadata.get("url"))
        try:
            with self._op_lock:
                navigation = self._navigate_with_retry(url)
                if is_target_page:
                    self.usage.kimi_target_pages_visited += 1
                snapshot = self._command("snapshot", {})
            tree = str(snapshot.get("tree", ""))
            final_url = str(snapshot.get("url") or navigation.get("url") or url)
            # Browser error pages (navigation failures) are not sources.
            if not final_url.lower().startswith(("http://", "https://")):
                self.usage.kimi_status = "BLOCKED"
                self.usage.reason = f"navigation did not reach a real page for {url}"
                return SearchResultEnvelope(
                    adapter=self.name, query_id=request.query_id, status="error",
                    diagnostics=[f"navigation error page for {url}"],
                )
            return SearchResultEnvelope(
                adapter=self.name,
                query_id=request.query_id,
                status="ok" if tree else "partial",
                hits=[SearchHit(
                    requested_url=url,
                    final_url=final_url,
                    title=str(snapshot.get("title") or ""),
                    text=tree,
                    status="ok" if tree else "partial",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    diagnostics=[] if tree else ["empty accessibility snapshot"],
                    metadata={"tab_id": navigation.get("tabId"), "target_page": is_target_page},
                )],
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self.usage.kimi_status = "BLOCKED"
            self.usage.reason = f"webbridge command failed: {type(exc).__name__}: {exc}"
            return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="error", diagnostics=[f"webbridge command failed: {type(exc).__name__}: {exc}"])

    def _navigate_with_retry(self, url: str) -> dict[str, Any]:
        """Navigate reusing the session tab; recover from a dead tab once.

        ``newTab=True`` on every call leaked tabs until the browser dropped
        them, after which snapshot failed with ``No tab with given id``.
        Reusing the current tab keeps the session at one tab; if the daemon
        reports a stale/missing tab, one retry opens a fresh tab.
        """
        try:
            return self.navigate_to(url, new_tab=False)
        except OSError as exc:
            message = str(exc)
            if "no tab with given id" not in message.casefold():
                raise
            return self.navigate_to(url, new_tab=True)


KimiWebBridgeAdapter = KimiWebBridgeSearchAdapter
