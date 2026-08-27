from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Callable

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _base32(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        value, remainder = divmod(value, 32)
        chars.append(_ALPHABET[remainder])
    return "".join(reversed(chars))


def new_sortable_id(prefix: str, *, now: Callable[[], datetime] | None = None) -> str:
    """Create a sortable, ULID-shaped ID without requiring a third-party package."""
    clock = now or (lambda: datetime.now(timezone.utc))
    timestamp_ms = int(clock().timestamp() * 1000)
    randomness = secrets.randbits(80)
    return f"{prefix}-{_base32(timestamp_ms, 10)}{_base32(randomness, 16)}"


class RunSequence:
    """Generate stable short IDs within one run."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, kind: str) -> str:
        self._counts[kind] = self._counts.get(kind, 0) + 1
        number = self._counts[kind]
        formats = {
            "claim": f"CLAIM-{number:06d}",
            "source": f"SOURCE-S{number:03d}",
            "image": f"IMAGE-I{number:03d}",
            "chart": f"CHART-C{number:03d}",
            "query": f"QUERY-Q{number:03d}",
            "retrieval": f"RET-R{number:03d}",
        }
        if kind not in formats:
            raise ValueError(f"Unsupported sequence kind: {kind}")
        return formats[kind]
