from __future__ import annotations

import json
import base64
import tempfile
import unittest
from pathlib import Path

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
        asset = Path(temp) / "fixture-product.png"
        asset.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="))
        bundle = bundle.model_copy(update={
            "images": [image.model_copy(update={"local_asset_ref": str(asset)}) for image in bundle.images],
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
            self.assertNotIn("<script src=", text)
            self.assertNotIn("<link rel=\"stylesheet\"", text)

    def test_product_html_contains_interactions_and_no_fabricated_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp, "normal_manufacturer.json")
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.PRODUCT_HTML)
            target = Path(temp) / "products.html"
            result = FrozenHtmlPublisher(ArtifactType.PRODUCT_HTML).publish(bundle, binding, target)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(result.status, "published")
            self.assertIn("productSearch", text)
            self.assertIn("comparePanel", text)
            self.assertNotIn("离线资产未归档", text)
        self.assertIn("data:image/png;base64,", text)

    def test_product_html_rejects_bundle_without_qualified_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp, "small_simple.json")
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.PRODUCT_HTML)
            with self.assertRaises(ValueError):
                FrozenHtmlPublisher(ArtifactType.PRODUCT_HTML).publish(bundle, binding, Path(temp) / "products.html")


if __name__ == "__main__":
    unittest.main()
