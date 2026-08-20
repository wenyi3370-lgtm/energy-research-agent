from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.artifacts.visuals import VisualPlanner, build_visual_manifest, render_visual_bundle, render_visual_svg
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
    def test_manifest_uses_only_qualified_lieflat_charts_and_one_canonical_svg(self) -> None:
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
            self.assertTrue(manifest.visuals)
            self.assertTrue({visual.family for visual in manifest.visuals}.issubset({"horizontal_bar", "donut", "funnel"}))
            self.assertTrue(all(visual.renderer == "lieflat-charts-gallery-port-svg-v2" for visual in manifest.visuals))
            self.assertTrue(all(visual.template_source and visual.template_card_title for visual in manifest.visuals))
            self.assertTrue(all(visual.color_system == "mono" for visual in manifest.visuals))
            self.assertTrue(all(visual.template_id in {"F4", "F5", "L13"} for visual in manifest.visuals))
            self.assertFalse({"process", "timeline", "network", "decision_tree", "matrix", "risk_matrix"} & {visual.family for visual in manifest.visuals})
            self.assertTrue(all("html" in visual.artifact_targets for visual in manifest.visuals))
            self.assertTrue(all(visual.source_ids or not visual.source_claim_ids for visual in manifest.visuals))
            for visual in manifest.visuals:
                values = [float(item.value) for item in visual.items if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)]
                if visual.template_id == "F5":
                    self.assertTrue(2 <= len(values) <= 8 and min(values) >= 0 and max(values) > 0 and len(set(values)) >= 2)
                elif visual.template_id == "F4":
                    self.assertTrue(2 <= len(values) <= 6 and min(values) >= 0 and sum(values) > 0)
                else:
                    self.assertTrue(3 <= len(values) <= 6 and min(values) >= 0)
                    self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))
                    self.assertTrue(any(left > right for left, right in zip(values, values[1:])))
            png, svg = render_visual_bundle(manifest.visuals[0], Path(temp) / "figures")
            self.assertTrue(png.is_file() and png.stat().st_size > 10_000)
            canonical_svg = render_visual_svg(manifest.visuals[0])
            self.assertEqual(canonical_svg, svg.read_text(encoding="utf-8"))
            self.assertIn('data-template-source="templates/', canonical_svg)
            html = svg.with_suffix(".html")
            self.assertTrue(html.is_file())
            self.assertIn(canonical_svg, html.read_text(encoding="utf-8"))
            from PIL import Image
            with Image.open(png) as image:
                self.assertEqual(image.size, (1280, 720))
                self.assertGreaterEqual(image.info.get("dpi", (0, 0))[0], 299)
            first_hash = hashlib.sha256(svg.read_bytes()).hexdigest()
            render_visual_bundle(manifest.visuals[0], Path(temp) / "figures")
            self.assertEqual(first_hash, hashlib.sha256(svg.read_bytes()).hexdigest())

    def test_visual_planner_maps_semantics_to_chart_family(self) -> None:
        planner = VisualPlanner()
        self.assertEqual(planner.recommend("time_series"), "F2")
        self.assertEqual(planner.recommend("two_dimension_opportunity"), "F8")
        with self.assertRaises(ValueError):
            planner.recommend("organization")


if __name__ == "__main__":
    unittest.main()
