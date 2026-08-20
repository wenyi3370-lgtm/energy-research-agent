from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.artifacts.ppt import PptMasterFrozenPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]


class Phase4PptTests(unittest.TestCase):
    def test_ppt_adapter_retains_17_slide_brief_when_executor_is_unconfigured(self) -> None:
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.4.0", model_gateway={"mode": "fixture"},
            ))
            state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                raw[0]["entities"][0]["canonical_name"],
                [ExtractedEvidenceBatch.model_validate(item) for item in raw],
                output_dir=Path(temp) / "freeze",
            )
            bundle = FreezeService(store).load_bundle(state.freeze_id)
            # PPT 已从交付流程移除（planner 不再计划），此处手工构造绑定以测试 ppt 模块本身
            from enterprise_energy_research.domain.models import ArtifactBinding
            from enterprise_energy_research.domain.enums import ArtifactStatus

            binding = ArtifactBinding(
                artifact_id="ART-PPT-TEST", type=ArtifactType.PPT,
                status=ArtifactStatus.PLANNED,
                claim_ids=[item.claim_id for item in bundle.claims],
                image_ids=[item.image_id for item in bundle.images],
            )
            result = PptMasterFrozenPublisher().publish(bundle, binding, Path(temp) / "report.pptx")
            self.assertEqual(result.status, "failed")
            brief_path = Path(temp) / "report_ppt_master_project" / "frozen_brief.json"
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            self.assertEqual(len(brief["slides"]), 17)
            self.assertEqual(brief["root_hash"], bundle.freeze.root_hash)
            self.assertEqual(brief["quality_contract"]["formal_route"], "embedded-pptmaster-svg-v1")
            self.assertTrue(brief["quality_contract"]["visual_element_required_on_every_slide"])
            self.assertEqual(brief["quality_contract"]["minimum_layout_families"], 4)
            self.assertTrue(brief["quality_contract"]["token_aware_wrap_required"])
            self.assertEqual(brief["quality_contract"]["maximum_geometry_overlap_pt"], 3)
            self.assertTrue(all(slide["action_title"] and slide["visual_id"] and slide["so_what"] for slide in brief["slides"]))
            self.assertGreaterEqual(len({slide["layout_family"] for slide in brief["slides"]}), 4)
            self.assertTrue((Path(temp) / "report_ppt_master_project" / "storyline.json").is_file())
            self.assertTrue((Path(temp) / "report_ppt_master_project" / "presentation_evidence_map.json").is_file())
            self.assertTrue((Path(temp) / "report_ppt_master_project" / "visual_manifest.json").is_file())
            self.assertFalse((Path(temp) / "report.pptx").exists())


if __name__ == "__main__":
    unittest.main()
