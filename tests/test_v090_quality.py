from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from energy_research_agent.domain.models import ImageEvidence
from energy_research_agent.research.image_semantics import ImageSemanticRouter
from energy_research_agent.validation.visual_qa import inspect_html_visual


class V090QualityTests(unittest.TestCase):
    def _image(self, text: str) -> ImageEvidence:
        return ImageEvidence(
            image_id="IMG-1", source_url="https://example.com/image.png", source_page_url="https://example.com/page",
            source_id="SRC-1", source_domain="example.com", source_title=text, image_type="other",
            sha256="a" * 64, phash="1" * 16, width=800, height=600, mime_type="image/png",
            verification_status="UNVERIFIED", confidence=0.0,
        )

    def test_image_semantic_routing_uses_page_context(self) -> None:
        self.assertEqual(ImageSemanticRouter.classify(self._image("公司生产线实景")).image_type, "production_line")
        self.assertEqual(ImageSemanticRouter.classify(self._image("产品应用场景")).image_type, "product_application")
        self.assertEqual(ImageSemanticRouter.classify(self._image("无语义图片")).image_type, "other")

    def test_html_static_check_blocks_without_four_rendered_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dashboard.html"
            path.write_text("<!doctype html><style>@media(max-width:768px){}</style><img src='data:image/png;base64,abcdefghijklmnop'>", encoding="utf-8")
            report = inspect_html_visual(path)
            self.assertEqual(report.status, "BLOCKED")
            self.assertTrue(any("360" in finding and "1920" in finding for finding in report.findings))


if __name__ == "__main__":
    unittest.main()
