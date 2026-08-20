from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from enterprise_energy_research.artifacts.excel import ExcelMasterFrozenPublisher
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


class Phase4OfficeTests(unittest.TestCase):
    def _bundle(self, temp: str):
        raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
        company = raw[0]["entities"][0]["canonical_name"]
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING, config_hash="fixture", code_version="0.6.1", model_gateway={"mode": "fixture"}))
        state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING), company,
            [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
        )
        return FreezeService(store).load_bundle(state.freeze_id), manifest

    def test_excel_master_publisher_creates_expected_sheets(self) -> None:
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.EXCEL)
            target = Path(temp) / "report.xlsx"
            result = ExcelMasterFrozenPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published")
            workbook = load_workbook(target, read_only=False, data_only=False)
            self.assertEqual(workbook.sheetnames, ["运行清单", "企业实体", "生产基地", "产品", "证据主表", "来源", "图片证据", "数据缺口", "能源画像", "合作机会"])
            self.assertFalse(workbook["证据主表"].sheet_view.showGridLines)
            self.assertIsNotNone(workbook["证据主表"].freeze_panes)

    def test_word_publisher_contains_real_toc_and_page_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self._bundle(temp)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published")
            with zipfile.ZipFile(target) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
                footer_xml = archive.read("word/footer1.xml").decode("utf-8")
            self.assertIn("TOC", document_xml)
            self.assertIn("PAGE", footer_xml)
            self.assertIn("tblLayout", document_xml)
            self.assertNotIn('w:val="TableGrid"', document_xml)
            self.assertGreaterEqual(document_xml.count("<w:drawing>"), 13)
            self.assertIn("数据来源：证据冻结", document_xml)
            visual_manifest = target.parent / "report_assets" / "visual_manifest.json"
            self.assertTrue(visual_manifest.is_file())
            payload = json.loads(visual_manifest.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(payload["visuals"]), 13)
            self.assertGreaterEqual(len({item["family"] for item in payload["visuals"]}), 3)
            for item in payload["visuals"]:
                self.assertTrue((target.parent / "report_assets" / "figures" / f"{item['visual_id']}.png").is_file())
                self.assertTrue((target.parent / "report_assets" / "figures" / f"{item['visual_id']}.svg").is_file())


if __name__ == "__main__":
    unittest.main()
