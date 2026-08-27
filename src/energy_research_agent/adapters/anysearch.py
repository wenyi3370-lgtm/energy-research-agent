from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from energy_research_agent.vendor import embedded_skill_root

from .base import AdapterHealth, SearchHit, SearchRequest, SearchResultEnvelope


class AnySearchCliAdapter:
    """Direct adapter for the embedded AnySearch CLI.

    Search is fail-closed: this adapter never falls back to another search
    provider when AnySearch is unavailable or returns an error.
    """

    name = "anysearch"
    version = "3.0.1"

    def __init__(self, skill_root: Path | None = None, cli_path: Path | None = None) -> None:
        self.skill_root = Path(skill_root) if skill_root else embedded_skill_root("anysearch")
        self.cli_path = Path(cli_path) if cli_path else None
        # Health TTL: per-query calls must not restart the CLI subprocess for
        # every search/extract (live-run speed).
        self._health_cache: tuple[float, AdapterHealth] | None = None

    def _command_prefix(self) -> list[str] | None:
        prefixes = self._command_prefixes()
        return prefixes[0] if prefixes else None

    def _command_prefixes(self) -> list[list[str]]:
        candidates: list[Path]
        if self.cli_path:
            candidates = [self.cli_path]
        else:
            scripts = self.skill_root / "scripts"
            candidates = [
                scripts / "anysearch_cli.py",
                scripts / "anysearch_cli.js",
                scripts / "anysearch_cli.ps1",
                scripts / "anysearch_cli.sh",
            ]

        prefixes: list[list[str]] = []
        for path in candidates:
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".py" and importlib.util.find_spec("requests"):
                prefixes.append([sys.executable, str(path)])
            if suffix == ".js" and (node := shutil.which("node")):
                prefixes.append([node, str(path)])
            if suffix == ".ps1" and os.name == "nt" and (powershell := shutil.which("powershell")):
                prefixes.append([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)])
            if suffix == ".sh" and (bash := shutil.which("bash")) and shutil.which("curl") and shutil.which("jq"):
                prefixes.append([bash, str(path)])
        return prefixes

    def health(self, *, refresh: bool = False) -> AdapterHealth:
        import time as _time
        now = _time.monotonic()
        if not refresh and self._health_cache is not None and now - self._health_cache[0] < 120:
            return self._health_cache[1]
        result = self._health_probe()
        self._health_cache = (now, result)
        return result

    def _health_probe(self) -> AdapterHealth:
        prefixes = self._command_prefixes()
        required = [self.skill_root / "SKILL.md", self.skill_root / "LICENSE", self.skill_root / "NOTICE"]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            return AdapterHealth(
                name=self.name,
                available=False,
                version=self.version,
                diagnostics=["embedded AnySearch snapshot is incomplete", *missing],
            )
        if not prefixes:
            return AdapterHealth(
                name=self.name,
                available=False,
                version=self.version,
                diagnostics=["no supported AnySearch CLI runtime is available"],
            )
        try:
            result = subprocess.run(
                [*prefixes[0], "doc"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except Exception as exc:
            return AdapterHealth(name=self.name, available=False, version=self.version, diagnostics=[f"AnySearch health check failed: {exc}"])
        available = result.returncode == 0 and "AnySearch Interface Specification" in result.stdout
        diagnostics = [] if available else [(result.stderr or result.stdout or "AnySearch doc command failed").strip()]
        return AdapterHealth(name=self.name, available=available, version=self.version, diagnostics=diagnostics)

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        health = self.health()
        if not health.available:
            return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="blocked", diagnostics=health.diagnostics)

        prefixes = self._command_prefixes()
        assert prefixes
        url = request.metadata.get("url")
        domain = request.metadata.get("domain")
        sub_domain = request.metadata.get("sub_domain")
        sub_domain_params = request.metadata.get("sub_domain_params")

        if bool(domain) != bool(sub_domain):
            return SearchResultEnvelope(
                adapter=self.name,
                query_id=request.query_id,
                status="blocked",
                diagnostics=["vertical search requires both domain and sub_domain; call AnySearch get_sub_domains first"],
            )

        diagnostics: list[str] = []
        # Long-pole pages may hang on transport; bound each CLI call. The
        # default stays 180s (production); ANYSEARCH_CLI_TIMEOUT allows
        # faster fail-overs on slow/proxied networks.
        cli_timeout = int(os.environ.get("ANYSEARCH_CLI_TIMEOUT", "180"))
        for index, prefix in enumerate(prefixes):
            command = self._build_command(
                prefix,
                request,
                url=url,
                domain=domain,
                sub_domain=sub_domain,
                sub_domain_params=sub_domain_params,
            )
            runtime = Path(prefix[-1]).suffix.lower().lstrip(".") or Path(prefix[0]).name
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=cli_timeout,
                )
            except Exception as exc:
                diagnostics.append(f"{runtime} runtime exception: {type(exc).__name__}: {exc}")
                continue

            output = result.stdout.strip()
            if result.returncode != 0:
                error_text = (result.stderr or output or "AnySearch command failed").strip()
                diagnostics.append(f"{runtime} failed: {error_text}")
                if runtime == "py" and "connection error" in error_text.lower():
                    diagnostics.extend(self._proxy_diagnostics())
                continue
            provider_error = self._provider_error_message(output)
            if provider_error:
                # Some AnySearch runtimes exit 0 while returning a plain-text
                # quota/auth/rate-limit notice. Treating that notice as page
                # content creates fake material evidence and false "no data"
                # exhaustion. This is an infrastructure block, not a hit.
                return SearchResultEnvelope(
                    adapter=self.name,
                    query_id=request.query_id,
                    status="blocked",
                    hits=[],
                    diagnostics=[*diagnostics, f"{runtime} provider blocked: {provider_error}"],
                )
            hits = self._parse_output(output, requested_url=str(url) if url else None)
            if hits:
                if index:
                    diagnostics.append(f"AnySearch recovered with {runtime} after {index} failed runtime(s)")
                return SearchResultEnvelope(
                    adapter=self.name,
                    query_id=request.query_id,
                    status="ok",
                    hits=hits,
                    diagnostics=diagnostics,
                )
            return SearchResultEnvelope(
                adapter=self.name,
                query_id=request.query_id,
                status="partial",
                hits=[],
                diagnostics=[*diagnostics, f"{runtime} returned no parseable result"],
            )

        return SearchResultEnvelope(
            adapter=self.name,
            query_id=request.query_id,
            status="error",
            diagnostics=diagnostics or ["Every bundled AnySearch CLI runtime failed"],
        )

    @staticmethod
    def _provider_error_message(output: str) -> str | None:
        text = " ".join((output or "").strip().split())
        folded = text.casefold()
        if not text or len(text) > 1000 or "http://" in folded or "https://" in folded:
            return None
        markers = (
            "total free quota", "quota exceeded", "insufficient quota",
            "rate limit exceeded", "too many requests", "invalid api key",
            "unauthorized", "access denied", "api key is required",
            # Anonymous mode sometimes answers with an auto-registration
            # notice instead of search results; parsing that notice as a
            # hit manufactures fake "raw capture" with zero facts.
            "automatically generated", "use the api key below",
            "免费额度", "额度已用完", "请求过于频繁", "无效的 api key",
        )
        return text[:500] if any(marker in folded for marker in markers) else None

    @staticmethod
    def _build_command(
        prefix: list[str],
        request: SearchRequest,
        *,
        url: object,
        domain: object,
        sub_domain: object,
        sub_domain_params: object,
    ) -> list[str]:
        # Runtime account rotation is carried only in the child process
        # environment. Never place a credential in argv: process listings and
        # timeout diagnostics may expose command-line arguments.
        base = list(prefix)
        if url:
            return [*base, "extract", str(url)]
        command = [*base, "search", request.query, "--max_results", str(min(request.max_results, 10))]
        if domain and sub_domain:
            command.extend(["--domain", str(domain), "--sub_domain", str(sub_domain)])
            if sub_domain_params is not None:
                value = sub_domain_params if isinstance(sub_domain_params, str) else json.dumps(sub_domain_params, ensure_ascii=False)
                command.extend(["--sdp", value])
        return command

    @staticmethod
    def _proxy_diagnostics() -> list[str]:
        proxies = urllib.request.getproxies()
        if not proxies:
            return ["Python reported a connection failure and no system proxy was discovered"]
        safe: list[str] = []
        for scheme in sorted(proxies):
            value = str(proxies[scheme])
            if "@" in value:
                value = value.split("://", 1)[0] + "://***@" + value.split("@", 1)[1]
            safe.append(f"{scheme}={value}")
        return ["Python inherited system proxy settings: " + ", ".join(safe)]

    @classmethod
    def _parse_output(cls, output: str, requested_url: str | None = None) -> list[SearchHit]:
        now = datetime.now(timezone.utc).isoformat()
        if not output or not output.strip():
            return []
        try:
            payload: Any = json.loads(output)
        except json.JSONDecodeError:
            hits = cls._parse_markdown_results(output, requested_url)
            if hits:
                return hits
            return [
                SearchHit(
                    requested_url=requested_url,
                    final_url=requested_url,
                    text=output,
                    status="partial",
                    retrieved_at=now,
                    metadata={"format": "markdown"},
                )
            ] if output else []

        raw_hits = cls._find_result_items(payload)
        hits: list[SearchHit] = []
        for item in raw_hits:
            url = item.get("url") or item.get("link") or item.get("source_url") or requested_url
            text = item.get("content") or item.get("text") or item.get("snippet") or item.get("description")
            hits.append(
                SearchHit(
                    requested_url=requested_url or url,
                    final_url=url,
                    title=item.get("title") or item.get("name"),
                    text=str(text) if text is not None else None,
                    status="ok" if (url or text) else "partial",
                    retrieved_at=now,
                    # Search-result text is a snippet: discovery-only. The
                    # extractor downgrades snippet-derived batches to SOURCE_D.
                    metadata={"format": "json", "raw": item, "snippet": True},
                )
            )
        if not hits and isinstance(payload, dict):
            text = payload.get("content") or payload.get("text") or payload.get("result")
            if isinstance(text, str) and text.strip():
                hits.append(SearchHit(
                    requested_url=requested_url,
                    final_url=requested_url,
                    text=text,
                    status="partial",
                    retrieved_at=now,
                    metadata={"format": "json", "raw": payload},
                ))
        return hits

    @classmethod
    def _parse_markdown_results(cls, output: str, requested_url: str | None = None) -> list[SearchHit]:
        """Parse the CLI's markdown result format.

        The embedded AnySearch CLI prints results as::

            ## Search Results (3 results, 2214ms)
            ### 1. <title>
            - **URL**: https://...
            <body lines until the next ### heading>

        JSON mode is preferred when available; this parser recovers the
        same fields (title/url/text) from the markdown rendering so the
        real research pipeline can consume adapter output.
        """
        import re

        now = datetime.now(timezone.utc).isoformat()
        blocks: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in output.splitlines():
            stripped = line.strip()
            title_match = re.match(r"^###\s+\d+\.\s+(.+)$", stripped)
            if title_match:
                if current:
                    blocks.append(current)
                current = {"title": title_match.group(1).strip(), "lines": []}
                continue
            url_match = re.match(r"^-\s*\*\*URL\*\*:\s*(\S+)$", stripped)
            if current is not None and url_match:
                current["url"] = url_match.group(1)
                continue
            if current is not None and stripped and not stripped.startswith("##"):
                current["lines"].append(stripped)
        if current:
            blocks.append(current)

        hits: list[SearchHit] = []
        for block in blocks:
            url = block.get("url") or requested_url
            text = "\n".join(block.get("lines", []))
            hits.append(SearchHit(
                requested_url=requested_url or url,
                final_url=url,
                title=block.get("title"),
                text=text or None,
                status="ok" if (url and text) else "partial",
                retrieved_at=now,
                metadata={"format": "markdown", "snippet": True},
            ))
        return hits

    @classmethod
    def _find_result_items(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            direct = [item for item in payload if isinstance(item, dict)]
            if direct:
                return direct
        if isinstance(payload, dict):
            for key in ("results", "hits", "items", "documents", "data", "result"):
                if key not in payload:
                    continue
                value = payload[key]
                if isinstance(value, list):
                    direct = [item for item in value if isinstance(item, dict)]
                    if direct:
                        return direct
                nested = cls._find_result_items(value)
                if nested:
                    return nested
        return []


AnySearchAdapter = AnySearchCliAdapter
