# -*- coding: utf-8 -*-
"""
按券商模板骨架填充 Word 报告（Stage 7 官方生成器）。

规则（format-and-visual-style.md 验证版）：
- 从 energy_market_research_report_template.docx 复制，保留券商排版（页眉页脚/章节结构/三线表）。
- 封面占位符替换：[[目标区域]] [[产品类别]] [[更新日期]] [[数据截止日期]] [[版本号]]。
- 每章表 X-1 填入证据 CSV 的真实数据（不新增表格）。
- 图表插入对应章节：图题在图下方（宋体五号按章编号）+ 来源注（9pt 灰）。
- 正式图表由 embedded-figure-production-v1 生成：白底深蓝/冷灰券商配色、可编辑 SVG 文本、
  ≥300 dpi PNG、来源/脚本/输出哈希与逐图视觉登记；本脚本只负责按清单插入已批准图表。
- 表格：整体居中（tblPr jc=center）、文字宋体小五 9pt + Times New Roman、表头加粗、
  水平垂直居中、单倍行距、三线表。
- 表题：居中并写入 keepNext/keepLines，禁止表题孤立在页尾、表格从下一页开始。
- 清理模板示例行残留的 [[xxx]] 占位符。
- 删除封面后的“文档控制与使用说明”章节，只保留正文。
- 一级标题居中且无底部横线（清除样式/段落级 pBdr 与 rightChars 等字符单位缩进）。

用法:
    python scripts/build_template_report.py --project-dir <proj> --region <approved-region> --category <approved-category> --update-date YYYY-MM-DD --data-cutoff YYYY-MM-DD [--prefix 市场深度调研与商业机会报告] [--charts-dir <dir>]
"""
from __future__ import annotations

import argparse
import json
import re as _re
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL

from _common import read_csv


TABLE_CAPTION_RE = _re.compile(r"^\s*表\s*[0-9一二三四五六七八九十Xx]+[-－—–][0-9Xx]+")
TABLE_HEADER_FILL = "D9E2EC"
TABLE_OUTER_RULE_COLOR = "000000"
TABLE_HEADER_RULE_COLOR = "1B365D"
TABLE_WIDTH_DXA = 8844  # 15.6 cm


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def set_east_asia(run, font_name: str) -> None:
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), font_name)


def set_run_font(run, size_pt: float = 9, bold: bool = False) -> None:
    """统一表格字体：宋体 + Times New Roman + 小五(9pt)。"""
    run.font.name = "Times New Roman"
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(size_pt)
    run.font.bold = bold


def replace_placeholders(doc: Document, mapping: dict[str, str]) -> None:
    containers = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)
    for p in containers:
        for key, val in mapping.items():
            if key in p.text:
                for run in p.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, val)


def clean_placeholders(doc: Document) -> int:
    """清理模板示例行残留的 [[xxx]] 占位符（含页眉页脚）。"""
    ph = _re.compile(r"\[\[[^\]]*\]\]")
    count = 0
    containers = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)
    for section in doc.sections:
        for story in (section.header, section.footer,
                      section.first_page_header, section.first_page_footer):
            containers.extend(story.paragraphs)
    for p in containers:
        if "[[" in p.text:
            for run in p.runs:
                if "[[" in run.text:
                    run.text = ph.sub("", run.text).strip()
                    count += 1
    return count


def apply_three_line_borders(doc: Document) -> int:
    """三线表：黑色 1.5 pt 顶/底线 + 深蓝 1 pt 表头线；浅蓝表头。"""
    count = 0
    for t in doc.tables:
        tblPr = t._tbl.tblPr
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
        # schema 顺序: tblStyle → tblW → tblBorders → tblLook
        tblW = tblPr.find(qn("w:tblW"))
        if tblW is not None:
            tblW.addnext(borders)
        else:
            tblPr.append(borders)
        for row_index, row in enumerate(t.rows):
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
                if row_index == 0:
                    bottom = tc_borders.find(qn("w:bottom"))
                    bottom.set(qn("w:val"), "single")
                    bottom.set(qn("w:sz"), "8")
                    bottom.set(qn("w:color"), TABLE_HEADER_RULE_COLOR)
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is not None:
                    tcW.addnext(tc_borders)
                else:
                    tcPr.append(tc_borders)
                if row_index != 0:
                    continue
                shading = OxmlElement("w:shd")
                shading.set(qn("w:val"), "clear")
                shading.set(qn("w:color"), "auto")
                shading.set(qn("w:fill"), TABLE_HEADER_FILL)
                tc_borders.addnext(shading)
        count += 1
    return count


