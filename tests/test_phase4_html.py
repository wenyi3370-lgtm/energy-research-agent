from __future__ import annotations

import json
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class Phase4HtmlTests(unittest.TestCase):
    def _bundle(self, temp: str, fixture: str):
        raw = json.loads((ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8"))
        company = raw[0]["entities"][0]["canonical_name"]
        batches = [ExtractedEvidenceBatch.model_validate(item) for item in raw]
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
            config_hash="fixture", code_version="0.4.0", model_gateway={"mode": "fixture"},
        ))
        state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
            company, batches, output_dir=Path(temp) / "freeze",
        )
        self.assertEqual(state.status, RunStatus.PASS)
        bundle = FreezeService(store).load_bundle(state.freeze_id)
        updated_images = []
        for index, image in enumerate(bundle.images):
            asset = Path(temp) / f"fixture-{index}.png"
            Image.new("RGB", (image.width, image.height), (40 + index * 30, 90, 140)).save(asset, "PNG")
            updated_images.append(image.model_copy(update={
                "local_asset_ref": str(asset), "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "mime_type": "image/png",
            }))
        bundle = bundle.model_copy(update={
            "images": updated_images,
        })
        return bundle, manifest

    def test_enterprise_html_is_standalone_and_embeds_frozen_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp, "normal_manufacturer.json")
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.ENTERPRISE_HTML)
            target = Path(temp) / "enterprise.html"
            result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(bundle, binding, target)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(result.status, "published")
            self.assertIn("SEVC", text)
            self.assertIn(bundle.freeze.root_hash, text)
            self.assertIn("frozen-data", text)
            self.assertIn("lieflat-inline", text)
            self.assertIn('"renderer":"lieflat-charts-gallery-port-svg-v2"', text)
            self.assertIn('data-visual-system="lieflat-mono"', text)
            self.assertIn('data-color-system="mono"', text)
            self.assertIn('id="entityRegister"', text)
            self.assertNotIn('id="orgChart"', text)
            self.assertNotIn("org-arrow", text)
            self.assertNotIn("linear-gradient", text)
            self.assertNotIn("--navy", text)
            self.assertNotIn("<script src=", text)
            self.assertNotIn("<link rel=\"stylesheet\"", text)

    def test_product_html_contains_interactions_and_no_fabricated_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp, "normal_manufacturer.json")
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.ENTERPRISE_HTML)
            target = Path(temp) / "enterprise_research_dashboard.html"
            result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(bundle, binding, target)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(result.status, "published")
            self.assertIn("productSearch", text)
            self.assertIn("comparePanel", text)
            self.assertIn("最多 4 项对比", text)
        self.assertIn("data:image/png;base64,", text)

    def test_product_html_rejects_bundle_without_qualified_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp, "small_simple.json")
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.ENTERPRISE_HTML)
            result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(bundle, binding, Path(temp) / "products.html")
            self.assertEqual(result.status, "published")
            self.assertIn("暂无满足证据与图片门禁", (Path(temp) / "products.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
