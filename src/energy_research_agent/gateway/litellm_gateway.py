from __future__ import annotations

import json
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from energy_research_agent.settings import Settings

from .base import GatewayError, ModelRequest, ModelResponse, StructuredRequest

T = TypeVar("T", bound=BaseModel)

# Reasoning providers (SiliconFlow DeepSeek-V4 family) sometimes leak the
# thinking chain into ``content`` as a literal ``...`` wrapper even
# though ``reasoning_content`` carries it separately.
_THINK_WRAPPER = re.compile(r"<think>[\s\S]*?</think>\n?", re.IGNORECASE)


class LiteLLMModelGateway:
    """Provider-neutral gateway with bounded transient fallback.

    LiteLLM is imported lazily so the evidence foundation can run without model dependencies.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _litellm() -> Any:
        try:
            import litellm
        except ImportError as exc:
            raise GatewayError("LiteLLM is not installed; install the 'models' optional dependency") from exc
        return litellm

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
        }

    def _provider_config(self, provider: str) -> tuple[str, str | None, str | None]:
        if provider == "deepseek":
            return self.settings.primary_model, self.settings.deepseek_api_base, self.settings.deepseek_api_key
        if provider == "openai":
            return self.settings.fallback_model, self.settings.openai_api_base, self.settings.openai_api_key
        raise GatewayError(f"Unsupported provider: {provider}")

    def _invoke(self, provider: str, request: ModelRequest) -> ModelResponse:
        model, api_base, api_key = self._provider_config(provider)
        if not api_key:
            raise GatewayError(f"Provider {provider} is not configured")
        litellm = self._litellm()
        start = time.perf_counter()
        kwargs: dict[str, Any] = {}
        # Structured extraction requires machine-readable JSON: ask the
        # provider for JSON mode (DeepSeek/OpenAI compatible). The extractor
        # prompt already mentions "JSON", which both providers require.
        if isinstance(request, StructuredRequest):
            kwargs["response_format"] = {"type": "json_object"}
        # Reasoning models burn quota on chain-of-thought tokens the pipeline
        # never reads and may leak the thinking wrapper into content; default
        # to non-thinking mode (quality-neutral for extraction/distillation,
        # ~60% cheaper on SiliconFlow V4-Flash). Opt back in via env.
        if not self.settings.enable_thinking:
            kwargs["enable_thinking"] = False
        # A provider can accept a request and never answer (observed on
        # SiliconFlow: one hung call stalled the whole mission for 20+ min).
        # Enforce the configured per-call timeout and retry in-place before
        # the provider fallback decides.
        timeout = max(5, int(self.settings.model_timeout_seconds))
        attempts = max(1, min(3, int(self.settings.model_max_attempts)))
        kwargs["timeout"] = timeout
        last_error: Exception | None = None
        response = None
        for _attempt in range(attempts):
            try:
                response = litellm.completion(
                    model=f"{provider}/{model}",
                    messages=request.messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    api_base=api_base,
                    api_key=api_key,
                    **kwargs,
                )
                break
            except Exception as exc:
                last_error = exc
        if response is None:
            raise GatewayError(
                f"Provider {provider} failed after {attempts} attempt(s) "
                f"({timeout}s timeout each): {type(last_error).__name__}: {last_error}"
            )
        choices = getattr(response, "choices", None) or []
        content = (choices[0].message.content or "") if choices else ""
        if content:
            content = _THINK_WRAPPER.sub("", content).strip()
        if not choices or not content.strip():
            # 空完成（空 choices）必须转为 GatewayError，而不是让
            # choices[0] 抛 IndexError 炸掉整个 run；fallback 逻辑接管。
            raise GatewayError(f"Provider {provider} returned an empty completion")
        elapsed = int((time.perf_counter() - start) * 1000)
        return ModelResponse(
            provider=provider,
            model=model,
            content=content,
            usage=dict(response.usage or {}),
            latency_ms=elapsed,
            raw_id=getattr(response, "id", None),
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        failures: list[str] = []
        providers = [self.settings.primary_provider]
        if self.settings.fallback_provider != self.settings.primary_provider:
            providers.append(self.settings.fallback_provider)
        for provider in providers:
            try:
                return self._invoke(provider, request)
            except GatewayError as exc:
                failures.append(str(exc))
            except Exception as exc:
                # Provider/transport failures may fall back. Schema validation errors happen later and never do.
                failures.append(f"{provider}: {type(exc).__name__}: {exc}")
        raise GatewayError("All configured providers failed: " + " | ".join(failures))

    def structured(self, request: StructuredRequest[T]) -> T:
        response = self.complete(request)
        content = _strip_code_fence(response.content)
        try:
            payload = json.loads(content)
            try:
                return request.response_model.model_validate(payload)
            except ValidationError as first:
                # LLMs sometimes emit partial dates ("2019-03") or
                # protocol-less URLs ("www.catl.com"); normalize those and
                # retry before giving up. Reasoning models also emit numerics
                # for string fields (founded_year: 2013), so stringify first.
                try:
                    return request.response_model.model_validate(_coerce_scalars(payload))
                except ValidationError:
                    pass
                try:
                    return request.response_model.model_validate(_repair_payload(payload))
                except ValidationError:
                    raise first
        except (json.JSONDecodeError, ValidationError) as exc:
            # Include a short raw excerpt and the schema error so failed
            # extractions are debuggable without logging the full response.
            detail = str(exc).replace("\n", " ")[:300]
            raise GatewayError(
                f"Structured response failed validation for {request.purpose}; "
                f"detail: {detail}; raw excerpt: {content[:120]!r}"
            ) from exc


def _strip_code_fence(content: str) -> str:
    """Strip a ```json ... ``` fence some providers wrap JSON output in."""
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _coerce_scalars(value: Any) -> Any:
    """Stringify int/float/bool leaves so numeric JSON values satisfy ``str``
    schema fields (reasoning models often emit founded_year as 2013)."""
    if isinstance(value, dict):
        return {key: _coerce_scalars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_coerce_scalars(item) for item in value]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return value


def _repair_payload(value: Any) -> Any:
    """Normalize common LLM output quirks before schema validation:
    partial dates ("2019-03" -> "2019-03-01") and protocol-less URLs
    ("www.catl.com" -> "https://www.catl.com")."""
    if isinstance(value, dict):
        return {key: _repair_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_repair_payload(item) for item in value]
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}", value):
            return value + "-01"
        if re.fullmatch(r"\d{4}", value):
            return value + "-01-01"
        if value.startswith("www."):
            return "https://" + value
    return value
