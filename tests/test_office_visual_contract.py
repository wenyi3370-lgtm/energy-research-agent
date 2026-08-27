from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from energy_research_agent.artifacts.diagram_design_adapter import DiagramDesignAdapter
from energy_research_agent.artifacts.narrative import NarrativeBuilder
from energy_research_agent.domain.enums import ArtifactType, RunStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import ExtractedEvidenceBatch, RunManifest
from energy_research_agent.evidence.freeze import FreezeService
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.graph.phase3_runner import Phase3Runner
from energy_research_agent.graph.state import ResearchState
from energy_research_agent.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class OfficeVisualContractTests(unittest.TestCase):
    def _bundle(self, temp: str):
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
            config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "fixture"},
        ))
        state, artifact_manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
            raw[0]["entities"][0]["canonical_name"],
            [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
        )
        return FreezeService(store).load_bundle(state.freeze_id), artifact_manifest

    def test_visual_manifest_is_diagram_design_and_evidence_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, artifact_manifest = self._bundle(temp)
            narrative = NarrativeBuilder().build(bundle)
            manifest = narrative.visual_manifest()
            self.assertEqual(manifest.visual_system, "diagram-design")
            self.assertTrue(manifest.visuals)
            adapter = DiagramDesignAdapter()
            for visual in manifest.visuals:
                self.assertIn(visual.visual_type, adapter.supported_types())
                self.assertTrue(visual.title)
                self.assertTrue(visual.decision_question)
                self.assertTrue(visual.business_thesis)
                self.assertIn(visual.destination, {"html", "word", "both"})
                self.assertTrue(visual.source_ids or visual.source_claim_ids or visual.semantic_pattern in {"quantitative_facts", "verified_relationship", "none"})

    def test_one_canonical_svg_and_same_source_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = self._bundle(temp)
            narrative = NarrativeBuilder().build(bundle)
            self.assertTrue(narrative.visuals, "fixture must produce at least one visual")
            adapter = DiagramDesignAdapter()
            figures = Path(temp) / "figures"
            for spec in narrative.visuals:
                result = adapter.build_visual(spec, figures, destination="both", png_scale=2)
                self.assertIn(result.status, {"rendered", "fallback_table"})
                self.assertNotEqual(result.status, "failed")
                self.assertTrue(result.svg_path.is_file())
                self.assertTrue(result.html_path.is_file())
                # canonical SVG block is embedded verbatim in the standalone file
                # (standalone export adds only the XML declaration, per export.md)
                self.assertIn(result.svg_markup, result.svg_path.read_text(encoding="utf-8"))
                self.assertTrue(result.svg_path.read_text(encoding="utf-8").startswith('<?xml version="1.0"'))
                # HTML embeds the SAME svg block (single source of truth)
                self.assertIn(result.svg_markup, result.html_path.read_text(encoding="utf-8"))
                # deterministic: re-render produces identical SVG
                again = adapter.build_visual_svg(spec)
                self.assertEqual(again, result.svg_markup)
                # accessibility contract from diagram-design export spec
                self.assertIn(f'id="{spec.visual_id}-title"', result.svg_markup)
                self.assertIn(f'id="{spec.visual_id}-desc"', result.svg_markup)
                self.assertIn(f'aria-labelledby="{spec.visual_id}-title {spec.visual_id}-desc"', result.svg_markup)
                self.assertIn('role="img"', result.svg_markup)
                # PNG is rasterized from the same HTML when a browser exists
                if result.png_path is not None:
                    self.assertTrue(result.png_path.stat().st_size > 1000)
                    from PIL import Image
                    with Image.open(result.png_path) as image:
                        self.assertGreaterEqual(image.size[0], result.width)

    def test_failed_renderer_never_silently_drops_visual(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = self._bundle(temp)
            narrative = NarrativeBuilder().build(bundle)
            spec = narrative.visuals[0]
            adapter = DiagramDesignAdapter()
            figures = Path(temp) / "figures"
            broken = spec.model_copy(deep=True, update={"visual_type": "line"})
            broken.items = []  # no real time series: renderer must degrade, never emit an empty line
            result = adapter.build_visual(broken, figures, destination="both")
            self.assertEqual(result.status, "fallback_table")
            self.assertIn("renderer error", result.fallback_reason or "")
            self.assertNotIn("<polyline", result.svg_markup or "")
            self.assertTrue(result.svg_path.is_file())  # fallback table was emitted, not dropped


if __name__ == "__main__":
    unittest.main()
