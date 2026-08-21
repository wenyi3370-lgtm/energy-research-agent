"""P0-12 / P0-13 regression: goal pipeline trace spans PLANNED -> PUBLISHED,
and gap reasons are classified by the exact stage where the chain stopped.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.adapters.base import SearchHit, SearchResultEnvelope
from enterprise_energy_research.domain.enums import EnterpriseComplexity
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import DataGap
from enterprise_energy_research.research.pipeline_trace import (
    GapReasonClassifier, GoalPipelineTrace,
)
from enterprise_energy_research.research.planner import ResearchPlanner


def envelope(topic: str, hits: int = 0, text_hits: int = 0):
    return SearchResultEnvelope(
        adapter="anysearch", query_id="q", status="ok", topic=topic,
        hits=[
            SearchHit(
                final_url=f"https://example.com/{i}", title="t",
                text="page" if i < text_hits else None,
                status="ok", retrieved_at="2026-08-20T00:00:00Z",
            )
            for i in range(hits)
        ],
    )


class PipelineTraceTests(unittest.TestCase):
    def test_goal_trace_search_to_publish(self) -> None:
        run_id = "RUN-1"
        plan = ResearchPlanner().build(
            run_id, "E1", "ACME", EnterpriseComplexity.ENTERPRISE_NORMAL,
            {"max_queries": 6, "max_pages": 20},
        )
        trace = GoalPipelineTrace.blank(run_id, ["image_evidence", "company_identity"])
        trace.record_plan(plan.queries)
        trace.record_envelope(envelope("company_identity", hits=2, text_hits=1), 2, 2, 1)
        trace.record_synthesis("company_identity", 1, 1)
        trace.stopping_stage()
        self.assertIn("PLANNED", trace.goals["company_identity"].stages)
        self.assertIn("PUBLISHED", trace.goals["company_identity"].stages)
        self.assertEqual(trace.goals["company_identity"].published_findings, 1)
        with tempfile.TemporaryDirectory() as temp:
            path = trace.write(Path(temp))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["goals"]["company_identity"]["search_hits"], 2)

    def test_gap_reason_taxonomy_is_precise(self) -> None:
        run_id = "RUN-2"
        gap = DataGap(gap_id="G1", field_name="factories", importance="critical", reason="missing", next_action="x")
        classifier = GapReasonClassifier()

        trace = GoalPipelineTrace.blank(run_id, ["factories"])
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "NOT_SEARCHED")

        trace.goal("factories").queries = 3
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "SEARCHED_NOT_FOUND")

        trace.goal("factories").search_hits = 5
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "FOUND_NOT_RETRIEVED")

        trace.goal("factories").retrieved_pages = 2
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "RETRIEVED_NOT_EXTRACTED")

        trace.goal("factories").extracted_claims = 4
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "EXTRACTED_NOT_NORMALIZED")

        trace.goal("factories").normalized_claims = 4
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "NORMALIZED_NOT_VERIFIED")

        trace.goal("factories").verified_claims = 2
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "VERIFIED_NOT_SYNTHESIZED")

        trace.goal("factories").synthesis_findings = 1
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "SYNTHESIZED_NOT_PUBLISHED")

        trace.goal("factories").published_findings = 1
        # Only after real searching + retrieval + publication is a
        # PUBLIC_EVIDENCE_GAP permitted.
        self.assertEqual(classifier.classify(gap, trace, family="factories"), "PUBLIC_EVIDENCE_GAP")

    def test_public_evidence_gap_requires_actual_search(self) -> None:
        trace = GoalPipelineTrace.blank("RUN-3", ["financials"])
        gap = DataGap(gap_id="G2", field_name="financials", importance="critical", reason="missing", next_action="x")
        self.assertNotEqual(
            GapReasonClassifier().classify(gap, trace, family="financials"),
            "PUBLIC_EVIDENCE_GAP",
        )


if __name__ == "__main__":
    unittest.main()
