"""Watchlist: recurring research subjects (Phase 14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from ...domain.models import StrictModel
from ..contracts import ResearchRequest
from ..enums import Priority, ResearchType
from .schedule import ScheduleRule, next_run_after


class WatchlistItem(StrictModel):
    """One monitored subject: a task template + recurrence rule."""

    name: str = Field(min_length=1)
    schedule: ScheduleRule
    task: ResearchRequest
    monitor_fields: list[str] = Field(default_factory=list)
    enabled: bool = True

    def is_due(self, now: Any, last_run_at: Any | None = None) -> bool:
        return self.enabled and now >= next_run_after(last_run_at, self.schedule, now)


def load_watchlist(path: Path) -> list[WatchlistItem]:
    from ...settings import load_yaml

    payload = load_yaml(path)
    return [WatchlistItem.model_validate(item) for item in payload.get("items", [])]