def apply_spec_styles(doc: Document) -> int:
    """按 format-and-visual-style.md 改写 styles.xml 的 Heading1-4 + Normal。
    一级: 黑体22pt加粗居中 段前18段后12 固定30pt行距
    二级: 仿宋14pt加粗 6pt 固定24pt | 三级: 仿宋12pt加粗 6pt 固定24pt
    四级: 宋体10.5pt加粗 固定24pt 首行缩进 | 正文: 宋体12pt 固定22pt 首行缩进两字符"""
    # 用 python-docx 的 styles 对象改写 styles.xml
    replacements = {
        "Heading1": ("黑体", 22, True, "center", 30, 18, 12),
        "Heading2": ("仿宋", 14, True, "left", 24, 6, 6),
        "Heading3": ("仿宋", 12, True, "left", 24, 6, 6),
        "Heading4": ("宋体", 10.5, True, "left", 24, 0, 0),
    }
    count = 0
    styles_map = {s.style_id: s for s in doc.styles}
    for sid, (ea, size, bold, jc, line, before, after) in replacements.items():
        st = styles_map.get(sid)
        if st is None:
            continue
        # rPr: 字体/字号/加粗
        rpr = st.element.get_or_add_rPr()
        rFonts = rpr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rpr.insert(0, rFonts)
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rFonts.set(qn("w:eastAsia"), ea)
        sz_el = rpr.find(qn("w:sz"))
        if sz_el is None:
            sz_el = OxmlElement("w:sz")
            rpr.append(sz_el)
        sz_el.set(qn("w:val"), str(int(size * 2)))
        # pPr: 行距/间距/对齐
        ppr = st.element.get_or_add_pPr()
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            ppr.insert(0, spacing)
        spacing.set(qn("w:before"), str(int(before * 20)))
        spacing.set(qn("w:after"), str(int(after * 20)))
        spacing.set(qn("w:line"), str(int(line * 20)))
        spacing.set(qn("w:lineRule"), "exact")
        jc_el = ppr.find(qn("w:jc"))
        if jc_el is None:
            jc_el = OxmlElement("w:jc")
            ppr.append(jc_el)
        jc_el.set(qn("w:val"), jc)
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            ppr.append(ind)
        ind.set(qn("w:left"), "0")
        ind.set(qn("w:right"), "0")
        ind.set(qn("w:firstLine"), "0")
        ind.set(qn("w:hanging"), "0")
        # 字符单位缩进（rightChars 等）在 Word 中优先于磅值缩进，必须显式清除，
        # 否则模板残留的 rightChars 会让居中标题在视觉上偏左。
        for attr in ("leftChars", "rightChars", "firstLineChars", "hangingChars"):
            ind.attrib.pop(qn(f"w:{attr}"), None)
        # 一级标题不带底部横线：横线横跨整栏会让居中标题看起来像居左。
        if sid == "Heading1":
            pbdr = ppr.find(qn("w:pBdr"))
            if pbdr is not None:
                ppr.remove(pbdr)
        count += 1
    # Normal: 宋体12pt 固定22pt 首行缩进两字符
    try:
        normal = doc.styles["Normal"]
        rpr = normal.element.get_or_add_rPr()
        rFonts = rpr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rpr.insert(0, rFonts)
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rFonts.set(qn("w:eastAsia"), "宋体")
        sz_el = rpr.find(qn("w:sz"))
        if sz_el is None:
            sz_el = OxmlElement("w:sz")
            rpr.append(sz_el)
        sz_el.set(qn("w:val"), "24")
        ppr = normal.element.get_or_add_pPr()
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            ppr.insert(0, spacing)
        spacing.set(qn("w:line"), "440")
        spacing.set(qn("w:lineRule"), "exact")
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            ppr.append(ind)
        ind.set(qn("w:firstLine"), "480")
        count += 1
    except KeyError:
        pass
    return count


