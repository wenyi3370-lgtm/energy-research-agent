"""Visual regression guards (P0 refactor): the accepted consulting visual
system is diagram-design, not Lieflat.  Frozen values below were captured
from the approved refactored visual layer.
"""

from __future__ import annotations

import hashlib
import re
import unittest

from enterprise_energy_research.artifacts import html as html_module
from enterprise_energy_research.artifacts.diagram_design_adapter import ENTERPRISE_PROFILE
from enterprise_energy_research.artifacts.visual_policy import colors, word_policy

# P0 third-round baseline: ENTERPRISE RESEARCH DASHBOARD hero (real KPI grid,
# judgement demoted to one module) instead of the decision-first hero.
FROZEN_CSS_SHA256 = "f4bc660a21f34da93907d287cc238345316ad18360ed0d180ea32110bbd9d908"

FROZEN_WORD_POLICY = {
    "page": "A4", "body_cjk_font": "SimSun", "body_latin_font": "Times New Roman",
    "body_size_pt": 12, "line_spacing_pt": 22, "first_line_indent_characters": 2,
    "heading_1_size_pt": 22, "heading_2_size_pt": 14, "heading_3_size_pt": 12,
    "table_size_pt": 9, "table_style": "three-line", "figure_png_dpi": 300,
    "maximum_figure_width_cm": 15.6, "minimum_analysis_characters_before_visual": 0,
    "require_editable_svg": True,
    "evidence_images": {
        "require_publication_manifest": True,
        "require_sha256_mime_dimension_revalidation": True,
        "normalize_to_offline_png": True,
        "require_caption_and_original_page_source": True,
        "supplement_charts_never_replace": True,
        "require_target_entity_binding": True,
        "require_visual_verification": True,
    },
}

FROZEN_COLORS = {
    "black": "#1B1F26", "canvas": "#F7F8FA", "cobalt": "#2D5A8A",
    "cool_gray": "#4A5568", "navy": "#1B365D", "pale_gray": "#C9D4E0",
    "white": "#FFFFFF",
}

FROZEN_VISUAL_SYSTEM = "diagram-design"


class VisualRegressionTests(unittest.TestCase):
    def test_visual_css_hash_unchanged(self) -> None:
        current = hashlib.sha256(html_module.CSS.encode("utf-8")).hexdigest()
        self.assertEqual(current, FROZEN_CSS_SHA256, "HTML CSS theme changed")

    def test_word_style_contract_unchanged(self) -> None:
        self.assertEqual(word_policy(), FROZEN_WORD_POLICY, "Word style contract changed")

    def test_visual_system_contract_unchanged(self) -> None:
        self.assertEqual(colors(), FROZEN_COLORS, "consulting palette changed")
        # The approved visual system is diagram-design with the enterprise profile.
        self.assertEqual(ENTERPRISE_PROFILE["accent"], "#1B365D", "navy accent changed")
        self.assertIn("Microsoft YaHei", ENTERPRISE_PROFILE["font_sans"])

    def test_html_layout_is_narrative_driven(self) -> None:
        # No fixed 18-section layout: sections come from the narrative payload.
        document = html_module.FrozenHtmlPublisher._document("测试企业", {
            "meta": {"freeze": "x", "researchDate": "2026-08-20", "generatedAt": "2026-08-21",
                     "counts": {"verified_claims": 1, "sources": 1, "chapters": 2}},
            "entity": {"type": "company", "region": "中国", "id": "e1", "name": "测试企业", "status": "verified", "website": ""},
            "chapters": [
                {"id": "executive_summary", "title": "决策结论"},
                {"id": "sources", "title": "数据来源"},
            ],
            "decisionQuestions": ["问题"], "insights": [], "products": [], "sources": [],
        })
        self.assertIn('data-visual-system="diagram-design"', document)
        self.assertNotIn("lieflat", document.lower())
        # dynamic nav comes from the chapters payload, not a fixed list
        self.assertIn("决策结论", document)
        self.assertNotIn("集团与成员证据名录", document)
        fixed_sections = re.findall(r'<section id="([^"]+)"', document)
        self.assertEqual(fixed_sections, [])  # no fixed section list; chapters are dynamic


if __name__ == "__main__":
    unittest.main()
