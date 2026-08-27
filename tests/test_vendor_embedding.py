from __future__ import annotations

import unittest

from enterprise_energy_research.artifacts.excel import ExcelMasterFrozenPublisher
from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.artifacts.ppt import PptMasterFrozenPublisher
from enterprise_energy_research.domain.enums import ArtifactType
from enterprise_energy_research.vendor import EMBEDDED_SKILLS, embedded_skill_available, embedded_skill_root


class VendorEmbeddingTests(unittest.TestCase):
    def test_all_external_skills_are_embedded(self) -> None:
        self.assertEqual(
            set(EMBEDDED_SKILLS),
            {"anysearch", "excel-master", "ppt-master", "frontend-design", "kimi-webbridge", "diagram-design", "overseas-energy-market-research"},
        )
        for name in EMBEDDED_SKILLS:
            with self.subTest(name=name):
                self.assertTrue(embedded_skill_available(name))

    def test_overseas_market_skill_core_resources_are_present(self) -> None:
        root = embedded_skill_root("overseas-energy-market-research")
        for relative in (
            "SKILL.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "VENDOR_INFO.md",
            "scripts/run_workflow.py", "scripts/init_research_project.py",
            "scripts/validate_stage_gate.py", "scripts/web_collection/router.py",
            "scripts/web_collection/journal.py", "scripts/collection_quantity_policy.py",
            "assets/config/collection_quantity_policy.yaml",
            "workflows/overseas_energy_research.workflow.yaml",
            "agents/openai.yaml",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file())

    def test_publishers_prefer_embedded_skill_roots(self) -> None:
        excel = ExcelMasterFrozenPublisher()
        html = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML)
        ppt = PptMasterFrozenPublisher()
        self.assertEqual(excel.skill_root, embedded_skill_root("excel-master"))
        self.assertEqual(html.skill_root, embedded_skill_root("frontend-design"))
        self.assertEqual(ppt.skill_root, embedded_skill_root("ppt-master"))
        self.assertTrue(excel.health().available)
        self.assertTrue(html.health().available)
        self.assertFalse(ppt.health().available)
        self.assertIn("blocking confirmation", " ".join(ppt.health().diagnostics))

    def test_ppt_quality_gate_resources_are_present(self) -> None:
        root = embedded_skill_root("ppt-master")
        for relative in (
            "scripts/svg_quality_checker.py",
            "scripts/finalize_svg.py",
            "scripts/svg_to_pptx.py",
            "templates/design_spec_reference.md",
            "references/strategist.md",
            "references/executor-base.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file())

    def test_anysearch_multiruntime_resources_are_present(self) -> None:
        root = embedded_skill_root("anysearch")
        for relative in (
            "LICENSE", "NOTICE", "scripts/anysearch_cli.py", "scripts/anysearch_cli.js",
            "scripts/anysearch_cli.ps1", "scripts/anysearch_cli.sh",
            "scripts/shared/constants.json", "scripts/shared/doc_spec.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file())

    def test_diagram_design_skill_and_license_are_present(self) -> None:
        root = embedded_skill_root("diagram-design")
        for relative in (
            "SKILL.md", "LICENSE", "THIRD_PARTY_LICENSES.md",
            "references/style-guide.md", "references/export.md",
            "references/output-spec.md", "references/semantic-patterns.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file())

    def test_diagram_design_third_party_notices_are_present(self) -> None:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "third_party" / "diagram-design" / "LICENSE").is_file())
        self.assertTrue((root / "third_party" / "diagram-design" / "NOTICE.md").is_file())


if __name__ == "__main__":
    unittest.main()
