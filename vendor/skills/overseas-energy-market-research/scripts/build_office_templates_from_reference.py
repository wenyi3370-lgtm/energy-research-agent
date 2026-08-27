from __future__ import annotations

import argparse
import html
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


BLACK = "000000"
DEEP_BLUE = "123A7A"
COBALT = "2563EB"
CHARCOAL = "1F2937"
COOL_GRAY = "6B7280"
LIGHT_GRAY = "F3F6FA"
MID_GRAY = "D9E2EC"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def set_run_font(run, *, east_asia="宋体", latin="Times New Roman", size=10.5, bold=False, color=BLACK):
    run.font.name = latin
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), east_asia)
    r_fonts.set(qn("w:ascii"), latin)
    r_fonts.set(qn("w:hAnsi"), latin)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_text(cell, text: str, *, bold=False, size=9, fill: str | None = None) -> None:
    cell.text = ""
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    run = p.add_run(text)
    set_run_font(run, size=size, bold=bold, color=BLACK)
    if fill:
        set_cell_shading(cell, fill)


def clear_document_body(doc: Document) -> None:
    body = doc._body._element
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def add_para(doc: Document, text: str = "", *, style: str | None = None, size=10.5, bold=False, align=None):
    p = doc.add_paragraph(style=style)
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    set_run_font(run, size=size, bold=bold, color=BLACK)
    return p


def add_heading(doc: Document, text: str, level: int) -> None:
    style = f"Heading {level}" if level <= 3 else None
    size = {1: 15, 2: 14, 3: 10.5}.get(level, 10.5)
    p = add_para(doc, text, style=style, size=size, bold=True)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if level == 1 else WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(8 if level == 1 else 4)
    p.paragraph_format.space_after = Pt(4)


def add_table(doc: Document, caption: str, headers: list[str], rows: list[list[str]], source_note: str) -> None:
    add_para(doc, caption, size=9, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, header in enumerate(headers):
        set_cell_text(hdr[i], header, bold=True, size=9, fill=MID_GRAY)
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value, size=9, fill=None)
    add_para(doc, source_note, size=9)


def build_docx(src: Path, dst: Path) -> None:
    doc = Document(str(src))
    clear_document_body(doc)
    for section in doc.sections:
        section.orientation = WD_ORIENT.PORTRAIT
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(10.5)
    styles["Normal"].font.color.rgb = RGBColor.from_string(BLACK)
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    add_para(doc, "[[目标区域]][[产品类别]]产品与行业市场调研报告", size=18, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "市场背景 · 竞品矩阵 · 用户痛点 · 机会点 · 行动建议", size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "更新日期：[[更新日期]]    数据截止：[[数据截止日期]]    版本：[[版本号]]", size=9, align=WD_ALIGN_PARAGRAPH.CENTER)

    add_heading(doc, "核心结论", 1)
    add_para(doc, "本页用于放置3-5条基于已核验来源的关键结论。每条结论必须引用来源台账中的证据编号，禁止无来源判断。", size=10.5)
    add_table(
        doc,
        "表0-1 核心结论与证据索引",
        ["序号", "核心结论", "证据编号", "置信度", "待核实事项"],
        [["1", "[[结论]]", "[[source_id]]", "高/中/低", "[[待核实]]"]],
        "数据来源：来源台账；注：所有结论需与原始数据、URL或本地文件路径对应。",
    )

    sections = [
        ("1 市场快速扫描", "梳理未来五年市场规模、增长率、主要国家政策驱动因素，并用一页表格总结三类核心玩家。"),
        ("2 竞品名单与对比框架", "基于市场地位、产品相似性与战略方向锁定3-5家核心竞品，列出代表型号和数据来源计划。"),
        ("3 核心竞品产品参数对比", "优先引用用户提供的本地参数文件；若需联网搜索，先记录原因并逐项保留URL。"),
        ("4 定价与渠道初步分析", "按型号、ASIN/SKU、渠道、日期、税费与运费口径记录价格差异。"),
        ("5 渠道与服务策略", "比较线上/线下渠道覆盖、本地售后、多语言APP、安装指导与配置服务。"),
        ("6 用户痛点与口碑分析", "先爬取并保存原始评论语料，再基于原始评论提炼痛点、典型原话与Top购买因素。"),
        ("7 综合矩阵与SWOT", "整合竞品参数、价格、渠道、服务、口碑与战略判断，输出机会点。"),
        ("8 行动建议", "围绕容量段、协议/VPP兼容、渠道首发、价格带与产品定位形成可执行建议。"),
    ]
    for title, desc in sections:
        add_heading(doc, title, 1)
        add_para(doc, desc, size=10.5)
        add_table(
            doc,
            f"表{title.split()[0]}-1 本章节证据清单",
            ["证据项", "来源URL/本地文件", "数据日期", "适用型号", "备注"],
            [["[[证据项]]", "[[URL或本地文件路径]]", "[[日期]]", "[[型号]]", "[[备注]]"]],
            "数据来源：来源台账；注：缺失、冲突或无法核验的信息统一标注“待核实”。",
        )

    add_heading(doc, "附录：证据限制、模型假设与来源台账", 1)
    add_para(doc, "附录应引用内部证据问题清单、模型假设、原始评论语料和来源台账。最终 Excel 不显示内部证据问题表，完整 URL 台账置于最后一张表。", size=10.5)
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))


