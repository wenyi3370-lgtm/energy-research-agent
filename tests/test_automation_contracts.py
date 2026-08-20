import unittest

from pydantic import ValidationError

from enterprise_energy_research.automation import (
    ArtifactRef,
    CostMetrics,
    Priority,
    ResearchError,
    ResearchRequest,
    ResearchResult,
    ResearchType,
    RiskLevel,
    TaskStatus,
)
from enterprise_energy_research.domain.enums import ArtifactStatus, ArtifactType, ValidationStatus


SPEC_EXAMPLE = {
    "task_id": "TH_BESS_001",
    "requested_by": "user_001",
    "country": "Thailand",
    "product": "Residential BESS",
    "research_type": "market_entry",
    "topics": ["market_size", "policy", "competitor", "pricing", "channel"],
    "priority": "normal",
    "language": "zh-CN",
}


class TestResearchRequest(unittest.TestCase):
    def test_spec_example_parses(self):
        request = ResearchRequest.model_validate(SPEC_EXAMPLE)
        self.assertEqual(request.task_id, "TH_BESS_001")
        self.assertEqual(request.research_type, ResearchType.MARKET_ENTRY)
        self.assertEqual(request.priority, Priority.NORMAL)
        self.assertEqual(request.language, "zh-CN")
        self.assertEqual(len(request.topics), 5)
        self.assertIsNone(request.company)
        self.assertIsNone(request.idempotency_key)

    def test_requires_at_least_one_subject(self):
        payload = {"task_id": "T1", "requested_by": "u1", "research_type": "other"}
        with self.assertRaises(ValidationError):
            ResearchRequest.model_validate(payload)

    def test_rejects_unknown_fields(self):
        payload = dict(SPEC_EXAMPLE, unexpected_field="x")
        with self.assertRaises(ValidationError):
            ResearchRequest.model_validate(payload)

    def test_rejects_blank_identifiers(self):
        payload = dict(SPEC_EXAMPLE, task_id="   ")
        with self.assertRaises(ValidationError):
            ResearchRequest.model_validate(payload)

    def test_normalizes_whitespace_and_drops_empty_topics(self):
        payload = dict(SPEC_EXAMPLE, task_id="  TH_BESS_001  ", topics=["policy", "  ", ""])
        request = ResearchRequest.model_validate(payload)
        self.assertEqual(request.task_id, "TH_BESS_001")
        self.assertEqual(request.topics, ["policy"])

    def test_to_domain_request_with_company(self):
        payload = dict(SPEC_EXAMPLE, company="ABC Energy Co., Ltd.")
        request = ResearchRequest.model_validate(payload)
        domain = request.to_domain_request(request_id="REQ-1")
        self.assertEqual(domain.raw_company_name, "ABC Energy Co., Ltd.")
        self.assertEqual(domain.locale, "zh-CN")
        self.assertEqual(domain.optional_scope["task_id"], "TH_BESS_001")
        self.assertEqual(domain.optional_scope["research_type"], "market_entry")

    def test_to_domain_request_without_company_synthesizes_market_subject(self):
        request = ResearchRequest.model_validate(SPEC_EXAMPLE)
        domain = request.to_domain_request(request_id="REQ-2")
        self.assertEqual(domain.raw_company_name, "Thailand Residential BESS market")
        self.assertEqual(domain.optional_scope["product"], "Residential BESS")
        self.assertEqual(domain.optional_scope["topics"][0], "market_size")


class TestResearchResult(unittest.TestCase):
    def build_result(self) -> ResearchResult:
        return ResearchResult(
            run_id="RUN-001",
            task_id="TH_BESS_001",
            status=TaskStatus.PUBLISHED,
            validation_status=ValidationStatus.PASS_WITH_WARNINGS,
            confidence=0.82,
            risk_level=RiskLevel.MEDIUM,
            review_required=True,
            review_reasons=["conflicting_sources"],
            evidence_count=128,
            conflict_count=2,
            gap_count=3,
            artifact_manifest=[
                ArtifactRef(
                    artifact_type=ArtifactType.WORD,
                    status=ArtifactStatus.PUBLISHED,
                    location="outputs/RUN-001/word/report.docx",
                )
            ],
            cost_metrics=CostMetrics(input_tokens=12000, output_tokens=3000, llm_calls=14),
        )

    def test_result_round_trips_through_json(self):
        result = self.build_result()
        restored = ResearchResult.model_validate_json(result.model_dump_json())
        self.assertEqual(restored, result)

    def test_result_defaults(self):
        result = ResearchResult(run_id="RUN-2", task_id="T2", status=TaskStatus.CREATED)
        self.assertFalse(result.review_required)
        self.assertEqual(result.evidence_count, 0)
        self.assertEqual(result.cost_metrics.estimated_cost_usd, 0.0)
        self.assertIsNone(result.error)
        self.assertIsNone(result.validation_status)

    def test_confidence_is_bounded(self):
        with self.assertRaises(ValidationError):
            ResearchResult(
                run_id="RUN-3", task_id="T3", status=TaskStatus.FAILED, confidence=1.5
            )

    def test_structured_error(self):
        error = ResearchError(
            error_type="TRANSIENT_SEARCH_FAILURE",
            message="anysearch timeout",
            failed_step="SEARCH",
            retryable=True,
        )
        result = ResearchResult(
            run_id="RUN-4", task_id="T4", status=TaskStatus.FAILED, error=error
        )
        self.assertTrue(result.error.retryable)
        self.assertEqual(result.error.failed_step, "SEARCH")

    def test_task_status_covers_full_state_machine(self):
        expected = {
            "CREATED", "QUEUED", "RESEARCHING", "EVIDENCE_COLLECTED", "VALIDATING",
            "REVIEW_REQUIRED", "APPROVED", "REJECTED", "FROZEN", "PUBLISHING",
            "PUBLISHED", "RETRYING", "FAILED", "BLOCKED",
        }
        self.assertEqual({status.value for status in TaskStatus}, expected)


if __name__ == "__main__":
    unittest.main()
