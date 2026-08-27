"""Product-image linkage + brand x channel matrix regression tests.

1) t1: pixel-verified product photos archived under product-level entity ids
   (no Product record linkage) must still enter the products chapter inline
   instead of falling out of every chapter budget.
2) t2: channel heatmap prefers a brand x channel matrix built from
   05/06 channel columns and falls back to the model-level view when
   brand-level evidence is too thin.
"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
VENDOR_SCRIPTS = SKILL_ROOT / "vendor" / "skills" / "overseas-energy-market-research" / "scripts"

from tests.test_office_image_publication import OfficeImagePublicationTests

try:
    if str(VENDOR_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(VENDOR_SCRIPTS))
    import render_charts  # noqa: E402

    RENDER_CHARTS_OK = True
except Exception:  # pragma: no cover - matplotlib/theme deps optional in host venv
    render_charts = None
    RENDER_CHARTS_OK = False


class UnlinkedProductImageChapterTests(unittest.TestCase):
    def _bundle_with_unlinked_product_images(self, temp: str):
        base = OfficeImagePublicationTests()
        bundle, word_binding, _ = base._bundle_and_bindings(temp)
        template = bundle.images[0]
        extras = []
        for index in range(10):
            extras.append(template.model_copy(update={
                "image_id": f"IMAGE-UNLINKED-{index}",
                "image_type": "product",
                "product_id": None,
                "factory_id": None,
                "target_entity_type": "product",
                # archived under a product-level entity id, not the company
                "target_entity_id": f"ENT-PRODUCT-ENTITY-{index % 3}",
                "entity_id": None,
                "phash": f"unlinked-phash-{index}",
                "alt_text": f"未绑定产品记录的产品图 {index}",
                "visual_verified": True,
                "verification_method": "vision",
            }))
        return bundle.model_copy(update={"images": [*bundle.images, *extras]}), {
            item.image_id for item in extras
        }

    def test_products_chapter_includes_unlinked_product_images(self) -> None:
        from energy_research_agent.artifacts.narrative import NarrativeBuilder

        with tempfile.TemporaryDirectory() as temp:
            bundle, extra_ids = self._bundle_with_unlinked_product_images(temp)
            ids = NarrativeBuilder()._images_for(
                bundle,
                chapter="products",
                entity_id=bundle.entities[0].entity_id,
                product_ids=set(),
            )
            # all ten verified product photos enter inline despite the
            # static chapter budget of 8
            self.assertTrue(extra_ids <= set(ids), f"missing: {extra_ids - set(ids)}")

    def test_products_chapter_prefers_linked_images_first(self) -> None:
        from energy_research_agent.artifacts.narrative import NarrativeBuilder

        with tempfile.TemporaryDirectory() as temp:
            bundle, extra_ids = self._bundle_with_unlinked_product_images(temp)
            product_id = bundle.products[0].product_id
            ids = NarrativeBuilder()._images_for(
                bundle,
                chapter="products",
                entity_id=bundle.entities[0].entity_id,
                product_ids={product_id},
            )
            self.assertTrue(extra_ids <= set(ids))


@unittest.skipUnless(RENDER_CHARTS_OK, "render_charts dependencies unavailable")
class BrandChannelMatrixTests(unittest.TestCase):
    def _write(self, project: Path, filename: str, rows: list[dict]) -> None:
        if not rows:
            return
        with (project / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_brand_channel_matrix_merges_05_and_06(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self._write(project, "05_Pricing_Channel.csv", [
                {"brand": "比亚迪", "exact_model": "Battery-Box", "channel": "分销商、EPC"},
                {"brand": "未披露", "exact_model": "户用储能系统", "channel": "未披露"},
            ])
            self._write(project, "06_Channel_Service.csv", [
                {"brand": "隆基", "exact_model": "品牌整体", "online_channel": "官网直销",
                 "offline_channel": "安装商", "installation_service": "未披露"},
                {"brand": "未披露", "exact_model": "未知", "online_channel": "",
                 "offline_channel": "", "installation_service": ""},
            ])
            matrix, sources, _ = render_charts._brand_channel_matrix(project)
            self.assertEqual(matrix["比亚迪"], {"分销商", "EPC"})
            self.assertEqual(matrix["隆基"], {"官网直销", "安装商"})
            self.assertEqual(len(matrix), 2)
            self.assertIn("05_Pricing_Channel.csv", sources)
            self.assertIn("06_Channel_Service.csv", sources)

    def test_channel_heatmap_uses_brand_matrix_when_available(self) -> None:
        plt = render_charts.load_matplotlib()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self._write(project, "05_Pricing_Channel.csv", [
                {"brand": "比亚迪", "exact_model": "Battery-Box", "channel": "分销商、EPC"},
            ])
            self._write(project, "06_Channel_Service.csv", [
                {"brand": "Sonnen", "exact_model": "品牌整体", "online_channel": "电商",
                 "offline_channel": "能源服务商", "installation_service": ""},
            ])
            result = render_charts.channel_heatmap(project, plt)
            self.assertIsNotNone(result)
            _fig, meta = result
            self.assertEqual(meta["name"], "channel_coverage_heatmap")
            self.assertEqual(meta["title"], "品牌渠道覆盖热力图")
            self.assertIn("八、定价、渠道、安装与服务网络", meta["placement"]["section_heading"])

    def test_channel_heatmap_falls_back_to_model_level(self) -> None:
        plt = render_charts.load_matplotlib()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            # only one brand -> brand matrix rejected, model-level fallback
            self._write(project, "05_Pricing_Channel.csv", [
                {"brand": "比亚迪", "exact_model": "Battery-Box HVM", "channel": "分销商"},
                {"brand": "未披露", "exact_model": "户用储能系统", "channel": "电商"},
            ])
            result = render_charts.channel_heatmap(project, plt)
            self.assertIsNotNone(result)
            _fig, meta = result
            self.assertEqual(meta["title"], "渠道覆盖热力图")


if __name__ == "__main__":
    unittest.main()
