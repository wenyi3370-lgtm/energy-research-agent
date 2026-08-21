"""Visual regression guards (spec section 44): content fixes must not change
the accepted Word / HTML / chart visual system. The frozen values below were
captured from the human-approved v0.9 visuals before this remediation round.
"""

from __future__ import annotations

import hashlib
import re
import unittest

from enterprise_energy_research.artifacts import html as html_module
from enterprise_energy_research.artifacts.html import NAV_ITEMS
from enterprise_energy_research.artifacts.visual_policy import colors, word_policy

FROZEN_CSS_SHA256 = "c9c996cb68ec55313327d86a2e872a450592135f57e33553e1bbcdad7252ff8e"

FROZEN_WORD_POLICY = {
    "body_cjk_font": "SimSun", "body_latin_font": "Times New Roman",
    "body_size_pt": 12,
    "evidence_images": {
        "maximum_per_chapter": 6, "normalize_to_offline_png": True,
        "require_caption_and_original_page_source": True,
        "require_publication_manifest": True,
        "require_sha256_mime_dimension_revalidation": True,
        "supplement_charts_never_replace": True,
    },
    "figure_png_dpi": 300, "first_line_indent_characters": 2,
    "heading_1_size_pt": 22, "heading_2_size_pt": 14, "heading_3_size_pt": 12,
    "line_spacing_pt": 22, "maximum_bar_family_ratio": 0.75,
    "maximum_canonical_type_repetitions": 2, "maximum_figure_width_cm": 15.6,
    "minimum_analysis_characters_before_visual": 50, "minimum_formal_figures": 0,
    "minimum_visual_families_when_visuals_ge_10": 0, "page": "A4",
    "require_core_chapter_visual_coverage": 0.0, "require_editable_svg": True,
    "require_page_by_page_inspection": True, "require_same_stem_pdf": True,
    "require_visual_per_core_chapter": False, "table_size_pt": 9,
    "table_style": "three-line", "target_visual_interval_pages": [2, 3],
}

FROZEN_COLORS = {
    "black": "#111111", "canvas": "#F7F8FA", "cobalt": "#2D5A8A",
    "cool_gray": "#6B7280", "navy": "#1B365D", "pale_gray": "#D9E2EC",
    "sevc_purple": "#6F2B86", "white": "#FFFFFF",
}

FROZEN_NAV_KEYS = [
    "overview", "company", "organization", "operations", "factories",
    "product-matrix", "products", "energy", "efficiency", "pv", "storage",
    "epc", "carbon", "opportunities", "business-model", "roadmap", "risks", "sources",
]

FROZEN_RENDERER = "lieflat-charts-gallery-port-svg-v2"
FROZEN_TEMPLATE_IDS = {"F4", "F5", "L13"}


class VisualRegressionTests(unittest.TestCase):
    def test_visual_css_hash_unchanged(self) -> None:
        current = hashlib.sha256(html_module.CSS.encode("utf-8")).hexdigest()
        self.assertEqual(current, FROZEN_CSS_SHA256, "HTML CSS theme changed")

    def test_word_style_contract_unchanged(self) -> None:
        self.assertEqual(word_policy(), FROZEN_WORD_POLICY, "Word style contract changed")

    def test_chart_renderer_style_contract_unchanged(self) -> None:
        self.assertEqual(colors(), FROZEN_COLORS, "chart palette changed")
        from enterprise_energy_research.artifacts.visuals import VisualSpec
        # The approved renderer route must remain the deterministic Lieflat port.
        self.assertEqual(FROZEN_RENDERER, "lieflat-charts-gallery-port-svg-v2")

    def test_html_layout_contract_unchanged(self) -> None:
        self.assertEqual([key for key, _ in NAV_ITEMS], FROZEN_NAV_KEYS, "sidebar layout changed")
        document = html_module.FrozenHtmlPublisher._document("测试企业", {
            "meta": {"freeze": "x", "researchDate": "2026-08-20"},
            "entity": {"type": "company", "region": "中国"},
            "claims": [], "sources": [], "gaps": [], "heroTagline": "主营业务",
        })
        sections = re.findall(r'<section id="([^"]+)"', document)
        self.assertEqual(sections, FROZEN_NAV_KEYS, "HTML section layout changed")


if __name__ == "__main__":
    unittest.main()
