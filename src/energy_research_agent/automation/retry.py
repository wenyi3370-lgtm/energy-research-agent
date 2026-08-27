"""Retry policy: transient/permanent classification + bounded backoff (Phase 8).

A retry is only worthwhile for *transient* failures (adapter outages,
network timeouts, gateway 5xx). Domain errors (invalid transitions,
validation rejections, pydantic errors) are permanent by nature and must
surface to a human instead of burning quota. The policy is the single
source of truth for both classification and the retry bound the service
enforces against the durable ``workflow_events`` trail.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..adapters.base import AdapterError
from ..gateway.base import GatewayError
from .db import DuplicateTaskError, RunNotFoundError
from .state_machine import InvalidTransitionError

# Errors known to be permanent: retrying them can never succeed.
_PERMANENT = (
    ValueError,
    ValidationError,
    InvalidTransitionError,
    DuplicateTaskError,
    RunNotFoundError,
    KeyError,
    TypeError,
    NotImplementedError,
)


def is_transient(exc: BaseException) -> bool:
    """Classify an exception; unknown infrastructure errors default to transient."""
    if isinstance(exc, _PERMANENT):
        return False
    if isinstance(exc, (AdapterError, GatewayError, TimeoutError, ConnectionError, OSError)):
        return True
    return True  # default transient: safer to allow bounded retry


class RetryPolicy:
    """Bounded retry schedule with exponential backoff and jitter.

    ``max_retries`` mirrors the service bound; ``base_delay_seconds`` and
    ``max_delay_seconds`` shape the backoff curve.
    """

    DEFAULTS: dict[str, Any] = {
        "max_retries": 3,
        "base_delay_seconds": 5,
        "max_delay_seconds": 300,
        "jitter_ratio": 0.2,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        merged = dict(self.DEFAULTS)
        merged.update(config or {})
        self.max_retries = int(merged["max_retries"])
        self.base_delay = float(merged["base_delay_seconds"])
        self.max_delay = float(merged["max_delay_seconds"])
        self.jitter_ratio = float(merged.get("jitter_ratio", 0.2))

    @staticmethod
    def load(path: Path) -> "RetryPolicy":
        from ..settings import load_yaml

        try:
            payload = load_yaml(path)
        except FileNotFoundError:
            return RetryPolicy()
        return RetryPolicy(payload.get("retry", {}))

    def should_retry(self, exc: BaseException, *, attempts_used: int) -> bool:
        """Attempts are counted from the durable RETRYING event trail."""
        return is_transient(exc) and attempts_used < self.max_retries

    def backoff_seconds(self, attempt: int) -> float:
        """Exponential backoff with jitter for the *next* (1-based) attempt.

        The jitter is applied before the final cap so the returned delay
        never exceeds ``max_delay``.
        """
        delay = min(self.base_delay * (2 ** max(attempt - 1, 0)), self.max_delay)
        jitter = delay * self.jitter_ratio
        return max(0.0, min(delay + random.uniform(-jitter, jitter), self.max_delay))

    def sleep_before_retry(self, attempt: int) -> None:
        """Blocking helper for worker loops; tests may monkeypatch time."""
        time.sleep(self.backoff_seconds(attempt))
