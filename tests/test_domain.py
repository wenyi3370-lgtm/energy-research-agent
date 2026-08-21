from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError

from enterprise_energy_research.domain.enums import ProductDashboardDecision, StatementType
from enterprise_energy_research.domain.ids import RunSequence
from enterprise_energy_research.domain.models import ProductDetection, Solution


class DomainTests(unittest.TestCase):
    def test_run_sequence_formats(self) -> None:
        sequence = RunSequence()
        self.assertEqual(sequence.next("claim"), "CLAIM-000001")
        self.assertEqual(sequence.next("source"), "SOURCE-S001")
        self.assertEqual(sequence.next("image"), "IMAGE-I001")

    def test_product_dashboard_requires_physical_product(self) -> None:
        with self.assertRaises(ValidationError):
            ProductDetection(
                has_physical_products=False,
                product_confidence=0.5,
                product_count=0,
                qualifying_product_ids=[],
                dashboard_decision=ProductDashboardDecision.GENERATE,
                reason="invalid",
            )

    def test_inference_requires_assumptions(self) -> None:
        with self.assertRaises(ValidationError):
            Solution(
                solution_id="SOL-X",
                engine="EPC",
                target_ids=["ENT-X"],
                opportunity="Roof PV",
                proposed_solution="Assess roof PV",
                benefit_logic="Reduce purchased electricity",
                next_step="Site survey",
                priority="B",
                statement_type=StatementType.ANALYTICAL_INFERENCE,
            )

    def test_langgraph_is_an_explicit_optional_dependency(self) -> None:
        # langgraph must be declared ONLY under optional dependencies — never
        # in the base install. This checks the declaration itself, so it holds
        # whether or not langgraph happens to be installed in the test env.
        text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        parts = text.split("[project.optional-dependencies]")
        self.assertEqual(len(parts), 2, "pyproject must declare optional dependencies")
        self.assertNotIn("langgraph", parts[0], "langgraph must not be a base dependency")
        self.assertIn("langgraph", parts[1], "langgraph must be an explicit optional dependency")
        self.assertNotIn("langgraph", text.split("[tool.setuptools]")[0].split("[project.optional-dependencies]")[0])


if __name__ == "__main__":
    unittest.main()
