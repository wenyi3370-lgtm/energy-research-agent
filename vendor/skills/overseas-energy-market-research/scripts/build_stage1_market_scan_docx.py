from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from _common import now_iso, read_csv


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def set_run_font(run, size: int = 12, bold: bool = False) -> None:
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)


def add_heading(document: Document, text: str, level: int = 1) -> None:
    paragraph = document.add_paragraph(style=f"Heading {min(max(level, 1), 4)}")
    if level == 1:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run(text)


def add_para(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="Normal")
    paragraph.add_run(text)


def add_table(document: Document, headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = paragraph.add_run(header)
        set_run_font(run, size=9, bold=True)
    for row in rows[:limit]:
        cells = table.add_row().cells
        for i, header in enumerate(headers):
            cell = cells[i]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            run = paragraph.add_run(str(row.get(header, "")))
            set_run_font(run, size=9)


def replace_placeholders(document: Document, mapping: dict[str, str]) -> None:
    containers = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)
    for paragraph in containers:
        for run in paragraph.runs:
            for old, new in mapping.items():
                run.text = run.text.replace(old, new)


def build(project_dir: Path, output: Path, region: str, category: str) -> None:
    template = skill_root() / "assets" / "templates" / "word" / "energy_market_research_report_template.docx"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    document = Document(output)
    replace_placeholders(
        document,
        {
            "[[目标区域]]": region,
            "[[产品类别]]": category,
            "[[更新日期]]": now_iso(),
            "[[来源机构/平台清单]]": "见文末来源表",
            "[[项目名称]]": f"{region}{category}市场快速扫描",
        },
    )

    _, market_rows = read_csv(project_dir / "01_Market_Scan.csv") if (project_dir / "01_Market_Scan.csv").exists() else ([], [])
    _, comp_rows = read_csv(project_dir / "02_Competitor_List.csv") if (project_dir / "02_Competitor_List.csv").exists() else ([], [])
    _, source_rows = read_csv(project_dir / "00_Source_Ledger.csv") if (project_dir / "00_Source_Ledger.csv").exists() else ([], [])

    document.add_page_break()
    add_heading(document, "一、市场快速扫描", 1)
    add_para(document, f"本节基于项目证据台账与市场扫描表生成。当前市场数据记录 {len(market_rows)} 条，竞品/玩家记录 {len(comp_rows)} 条。观测值、推导值、模型估算和情景假设必须明确区分。")
    add_heading(document, "1.1 市场规模与增长", 2)
    add_table(document, ["value_class", "country", "province_state", "market_segment", "metric", "year_period", "raw_value", "unit", "currency", "growth_rate", "source_url"], market_rows)
    add_heading(document, "1.2 政策驱动摘要", 2)
    add_table(document, ["country", "province_state", "policy_or_demand_driver", "source_url", "access_date", "verification_status", "notes"], market_rows)
    add_heading(document, "1.3 三类核心玩家", 2)
    add_table(document, ["brand", "country", "player_type", "representative_model", "strategic_fit", "source_url"], comp_rows)
    add_heading(document, "1.4 来源与限制", 2)
    add_table(document, ["source_id", "evidence_item", "source_url", "access_date", "verification_status"], source_rows)

    document.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Stage 1 market quick scan Word report from CSV evidence tables.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--region", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--output", default="deliverables/市场快速扫描笔记.docx")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    build(project_dir, output, args.region, args.category)
    print(f"Wrote Stage 1 report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