def style_header(ws, row: int, start_col: int, end_col: int) -> None:
    fill = PatternFill("solid", fgColor=DEEP_BLUE)
    font = Font(name="Times New Roman", bold=True, color="FFFFFF", size=10)
    side = Side(style="thin", color="D9E2EC")
    for col in range(start_col, end_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(left=side, right=side, top=side, bottom=side)


def build_xlsx(src: Path, dst: Path) -> None:
    # Load the reference workbook to ensure the source is readable; the adapted
    # workbook is rebuilt with research-specific tabs.
    load_workbook(str(src), data_only=False).close()
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {
        "00_调研审批": ["approval_id", "outline_version", "outline_path", "scope_summary", "reviewer", "approval_status", "approval_date", "approval_message", "scope_change_requires_reapproval", "notes"],
        "01_Market_Scan": ["record_id", "value_class", "global_region", "country", "province_state", "city_site", "market_segment", "metric", "year_period", "raw_value", "unit", "currency", "tax_basis", "growth_rate", "policy_or_demand_driver", "source_id", "source_url", "access_date", "verification_status", "notes"],
        "02_Competitor_List": ["brand", "parent_company", "country", "player_type", "representative_model", "strategic_fit", "source_url", "verification_status"],
        "03_Model_Identifier_Check": ["model_id", "brand", "product_family", "exact_model", "asin", "sku", "model_code", "product_url", "page_title", "variant_bundle", "identifier_source_url", "checked_date", "match_status", "conflict_note"],
        "04_Product_Parameters": ["parameter_id", "brand", "exact_model", "parameter_group", "parameter_name", "raw_value", "unit", "source_priority", "source_url", "local_file_path", "local_file_location", "access_or_extraction_date", "identifier", "verification_status", "web_source_reason", "notes"],
        "05_Pricing_Channel": ["brand", "exact_model", "configuration", "price", "currency", "channel", "product_url", "capture_date", "tax_included", "shipping_included", "promotion", "verification_status"],
        "06_Channel_Service": ["brand", "exact_model", "online_channel", "offline_channel", "rating", "review_count", "service_feature", "source_url", "verification_status"],
        "07_Raw_Reviews": ["review_id", "platform", "product_url", "review_url", "exact_model", "product_identifier", "asin", "sku", "variant_config", "review_date", "crawl_date", "rating", "language", "original_text", "translated_summary", "collection_tool", "review_limit_note", "verification_status"],
        "08_Review_Coding": ["theme_id", "theme", "raw_review_row_ids", "source_urls", "exact_model", "product_identifier", "frequency_count", "severity", "representative_quote", "summary_cn", "notes"],
        "09_Integrated_Matrix": ["competitor_id", "brand", "exact_model", "product_type", "capacity_kwh", "power_kw", "pv_input_w", "price", "currency", "channel_coverage", "smart_features", "vpp_protocols", "user_pain_score", "strategic_judgment", "evidence_row_ids", "verification_status"],
        "10_SWOT_Opportunity": ["brand_or_opportunity", "strength", "weakness", "opportunity", "threat", "risk_level", "evidence_row_ids", "action_implication"],
        "12_Model_Assumptions": ["assumption_id", "model_module", "parameter_symbol", "parameter_name", "value_class", "low_value", "base_value", "high_value", "unit", "geography", "period", "rationale", "formula_or_use", "source_ids", "source_urls", "confidence", "owner", "approval_status", "notes"],
        "13_Model_Results": ["result_id", "model_module", "scenario", "metric", "value", "unit", "geography", "period", "value_class", "formula_or_method", "input_assumption_ids", "evidence_row_ids", "validation_check", "sensitivity_or_uncertainty", "confidence", "interpretation", "verification_status", "notes"],
        "14_Simulated_Modeling_Data": ["simulation_id", "assumption_id", "model_module", "variable", "geography", "period", "unit", "simulation_method", "distribution_or_process", "calibration_source_ids", "calibration_source_urls", "calibration_parameters", "physical_lower_bound", "physical_upper_bound", "correlation_or_time_structure", "random_seed", "sample_size", "generator_code_path", "generated_data_path", "validation_method", "validation_result", "sensitivity_or_uncertainty", "value_class", "approval_status", "notes"],
        "99_来源与口径": ["source_id", "stage", "evidence_item", "value_class", "source_type", "platform_id", "collection_tool", "source_title", "publisher", "publisher_group", "source_url", "root_domain", "canonical_source_id", "source_relation_type", "local_file_path", "source_location", "publication_date", "access_date", "data_type", "global_region", "country", "province_state", "city_site", "reliability_tier", "exact_model", "product_identifier", "asin", "sku", "raw_value", "unit", "currency", "tax_basis", "evidence_row_ids", "notes", "verification_status"],
    }
    thin = Side(style="thin", color="D9E2EC")
    for name, headers in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(headers)
        style_header(ws, 1, 1, len(headers))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
        for col_idx, header in enumerate(headers, start=1):
            width = max(12, min(34, len(header) + 4))
            ws.column_dimensions[get_column_letter(col_idx)].width = width
            for row in range(2, 202):
                cell = ws.cell(row=row, column=col_idx)
                cell.font = Font(name="Times New Roman", size=10, color="000000")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.sheet_view.showGridLines = False
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(dst))


