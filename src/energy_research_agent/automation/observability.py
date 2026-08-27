"""Observability: gateway usage capture, step timing, structured events (Phase 10).

Three pieces, all optional wrappers so the research kernel stays untouched:

- :class:`CountingGateway` wraps any ``ModelGateway`` and accumulates
  token/call counters plus per-call latency, so token and cost data can be
  collected without changing the gateway protocol.
- :func:`run_span` is a context manager that measures one workflow step
  (research / validation / publishing) in wall-clock seconds.
- :func:`log_event` emits a single-line structured event for the automation
  control plane (request_id/run_id/step/duration_ms/...); it never logs
  secrets, keys or payload bodies.

Cost estimation uses a small per-provider price table and is always
labeled *estimated* — the audit forbids fabricating cost numbers, and
tokens without a live gateway simply stay zero.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Generic, TypeVar

from ..gateway.base import ModelGateway, ModelRequest, ModelResponse, StructuredRequest

logger = logging.getLogger("energy_research_agent.automation")

T = TypeVar("T")

# USD per 1M tokens, best-effort list pricing (overridable via config).
DEFAULT_PRICES_USD_PER_1M: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.14, "output": 0.28},
    "openai": {"input": 0.15, "output": 0.60},
    "kimi": {"input": 0.20, "output": 0.80},
    "default": {"input": 0.15, "output": 0.60},
}


class GatewayUsage:
    """Accumulated counters captured by :class:`CountingGateway`."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_calls = 0
        self.estimated_cost_usd = 0.0
        self.latency_ms: list[int] = []

    def record(self, response: ModelResponse, prices: dict[str, dict[str, float]]) -> None:
        usage = response.usage or {}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        provider = response.provider or "default"
        table = prices.get(provider) or prices.get("default", DEFAULT_PRICES_USD_PER_1M["default"])
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.llm_calls += 1
        self.estimated_cost_usd += (
            input_tokens * table.get("input", 0.0) + output_tokens * table.get("output", 0.0)
        ) / 1_000_000.0
        if response.latency_ms is not None:
            self.latency_ms.append(response.latency_ms)

    def snapshot(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "llm_calls": self.llm_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }


class CountingGateway(ModelGateway, Generic[T]):
    """Gateway decorator that records usage without altering the protocol."""

    def __init__(
        self,
        inner: ModelGateway,
        usage: GatewayUsage | None = None,
        prices: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.inner = inner
        self.usage = usage or GatewayUsage()
        self.prices = prices or DEFAULT_PRICES_USD_PER_1M

    def complete(self, request: ModelRequest) -> ModelResponse:
        started = time.perf_counter()
        response = self.inner.complete(request)
        self._record(response, started)
        return response

    def structured(self, request: StructuredRequest[T]) -> T:
        started = time.perf_counter()
        response = self.inner.structured(request)
        self._record(self._response_from(request, response), started)
        return response

    def health(self) -> dict[str, Any]:
        return self.inner.health()

    def _record(self, response: ModelResponse, started: float) -> None:
        if response.latency_ms is None:
            response.latency_ms = int((time.perf_counter() - started) * 1000)
        self.usage.record(response, self.prices)

    @staticmethod
    def _response_from(request: StructuredRequest[T], model: T) -> ModelResponse:
        """structured() returns the model, not a ModelResponse; synthesize one."""
        return ModelResponse(
            provider=request.metadata.get("provider", "unknown"),
            model=request.metadata.get("model", "unknown"),
            content="",
            usage=request.metadata.get("usage", {}),
            latency_ms=None,
        )


@contextmanager
def run_span(step: str, *, run_id: str | None = None, request_id: str | None = None):
    """Measure one workflow step; always emits a structured event on exit."""
    started = time.perf_counter()
    fields: dict[str, Any] = {}
    try:
        yield fields
    finally:
        fields["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        log_event("step.finished", step=step, run_id=run_id, request_id=request_id, **fields)


def log_event(event: str, **fields: Any) -> None:
    """Emit one JSON-line event for the automation control plane."""
    payload = {"event": event}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