def format_tables(doc: Document) -> None:
    """表格规则：居中 + 宋体小五9pt + 表头加粗 + 水平垂直居中 + 单倍行距 + 三线表。"""
    for table_index, t in enumerate(doc.tables):
        column_count = len(t.columns)
        if column_count == 2:
            widths = [2200, 6644]
        elif column_count == 5 and table_index == 1:
            widths = [800, 3200, 1800, 1100, 1944]
        elif column_count == 5:
            widths = [1600, 2300, 1500, 2200, 1244]
        else:
            base, remainder = divmod(TABLE_WIDTH_DXA, max(1, column_count))
            widths = [base + (1 if index < remainder else 0) for index in range(column_count)]

        tblPr = t._tbl.tblPr
        tblW = tblPr.find(qn("w:tblW"))
        if tblW is None:
            tblW = OxmlElement("w:tblW")
            tblPr.append(tblW)
        tblW.set(qn("w:type"), "dxa")
        tblW.set(qn("w:w"), str(TABLE_WIDTH_DXA))
        t.autofit = False
        grid = t._tbl.tblGrid
        for child in list(grid):
            grid.remove(child)
        for width in widths:
            grid_col = OxmlElement("w:gridCol")
            grid_col.set(qn("w:w"), str(width))
            grid.append(grid_col)

        jc = tblPr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            tblPr.append(jc)
        jc.set(qn("w:val"), "center")
        for ri, row in enumerate(t.rows):
            if ri == 0:
                trPr = row._tr.get_or_add_trPr()
                header_repeat = trPr.find(qn("w:tblHeader"))
                if header_repeat is None:
                    header_repeat = OxmlElement("w:tblHeader")
                    trPr.append(header_repeat)
                header_repeat.set(qn("w:val"), "true")
            for column_index, cell in enumerate(row.cells):
                tcPr = cell._tc.get_or_add_tcPr()
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is None:
                    tcW = OxmlElement("w:tcW")
                    tcPr.insert(0, tcW)
                tcW.set(qn("w:type"), "dxa")
                tcW.set(qn("w:w"), str(widths[min(column_index, len(widths) - 1)]))
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                for p in cell.paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    pf = p.paragraph_format
                    pf.space_before = Pt(0)
                    pf.space_after = Pt(0)
                    pf.first_line_indent = Pt(0)
                    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
                    for run in p.runs:
                        set_run_font(run, 9, bold=(ri == 0))
                        if ri == 0:
                            run.font.color.rgb = RGBColor(27, 54, 93)
    apply_three_line_borders(doc)


def format_table_captions(doc: Document) -> int:
    """表题居中，并与下一张表保持同页，避免表题孤立在页尾。"""
    try:
        style = doc.styles["Table Caption"]
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.keep_together = True
    except KeyError:
        pass

    count = 0
    for paragraph in doc.paragraphs:
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name != "Table Caption" and not TABLE_CAPTION_RE.match(paragraph.text or ""):
            continue
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.keep_together = True
        count += 1
    return count


def center_heading_1_paragraphs(doc: Document) -> int:
    """Apply direct H1 centering with zero left/right/first-line indents.

    同时删除段落级底部横线（pBdr）和字符单位缩进（rightChars 等），
    否则居中标题在视觉上会偏左。"""
    count = 0
    for paragraph in doc.paragraphs:
        if paragraph.style is not None and paragraph.style.style_id == "Heading1":
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.left_indent = Pt(0)
            paragraph.paragraph_format.right_indent = Pt(0)
            paragraph.paragraph_format.first_line_indent = Pt(0)
            ppr = paragraph._p.get_or_add_pPr()
            pbdr = ppr.find(qn("w:pBdr"))
            if pbdr is not None:
                ppr.remove(pbdr)
            ind = ppr.find(qn("w:ind"))
            if ind is not None:
                for attr in ("leftChars", "rightChars", "firstLineChars", "hangingChars"):
                    ind.attrib.pop(qn(f"w:{attr}"), None)
            count += 1
    return count