def replace_pptx_text(src: Path, dst: Path) -> None:
    replacements = {
        "欧洲阳台光储产品": "[[目标区域]][[产品类别]]",
        "欧洲阳台光储": "[[目标区域]][[产品类别]]",
        "阳台光储": "[[产品类别]]",
        "竞品调研报告": "能源产品与行业市场调研报告",
        "欧洲": "[[目标区域]]",
        "德国": "[[重点国家]]",
        "2026年6月": "[[更新日期]]",
        "Amazon.de": "[[目标电商平台]]",
        "MediaMarkt": "[[重点零售渠道]]",
        "Saturn": "[[重点零售渠道]]",
        "Bundesnetzagentur, SolarPower Europe, VDE, Amazon.de, ComputerBase": "[[来源机构/平台清单]]",
        "覆盖6国市场、10款核心竞品、2,000+用户反馈": "[[覆盖国家数]]国市场、[[竞品数量]]款核心竞品、[[评论数量]]+用户反馈",
        "海外能源产品海外能源产品竞品调研报告": "能源产品与行业市场调研报告",
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(src, "r") as zin, ZipFile(dst, "w", ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".xml") and item.filename.startswith("ppt/"):
                text = data.decode("utf-8", errors="ignore")
                for old, new in replacements.items():
                    text = text.replace(html.escape(old), html.escape(new))
                    text = text.replace(old, new)
                text = text.replace("海外能源产品海外能源产品竞品调研报告", "能源产品与行业市场调研报告")
                data = text.encode("utf-8")
            zout.writestr(item, data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Adapt Office references into domestic/global energy market research Skill assets.")
    parser.add_argument("--source-dir", required=True, help="Folder containing one .docx, one .xlsx, and one .pptx reference template.")
    parser.add_argument("--output-root", default=str(skill_root() / "assets" / "templates"), help="Skill assets/templates directory.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    src_docx = next(source_dir.glob("*.docx"))
    src_xlsx = next(source_dir.glob("*.xlsx"))
    src_pptx = next(source_dir.glob("*.pptx"))

    out_docx = output_root / "word" / "energy_market_research_report_template.docx"
    out_xlsx = output_root / "excel" / "energy_market_research_workbook_template.xlsx"
    out_pptx = output_root / "ppt" / "energy_market_research_presentation_template.pptx"

    fusion_manifest = output_root / "word" / "word_template_fusion_manifest.json"
    if fusion_manifest.exists() and out_docx.exists():
        print(
            "Preserving fused Word template. "
            "Use scripts/build_fused_word_template.py to rebuild it from the retained Word sources."
        )
    else:
        build_docx(src_docx, out_docx)
    build_xlsx(src_xlsx, out_xlsx)
    replace_pptx_text(src_pptx, out_pptx)

    reference_dir = output_root / "reference_originals"
    reference_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_docx, reference_dir / src_docx.name)
    shutil.copy2(src_xlsx, reference_dir / src_xlsx.name)
    shutil.copy2(src_pptx, reference_dir / src_pptx.name)

    print(f"Word template: {out_docx}")
    print(f"Excel template: {out_xlsx}")
    print(f"PPT template: {out_pptx}")
    print(f"Reference originals copied to: {reference_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
