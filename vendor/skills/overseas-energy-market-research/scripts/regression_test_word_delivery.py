from __future__ import annotations

import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.text import WD_LINE_SPACING

from _common import read_csv, write_csv
from validate_word_delivery import (
    validate_centering_contract,
    validate_data_source_label,
    validate_table_caption_pagination_contract,
    validate_table_geometry_contract,
    validate_table_text_contract,
    validate_table_visual_contract,
)


CSV_FIXTURES = {
    "01_Market_Scan.csv": ("market_scan_template.csv", {
        "record_id": "M001", "value_class": "observed", "country": "Fixtureland",
        "city_site": "Fixture City", "market_segment": "storage", "metric": "market_size",
        "year_period": "2030", "raw_value": "125", "unit": "MWh", "currency": "",
        "source_id": "S001", "source_url": "https://example.com/market", "access_date": "2026-08-09",
        "verification_status": "verified",
    }),
    "02_Competitor_List.csv": ("competitor_list_template.csv", {
        "brand": "Fixture Energy", "country": "Fixtureland", "player_type": "manufacturer",
        "representative_model": "FE-100", "strategic_fit": "high", "source_url": "https://example.com/brand",
        "verification_status": "verified",
    }),
    "04_Product_Parameters.csv": ("product_parameters_template.csv", {
        "parameter_id": "P001", "brand": "Fixture Energy", "exact_model": "FE-100",
        "parameter_name": "capacity", "raw_value": "10", "unit": "kWh", "source_priority": "official",
        "source_url": "https://example.com/spec", "access_or_extraction_date": "2026-08-09",
        "verification_status": "verified",
    }),
    "05_Pricing_Channel.csv": ("pricing_channel_template.csv", {
        "pricing_id": "PR001", "value_class": "observed", "country": "Fixtureland",
        "brand": "Fixture Energy", "exact_model": "FE-100", "configuration": "10kWh kit",
        "list_price": "5000", "discounted_price": "4800", "currency": "FXD", "tax_included": "yes",
        "product_url": "https://example.com/price", "capture_date": "2026-08-09", "source_id": "S002",
        "verification_status": "verified",
    }),
    "08_Review_Coding.csv": ("review_coding_template.csv", {
        "theme_id": "T001", "theme": "installation", "raw_review_row_ids": "R001;R002",
        "exact_model": "FE-100", "frequency_count": "2", "severity": "medium",
        "summary_cn": "安装流程清晰",
    }),
    "09_Integrated_Matrix.csv": ("integrated_matrix_template.csv", {
        "competitor_id": "C001", "brand": "Fixture Energy", "exact_model": "FE-100",
        "capacity_kwh": "10", "power_kw": "5", "strategic_judgment": "适合试点",
        "evidence_row_ids": "M001;PR001", "verification_status": "verified",
    }),
    "10_SWOT_Opportunity.csv": ("swot_opportunity_template.csv", {
        "brand": "Fixture Energy", "exact_model": "FE-100", "strength": "本地服务",
        "opportunity": "试点合作", "risk_level": "medium", "opportunity_priority": "high",
        "evidence_row_ids": "M001;PR001", "verification_status": "verified",
    }),
}


def build_fixture(project_dir: Path) -> Path:
    skill_root = Path(__file__).resolve().parents[1]
    template_root = skill_root / "assets" / "templates" / "csv"
    for target, (template_name, values) in CSV_FIXTURES.items():
        fields, _ = read_csv(template_root / template_name)
        row = {field: str(values.get(field, "")) for field in fields}
        write_csv(project_dir / target, fields, [row])
    command = [
        sys.executable,
        str(Path(__file__).with_name("build_template_report.py")),
        "--project-dir", str(project_dir),
        "--region", "Fixtureland",
        "--category", "Residential storage",
        "--update-date", "2026-08-09",
        "--data-cutoff", "2026-08-08",
        "--prefix", "fixture_report",
    ]
    subprocess.run(command, check=True)
    return project_dir / "deliverables" / "fixture_report.docx"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="word_delivery_regression_") as raw:
        project_dir = Path(raw)
        report = build_fixture(project_dir)
        document = Document(report)
        core = document.tables[1]
        if len(core.rows) != 3:
            raise AssertionError(f"Expected two core-conclusion rows, got {len(core.rows) - 1}")
        values = [cell.text for cell in core.rows[1].cells]
        if values != ["1", "market_size：125/MWh", "S001", "observed", "verified"]:
            raise AssertionError(f"Five-column core mapping failed: {values}")
        all_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        all_text += "\n" + "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        for forbidden in ("Germany", "德国储能系统索引", "Amazon.de", "600-1500 EUR"):
            if forbidden in all_text:
                raise AssertionError(f"Hard-coded market residue remains: {forbidden}")
        if "试点合作/本地服务" not in document.tables[9].rows[1].cells[1].text:
            raise AssertionError("Action table was not populated from 10_SWOT_Opportunity.csv")

        gates = (
            validate_centering_contract,
            validate_table_text_contract,
            validate_table_visual_contract,
            validate_table_caption_pagination_contract,
            validate_table_geometry_contract,
            validate_data_source_label,
        )
        problems = [problem for gate in gates for problem in gate(report)]
        if problems:
            raise AssertionError("Word structural gates failed: " + "; ".join(problems[:10]))

        duplicated = project_dir / "duplicate_table_caption.docx"
        duplicated_doc = Document(report)
        target_table = duplicated_doc.tables[1]
        previous = target_table._tbl.getprevious()
        if previous is None:
            raise AssertionError("Fixture has no table-caption anchor")
        target_table._tbl.addprevious(deepcopy(previous))
        duplicated_doc.save(duplicated)
        duplicate_problems = validate_table_caption_pagination_contract(duplicated)
        if not any("duplicate table caption" in problem.lower() or "Duplicate table caption" in problem for problem in duplicate_problems):
            raise AssertionError("Duplicate table caption regression was not detected")
        repaired = project_dir / "duplicate_table_caption_repaired.docx"
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("polish_word_ib_style.py")), str(duplicated), "--out", str(repaired)],
            check=True,
        )
        repaired_problems = validate_table_caption_pagination_contract(repaired)
        if repaired_problems:
            raise AssertionError("Duplicate table caption repair failed: " + "; ".join(repaired_problems[:5]))

        # Reproduce the production failure: an exact 12 pt Figure Image style
        # clips a multi-inch inline drawing to a thin strip. The structural
        # validator must reject it even before visual rendering.
        broken = project_dir / "broken_exact_line_height.docx"
        broken_doc = Document(report)
        figure_style = broken_doc.styles["Figure Image"]
        figure_style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        figure_style.paragraph_format.line_spacing = 12
        broken_doc.save(broken)
        clipping_problems = validate_centering_contract(broken)
        if not any("fixed line height clips charts" in problem for problem in clipping_problems):
            raise AssertionError("Exact-line-height figure regression was not detected")
    print("Word delivery regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
