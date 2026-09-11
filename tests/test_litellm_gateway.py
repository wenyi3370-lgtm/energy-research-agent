from __future__ import annotations

from types import SimpleNamespace

from energy_research_agent.gateway.base import ModelRequest
from energy_research_agent.gateway.litellm_gateway import LiteLLMModelGateway
from energy_research_agent.settings import Settings


class _FakeLiteLLM:
    calls: list[dict[str, object]] = []

    @classmethod
    def completion(cls, **kwargs: object) -> SimpleNamespace:
        cls.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))],
            usage={},
            id="test-response",
        )


def _complete(monkeypatch: object, *, api_base: str) -> dict[str, object]:
    _FakeLiteLLM.calls.clear()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        LiteLLMModelGateway,
        "_litellm",
        staticmethod(lambda: _FakeLiteLLM),
    )
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        deepseek_api_base=api_base,
        primary_model="deepseek-v4-flash",
        primary_provider="deepseek",
        fallback_provider="deepseek",
        enable_thinking=False,
    )
    LiteLLMModelGateway(settings).complete(
        ModelRequest(
            purpose="test",
            messages=[{"role": "user", "content": "Reply OK"}],
            max_tokens=8,
        )
    )
    return _FakeLiteLLM.calls[0]


def test_official_deepseek_uses_documented_thinking_toggle(monkeypatch: object) -> None:
    call = _complete(monkeypatch, api_base="https://api.deepseek.com")

    assert call["model"] == "deepseek/deepseek-v4-flash"
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "enable_thinking" not in call


def test_compatible_endpoint_keeps_legacy_thinking_toggle(monkeypatch: object) -> None:
    call = _complete(monkeypatch, api_base="https://example.invalid/v1")

    assert call["enable_thinking"] is False
    assert "extra_body" not in call
