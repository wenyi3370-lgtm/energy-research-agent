"""Automation-layer regression eval (Phase 12).

Runs every evals.json case that carries a structured ``task`` through the
offline automation pipeline (SyntheticKernelExecutor — deterministic, no
network) and verifies:

- the run reaches PUBLISHED (no FAILED/BLOCKED),
- every ``expectations`` string appears in the structured result JSON.

This is a *regression* eval of the workflow mechanics, not a golden LLM
eval: the original free-form prompts (id 1-3) are human-driven and are
skipped here. Exit code is non-zero when any case fails, so the script
fits CI.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from enterprise_energy_research.automation.contracts import ResearchRequest
from enterprise_energy_research.automation.db import AutomationDatabase
from enterprise_energy_research.automation.executor import SyntheticKernelExecutor
from enterprise_energy_research.automation.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def run_eval() -> int:
    payload = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
    cases = [item for item in payload["evals"] if "task" in item]
    print(f"automation eval: {len(cases)} structured cases")
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db = AutomationDatabase(f"sqlite:///{tmp / 'eval.db'}")
        service = ResearchService(
            db, SyntheticKernelExecutor(), workdir=tmp / "work"
        )
        try:
            for case in cases:
                request = ResearchRequest.model_validate(case["task"])
                submitted = service.submit(request)
                result = service.execute_run(submitted.run_id)
                blob = result.model_dump_json()
                missing = [
                    expectation
                    for expectation in case.get("expectations", [])
                    if expectation not in blob
                ]
                status = "PASS" if (result.status.value == "PUBLISHED" and not missing) else "FAIL"
                if status == "FAIL":
                    failures += 1
                print(
                    f"[{status}] eval-{case['id']} {case['task']['task_id']} "
                    f"-> {result.status.value} missing={missing or '-'}"
                )
        finally:
            db.engine.dispose()
    print(f"result: {'OK' if failures == 0 else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_eval())