FRONT_MATTER_HEADING = "文档控制与使用说明"


def _is_heading_1_el(el) -> bool:
    if el.tag != qn("w:p"):
        return False
    ppr = el.find(qn("w:pPr"))
    if ppr is None:
        return False
    pstyle = ppr.find(qn("w:pStyle"))
    return pstyle is not None and pstyle.get(qn("w:val")) == "Heading1"


def _para_text_el(el) -> str:
    return "".join(node.text or "" for node in el.iter(qn("w:t")))


def strip_template_front_matter(doc: Document) -> int:
    """删除封面后的“文档控制与使用说明”章节（H1 + 说明段 + 说明表），只保留正文。"""
    body = doc.element.body
    children = list(body.iterchildren())
    start = None
    for i, el in enumerate(children):
        if _is_heading_1_el(el) and _para_text_el(el).strip() == FRONT_MATTER_HEADING:
            start = i
            break
    if start is None:
        return 0
    removed = 0
    for el in children[start + 1:]:
        if _is_heading_1_el(el):
            break
        body.remove(el)
        removed += 1
    body.remove(children[start])
    return removed + 1


def format_image_paragraphs(doc: Document) -> None:
    """图片段落：单倍行距 + 段前6pt + 居中。用 XML 直接写 spacing 保证单倍行距生效。"""
    # Repair the paragraph style as well as direct formatting. A style-level
    # ``lineRule=exact`` still clips an inline drawing when the paragraph has
    # no direct spacing override (the 2026-08 AU V2G regression).
    try:
        figure_style = doc.styles["Figure Image"]
        sf = figure_style.paragraph_format
        sf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        sf.line_spacing = 1.0
        sf.space_before = Pt(6)
        sf.space_after = Pt(0)
        sf.keep_with_next = True
        sf.keep_together = True
        sf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    except KeyError:
        pass

    for p in doc.paragraphs:
        blips = p._element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        if blips:
            # register_word_delivery structural gate requires the Figure Image
            # style on every inline figure paragraph (v1.2.8 consistency fix)
            try:
                p.style = doc.styles["Figure Image"]
            except KeyError:
                pass
            pPr = p._p.get_or_add_pPr()
            spacing = pPr.find(qn("w:spacing"))
            if spacing is None:
                spacing = OxmlElement("w:spacing")
                pPr.insert(0, spacing)
            # 单倍行距: line=240 lineRule=auto
            spacing.set(qn("w:line"), "240")
            spacing.set(qn("w:lineRule"), "auto")
            spacing.set(qn("w:before"), str(int(6 * 20)))
            spacing.set(qn("w:after"), "0")
            # 清掉可能继承的首行缩进
            ind = pPr.find(qn("w:ind"))
            if ind is not None:
                ind.set(qn("w:firstLine"), "0")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.keep_together = True


