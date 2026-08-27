"""Recurrence rules for scheduled research (Phase 14).

Deliberately dependency-free (no croniter): the supported cadences are the
ones this workflow actually needs — ``daily``, ``weekly``, ``monthly`` and
plain intervals. Everything is computed in the caller's local timezone
(naive datetimes), which is fine for a single-region deployment.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from ...domain.models import StrictModel

Cadence = Literal["hourly", "daily", "weekly", "monthly"]


class ScheduleRule(StrictModel):
    cadence: Cadence
    interval: int = Field(default=1, ge=1)
    at_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    weekday: int | None = Field(default=None, ge=0, le=6)  # weekly: 0=Monday..6=Sunday
    day_of_month: int | None = Field(default=None, ge=1, le=31)  # monthly

    def describe(self) -> str:
        parts = [f"every {self.interval} {self.cadence}(s)"]
        if self.at_time:
            parts.append(f"at {self.at_time}")
        if self.weekday is not None:
            parts.append(f"weekday {self.weekday}")
        if self.day_of_month is not None:
            parts.append(f"day {self.day_of_month}")
        return ", ".join(parts)


def next_run_after(
    last_run_at: datetime | None,
    rule: ScheduleRule,
    now: datetime,
) -> datetime:
    """Compute the next scheduled run time after the given anchor.

    The result is the *planned* anchor moment (which may already be in the
    past — the caller's ``is_due`` treats that as "missed, run now").
    Weekday/monthly cadences align to the rule's day/time anchors.
    """
    if last_run_at is None:
        return _anchor_from_now(rule, now)
    if rule.cadence == "hourly":
        return last_run_at + timedelta(hours=rule.interval)
    if rule.cadence == "daily":
        return _align_time(last_run_at + timedelta(days=rule.interval), rule, fallback=last_run_at.time())
    if rule.cadence == "weekly":
        monday = last_run_at.date() - timedelta(days=last_run_at.weekday())
        weekday = rule.weekday if rule.weekday is not None else last_run_at.weekday()
        target = monday + timedelta(weeks=rule.interval, days=weekday)
        return _align_time(datetime.combine(target, last_run_at.time()), rule, fallback=last_run_at.time())
    # monthly: add months without a calendar library, then align day/time
    month_index = last_run_at.year * 12 + (last_run_at.month - 1) + rule.interval
    year, month = divmod(month_index, 12)
    day_of_month = rule.day_of_month if rule.day_of_month is not None else min(last_run_at.day, 28)
    base = last_run_at.replace(year=year, month=month + 1, day=min(day_of_month, 28))
    return _align_time(base, rule, fallback=last_run_at.time())


def _align_time(value: datetime, rule: ScheduleRule, *, fallback) -> datetime:
    """Apply at_time when configured; otherwise keep the anchor's time."""
    if not rule.at_time:
        return value
    hour, minute = (int(part) for part in rule.at_time.split(":"))
    return value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _anchor_from_now(rule: ScheduleRule, now: datetime) -> datetime:
    anchor = now.replace(second=0, microsecond=0)
    if rule.at_time:
        hour, minute = (int(part) for part in rule.at_time.split(":"))
        anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if anchor < now:
            anchor += timedelta(days=1)
    if rule.cadence == "weekly" and rule.weekday is not None:
        days_ahead = (rule.weekday - anchor.weekday()) % 7
        anchor += timedelta(days=days_ahead)
        if rule.at_time and anchor < now:
            anchor += timedelta(days=7)
    if rule.cadence == "monthly" and rule.day_of_month is not None:
        if anchor.day > rule.day_of_month:
            anchor += timedelta(days=1)
        try:
            anchor = anchor.replace(day=rule.day_of_month)
        except ValueError:
            anchor = anchor.replace(day=28)
    return anchor
