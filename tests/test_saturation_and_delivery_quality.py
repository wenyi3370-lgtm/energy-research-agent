from __future__ import annotations

import unittest
from pathlib import Path

from enterprise_energy_research.research.planner import ResearchPlanner
from enterprise_energy_research.research.saturation import CollectionAttemptSummary, DataSaturationValidator
from enterprise_energy_research.settings import load_yaml
from enterprise_energy_research.validation.delivery_quality import PptVisualDeliveryRecord, inspect_ppt_visual_delivery
from enterprise_energy_research.domain.enums import EnterpriseComplexity


ROOT = Path(__file__).resolve().parents[1]


class SaturationAndDeliveryQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_yaml(ROOT / "config" / "collection_saturation_policy.yaml")

    def _attempt(self, goal: str, round_name: str, batch: str, new: list[str] | None = None) -> CollectionAttemptSummary:
        return CollectionAttemptSummary(
            goal_family=goal,
            round=round_name,
            batch_id=batch,
            attempted_queries=1,
            unique_sources=2,
            source_types={"official", "independent"},
            fulltext_captures=1,
            material_records=1,
            critical_claim_count=1 if round_name == "R3" else 0,
            independently_verified_critical_claim_count=1 if round_name == "R3" else 0,
            inspected_sources=2,
            new_high_priority_ids=new or [],
            raw_capture_refs=[f"raw/{goal}/{batch}.json"],
        )

    def test_planner_emits_three_rounds_per_topic(self) -> None:
        plan = ResearchPlanner().build(
            "RUN-1", "ENT-1", "测试公司", EnterpriseComplexity.ENTERPRISE_NORMAL,
            {"max_queries": 90, "max_pages": 120},
        )
        by_topic: dict[str, set[str]] = {}
        for query in plan.queries:
            by_topic.setdefault(query.topic, set()).add(query.collection_round)
        self.assertTrue(by_topic)
        self.assertTrue(all(rounds == {"R1", "R2", "R3"} for rounds in by_topic.values()))

    def test_three_rounds_and_two_zero_batches_can_saturate(self) -> None:
        attempts = [
            self._attempt("identity", "R1", "b1", ["entity"]),
            self._attempt("identity", "R2", "b2", ["registered-name"]),
            self._attempt("identity", "R3", "b3"),
            self._attempt("identity", "R3", "b4"),
        ]
        result = DataSaturationValidator(self.policy).assess(attempts, scoped_goal_families=["identity"])
        self.assertEqual(result.status, "SATURATED")

    def test_budget_exhaustion_with_missing_rounds_blocks(self) -> None:
        result = DataSaturationValidator(self.policy).assess(
            [self._attempt("identity", "R1", "b1")],
            scoped_goal_families=["identity"],
            critical_gap_ids=["identity-controller"],
            budget_exhausted=True,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("identity", result.missing_rounds)

    def test_ppt_visual_gate_requires_fix_cycle_and_visuals(self) -> None:
        findings = inspect_ppt_visual_delivery(PptVisualDeliveryRecord(
            slide_count=17,
            rendered_slide_count=17,
            all_pages_inspected=True,
            contact_sheet_exists=True,
            visual_fix_cycle_count=0,
            action_title_count=15,
            visual_slide_count=16,
            sourced_slide_count=16,
            layout_family_count=4,
            storyline_exists=True,
            evidence_map_exists=True,
            full_rerender_after_fix=False,
        ))
        self.assertTrue(any("fix" in finding for finding in findings))
        self.assertTrue(any("Text-only" in finding for finding in findings))

    def test_ppt_visual_gate_accepts_complete_visual_record(self) -> None:
        findings = inspect_ppt_visual_delivery(PptVisualDeliveryRecord(
            slide_count=17,
            rendered_slide_count=17,
            all_pages_inspected=True,
            contact_sheet_exists=True,
            visual_fix_cycle_count=1,
            action_title_count=15,
            visual_slide_count=17,
            sourced_slide_count=16,
            layout_family_count=9,
            storyline_exists=True,
            evidence_map_exists=True,
            maximum_consecutive_same_layout=1,
            full_rerender_after_fix=True,
            required_verified_image_count=3,
            embedded_verified_image_count=3,
            image_caption_source_count=3,
        ))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
