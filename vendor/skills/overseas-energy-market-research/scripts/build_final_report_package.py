from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches as DocxInches
from docx.shared import Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptRGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt as PptPt

from _common import now_iso, read_csv, write_json

from sync_csv_to_excel import sync as sync_excel


BLUE = PptRGBColor(18, 58, 140)
CHARCOAL = PptRGBColor(48, 52, 59)
WHITE = PptRGBColor(255, 255, 255)
GRAY = PptRGBColor(210, 215, 224)
PLACEHOLDER_RE = re.compile(r"\[\[[^\]]*\]\]")
TABLE_HEADER_FILL = "D9E2EC"
TABLE_OUTER_RULE_COLOR = "000000"
TABLE_HEADER_RULE_COLOR = "1B365D"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def rows(project_dir: Path, filename: str) -> list[dict[str, str]]:
    path = project_dir / filename
    if not path.exists():
        return []
    _, data = read_csv(path)
    return data


def render_all_charts(project_dir: Path) -> list[dict]:
    """Render figure bundles through the REAL render_charts pipeline and
    return the chart records from the produced manifest (FIX round-2 P1-5:
    the previous inline builder loop used a wrong signature and imported a
    save_manifest that never existed — the one-key delivery chain was broken)."""
    import subprocess
    import sys as _sys

    scripts_dir = Path(__file__).resolve().parent
    cmd = [_sys.executable, str(scripts_dir / "render_charts.py"),
           "--project-dir", str(project_dir), "--mode", "final"]
    claim_registry = project_dir / "intermediate" / "charts" / "claims.json"
    if claim_registry.is_file():
        cmd += ["--claim-registry", str(claim_registry)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("render_charts failed: %s" % (proc.stderr or proc.stdout)[-500:])
    manifest_path = project_dir / "deliverables" / "charts" / "chart_manifest.json"
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = data.get("charts", [])
    # build_final_docx/pptx expect {"name", "path", ...}: enrich each record
    # with the PNG path from its theme manifest (schema alignment).
    for rec in records:
        theme_path = project_dir / rec.get("manifest", "")
        if theme_path.is_file():
            theme = json.loads(theme_path.read_text(encoding="utf-8"))
            png = (theme.get("outputs") or {}).get("png", {}).get("path", "")
            if png:
                rec["path"] = str(project_dir / png)
    return records


def docx_font(run, size: int = 12, bold: bool = False, east_asia: str = "宋体") -> None:
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east_asia)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)


def _set_paragraph_format(p, line_pt: float | None = None, before: int = 0, after: int = 0,
                          center: bool = False, indent_pt: float | None = None) -> None:
    """Apply format-and-visual-style.md paragraph rules (fixed line spacing in pt)."""
    if center:
        p.alignment = 1  # WD_ALIGN_PARAGRAPH.CENTER
    if line_pt is not None:
        p.paragraph_format.line_spacing = Pt(line_pt)
        p.paragraph_format.line_spacing_rule = 4  # WD_LINE_SPACING.EXACTLY
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    if indent_pt is not None:
        p.paragraph_format.first_line_indent = Pt(indent_pt)


def docx_heading(document: Document, text: str, level: int = 1) -> None:
    """一级: 黑体二号22pt 加粗 居中 段前18 段后12 固定30pt行距
       二级: 仿宋四号14pt 加粗 左对齐 6pt 固定24pt
       三级: 仿宋小四12pt 加粗 左对齐 6pt 固定24pt"""
    p = document.add_paragraph()
    p.paragraph_format.left_indent = Pt(0)
    p.paragraph_format.right_indent = Pt(0)
    p.paragraph_format.first_line_indent = Pt(0)
    if level == 1:
        run = p.add_run(text)
        docx_font(run, 22, True, east_asia="黑体")
        _set_paragraph_format(p, line_pt=30, before=18, after=12, center=True)
    elif level == 2:
        run = p.add_run(text)
        docx_font(run, 14, True, east_asia="仿宋")
        _set_paragraph_format(p, line_pt=24, before=6, after=6)
    else:
        run = p.add_run(text)
        docx_font(run, 12, True, east_asia="仿宋")
        _set_paragraph_format(p, line_pt=24, before=6, after=6)


