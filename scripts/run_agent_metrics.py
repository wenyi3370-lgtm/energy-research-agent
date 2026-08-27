"""Aggregate agent metrics (§59) from the mission store into evals/agent_metrics.json.

Usage:
    python scripts/run_agent_metrics.py [--store path/to/agent_store.sqlite3] [--output evals/agent_metrics.json]

Reads the persisted "metrics" trace event per mission and summarizes the
cohort: completion rates, core coverage, recovery success, evidence yield,
routing mode share and token usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate Agent evaluation metrics (§59)")
    parser.add_argument("--store", default="", help="MissionStore sqlite path")
    parser.add_argument("--output", default="evals/agent_metrics.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from energy_research_agent.agent.mission_store import MissionStore

    store = MissionStore(Path(args.store) if args.store else None)
    missions = store.list_missions(limit=500)
    rows = []
    for mission in missions:
        metrics = store.metrics_for(mission.mission_id)
        if metrics:
            rows.append({
                "mission_id": mission.mission_id,
                "mode": metrics.get("mode"),
                "status": metrics.get("status"),
                **metrics,
            })
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "mission_count": len(rows),
        "aggregates": {},
        "missions": rows,
    }
    if rows:
        def _avg(key: str):
            values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
            return round(sum(values) / len(values), 4) if values else None

        summary["aggregates"] = {
            "goal_completion_rate": _avg("goal_completion_rate"),
            "core_goal_coverage": _avg("core_goal_coverage"),
            "dynamic_goal_completion_rate": _avg("dynamic_goal_completion_rate"),
            "recovery_success_rate": _avg("recovery_success_rate"),
            "valid_evidence_yield": _avg("valid_evidence_yield"),
            "citation_traceability": _avg("citation_traceability"),
            "routing_llm_rate": _avg("routing_llm_rate"),
            "agent_token_usage_total": sum(row.get("agent_token_usage") or 0 for row in rows),
            "completion_rate": round(
                sum(1 for row in rows if row.get("status") == "COMPLETED") / len(rows), 4
            ),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "missions": len(rows), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
