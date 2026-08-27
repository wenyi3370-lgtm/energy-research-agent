"""P0-19 regression: the generic research platform must not hardcode any
specific company's facts or industry parameters.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CONFIG = ROOT / "config"

COMPANY_TOKENS = (
    "杉金光电", "杉杉", "shanshan", "芬兰负极材料", "偏光片", "polarizer",
    "韩国、日本销售", "四川基地", "内蒙古厂区",
)
# Parameter explanations may only exist inside the industry-keyed registry.
INDUSTRY_PARAM_TOKENS = ("D50", "振实密度", "首次效率")


class NoHardcodingTests(unittest.TestCase):
    def test_no_company_specific_hardcoding(self) -> None:
        violations: list[str] = []
        for path in [*SRC.rglob("*.py"), *CONFIG.rglob("*.yaml")]:
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in COMPANY_TOKENS:
                if token.lower() in text.lower():
                    violations.append(f"{path}: {token}")
        self.assertEqual(violations, [], "company-specific hardcoding remains")

    def test_industry_parameters_not_hardcoded_in_publishers(self) -> None:
        """D50-style explanations must not live unconditionally in publishers."""
        for name in ("word.py", "html.py", "excel.py"):
            path = SRC / "energy_research_agent" / "artifacts" / name
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in INDUSTRY_PARAM_TOKENS:
                self.assertNotIn(token, text, f"{name} hardcodes industry parameter {token}")

    def test_parameter_registry_is_industry_keyed(self) -> None:
        from energy_research_agent.research.parameter_registry import ParameterInterpretationRegistry
        registry = ParameterInterpretationRegistry()
        self.assertIsNotNone(registry.interpretation("battery_material", None, "D50"))
        # Other industries receive no battery-material commentary.
        self.assertIsNone(registry.interpretation("textile", None, "D50"))
        self.assertIsNone(registry.interpretation(None, None, "D50"))


if __name__ == "__main__":
    unittest.main()
