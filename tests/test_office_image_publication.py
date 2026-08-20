from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from enterprise_energy_research.artifacts.ppt import PptMasterFrozenPublisher
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class OfficeImagePublicationTests(unittest.TestCase):
    def _bundle_and_bindings(self, temp: str):
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
            config_hash="fixture", code_version="0.8.1", model_gateway={"mode": "fixture"},
        ))
        state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
            raw[0]["entities"][0]["canonical_name"],
            [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
        )
        bundle = FreezeService(store).load_bundle(state.freeze_id)

        def asset(name: str, size: tuple[int, int], color: tuple[int, int, int]) -> tuple[Path, str]:
            path = Path(temp) / name
            Image.new("RGB", size, color).save(path, format="PNG")
            return path, hashlib.sha256(path.read_bytes()).hexdigest()

        logo_path, logo_hash = asset("logo.png", (800, 300), (111, 43, 134))
        product_path, product_hash = asset("product.png", (1200, 900), (45, 90, 138))
        factory_path, factory_hash = asset("factory.png", (1200, 800), (27, 54, 93))
        logo = next(image for image in bundle.images if image.image_type == "logo").model_copy(update={
            "local_asset_ref": str(logo_path), "sha256": logo_hash, "mime_type": "image/png", "width": 800, "height": 300,
        })
        product = next(image for image in bundle.images if image.image_type == "product").model_copy(update={
            "local_asset_ref": str(product_path), "sha256": product_hash, "mime_type": "image/png", "width": 1200, "height": 900,
        })
        factory = product.model_copy(update={
            "image_id": "IMAGE-FACTORY-TEST", "image_type": "factory", "product_id": None,
            "factory_id": bundle.factories[0].factory_id, "local_asset_ref": str(factory_path),
            "sha256": factory_hash, "phash": "factory-test-phash", "width": 1200, "height": 800,
            "alt_text": "示例能源装备有限公司生产基地实景",
        })
        bundle = bundle.model_copy(update={"images": [logo, product, factory]})
        word_binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD).model_copy(update={
            "image_ids": [logo.image_id, product.image_id, factory.image_id],
        })
        # PPT 已从交付流程移除（planner 不再计划），手工构造绑定以测试 ppt 模块图片契约
        from enterprise_energy_research.domain.models import ArtifactBinding
        from enterprise_energy_research.domain.enums import ArtifactStatus

        ppt_binding = ArtifactBinding(
            artifact_id="ART-PPT-IMG", type=ArtifactType.PPT, status=ArtifactStatus.PLANNED,
            claim_ids=word_binding.claim_ids,
            image_ids=[logo.image_id, product.image_id, factory.image_id],
        )
        return bundle, word_binding, ppt_binding

    def test_word_embeds_real_images_in_mapped_chapters_without_removing_charts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, binding, _ = self._bundle_and_bindings(temp)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published")
            self.assertEqual(set(result.used_image_ids), set(binding.image_ids))
            with zipfile.ZipFile(target) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
            self.assertGreaterEqual(xml.count("<w:drawing>"), 22)  # 19 charts + 3 verified images
            self.assertIn("图 4-P1", xml)
            self.assertIn("图 5-P1", xml)
            self.assertIn("图片来源：", xml)
            image_manifest = json.loads((Path(temp) / "report_assets" / "image_publication_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(image_manifest["artifact_selections"]["word"]), set(binding.image_ids))
            self.assertEqual(len(image_manifest["prepared_images"]), 3)
            self.assertTrue((Path(temp) / "report_assets" / "visual_manifest.json").is_file())

    def test_ppt_contract_adds_images_beside_existing_product_and_factory_charts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _, binding = self._bundle_and_bindings(temp)
            target = Path(temp) / "report.pptx"
            result = PptMasterFrozenPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "failed")  # executor confirmation remains a hard stop
            project = Path(temp) / "report_ppt_master_project"
            brief = json.loads((project / "frozen_brief.json").read_text(encoding="utf-8"))
            product_slide = brief["slides"][7]
            factory_slide = brief["slides"][6]
            self.assertEqual(product_slide["visual_id"], "FIG-04-PRODUCT-PORTFOLIO")
            self.assertEqual(factory_slide["visual_id"], "FIG-05-FACTORY-FOOTPRINT")
            self.assertTrue(any(item["image_type"] == "product" for item in product_slide["image_placements"]))
            self.assertTrue(any(item["image_type"] == "factory" for item in factory_slide["image_placements"]))
            self.assertTrue(all(item["caption"] and item["source_note"] for slide in brief["slides"] for item in slide["image_placements"]))
            selected = brief["presentation_evidence_map"]["required_verified_image_ids"]
            self.assertEqual(set(selected), set(binding.image_ids))
            self.assertEqual(set(result.used_image_ids), set(binding.image_ids))


if __name__ == "__main__":
    unittest.main()