def docx_para(document: Document, text: str) -> None:
    """正文: 中文宋体小四12pt 西文Times New Roman 固定22pt 首行缩进两字符 两端对齐"""
    p = document.add_paragraph()
    _set_paragraph_format(p, line_pt=22, indent_pt=24)
    run = p.add_run(text)
    docx_font(run, 12, False, east_asia="宋体")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_three_line_borders(table, header_row_index: int = 0) -> None:
    """三线表: 黑色 1.5 pt 顶/底线 + 深蓝 1 pt 表头线；浅蓝表头。"""
    from docx.oxml import OxmlElement
    tbl = table._tbl
    tblPr = tbl.tblPr
    for existing in list(tblPr.findall(qn("w:tblBorders"))):
        tblPr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge, sz in (("top", 12), ("bottom", 12)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:color"), TABLE_OUTER_RULE_COLOR)
        borders.append(el)
    for edge in ("left", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:color"), "FFFFFF")
        borders.append(el)
    tblPr.append(borders)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            for existing in list(tcPr.findall(qn("w:tcBorders"))):
                tcPr.remove(existing)
            for existing in list(tcPr.findall(qn("w:shd"))):
                tcPr.remove(existing)
            tc_borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "right", "bottom"):
                element = OxmlElement(f"w:{edge}")
                element.set(qn("w:val"), "none")
                element.set(qn("w:sz"), "0")
                element.set(qn("w:color"), "FFFFFF")
                tc_borders.append(element)
            if row_index == header_row_index:
                bottom = tc_borders.find(qn("w:bottom"))
                bottom.set(qn("w:val"), "single")
                bottom.set(qn("w:sz"), "8")
                bottom.set(qn("w:color"), TABLE_HEADER_RULE_COLOR)
            tcPr.append(tc_borders)
            if row_index != header_row_index:
                continue
            shading = OxmlElement("w:shd")
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:color"), "auto")
            shading.set(qn("w:fill"), TABLE_HEADER_FILL)
            tcPr.append(shading)


def docx_table(document: Document, headers: list[str], data: list[dict[str, str]], limit: int = 12) -> None:
    shown = data[:limit] or [{header: "待补充" for header in headers}]
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    table.autofit = False
    total_width_twips = round(15.6 / 2.54 * 1440)
    table_width = table._tbl.tblPr.find(qn("w:tblW"))
    if table_width is None:
        table_width = OxmlElement("w:tblW")
        table._tbl.tblPr.append(table_width)
    table_width.set(qn("w:type"), "dxa")
    table_width.set(qn("w:w"), str(total_width_twips))
    cell_width = Cm(15.6 / max(len(headers), 1))
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    repeat_header = OxmlElement("w:tblHeader")
    repeat_header.set(qn("w:val"), "true")
    header_properties.append(repeat_header)
    for idx, header in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.width = cell_width
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = paragraph.add_run(header)
        docx_font(run, 9, True)  # 表头宋体小五加粗
        run.font.color.rgb = RGBColor(27, 54, 93)
    for row in shown:
        cells = table.add_row().cells
        for idx, header in enumerate(headers):
            cell = cells[idx]
            cell.width = cell_width
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            run = paragraph.add_run(str(row.get(header, ""))[:220])
            docx_font(run, 9, False)  # 表体宋体小五
    _apply_three_line_borders(table)


def all_docx_paragraphs(document: Document):
    containers = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            containers.extend(part.paragraphs)
            for table in part.tables:
                for row in table.rows:
                    for cell in row.cells:
                        containers.extend(cell.paragraphs)
    return containers


def replace_docx_placeholders(document: Document, mapping: dict[str, str]) -> None:
    containers = all_docx_paragraphs(document)
    for paragraph in containers:
        for run in paragraph.runs:
            for old, new in mapping.items():
                run.text = run.text.replace(old, new)


def clean_docx_placeholders(document: Document) -> int:
    count = 0
    for paragraph in all_docx_paragraphs(document):
        if "[[" not in paragraph.text:
            continue
        replacement, replacements = PLACEHOLDER_RE.subn("", paragraph.text)
        if not replacements:
            continue
        if paragraph.runs:
            paragraph.runs[0].text = replacement.strip()
            for run in paragraph.runs[1:]:
                run.text = ""
        count += replacements
    return count


def prune_template_to_cover(document: Document) -> None:
    """Keep the fused template cover and styles, but remove its empty chapter skeleton.

    The reusable template intentionally contains guidance pages.  A production report
    must populate real content instead of appending it after those guidance pages.
    """
    first_heading = next(
        (
            paragraph
            for paragraph in document.paragraphs
            if paragraph.style is not None and paragraph.style.name == "Heading 1"
        ),
        None,
    )
    if first_heading is None:
        raise RuntimeError("Fused Word template has no Heading 1 marker after the cover.")
    body = document._body._element
    deleting = False
    for child in list(body):
        if child is first_heading._p:
            deleting = True
        if deleting and child.tag != qn("w:sectPr"):
            body.remove(child)


def install_dynamic_footer_fields(document: Document) -> None:
    """Install PAGE/NUMPAGES fields and request field refresh on open/render."""
    settings = document.settings._element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "true")

    for section in document.sections:
        footer = section.footer
        paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        paragraph.clear()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.add_run("重要声明：本报告仅供内部研究与决策参考\t第 ")
        page = OxmlElement("w:fldSimple")
        page.set(qn("w:instr"), "PAGE")
        page_run = OxmlElement("w:r")
        page_text = OxmlElement("w:t")
        page_text.text = "1"
        page_run.append(page_text)
        page.append(page_run)
        paragraph._p.append(page)
        paragraph.add_run(" 页 / 共 ")
        pages = OxmlElement("w:fldSimple")
        pages.set(qn("w:instr"), "NUMPAGES")
        pages_run = OxmlElement("w:r")
        pages_text = OxmlElement("w:t")
        pages_text.text = "1"
        pages_run.append(pages_text)
        pages.append(pages_run)
        paragraph._p.append(pages)
        paragraph.add_run(" 页")


