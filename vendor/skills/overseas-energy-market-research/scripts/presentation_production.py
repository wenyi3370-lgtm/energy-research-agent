from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PIPELINE_ID = "embedded-pptmaster-svg-v1"
RENDERER_ID = "embedded-native-pptx-renderer-v1"
IMAGE_PIPELINE_ID = "embedded-ewo-image-acquisition-v1"
ALLOWED_RASTER_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
ALLOWED_FALLBACK_CODES = {
    "insufficient_balance",
    "connection_unavailable",
    "credential_unavailable",
    "permission_disabled",
    "upstream_timeout",
    "upstream_failure",
    "global_image_generation_disabled",
}
PLACEHOLDER_RE = re.compile(r"\[\[[^\]]+\]\]|\b(?:lorem ipsum|placeholder|xxxx+)\b", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_path(path: Path, project_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def resolve_path(value: str | Path, project_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_dir / path).resolve()


def detect_raster_format(path: Path) -> str | None:
    with path.open("rb") as handle:
        header = handle.read(12)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def slide_count(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        return sum(
            1
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )


def pptx_media_hashes(path: Path) -> set[str]:
    hashes: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("ppt/media/") and not name.endswith("/"):
                hashes.add(hashlib.sha256(archive.read(name)).hexdigest())
    return hashes


def validate_raster(path: Path) -> tuple[str, str]:
    expected = ALLOWED_RASTER_FORMATS.get(path.suffix.lower())
    if expected is None:
        raise ValueError(f"Image must be PNG, JPEG, or WebP: {path}")
    actual = detect_raster_format(path)
    if actual != expected:
        raise ValueError(f"Image bytes do not match the {expected} extension: {path}")
    return actual, sha256_file(path)


def normalize_fallback_reason(code: str, detail: str) -> dict[str, str]:
    code = code.strip().casefold()
    if code not in ALLOWED_FALLBACK_CODES:
        code = "upstream_failure"
    detail = detail.strip() or code
    return {"code": code, "detail": detail}


def classify_ewo_failure(status: int | None, code: str, message: str) -> dict[str, str]:
    normalized_code = (code or "").upper()
    text = f"{code} {message}".casefold()
    if status in {402, 429} and "insufficient" in text:
        return normalize_fallback_reason("insufficient_balance", message or code)
    if normalized_code == "AGENT_SKILL_NOT_ENABLED" or status == 403:
        return normalize_fallback_reason("permission_disabled", message or code)
    if status == 401:
        return normalize_fallback_reason("credential_unavailable", message or code)
    if status in {408, 504} or "timeout" in text:
        return normalize_fallback_reason("upstream_timeout", message or code)
    if status is None and any(token in text for token in ("refused", "unreachable", "connect")):
        return normalize_fallback_reason("connection_unavailable", message or code)
    return normalize_fallback_reason("upstream_failure", message or code or f"HTTP {status}")


@dataclass(frozen=True)
class EwoCredentials:
    origin: str
    key: str
    source: str
    agent_id: str


def resolve_ewo_credentials() -> EwoCredentials:
    import os

    try:
        import tomllib  # Python 3.11+
    except ImportError:  # Python 3.10 fallback
        import tomli as tomllib  # type: ignore[no-redef]

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if base_url.startswith("http://127.0.0.1:") and token:
        return EwoCredentials(base_url, token, "managed_launch", "claude-code")

    config_path = Path.home() / ".codex" / "config.toml"
    auth_path = Path.home() / ".codex" / "auth.json"
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
            provider = ((config.get("model_providers") or {}).get("ewo") or {})
            origin = str(provider.get("base_url") or "").strip().removesuffix("/v1").rstrip("/")
            key = str(provider.get("experimental_bearer_token") or "").strip()
            if not key and auth_path.exists():
                key = str(json.loads(auth_path.read_text(encoding="utf-8-sig")).get("OPENAI_API_KEY") or "").strip()
            if origin and key:
                return EwoCredentials(origin, key, "codex_config", "codex")
        except (OSError, ValueError, TypeError):
            pass

    fallback_token = Path.home() / ".ewo" / ".habitat-local-proxy-token"
    if fallback_token.exists():
        key = fallback_token.read_text(encoding="utf-8-sig").strip()
        if key:
            agent_id = os.environ.get("EWO_AGENT_ID", "claude-code").strip() or "claude-code"
            if agent_id not in {"claude-code", "codex", "hermes", "openclaw"}:
                raise RuntimeError(f"Unsupported EWO_AGENT_ID: {agent_id}")
            return EwoCredentials("http://127.0.0.1:18799", key, "desktop_proxy", agent_id)
    raise RuntimeError("EWO credentials are unavailable; no usable managed, Codex, or desktop-proxy credential was found.")


def _request_json(url: str, key: str, payload: dict[str, Any] | None, *, timeout: int) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"code": f"HTTP_{exc.code}", "message": raw[:500]}
        return exc.code, body


def _save_ewo_result(payload: dict[str, Any], output: Path, *, timeout: int) -> None:
    data = (((payload.get("result") or {}).get("response") or {}).get("data") or [])
    if not data:
        raise RuntimeError("EWO succeeded without image data")
    item = data[0] or {}
    output.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        output.write_bytes(base64.b64decode(item["b64_json"], validate=True))
        return
    if item.get("url"):
        request = urllib.request.Request(str(item["url"]), method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            output.write_bytes(response.read())
        return
    raise RuntimeError("EWO succeeded without b64_json or URL")


def invoke_ewo_image(
    prompt: str,
    output: Path,
    *,
    size: str = "1536x1024",
    output_format: str = "png",
    quality: str = "high",
    model: str = "gpt-image-2",
    timeout: int = 180,
) -> dict[str, Any]:
    credentials = resolve_ewo_credentials()
    body = {
        "agent_id": credentials.agent_id,
        "skill_id": "habitat.image.generate",
        "tool_name": "habitat_image_generate",
        "model_alias": model,
        "arguments": {
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "background": "opaque",
            "output_format": output_format,
        },
    }
    endpoint = f"{credentials.origin}/api/v1/capabilities/invoke"
    status, response = _request_json(endpoint, credentials.key, body, timeout=timeout)
    if status == 503:
        status, response = _request_json(endpoint, credentials.key, body, timeout=timeout)
    state = str(response.get("status") or "").casefold()
    invocation_id = str(response.get("id") or "")
    if status < 400 and state in {"accepted", "running"} and invocation_id:
        import time

        poll_url = f"{credentials.origin}/api/v1/capabilities/invocations/{invocation_id}/result"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(3)
            status, response = _request_json(poll_url, credentials.key, None, timeout=min(30, timeout))
            state = str(response.get("status") or "").casefold()
            if state in {"succeeded", "failed"} or status >= 400:
                break
        else:
            raise TimeoutError("EWO image invocation timed out")
    if status >= 400 or state == "failed":
        code = str(response.get("code") or ((response.get("error") or {}).get("code") or ""))
        message = str(response.get("message") or ((response.get("error") or {}).get("message") or ""))
        failure = classify_ewo_failure(status, code, message)
        raise RuntimeError(json.dumps(failure, ensure_ascii=False))
    if state != "succeeded":
        raise RuntimeError(json.dumps(classify_ewo_failure(status, "", f"Unexpected EWO state: {state}"), ensure_ascii=False))
    _save_ewo_result(response, output, timeout=timeout)
    image_format, digest = validate_raster(output)
    return {
        "provider": "ewo",
        "credential_source": credentials.source,
        "agent_id": credentials.agent_id,
        "format": image_format,
        "sha256": digest,
        "model": model,
    }
