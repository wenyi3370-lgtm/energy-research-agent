from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def evaluate() -> dict:
    contract = json.loads((ROOT / "evals" / "recorded_cases.json").read_text(encoding="utf-8"))
    results = []
    for case in contract["cases"]:
        batches = json.loads((ROOT / "tests" / "fixtures" / case["fixture"]).read_text(encoding="utf-8"))
        counts = {
            kind: sum(len(batch.get(kind, [])) for batch in batches)
            for kind in ("entities", "claims", "products", "images", "factories", "conflicts", "gaps")
        }
        # Recorded extraction batches represent one fetched source each.  Some
        # fixtures also carry nested source records, so count both shapes
        # without requiring the fixture format to change.
        counts["sources"] = sum(
            max(1 if batch.get("source_url") else 0, len(batch.get("sources", [])))
            for batch in batches
        )
        findings = []
        for key, threshold in case.items():
            if not key.startswith("minimum_"):
                continue
            kind = key.removeprefix("minimum_")
            if counts.get(kind, 0) < threshold:
                findings.append(f"{kind}={counts.get(kind, 0)} below {threshold}")
        results.append({"fixture": case["fixture"], "counts": counts, "status": "PASS" if not findings else "BLOCKED", "findings": findings})
    return {"schema_version": "1.0", "layer": "L2_RECORDED_RESEARCH", "status": "PASS" if all(row["status"] == "PASS" for row in results) else "BLOCKED", "cases": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "evals" / "recorded_research_eval.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
