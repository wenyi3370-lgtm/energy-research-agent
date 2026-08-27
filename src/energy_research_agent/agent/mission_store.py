"""Mission persistence: the agent's audit store.

Missions, goals, routing, approvals, skill runs and trace events are durable
records (SQLite via stdlib), keyed by mission_id. This is the agent trace
backing store for the portal (§50) — IDs, timestamps and counts, never secrets.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from energy_research_agent.domain.models import utc_now as _utc_now  # reuse domain clock

from .models import MissionApproval, ResearchMission


SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_runs (
    skill_run_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    payload TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_mission ON trace_events(mission_id);
CREATE INDEX IF NOT EXISTS idx_skill_runs_mission ON skill_runs(mission_id);
"""


def default_store_path() -> Path:
    from energy_research_agent.vendor import repository_root

    override = __import__("os").environ.get("ERA_AGENT_DB")
    if override:
        return Path(override)
    return repository_root() / "outputs" / "agent" / "agent_store.sqlite3"


class MissionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    # -- missions -----------------------------------------------------------

    def upsert_mission(self, mission: ResearchMission) -> None:
        now = _utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO missions(mission_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(mission_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
                (mission.mission_id, mission.model_dump_json(), now, now),
            )

    def get_mission(self, mission_id: str) -> ResearchMission | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM missions WHERE mission_id = ?", (mission_id,)
            ).fetchone()
        return ResearchMission.model_validate_json(row["payload"]) if row else None

    def list_missions(self, limit: int = 100) -> list[ResearchMission]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM missions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [ResearchMission.model_validate_json(row["payload"]) for row in rows]

    # -- approvals ------------------------------------------------------------

    def record_approval(self, approval: MissionApproval) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO approvals(approval_id, mission_id, payload, decided_at) VALUES (?, ?, ?, ?)",
                (approval.approval_id, approval.mission_id, approval.model_dump_json(), approval.decided_at.isoformat()),
            )

    def latest_approval(self, mission_id: str) -> MissionApproval | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM approvals WHERE mission_id = ? ORDER BY decided_at DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
        return MissionApproval.model_validate_json(row["payload"]) if row else None

    # -- skill runs / trace -----------------------------------------------------

    def record_skill_run(self, mission_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO skill_runs(skill_run_id, mission_id, skill_name, payload, completed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    payload["skill_run_id"], mission_id, payload.get("skill_name", ""),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _utc_now().isoformat(),
                ),
            )

    def trace(self, mission_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO trace_events(mission_id, event, payload, created_at) VALUES (?, ?, ?, ?)",
                (mission_id, event, json.dumps(payload or {}, ensure_ascii=False, default=str), _utc_now().isoformat()),
            )

    def trace_for(self, mission_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event, payload, created_at FROM trace_events WHERE mission_id = ? ORDER BY seq LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        return [
            {"event": row["event"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def skill_runs_for(self, mission_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT skill_name, payload, completed_at FROM skill_runs WHERE mission_id = ? ORDER BY completed_at",
                (mission_id,),
            ).fetchall()
        return [
            {
                "skill_name": row["skill_name"],
                "payload": json.loads(row["payload"]),
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]

    def metrics_for(self, mission_id: str) -> dict[str, Any] | None:
        for event in self.trace_for(mission_id):
            if event["event"] == "metrics":
                return event["payload"]
        return None
