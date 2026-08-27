"""Early-stop control for the deep-research recovery loop.

The ten-round recovery loop exists to close searchable coverage gaps.  Two
real-world failure modes make running all ten rounds wasteful:

1. A gap is evidence-absent (small-cap target, non-public data): more search
   rounds cannot close it, yet the loop keeps retrying for hours because the
   gap stays formally "searchable".
2. The caller wants a bounded wall-clock budget regardless of gap state.

This module centralizes the stop decision so it stays unit-testable without
a live gateway or a ten-hour reproduction.
"""
from __future__ import annotations


def record_gap_round(persistent_gaps: dict[str, int], result: dict) -> None:
    """Count how many consecutive rounds each high-coverage gap survived."""
    for gap in result.get("high_coverage_gaps", []) or []:
        persistent_gaps[gap] = persistent_gaps.get(gap, 0) + 1


def stop_reason(
    persistent_gaps: dict[str, int],
    result: dict,
    *,
    deadline: float | None,
    now: float,
    stall_rounds: int = 3,
) -> str | None:
    """Return a terminal status when the loop should stop without publishing.

    - ``evidence_absent_converged``: the same high-coverage gap survived
      ``stall_rounds`` rounds while verified claims stopped growing — the
      evidence is absent, not under-searched; more rounds only burn quota.
    - ``time_budget_exhausted``: the wall-clock budget elapsed.

    Returns ``None`` when the loop should continue.
    """
    before = result.get("verified_claims_before")
    after = result.get("verified_claims_after")
    claims_stalled = before is not None and after is not None and after <= before
    if claims_stalled and any(count >= stall_rounds for count in persistent_gaps.values()):
        return "evidence_absent_converged"
    if deadline is not None and now > deadline:
        return "time_budget_exhausted"
    return None