def insert_charts(
    doc: Document,
    charts_dir: Path,
    section_marker: str = "四、市场规模、细分、产业链与增长情景",
    caption_chapter: int = 4,
) -> int:
    """Insert approved figures after substantive analysis paragraphs in their declared sections."""
    if not charts_dir.exists():
        return 0

    figure_specs = []
    for manifest_path in sorted(charts_dir.glob("fig*.theme.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print(f"  [warn] insert_charts: 无法读取 {manifest_path.name}: {exc}")
            continue
        png_record = (manifest.get("outputs") or {}).get("png") or {}
        raw_png = Path(str(png_record.get("path") or ""))
        png = raw_png if raw_png.is_absolute() else manifest_path.with_name(raw_png.name)
        placement = manifest.get("word_placement") or {}
        if not png.exists():
            print(f"  [warn] insert_charts: 图像不存在 {png}")
            continue
        figure_specs.append(
            {
                "png": png,
                "section": placement.get("section_heading") or section_marker,
                "caption": placement.get("caption") or manifest.get("title") or png.stem,
                "source_note": placement.get("source_note") or "数据来源：项目证据台账。",
            }
        )
    if not figure_specs:
        for png in sorted(charts_dir.glob("fig*.png")):
            figure_specs.append(
                {
                    "png": png,
                    "section": section_marker,
                    "caption": png.stem,
                    "source_note": "数据来源：项目证据台账。",
                }
            )
    if not figure_specs:
        return 0

    original_paragraphs = list(doc.paragraphs)
    heading_indices = [
        index
        for index, paragraph in enumerate(original_paragraphs)
        if paragraph.style and paragraph.style.name == "Heading 1"
    ]
    grouped: dict[str, list[dict]] = {}
    for spec in figure_specs:
        grouped.setdefault(str(spec["section"]), []).append(spec)

    chinese_numbers = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
        "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
    }
    inserted = 0
    used_chapter_numbers: set[int] = set()
    for section, specs in grouped.items():
        heading_index = next(
            (index for index, paragraph in enumerate(original_paragraphs) if paragraph.text.strip() == section),
            None,
        )
        if heading_index is None:
            print(f"  [warn] insert_charts: 未找到章节锚点 {section!r}，跳过 {len(specs)} 张图表")
            continue
        next_heading = next((index for index in heading_indices if index > heading_index), len(original_paragraphs))
        analysis_paragraphs = [
            paragraph
            for paragraph in original_paragraphs[heading_index + 1 : next_heading]
            if len(paragraph.text.strip()) >= 50
            and "[[" not in paragraph.text
            and not paragraph.text.strip().startswith(("图", "表", "数据来源", "资料来源"))
        ]
        if len(analysis_paragraphs) < len(specs):
            print(
                f"  [warn] insert_charts: {section!r} 只有 {len(analysis_paragraphs)} 个实质分析段，"
                f"仅插入前 {len(analysis_paragraphs)} 张，避免图表堆叠"
            )
        number_match = _re.match(r"^([一二三四五六七八九十]+)、", section)
        if number_match:
            chapter_number = chinese_numbers.get(number_match.group(1), caption_chapter)
        else:
            # 无序号章节（如序章"核心结论与证据状态"）：从 15 起取未占用编号，
            # 避免回退到 caption_chapter 与正文章节图号冲突
            chapter_number = 15
            while chapter_number in used_chapter_numbers:
                chapter_number += 1
        used_chapter_numbers.add(chapter_number)
        for local_index, (spec, analysis_paragraph) in enumerate(zip(specs, analysis_paragraphs), start=1):
            figure_label = f"图{chapter_number}-{local_index}"
            if figure_label not in analysis_paragraph.text:
                reference_run = analysis_paragraph.add_run(f"（见{figure_label}）")
                reference_run.font.size = Pt(10.5)
                set_east_asia(reference_run, "宋体")
            anchor = analysis_paragraph._p
            png = spec["png"]
            p_img = doc.add_paragraph()
            run = p_img.add_run()
            run.add_picture(str(png), width=Inches(5.2))
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_cap = doc.add_paragraph()
            p_cap.paragraph_format.space_before = Pt(0)
            p_cap.paragraph_format.space_after = Pt(6)
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_cap.paragraph_format.keep_with_next = True
            p_cap.paragraph_format.keep_together = True
            r = p_cap.add_run(f"{figure_label} {spec['caption']}")
            r.font.size = Pt(10.5)
            set_east_asia(r, "宋体")
            p_note = doc.add_paragraph()
            p_note.paragraph_format.space_after = Pt(12)
            r2 = p_note.add_run(str(spec["source_note"]))
            r2.font.size = Pt(9)
            r2.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            set_east_asia(r2, "宋体")
            for new_p in (p_img._p, p_cap._p, p_note._p):
                anchor.addnext(new_p)
                anchor = new_p
            inserted += 1
    return inserted


def _drop_placeholder_rows(doc: Document) -> int:
    """删除模板表格中的示例占位行（含 [[xxx]] 的行），避免表头下出现空行。"""
    dropped = 0
    for t in doc.tables:
        for row in list(t.rows):
            row_text = "".join(c.text for c in row.cells)
            if "[[" in row_text:
                tr = row._tr
                tr.getparent().remove(tr)
                dropped += 1
    return dropped


def fill_tables_from_csv(doc: Document, project_dir: Path) -> None:
    """把证据 CSV 的关键行填入模板表 1-8（表 0 为核心结论）。

    索引约定：doc.tables[0] 是封面信息表，正文的表0-1从 doc.tables[1] 开始，
    表N-1对应 doc.tables[N+1]。"""
    _drop_placeholder_rows(doc)
    def load(name):
        try:
            _, rows = read_csv(Path(project_dir) / name)
            return rows
        except Exception as exc:
            print(f"  [warn] fill_tables_from_csv: {name} 读取失败: {exc}")
            return []

    market = load("01_Market_Scan.csv")
    competitors = load("02_Competitor_List.csv")
    params = load("04_Product_Parameters.csv")
    pricing = load("05_Pricing_Channel.csv")
    reviews = load("08_Review_Coding.csv")
    matrix = load("09_Integrated_Matrix.csv")
    opportunities = load("10_SWOT_Opportunity.csv")

    def scope(*values: object) -> str:
        return "/".join(str(value).strip() for value in values if str(value or "").strip())

    def add_rows(table, rows: list[list[object]]) -> None:
        for values in rows:
            cells = table.add_row().cells
            padded = [str(value or "") for value in values[: len(cells)]]
            padded.extend([""] * (len(cells) - len(padded)))
            for index, value in enumerate(padded):
                cells[index].text = value

    # 所有正文表统一映射五列：事项、值/结论、范围、来源、类别/限制。
    add_rows(
        doc.tables[2],
        [
            [
                row.get("metric", ""),
                scope(row.get("raw_value", ""), row.get("unit", ""), row.get("currency", "")),
                scope(row.get("country", ""), row.get("city_site", ""), row.get("year_period", "")),
                row.get("source_id", ""),
                scope(row.get("value_class", ""), row.get("verification_status", "")),
            ]
            for row in market[:3]
        ],
    )

    # 表2-1 竞品名单
    add_rows(
        doc.tables[3],
        [
            [
                scope(row.get("brand", ""), row.get("representative_model", "")),
                scope(row.get("player_type", ""), row.get("strategic_fit", "")),
                row.get("country", ""),
                row.get("source_url", ""),
                row.get("verification_status", "pending"),
            ]
            for row in competitors[:3]
        ],
    )

    # 表3-1 产品参数
    add_rows(
        doc.tables[4],
        [
            [
                row.get("parameter_name", ""),
                scope(row.get("raw_value", ""), row.get("unit", "")),
                scope(row.get("exact_model", ""), row.get("access_or_extraction_date", "")),
                row.get("source_url", "") or row.get("local_file_path", ""),
                scope(row.get("source_priority", ""), row.get("verification_status", "")),
            ]
            for row in params[:3]
        ],
    )

    # 表4-1 定价渠道
    add_rows(
        doc.tables[5],
        [
            [
                scope(row.get("brand", ""), row.get("configuration", "")),
                scope(row.get("discounted_price") or row.get("list_price", ""), row.get("currency", "")),
                scope(row.get("country", ""), row.get("capture_date", "")),
                row.get("source_id", "") or row.get("product_url", ""),
                scope(row.get("value_class", ""), row.get("verification_status", ""), f"tax={row.get('tax_included','') or 'unknown'}"),
            ]
            for row in pricing[:3]
        ],
    )

    # 表6-1 评论主题
    add_rows(
        doc.tables[7],
        [
            [
                row.get("theme", ""),
                scope(row.get("summary_cn", ""), f"frequency={row.get('frequency_count','')}", f"severity={row.get('severity','')}"),
                row.get("exact_model", ""),
                row.get("raw_review_row_ids", ""),
                "review-coded",
            ]
            for row in reviews[:3]
        ],
    )

    # 表0-1 核心结论：只使用项目真实行，不写死国家、品牌、货币或价格带。
    core_rows: list[list[object]] = []
    candidates = [("market", row) for row in market[:2]] + [("pricing", row) for row in pricing[:1]]
    for sequence, (kind, row) in enumerate(candidates, start=1):
        if kind == "market":
            conclusion = f"{row.get('metric','')}：{scope(row.get('raw_value',''), row.get('unit',''), row.get('currency',''))}"
            source_id = row.get("source_id", "")
            value_class = row.get("value_class", "")
        else:
            conclusion = f"{scope(row.get('brand',''), row.get('configuration',''))}：{scope(row.get('discounted_price') or row.get('list_price',''), row.get('currency',''))}"
            source_id = row.get("source_id", "")
            value_class = row.get("value_class", "")
        core_rows.append([sequence, conclusion, source_id, value_class, row.get("verification_status", "")])
    add_rows(doc.tables[1], core_rows)

    # 表5-1 渠道服务（从竞品推导）
    add_rows(
        doc.tables[6],
        [
            [
                row.get("brand", ""),
                scope(row.get("player_type", ""), row.get("strategic_fit", "")),
                scope(row.get("country", ""), row.get("representative_model", "")),
                row.get("source_url", ""),
                row.get("verification_status", ""),
            ]
            for row in competitors[:3]
        ],
    )

    # 表7-1 SWOT（从矩阵推导）
    add_rows(
        doc.tables[8],
        [
            [
                scope(row.get("brand", ""), row.get("exact_model", "")),
                row.get("strategic_judgment", ""),
                scope(row.get("capacity_kwh", ""), row.get("power_kw", "")),
                row.get("evidence_row_ids", ""),
                row.get("verification_status", ""),
            ]
            for row in matrix[:3]
        ],
    )

    # 表8-1 行动建议：来自 10_SWOT_Opportunity.csv，不生成通用占位建议。
    add_rows(
        doc.tables[9],
        [
            [
                scope(row.get("brand", ""), row.get("exact_model", "")),
                scope(row.get("opportunity", ""), row.get("strength", "")),
                scope(row.get("opportunity_priority", ""), row.get("risk_level", "")),
                row.get("evidence_row_ids", ""),
                scope(row.get("verification_status", ""), row.get("notes", "")),
            ]
            for row in opportunities[:3]
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build spec-compliant Word report from brokerage template skeleton.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--prefix", default="市场深度调研与商业机会报告")
    parser.add_argument("--charts-dir", default="", help="Chart PNG directory (default: <project>/intermediate/charts)")
    parser.add_argument("--update-date", required=True, help="Approved cover update date (YYYY-MM-DD)")
    parser.add_argument("--data-cutoff", required=True, help="Approved data cutoff date (YYYY-MM-DD)")
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    root = skill_root()
    tpl = root / "assets" / "templates" / "word" / "energy_market_research_report_template.docx"
    out = project_dir / "deliverables" / f"{args.prefix}.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    charts_dir = Path(args.charts_dir).expanduser().resolve() if args.charts_dir else project_dir / "intermediate" / "charts"

    doc = Document(str(tpl))
    n_front = strip_template_front_matter(doc)

    replace_placeholders(doc, {
        "[[机构名称]]": "四川动力电池产业创新中心",
        "[[目标区域]]": args.region,
        "[[产品/系统类别]]": args.category,
        "[[产品类别]]": args.category,
        "[[更新日期]]": args.update_date,
        "[[数据截止日期]]": args.data_cutoff,
        "[[版本号]]": args.version,
    })

    fill_tables_from_csv(doc, project_dir)
    n_clean = clean_placeholders(doc)
    n_styles = apply_spec_styles(doc)
    n_heading_1 = center_heading_1_paragraphs(doc)
    format_tables(doc)
    n_table_captions = format_table_captions(doc)
    n_charts = insert_charts(doc, charts_dir)
    format_image_paragraphs(doc)  # 必须在 insert_charts 之后，否则新图片段落未被格式化

    doc.save(str(out))
    print(f"Wrote: {out}")
    print(
        f"Styles applied: {n_styles}, H1 centered: {n_heading_1}, table captions locked: {n_table_captions}, "
        f"placeholders cleaned: {n_clean}, charts inserted: {n_charts}, front matter removed: {n_front}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
