"""Phase 5/8/10/11/13 tests: review policy, retry policy, observability, ROI,
failure library."""

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.automation.contracts import ResearchRequest
from enterprise_energy_research.automation.executor import ExecutionOutcome
from enterprise_energy_research.automation.failure_library import FailureCase, FailureLibrary
from enterprise_energy_research.automation.observability import CountingGateway, GatewayUsage
from enterprise_energy_research.automation.retry import RetryPolicy, is_transient
from enterprise_energy_research.automation.review import ReviewGateResult, ReviewPolicy
from enterprise_energy_research.automation.roi import RoiCalculator, RoiRunRow
from enterprise_energy_research.domain.enums import ValidationStatus

ROOT = Path(__file__).resolve().parents[1]


def make_request(**overrides) -> ResearchRequest:
    payload = {
        "task_id": "TH_BESS_001",
        "requested_by": "user_001",
        "country": "Thailand",
        "product": "Residential BESS",
        "research_type": "market_entry",
        "topics": ["market_size"],
    }
    payload.update(overrides)
    return ResearchRequest.model_validate(payload)


class ReviewPolicyTests(unittest.TestCase):
    def test_default_has_no_human_review_rules_enabled(self):
        policy = ReviewPolicy()
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS)
        result = policy.evaluate(outcome, make_request())
        self.assertFalse(result.review_required)

    def test_default_warnings_do_not_trigger_review(self):
        policy = ReviewPolicy()
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS_WITH_WARNINGS)
        result = policy.evaluate(outcome, make_request())
        self.assertFalse(result.review_required)
        self.assertEqual(result.reasons, [])

    def test_rv02_low_confidence(self):
        policy = ReviewPolicy({"RV-02_low_confidence": {"enabled": True, "min_confidence": 0.70}})
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS, confidence=0.55)
        self.assertTrue(policy.evaluate(outcome, make_request()).review_required)
        high = ExecutionOutcome(validation_status=ValidationStatus.PASS, confidence=0.95)
        self.assertFalse(policy.evaluate(high, make_request()).review_required)

    def test_rv04_conflicts(self):
        policy = ReviewPolicy({"RV-04_conflicts": {"enabled": True}})
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS, conflict_count=2)
        result = policy.evaluate(outcome, make_request())
        self.assertTrue(result.review_required)
        self.assertIn("RV-04", result.reasons[0])

    def test_rv06_low_evidence(self):
        policy = ReviewPolicy({"RV-06_low_evidence": {"enabled": True, "min_evidence": 10}})
        sparse = ExecutionOutcome(validation_status=ValidationStatus.PASS, evidence_count=3)
        self.assertTrue(policy.evaluate(sparse, make_request()).review_required)

    def test_rv08_market_scope(self):
        policy = ReviewPolicy({"RV-08_market_scope": {"enabled": True}})
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS)
        market = make_request(company=None, country="Thailand")
        self.assertTrue(policy.evaluate(outcome, market).review_required)
        company = make_request(company="某公司", country="Thailand")
        self.assertFalse(policy.evaluate(outcome, company).review_required)

    def test_rv09_sensitive_types(self):
        policy = ReviewPolicy({"RV-09_sensitive_types": {"enabled": True}})
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS)
        self.assertTrue(
            policy.evaluate(outcome, make_request(research_type="policy_regulation")).review_required
        )
        self.assertFalse(
            policy.evaluate(outcome, make_request(research_type="market_entry")).review_required
        )

    def test_rv10_urgent_priority(self):
        policy = ReviewPolicy({"RV-10_urgent_priority": {"enabled": True}})
        outcome = ExecutionOutcome(validation_status=ValidationStatus.PASS)
        self.assertTrue(policy.evaluate(outcome, make_request(priority="urgent")).review_required)

    def test_load_from_yaml(self):
        policy = ReviewPolicy.load(ROOT / "config" / "review_policy.yaml")
        self.assertFalse(any(rule.get("enabled") for rule in policy.rules.values()))

    def test_all_ten_rules_exist(self):
        policy = ReviewPolicy()
        self.assertEqual(len(policy.rules), 10)


