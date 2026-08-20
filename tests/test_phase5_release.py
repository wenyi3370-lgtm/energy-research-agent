from __future__ import annotations

import hashlib
import base64
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from enterprise_energy_research.artifacts.excel import ExcelMasterFrozenPublisher
from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus, ValidationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.release.audit import ArtifactConsistencyAuditor
from enterprise_energy_research.release.package import ReleasePackageBuilder
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class Phase5ReleaseTests(unittest.TestCase):
    def _published(self, temp: str):
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
            config_hash="fixture", code_version="0.5.0", model_gateway={"mode": "fixture"},
        ))
        state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
            raw[0]["entities"][0]["canonical_name"],
            [ExtractedEvidenceBatch.model_validate(item) for item in raw],
            output_dir=Path(temp) / "freeze",
        )
        bundle = FreezeService(store).load_bundle(state.freeze_id)
        updated_images = []
        for index, image in enumerate(bundle.images):
            asset = Path(temp) / f"fixture-{index}.png"
            Image.new("RGB", (image.width, image.height), (35 + index * 40, 90, 145)).save(asset, "PNG")
            updated_images.append(image.model_copy(update={
                "local_asset_ref": str(asset), "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "mime_type": "image/png",
            }))
        bundle = bundle.model_copy(update={
            "images": updated_images,
        })
        output = Path(temp) / "artifacts"
        publishers = {
            ArtifactType.EXCEL: (ExcelMasterFrozenPublisher(), "report.xlsx"),
            ArtifactType.WORD: (FrozenWordPublisher(), "report.docx"),
            ArtifactType.ENTERPRISE_HTML: (FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML), "enterprise.html"),
        }
        selected = [item for item in manifest.artifacts if item.type in publishers]
        scoped_manifest = manifest.model_copy(update={"artifacts": selected})
        results = []
        for binding in selected:
            publisher, filename = publishers[binding.type]
            results.append(publisher.publish(bundle, binding, output / filename))
        return bundle, scoped_manifest, results

    def test_cross_artifact_audit_and_package_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest, results = self._published(temp)
            report = ArtifactConsistencyAuditor().audit(bundle, manifest, results)
            self.assertEqual(report.status, ValidationStatus.PASS)
            first = ReleasePackageBuilder().build(report, results, Path(temp) / "release-a.zip")
            second = ReleasePackageBuilder().build(report, results, Path(temp) / "release-b.zip")
            self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), hashlib.sha256(second.read_bytes()).hexdigest())

    def test_tampered_artifact_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest, results = self._published(temp)
            html_result = next(item for item in results if item.artifact_type == ArtifactType.ENTERPRISE_HTML)
            Path(html_result.path).write_text("tampered", encoding="utf-8")
            report = ArtifactConsistencyAuditor().audit(bundle, manifest, results)
            self.assertEqual(report.status, ValidationStatus.BLOCKED)
            self.assertIn("ARTIFACT_HASH_MISMATCH", {item.code for item in report.findings})
            with self.assertRaises(ValueError):
                ReleasePackageBuilder().build(report, results, Path(temp) / "blocked.zip")


if __name__ == "__main__":
    unittest.main()
