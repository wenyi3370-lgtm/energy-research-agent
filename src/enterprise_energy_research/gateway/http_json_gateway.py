"""Dependency-free HTTP JSON gateway (OpenAI-compatible chat/completions).

Fallback for environments where LiteLLM cannot be installed (blocked package
index). Keeps the provider-neutral contract: DeepSeek primary, OpenAI
fallback, structured output via ``response_format: json_object`` plus strict
pydantic re-validation, bounded transient retry. No new dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from enterprise_energy_research.settings import Settings

from .base import GatewayError, ModelRequest, ModelResponse, StructuredRequest

T = TypeVar("T")

SYSTEM_HINT = (
    "You are an evidence-extraction engine. Reply with a single JSON object "
    "that exactly matches the requested schema. Never invent values that are "
    "not present in the supplied page text. Respond with JSON only."
)


def prune_to_schema(value: Any, schema: dict[str, Any], *, path: str = "", defs: dict[str, Any] | None = None) -> Any:
    """Recursively drop schema-unknown keys and untrustworthy records.

    - Unknown keys (LLM extras) are removed at every level ($ref resolved).
    - Entries under an ``images`` list are removed entirely: pixel dimensions,
      sha256 and phash cannot be derived from page text, and image evidence is
      owned by the browser image-discovery pipeline (P0-15/16).
    """
    if defs is None:
        defs = schema.get("$defs", {})
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = defs.get(name, {})
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        pruned: dict[str, Any] = {}
        for key, item in value.items():
            if key not in properties:
                continue
            pruned[key] = prune_to_schema(item, properties[key], path=f"{path}.{key}", defs=defs)
        # Value repair: models emit relative/invalid URLs for optional URL
        # fields. Drop them (never invent a base) so one bad value cannot
        # sink the whole page extraction.
        for key in ("official_website", "source_url", "canonical_url"):
            if key in pruned and isinstance(pruned[key], str) and pruned[key]:
                parsed = urllib.parse.urlparse(pruned[key])
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    pruned[key] = None
        return pruned
    if isinstance(value, list):
        item_schema = schema.get("items") or {}
        if path.endswith(".images"):
            return []
        return [prune_to_schema(item, item_schema, path=f"{path}[]", defs=defs) for item in value]
    return value


class HttpJsonModelGateway:
    """OpenAI-compatible structured gateway with no third-party runtime deps."""

    def __init__(self, settings: Settings, *, timeout_seconds: int | None = None) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds or max(5, int(settings.model_timeout_seconds))
        self.max_attempts = max(1, min(3, int(settings.model_max_attempts)))
        self.outbound_proxy = str(settings.outbound_proxy or "").strip() or None

    def health(self) -> dict[str, Any]:
        configured = {
            "deepseek": bool(self.settings.deepseek_api_key),
            "openai": bool(self.settings.openai_api_key),
        }
        return {
            "available": any(configured.values()),
            "primary_provider": self.settings.primary_provider,
            "fallback_provider": self.settings.fallback_provider,
            "configured": configured,
            "runtime": "http-json",
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "proxy": "configured" if self.outbound_proxy else "direct",
        }

    def _provider_config(self, provider: str) -> tuple[str, str, str]:
        if provider == "deepseek":
            return self.settings.primary_model, self.settings.deepseek_api_base, str(self.settings.deepseek_api_key or "")
        if provider == "openai":
            return self.settings.fallback_model, str(self.settings.openai_api_base or "https://api.openai.com/v1"), str(self.settings.openai_api_key or "")
        raise GatewayError(f"Unsupported provider: {provider}")

    def _invoke(self, provider: str, payload: dict[str, Any]) -> ModelResponse:
        model, api_base, api_key = self._provider_config(provider)
        if not api_key:
            raise GatewayError(f"Provider {provider} is not configured")
        url = api_base.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            start = time.perf_counter()
            try:
                proxy_map = (
                    {"http": self.outbound_proxy, "https": self.outbound_proxy}
                    if self.outbound_proxy else {}
                )
                opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy_map))
                with opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                payload_out = json.loads(raw)
                choice = payload_out["choices"][0]["message"]
                return ModelResponse(
                    provider=provider,
                    model=model,
                    content=str(choice.get("content") or ""),
                    usage=payload_out.get("usage") or {},
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    raw_id=str(payload_out.get("id")),
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, OSError) as exc:
                last_error = exc
                if attempt < self.max_attempts - 1:
                    time.sleep(2 * (attempt + 1))
        raise GatewayError(f"{provider} request failed: {type(last_error).__name__}: {last_error}")

    def _complete_payload(self, request: ModelRequest, *, json_mode: bool) -> dict[str, Any]:
        model, _, _ = self._provider_config(self.settings.primary_provider)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_HINT}, *request.messages],
            "temperature": request.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            return self._invoke(self.settings.primary_provider, self._complete_payload(request, json_mode=False))
        except GatewayError:
            if self.settings.fallback_provider and self.settings.openai_api_key:
                return self._invoke(self.settings.fallback_provider, self._complete_payload(request, json_mode=False))
            raise

    def structured(self, request: StructuredRequest[T]) -> T:
        try:
            response = self._invoke(self.settings.primary_provider, self._complete_payload(request, json_mode=True))
        except GatewayError:
            if self.settings.fallback_provider and self.settings.openai_api_key:
                response = self._invoke(self.settings.fallback_provider, self._complete_payload(request, json_mode=True))
            else:
                raise
        content = response.content.strip()
        # Strip markdown fences some models still emit in json mode.
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise GatewayError(f"structured response was not valid JSON: {exc}; head={content[:160]}") from exc
        try:
            return request.response_model.model_validate(value)
        except ValidationError:
            # Tolerant repair: the model cannot fabricate trustworthy image
            # metadata (sha256/phash/dimensions) from page text — image
            # evidence is owned by the browser image-discovery pipeline
            # (P0-15/16). Prune schema-violating extras and LLM image records,
            # then re-validate. Never invent values to fill gaps.
            repaired = prune_to_schema(value, request.response_model.model_json_schema())
            return request.response_model.model_validate(repaired)
