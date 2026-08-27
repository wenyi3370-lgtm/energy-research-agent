"""Every pixel-verified (valid) image must be embedded in Word and HTML.

Regression for run6 gap: 14 prepared images but only 1 embedded in the
Word report / HTML dashboard because per-chapter narrative image budgets
(IMAGE_BUDGETS) left most images unassigned. The Word appendix gallery
and the HTML evidence-gallery chapter guarantee full publication.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from energy_research_agent.artifacts.html import FrozenHtmlPublisher
from energy_research_agent.artifacts.word import FrozenWordPublisher
from energy_research_agent.domain.enums import ArtifactType

from tests.test_office_image_publication import OfficeImagePublicationTests


class AllVerifiedImagesEmbeddedTests(unittest.TestCase):
    def _bundle_with_budget_overflow_images(self, temp: str):
        base = OfficeImagePublicationTests()
        bundle, word_binding, _ = base._bundle_and_bindings(temp)
        # The products chapter budget is 8: adding 9 extra verified product
        # photos guarantees at least one valid image stays unassigned.
        extras = []
        for index in range(9):
            path = Path(temp) / f"extra_{index}.png"
            width, height = 320 + index, 240
            pixels = [
                ((x * 7 + y * 13 + index * 41) % 256, (x * 3 + y * 5 + index * 17) % 256, (x + y + index * 29) % 256)
                for y in range(height) for x in range(width)
            ]
            canvas = Image.new("RGB", (width, height))
            canvas.putdata(pixels)
            canvas.save(path, format="PNG")
            template = bundle.images[0]
            extras.append(template.model_copy(update={
                "image_id": f"IMAGE-EXTRA-{index}", "image_type": "product",
                "product_id": bundle.products[0].product_id, "factory_id": None,
                "local_asset_ref": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "phash": f"extra-phash-{index}",
                "width": width, "height": height,
                "alt_text": f"溢出预算的核验产品图 {index}",
                "visual_verified": True, "verification_method": "vision",
                "target_entity_id": bundle.entities[0].entity_id,
                "target_entity_type": "product",
            }))
        bundle = bundle.model_copy(update={"images": [*bundle.images, *extras]})
        word_binding = word_binding.model_copy(update={
            "image_ids": [*word_binding.image_ids, *[item.image_id for item in extras]],
        })
        return bundle, word_binding, {item.image_id for item in extras}

    def test_word_appendix_gallery_embeds_every_prepared_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, binding, extra_ids = self._bundle_with_budget_overflow_images(temp)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published")
            manifest = json.loads((Path(temp) / "report_assets" / "image_publication_manifest.json").read_text(encoding="utf-8"))
            prepared_ids = {item["image_id"] for item in manifest["prepared_images"]}
            self.assertTrue(extra_ids & prepared_ids)
            self.assertEqual(set(manifest["artifact_selections"]["word"]), prepared_ids)
            with zipfile.ZipFile(target) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
                media = [n for n in archive.namelist() if n.startswith("word/media/")]
            self.assertIn("附录 G：图片证据全集", xml)
            # products-chapter widening now embeds verified product images
            # inline; the appendix gallery only carries whatever remains.
            # Every prepared image must appear somewhere in the document.
            self.assertGreaterEqual(len(media), len(prepared_ids))

    def test_html_gallery_contains_every_prepared_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, binding, extra_ids = self._bundle_with_budget_overflow_images(temp)
            html_binding = binding.model_copy(update={"type": ArtifactType.ENTERPRISE_HTML})
            target = Path(temp) / "dashboard.html"
            result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(bundle, html_binding, target)
            self.assertEqual(result.status, "published")
            raw = target.read_text(encoding="utf-8")
            manifest = json.loads((Path(temp) / "dashboard_assets" / "image_publication_manifest.json").read_text(encoding="utf-8"))
            prepared_ids = {item["image_id"] for item in manifest["prepared_images"]}
            narrative = json.loads((Path(temp) / "dashboard_assets" / "narrative.json").read_text(encoding="utf-8"))
            assigned = {
                image_id
                for chapter in narrative.get("chapters", [])
                for image_id in chapter.get("image_ids", [])
            }
            # Widened products budget means every verified product image can
            # now be assigned inline; the gallery chapter only renders for
            # whatever genuinely remains unassigned.  Either way every
            # prepared image must be embedded somewhere in the HTML.
            overflow = prepared_ids - assigned
            if overflow:
                self.assertIn("图片证据全集", raw)
                for image_id in overflow:
                    self.assertIn(image_id, raw)
            self.assertGreaterEqual(raw.count("data:image/"), len(prepared_ids))