class RetryPolicyTests(unittest.TestCase):
    def test_transient_vs_permanent(self):
        self.assertTrue(is_transient(RuntimeError("backend down")))
        self.assertTrue(is_transient(TimeoutError()))
        self.assertFalse(is_transient(ValueError("bad input")))
        self.assertFalse(is_transient(NotImplementedError()))

    def test_should_retry_bounded(self):
        policy = RetryPolicy({"max_retries": 2})
        self.assertTrue(policy.should_retry(RuntimeError(), attempts_used=0))
        self.assertTrue(policy.should_retry(RuntimeError(), attempts_used=1))
        self.assertFalse(policy.should_retry(RuntimeError(), attempts_used=2))
        self.assertFalse(policy.should_retry(ValueError(), attempts_used=0))

    def test_backoff_grows_and_caps(self):
        policy = RetryPolicy({"base_delay_seconds": 5, "max_delay_seconds": 60})
        first = policy.backoff_seconds(1)
        later = policy.backoff_seconds(6)
        self.assertLess(first, later)
        self.assertLessEqual(later, 60.0)

    def test_load_from_yaml(self):
        policy = RetryPolicy.load(ROOT / "config" / "retry_policy.yaml")
        self.assertEqual(policy.max_retries, 3)


class CountingGatewayTests(unittest.TestCase):
    def test_counts_and_estimates_cost(self):
        from enterprise_energy_research.gateway.base import ModelRequest, ModelResponse

        class FakeGateway:
            def complete(self, request):
                return ModelResponse(
                    provider="deepseek", model="m", content="ok",
                    usage={"input_tokens": 1000, "output_tokens": 500},
                )

            def structured(self, request):
                raise NotImplementedError

            def health(self):
                return {"ok": True}

        usage = GatewayUsage()
        gateway = CountingGateway(FakeGateway(), usage=usage)
        gateway.complete(ModelRequest(purpose="test", messages=[{"role": "user", "content": "x"}]))
        snapshot = usage.snapshot()
        self.assertEqual(snapshot["input_tokens"], 1000)
        self.assertEqual(snapshot["output_tokens"], 500)
        self.assertEqual(snapshot["llm_calls"], 1)
        self.assertGreater(snapshot["estimated_cost_usd"], 0.0)


class RoiCalculatorTests(unittest.TestCase):
    def test_per_run_ratio(self):
        result = RoiCalculator.per_run(RoiRunRow(
            run_id="R1", manual_baseline_minutes=480.0, human_review_minutes=60.0,
            machine_total_seconds=900.0, adoption_status="ADOPTED",
        ))
        self.assertEqual(result.minutes_saved, 420.0)
        self.assertEqual(result.roi_ratio, 7.0)
        self.assertEqual(result.machine_minutes, 15.0)
        self.assertIn("7.0x", result.roi_comment)

    def test_aggregate_only_collected_data(self):
        rows = [
            RoiRunRow(run_id="R1", manual_baseline_minutes=480.0, human_review_minutes=60.0, adoption_status="ADOPTED"),
            RoiRunRow(run_id="R2", manual_baseline_minutes=240.0, human_review_minutes=120.0, adoption_status="REJECTED"),
        ]
        summary = RoiCalculator.aggregate(rows)
        self.assertEqual(summary["runs_with_feedback"], 2)
        self.assertEqual(summary["total_minutes_saved"], 540.0)
        self.assertEqual(summary["adopted_runs"], 1)
        self.assertGreater(summary["aggregate_roi_ratio"], 0)

    def test_empty_aggregate(self):
        summary = RoiCalculator.aggregate([])
        self.assertEqual(summary["runs_with_feedback"], 0)
        self.assertEqual(summary["aggregate_roi_ratio"], 0.0)


class FailureLibraryTests(unittest.TestCase):
    def test_load_catalog(self):
        library = FailureLibrary.load(ROOT / "docs" / "failure-cases" / "catalog.yaml")
        self.assertGreaterEqual(len(library.cases), 5)
        self.assertIn("quota", library.by_tag("quota")[0].tags)

    def test_match_by_detection_string(self):
        library = FailureLibrary.load(ROOT / "docs" / "failure-cases" / "catalog.yaml")
        hits = library.match("got 403: You've reached your usage limit for this billing cycle")
        self.assertTrue(any(case.case_id == "FC-001" for case in hits))

    def test_case_model_roundtrip(self):
        case = FailureCase(case_id="X", title="t", detection="d", recovery="r")
        self.assertEqual(case.case_id, "X")


if __name__ == "__main__":
    unittest.main()
