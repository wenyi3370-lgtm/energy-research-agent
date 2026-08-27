from __future__ import annotations

from energy_research_agent.gateway.base import ModelRequest
from energy_research_agent.gateway.http_json_gateway import HttpJsonModelGateway
from energy_research_agent.settings import Settings


def test_http_gateway_uses_bounded_network_settings_and_proxy() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        outbound_proxy="http://127.0.0.1:7897",
        model_timeout_seconds=37,
        model_max_attempts=2,
    )
    gateway = HttpJsonModelGateway(settings)
    health = gateway.health()
    assert health["timeout_seconds"] == 37
    assert health["max_attempts"] == 2
    assert health["proxy"] == "configured"


def test_http_gateway_forwards_max_tokens() -> None:
    settings = Settings(_env_file=None, deepseek_api_key="test-key")
    gateway = HttpJsonModelGateway(settings)
    request = ModelRequest(
        purpose="bounded-probe",
        messages=[{"role": "user", "content": "OK"}],
        max_tokens=123,
    )
    payload = gateway._complete_payload(request, json_mode=False)
    assert payload["max_tokens"] == 123
