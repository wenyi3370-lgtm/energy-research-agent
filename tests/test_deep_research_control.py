"""Deep-research early-stop control unit tests.

Covers the two real-world failure modes that used to stall the loop for
hours: evidence-absent gaps (small-cap target) and wall-clock budgets.
"""
from __future__ import annotations

import unittest

from energy_research_agent.automation.contracts import DeepResearchPayload
from energy_research_agent.automation.deep_research_control import (
    record_gap_round,
    stop_reason,
)


class RecordGapRoundTests(unittest.TestCase):
    def test_counts_consecutive_surviving_gaps(self) -> None:
        gaps: dict[str, int] = {}
        record_gap_round(gaps, {"high_coverage_gaps": ["coverage-revenue"]})
        record_gap_round(gaps, {"high_coverage_gaps": ["coverage-revenue", "coverage-profit"]})
        self.assertEqual(gaps, {"coverage-revenue": 2, "coverage-profit": 1})

    def test_missing_key_is_noop(self) -> None:
        gaps: dict[str, int] = {}
        record_gap_round(gaps, {})
        self.assertEqual(gaps, {})


class StopReasonTests(unittest.TestCase):
    def test_evidence_absent_converged(self) -> None:
        gaps = {"coverage-revenue": 3}
        result = {
            "verified_claims_before": 40,
            "verified_claims_after": 40,  # zero growth this round
        }
        self.assertEqual(
            stop_reason(gaps, result, deadline=None, now=0.0),
            "evidence_absent_converged",
        )

    def test_claims_still_growing_keeps_loop(self) -> None:
        gaps = {"coverage-revenue": 4}
        result = {"verified_claims_before": 40, "verified_claims_after": 43}
        self.assertIsNone(stop_reason(gaps, result, deadline=None, now=0.0))

    def test_short_streak_keeps_loop(self) -> None:
        gaps = {"coverage-revenue": 2}
        result = {"verified_claims_before": 40, "verified_claims_after": 40}
        self.assertIsNone(stop_reason(gaps, result, deadline=None, now=0.0))

    def test_time_budget_exhausted(self) -> None:
        self.assertEqual(
            stop_reason({}, {}, deadline=100.0, now=101.0),
            "time_budget_exhausted",
        )
        self.assertIsNone(stop_reason({}, {}, deadline=100.0, now=99.0))

    def test_no_deadline_never_times_out(self) -> None:
        self.assertIsNone(stop_reason({}, {}, deadline=None, now=10**9))


class PayloadContractTests(unittest.TestCase):
    def test_default_time_budget(self) -> None:
        payload = DeepResearchPayload(requirements="补充产品与产能证据")
        self.assertEqual(payload.time_budget_minutes, 90)

    def test_custom_time_budget_bounds(self) -> None:
        payload = DeepResearchPayload(requirements="补充产品与产能证据", time_budget_minutes=30)
        self.assertEqual(payload.time_budget_minutes, 30)
        with self.assertRaises(Exception):
            DeepResearchPayload(requirements="补充产品与产能证据", time_budget_minutes=1)


if __name__ == "__main__":
    unittest.main()
