from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from enterprise_energy_research.artifacts.visuals import build_visual_manifest, render_visual_bundle
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class OfficeVisualContractTests(unittest.TestCase):
    def test_manifest_has_chapter_coverage_variety_and_dual_render(self) -> None:
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.8.0", model_gateway={"mode": "fixture"},
            ))
            state, artifact_manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                raw[0]["entities"][0]["canonical_name"],
                [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
            )
            bundle = FreezeService(store).load_bundle(state.freeze_id)
            binding = next(item for item in artifact_manifest.artifacts if item.type == ArtifactType.WORD)
            manifest = build_visual_manifest(bundle, binding)
            core = {"executive_summary", "research_scope", "entity_overview", "products", "factories", "core_evidence", "energy", "epc", "zero_carbon", "storage_odm", "overseas", "cooperation", "roadmap", "risks", "conclusion"}
            self.assertTrue(core.issubset({visual.chapter_key for visual in manifest.visuals}))
            families = Counter(visual.family for visual in manifest.visuals)
            self.assertGreaterEqual(len(families), 3)
            self.assertLessEqual(families["horizontal_bar"] / len(manifest.visuals), 0.60)
            png, svg = render_visual_bundle(manifest.visuals[0], Path(temp) / "figures")
            self.assertTrue(png.is_file() and png.stat().st_size > 10_000)
            self.assertIn("<text", svg.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