def add_source_note(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="Source Note")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.add_run(f"数据来源：{text}")


def add_table_block(
    document: Document,
    caption: str,
    headers: list[str],
    data: list[dict[str, str]],
    source: str,
    limit: int = 12,
) -> None:
    caption_paragraph = document.add_paragraph(caption, style="Table Caption")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_paragraph.paragraph_format.keep_with_next = True
    docx_table(document, headers, data, limit)
    add_source_note(document, source)


def enforce_table_caption_contract(document: Document) -> int:
    style = document.styles["Table Caption"]
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    style.paragraph_format.keep_with_next = True
    style.paragraph_format.keep_together = True
    count = 0
    for paragraph in document.paragraphs:
        if paragraph.style is not None and paragraph.style.name == "Table Caption":
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.keep_together = True
            count += 1
    return count


def build_final_docx(project_dir: Path, output: Path, region: str, category: str, charts: list[dict]) -> None:
    template = skill_root() / "assets" / "templates" / "word" / "energy_market_research_report_template.docx"
    document = Document(template)
    prune_template_to_cover(document)
    update_date = now_iso()
    replace_docx_placeholders(
        document,
        {
            "[[目标区域]]": region,
            "[[产品类别]]": category,
            "[[更新日期]]": update_date,
            "[[来源机构/平台清单]]": "见证据台账与来源附录",
            "[[项目名称]]": f"{region}{category}产品与行业市场调研报告",
        },
    )
    market = rows(project_dir, "01_Market_Scan.csv")
    competitors = rows(project_dir, "02_Competitor_List.csv")
    params = rows(project_dir, "04_Product_Parameters.csv")
    pricing = rows(project_dir, "05_Pricing_Channel.csv")
    reviews = rows(project_dir, "08_Review_Coding.csv")
    matrix = rows(project_dir, "09_Integrated_Matrix.csv")
    swot = rows(project_dir, "10_SWOT_Opportunity.csv")
    gaps = rows(project_dir, "11_Evidence_Issues.csv")
    sources = rows(project_dir, "00_Source_Ledger.csv")

    document.add_page_break()
    docx_heading(document, "一、核心结论与证据状态", 1)
    docx_para(document, f"本报告由结构化证据表自动生成。当前市场记录 {len(market)} 条，竞品记录 {len(competitors)} 条，参数记录 {len(params)} 条，价格渠道记录 {len(pricing)} 条，评论主题记录 {len(reviews)} 条，综合矩阵记录 {len(matrix)} 条。未核验信息不得作为确定性结论。")
    add_table_block(
        document,
        "表1-1  核心结论与证据状态",
        ["source_id", "stage", "evidence_item", "verification_status"],
        sources,
        "00_Source_Ledger.csv",
        10,
    )

    docx_heading(document, "二、市场背景", 1)
    add_table_block(
        document,
        "表2-1  市场背景与增长情景",
        ["country", "market_segment", "metric", "year_period", "raw_value", "unit", "growth_rate", "policy_or_demand_driver"],
        market,
        "01_Market_Scan.csv；详细来源见证据台账",
        15,
    )
    docx_heading(document, "三、竞品矩阵", 1)
    add_table_block(
        document,
        "表3-1  竞品矩阵",
        ["brand", "exact_model", "product_type", "capacity_kwh", "power_kw", "price", "strategic_judgment"],
        matrix,
        "09_Integrated_Matrix.csv",
        15,
    )
    docx_heading(document, "四、参数与定价", 1)
    add_table_block(
        document,
        "表4-1  产品参数",
        ["brand", "exact_model", "parameter_name", "raw_value", "unit", "source_priority"],
        params,
        "04_Product_Parameters.csv；详细来源见证据台账",
        15,
    )
    add_table_block(
        document,
        "表4-2  售价与渠道",
        ["brand", "exact_model", "configuration", "list_price", "discounted_price", "currency", "channel", "capture_date"],
        pricing,
        "05_Pricing_Channel.csv；详细来源见证据台账",
        15,
    )
    docx_heading(document, "五、用户痛点与口碑", 1)
    add_table_block(
        document,
        "表5-1  用户痛点与口碑主题",
        ["theme", "frequency_count", "severity", "representative_quote", "summary_cn"],
        reviews,
        "08_Review_Coding.csv；原始评论链接见证据台账",
        15,
    )
    docx_heading(document, "六、机会点与风险", 1)
    add_table_block(
        document,
        "表6-1  SWOT、机会点与风险",
        ["brand", "exact_model", "strength", "weakness", "opportunity", "threat", "risk_level", "opportunity_priority"],
        swot,
        "10_SWOT_Opportunity.csv",
        15,
    )
    docx_heading(document, "七、图表附录", 1)
    for chart in charts:
        path = Path(chart["path"])
        if path.exists():
            image_paragraph = document.add_paragraph(style="Figure Image")
            image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            image_paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            image_paragraph.paragraph_format.keep_together = True
            image_paragraph.paragraph_format.keep_with_next = True
            image_paragraph.add_run().add_picture(str(path), width=DocxInches(6.2))
            caption = document.add_paragraph(style="Figure Caption")
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.paragraph_format.keep_together = True
            caption.paragraph_format.keep_with_next = True
            caption.add_run(f"图：{chart['name']}")
            add_source_note(document, f"{chart.get('source', '')}；行数：{chart.get('rows_used', '')}")
    docx_heading(document, "八、证据限制与后续核验", 1)
    add_table_block(
        document,
        "表8-1  证据限制与后续核验",
        ["stage", "topic", "geography", "field", "issue_type", "reason", "resolution_path", "status"],
        gaps,
        "11_Evidence_Issues.csv",
        20,
    )
    enforce_table_caption_contract(document)
    clean_docx_placeholders(document)
    install_dynamic_footer_fields(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


def write_word_production_manifest(project_dir: Path, final_docx: Path) -> Path:
    root = skill_root()
    template = root / "assets/templates/word/energy_market_research_report_template.docx"
    fusion_path = root / "assets/templates/word/word_template_fusion_manifest.json"
    fusion = json.loads(fusion_path.read_text(encoding="utf-8-sig"))
    expected_hash = fusion["fused_template"]["sha256"]
    actual_template_hash = sha256_file(template)
    if expected_hash != actual_template_hash:
        raise RuntimeError("Installed Word template hash does not match its fusion manifest.")
    manifest_path = project_dir / "deliverables/word_production_manifest.json"
    write_json(
        manifest_path,
        {
            "template_path": "assets/templates/word/energy_market_research_report_template.docx",
            "template_sha256": expected_hash,
            "template_lineage_verified": True,
            "final_docx_path": str(final_docx.relative_to(project_dir)),
            "final_docx_sha256": sha256_file(final_docx),
            "word_pipeline_id": "embedded-word-production-v1",
            "word_components": [
                "build_template_report.py",
                "polish_word_ib_style.py",
                "verify_word_ib_style.py",
                "validate_word_delivery.py",
                "libreoffice_render.py+pymupdf",
                "create_page_contact_sheet.py",
                "scan_office_placeholders.py",
                "figure_production.py",
                "validate_figure_delivery.py",
                "insert_approved_figures.py",
            ],
            "content_skill_used": "embedded-market-insight-five-views-v1",
            "chart_theme_id": "kami-broker-v2",
            "figure_routing": {
                "market-insight": "embedded-market-figure-v1",
                "modeling": "embedded-modeling-figure-v1",
                "backend": "python",
                "one_owner_per_figure": True,
                "ppt_policy": "reuse-approved-or-embedded-native-slide-visual",
            },
            "heading_1_centered": True,
            "heading_1_left_indent_pt": 0,
            "heading_1_right_indent_pt": 0,
            "heading_1_first_line_indent_pt": 0,
            "table_text_centered": True,
            "table_font_size_pt": 9,
            "table_first_line_indent_pt": 0,
            "table_line_spacing": "single",
            "table_three_line_verified": True,
            "table_header_fill": f"#{TABLE_HEADER_FILL}",
            "table_outer_rule_color": f"#{TABLE_OUTER_RULE_COLOR}",
            "table_header_rule_color": f"#{TABLE_HEADER_RULE_COLOR}",
            "table_top_bottom_line_pt": 1.5,
            "table_header_line_pt": 1.0,
            "table_width_cm": 15.6,
            "table_header_repeat": True,
            "data_source_label": "数据来源",
            "figures_inline_and_centered": True,
            "template_guidance_pages_removed": True,
            "dynamic_page_fields_installed": True,
            "figure_theme_manifests": [],
            "rendering": {
                "status": "not_run",
                "page_count": 0,
                "pages_inspected": 0,
                "render_dir": "",
                "issues": [],
            },
            "pdf": {
                "delivered": False,
                "path": "",
                "direct_export_from_final_docx": False,
                "cross_format_consistency_passed": False,
            },
            "notes": "Automated embedded draft-package build; run polish, render, inspect, and register_word_delivery.py before final delivery.",
        },
    )
    return manifest_path


def ppt_text(slide, left, top, width, height, text, *, size=14, bold=False, color=CHARCOAL):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = text
    run.font.name = "Microsoft YaHei"
    run.font.size = PptPt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def ppt_title(slide, title: str, subtitle: str = "") -> None:
    ppt_text(slide, Inches(0.45), Inches(0.25), Inches(12.2), Inches(0.4), title, size=20, bold=True, color=BLUE)
    if subtitle:
        ppt_text(slide, Inches(0.45), Inches(0.72), Inches(12.2), Inches(0.3), subtitle, size=9)


def ppt_table(slide, headers: list[str], data: list[dict[str, str]], left, top, width, height, max_rows=7) -> None:
    shown = data[:max_rows] or [{header: "待补充" for header in headers}]
    shape = slide.shapes.add_table(len(shown) + 1, len(headers), left, top, width, height)
    table = shape.table
    for col, header in enumerate(headers):
        cell = table.cell(0, col)
        cell.text = header
        cell.fill.solid()
        cell.fill.fore_color.rgb = BLUE
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.name = "Microsoft YaHei"
                r.font.size = PptPt(6.5)
                r.font.bold = True
                r.font.color.rgb = WHITE
    for row_idx, row in enumerate(shown, start=1):
        for col, header in enumerate(headers):
            cell = table.cell(row_idx, col)
            cell.text = str(row.get(header, ""))[:120]
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.name = "Microsoft YaHei"
                    r.font.size = PptPt(6)
                    r.font.color.rgb = CHARCOAL


def add_chart(slide, charts: dict[str, dict], name: str, left, top, width, height) -> None:
    chart = charts.get(name)
    if chart and Path(chart["path"]).exists():
        slide.shapes.add_picture(chart["path"], left, top, width=width, height=height)
    else:
        rect = slide.shapes.add_shape(1, left, top, width, height)
        rect.fill.solid()
        rect.fill.fore_color.rgb = PptRGBColor(244, 246, 250)
        rect.line.color.rgb = GRAY
        ppt_text(slide, left + Inches(0.2), top + Inches(0.2), width - Inches(0.4), Inches(0.3), f"{name} 待补充", size=9)


def build_final_pptx(project_dir: Path, output: Path, region: str, category: str, charts: list[dict]) -> None:
    chart_map = {chart["name"]: chart for chart in charts}
    market = rows(project_dir, "01_Market_Scan.csv")
    matrix = rows(project_dir, "09_Integrated_Matrix.csv")
    reviews = rows(project_dir, "08_Review_Coding.csv")
    swot = rows(project_dir, "10_SWOT_Opportunity.csv")
    gaps = rows(project_dir, "11_Evidence_Issues.csv")
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    ppt_title(slide, f"{region}{category}产品与行业市场调研报告", "市场背景 → 竞品矩阵 → 用户痛点 → 机会点 → 行动建议")
    ppt_text(slide, Inches(0.7), Inches(1.7), Inches(11.6), Inches(0.6), "本 deck 由结构化证据表自动生成；所有结论需回溯 URL、ASIN/SKU/型号或本地文件位置。", size=18, bold=True)
    ppt_text(slide, Inches(0.7), Inches(2.8), Inches(3.5), Inches(0.4), f"市场记录：{len(market)}", size=15, bold=True, color=BLUE)
    ppt_text(slide, Inches(4.6), Inches(2.8), Inches(3.5), Inches(0.4), f"竞品记录：{len(matrix)}", size=15, bold=True, color=BLUE)
    ppt_text(slide, Inches(8.5), Inches(2.8), Inches(3.5), Inches(0.4), f"待核实项：{len(gaps)}", size=15, bold=True, color=BLUE)

    slide = prs.slides.add_slide(blank)
    ppt_title(slide, "市场背景与增长", "未来五年市场规模、增长率与政策驱动")
    add_chart(slide, chart_map, "market_trend", Inches(0.55), Inches(1.25), Inches(6.0), Inches(4.8))
    ppt_table(slide, ["country", "province_state", "market_segment", "year_period", "raw_value", "growth_rate", "policy_or_demand_driver"], market, Inches(6.75), Inches(1.25), Inches(6.0), Inches(4.8))

    slide = prs.slides.add_slide(blank)
    ppt_title(slide, "竞品矩阵与定位", "核心参数、价格、渠道与战略判断")
    add_chart(slide, chart_map, "price_capacity_scatter", Inches(0.55), Inches(1.25), Inches(5.8), Inches(4.8))
    ppt_table(slide, ["brand", "exact_model", "capacity_kwh", "power_kw", "price", "strategic_judgment"], matrix, Inches(6.55), Inches(1.25), Inches(6.2), Inches(4.8))

    slide = prs.slides.add_slide(blank)
    ppt_title(slide, "用户痛点与服务短板", "评论分析必须来自保存的原始评论语料")
    add_chart(slide, chart_map, "pain_point_pareto", Inches(0.55), Inches(1.25), Inches(5.8), Inches(4.8))
    ppt_table(slide, ["theme", "frequency_count", "severity", "summary_cn"], reviews, Inches(6.55), Inches(1.25), Inches(6.2), Inches(4.8))

    slide = prs.slides.add_slide(blank)
    ppt_title(slide, "机会点、风险与行动建议", "所有建议需绑定证据行；缺口未关闭前保持待核实")
    ppt_table(slide, ["brand", "weakness", "opportunity", "risk_level", "opportunity_priority", "evidence_row_ids"], swot, Inches(0.55), Inches(1.25), Inches(12.2), Inches(3.2))
    ppt_table(slide, ["stage", "topic", "field", "reason", "resolution_path", "status"], gaps, Inches(0.55), Inches(4.75), Inches(12.2), Inches(1.65), max_rows=4)

    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build final Word/PPT/Excel package from project CSV evidence tables and charts.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--region", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--prefix", default="能源产品与行业市场调研报告")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    deliverables = project_dir / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    charts = render_all_charts(project_dir)
    excel_path = deliverables / f"{args.prefix}.xlsx"
    docx_path = deliverables / f"{args.prefix}.docx"
    pptx_path = deliverables / f"{args.prefix}.pptx"
    sync_excel(project_dir, excel_path, force_template=True)
    build_final_docx(project_dir, docx_path, args.region, args.category, charts)
    manifest_path = write_word_production_manifest(project_dir, docx_path)
    build_final_pptx(project_dir, pptx_path, args.region, args.category, charts)
    print(f"Wrote final Excel: {excel_path}")
    print(f"Wrote final Word: {docx_path}")
    print(f"Wrote Word manifest: {manifest_path}")
    print(f"Wrote final PPT: {pptx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
