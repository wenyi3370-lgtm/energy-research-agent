"""Monitor runner: due watchlist items -> research runs -> change detection (Phase 14).

The runner is a thin deterministic loop over the existing service:

1. ``run_due`` submits a follow-up research task for every due watchlist
   item (idempotent per item via ``idempotency_key`` derived from the
   item name + cadence) and executes it.
2. ``detect_change`` diffs the newest PUBLISHED run against the previous
   PUBLISHED run of the same task, over the item's monitored fields.

Scheduling state is intentionally kept outside the DB: ``last_run_at``
is derived from the durable ``research_runs`` table, so restarts never
lose or double-fire a scheduled check.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ...domain.models import Claim
from ...evidence.store import EvidenceStore
from ..contracts import ResearchRequest, ResearchResult
from ..db import AutomationDatabase, TaskRepository
from ..enums import TaskStatus
from ..service import ResearchService
from .change_detection import ChangeDetector, ChangeReport
from .schedule import next_run_after
from .watchlist import WatchlistItem


class MonitorRunner:
    def __init__(
        self,
        service: ResearchService,
        watchlist: list[WatchlistItem],
        *,
        db: AutomationDatabase | None = None,
        workdir: Path | None = None,
    ) -> None:
        self.service = service
        self.watchlist = watchlist
        self.db = db or service.db
        self.workdir = Path(workdir or service.workdir)

    # -- scheduling -----------------------------------------------------------

    def due_items(self, now: datetime) -> list[WatchlistItem]:
        return [
            item
            for item in self.watchlist
            if item.is_due(now, last_run_at=self._last_run_at(item))
        ]

    def run_due(self, now: datetime) -> list[ResearchResult]:
        """Submit + execute research for every due item; returns the runs.

        Each scheduled *window* gets its own task (``task_id`` carries the
        anchor date) so one monitoring subject can run many windows while
        keeping the service contract "one task -> one run chain". The
        idempotency key is anchored to the window, so repeated runs inside
        the same window replay instead of duplicating.
        """
        submitted: list[ResearchResult] = []
        for item in self.due_items(now):
            request = item.task.model_copy(deep=True)
            anchor = next_run_after(self._last_run_at(item), item.schedule, now)
            request.task_id = f"{item.task.task_id}:{anchor.date().isoformat()}"
            request.idempotency_key = f"watch:{item.name}:{anchor.isoformat()}"
            result = self.service.submit(request)
            if result.status == TaskStatus.QUEUED:  # fresh window task
                submitted.append(self.service.execute_run(result.run_id))
        return submitted

    # -- change detection -------------------------------------------------------

    def detect_change(
        self, item: WatchlistItem, new_run_id: str | None = None
    ) -> ChangeReport | None:
        """Diff the two most recent PUBLISHED runs of the item's task."""
        run_ids = self._published_run_ids(item.task.task_id, limit=2)
        if new_run_id and new_run_id not in run_ids:
            run_ids.insert(0, new_run_id)
        if len(run_ids) < 2:
            return None
        old_id, new_id = run_ids[1], run_ids[0]
        old_claims = self._claims(old_id)
        new_claims = self._claims(new_id)
        return ChangeDetector().detect(
            item.name, old_claims, new_claims, fields=item.monitor_fields or None
        )

    # -- internals ---------------------------------------------------------------

    def _last_run_at(self, item: WatchlistItem) -> datetime | None:
        """Most recent window task created for this monitoring subject.

        Window tasks carry ``idempotency_key = watch:<name>:<anchor>``, so
        the newest one is found by prefix, independent of the template
        task_id. Timestamps are normalized to naive UTC (Postgres returns
        aware datetimes, SQLite naive) so schedule comparisons never mix.
        """
        from sqlalchemy import select

        from ..db.models import ResearchRunRow, ResearchTaskRow

        session = self.db.session()
        try:
            stmt = (
                select(ResearchTaskRow)
                .where(ResearchTaskRow.idempotency_key.like(f"watch:{item.name}:%"))
                .order_by(ResearchTaskRow.created_at.desc())
                .limit(1)
            )
            task = session.execute(stmt).scalar_one_or_none()
            if task is None or task.active_run_id is None:
                return None
            run = session.get(ResearchRunRow, task.active_run_id)
            if run is None or run.created_at is None:
                return None
            created_at = run.created_at
            return created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
        finally:
            session.close()

    def _published_run_ids(self, task_id: str, *, limit: int) -> list[str]:
        """Latest PUBLISHED runs for a monitoring subject (template prefix)."""
        session = self.db.session()
        try:
            from sqlalchemy import select

            from ..db.models import ResearchRunRow

            stmt = (
                select(ResearchRunRow.run_id)
                .where(
                    ResearchRunRow.task_id.like(f"{task_id}:%"),
                    ResearchRunRow.status == str(TaskStatus.PUBLISHED),
                )
                .order_by(ResearchRunRow.finished_at.desc())
                .limit(limit)
            )
            return [row for (row,) in session.execute(stmt)]
        finally:
            session.close()

    def _claims(self, run_id: str) -> list[Claim]:
        store = EvidenceStore(self.workdir / run_id / "evidence.sqlite3")
        return store.list(run_id, "claim")
