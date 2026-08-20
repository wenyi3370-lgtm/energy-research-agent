from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.domain.enums import ArtifactType
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle
from enterprise_energy_research.vendor import embedded_skill_root


class ExcelMasterFrozenPublisher:
    name = "excel_master"
    artifact_type = ArtifactType.EXCEL

    def __init__(self, skill_root: Path | None = None, *, theme: str = "deep-navy", freeze_rows: int = 1) -> None:
        self.skill_root = skill_root or embedded_skill_root("excel-master")
        self.theme = theme
        self.freeze_rows = freeze_rows

    def health(self) -> AdapterHealth:
        available = (self.skill_root / "scripts" / "make_excel.py").is_file() and importlib.util.find_spec("pandas") is not None and importlib.util.find_spec("openpyxl") is not None
        return AdapterHealth(name=self.name, available=available, version="excel-master", diagnostics=[] if available else ["Excel Master、pandas 或 openpyxl 不可用"])

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        health = self.health()
        if not health.available:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=health.diagnostics)
        if binding.type != self.artifact_type:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=["Excel 发布器收到非 Excel 绑定"])
        import pandas as pd
        module_path = self.skill_root / "scripts" / "make_excel.py"
        spec = importlib.util.spec_from_file_location("eer_excel_master", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载 Excel Master")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        sheets = [
            ("运行清单", pd.DataFrame([
                {"field": "run_id", "value": bundle.run_manifest.run_id},
                {"field": "freeze_id", "value": bundle.freeze.freeze_id},
                {"field": "root_hash", "value": bundle.freeze.root_hash},
                {"field": "evidence_version", "value": bundle.freeze.evidence_version},
                {"field": "validation_status", "value": bundle.run_manifest.validation_status.value if bundle.run_manifest.validation_status else None},
            ])),
            ("企业实体", pd.DataFrame([self._row(x) for x in bundle.entities])),
            ("生产基地", pd.DataFrame([self._row(x) for x in bundle.factories])),
            ("产品", pd.DataFrame([self._row(x) for x in bundle.products])),
            ("证据主表", pd.DataFrame([self._row(x) for x in bundle.claims])),
            ("来源", pd.DataFrame([self._row(x) for x in bundle.sources])),
            ("图片证据", pd.DataFrame([self._row(x) for x in bundle.images])),
            ("数据缺口", pd.DataFrame([self._row(x) for x in bundle.gaps])),
            ("能源画像", pd.DataFrame([self._row(x) for x in bundle.energy_profiles])),
            ("合作机会", pd.DataFrame([self._row(x) for x in bundle.solutions])),
        ]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        module.make_excel(sheets, output_path, theme=self.theme, freeze_rows=self.freeze_rows)
        self._apply_layout(output_path)
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, path=output_path, content_sha256=digest, used_claim_ids=list(binding.claim_ids), used_image_ids=list(binding.image_ids), status="published")

    @staticmethod
    def _row(model: Any) -> dict[str, Any]:
        raw = model.model_dump(mode="json")
        return {key: value if isinstance(value, (str, int, float, bool)) or value is None else str(value) for key, value in raw.items()}

    @staticmethod
    def _apply_layout(output_path: Path) -> None:
        from openpyxl import load_workbook
        from openpyxl.styles import Alignment
        from openpyxl.utils import get_column_letter

        widths = {
            "claim_id": 20, "entity_id": 20, "factory_id": 20, "product_id": 20,
            "source_id": 18, "solution_id": 20, "energy_profile_id": 20, "gap_id": 20,
            "canonical_name": 28, "canonical_company_name": 28, "name": 26, "address": 24,
            "field_name": 30, "value": 34, "raw_text": 42, "context_text": 34,
            "opportunity": 44, "proposed_solution": 44, "benefit_logic": 38,
            "data_requirements": 32, "risks": 30, "next_step": 36, "assumptions": 38,
            "processes": 34, "parameters": 34, "description": 34, "canonical_url": 44,
            "source_title": 34, "scope": 30, "qualifier": 16, "notes": 28,
        }
        workbook = load_workbook(output_path)
        try:
            for sheet in workbook.worksheets:
                sheet.sheet_view.zoomScale = 85
                sheet.freeze_panes = "B2"
                sheet.auto_filter.ref = sheet.dimensions if sheet.max_row > 1 else None
                for column in range(2, sheet.max_column + 1):
                    header = str(sheet.cell(1, column).value or "")
                    if header in widths:
                        sheet.column_dimensions[get_column_letter(column)].width = widths[header]
                for row in sheet.iter_rows(min_row=2):
                    long_row = False
                    for cell in row[1:]:
                        text = "" if cell.value is None else str(cell.value)
                        if len(text) > 24:
                            long_row = True
                        cell.alignment = Alignment(
                            horizontal="right" if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool) else "left",
                            vertical="top", wrap_text=True,
                        )
                    if long_row:
                        sheet.row_dimensions[row[0].row].height = 36
                sheet.row_dimensions[1].height = 28
            workbook.save(output_path)
        finally:
            workbook.close()
