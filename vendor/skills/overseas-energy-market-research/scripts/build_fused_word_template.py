from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH,
    WD_BREAK,
    WD_LINE_SPACING,
    WD_TAB_ALIGNMENT,
    WD_TAB_LEADER,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = "000000"
DEEP_BLUE = "1B365D"
COOL_GRAY = "6B6A64"
LIGHT_BLUE = "D9E2EC"
LIGHT_GRAY = "F3F3F0"
TABLE_OUTER_RULE = "000000"
TABLE_HEADER_RULE = "1B365D"
TABLE_WIDTH_DXA = 8844
TABLE_INDENT_DXA = 120

SOURCE_NAMES = [
    "规则限定描述.docx",
    "欧洲阳台光储产品竞品分析-20260602.docx",
    "澳洲V2G&V2H市场深度调研计划-V1.2-20260520.docx",
    "非洲移动储能和户用储能深度市场调研计划-V1.0-20260610.docx",
    "车网互动规模化应用试点项目调研大纲-20260720.docx",
]

CHAPTERS = [
    ("一、执行摘要与决策问题", "回答本项目要支持的决策、核心结论、证据置信度及管理层需要采取的行动。"),
    ("二、调研边界、方法与证据体系", "定义地区、产品、客户、时间、币种、税费、数据类别、来源优先级与研究限制。"),
    ("三、宏观电力环境、政策、电价与市场准入", "覆盖供电可靠性、分时电价、上网规则、补贴、并网、标准、认证、税费与贸易规则。"),
    ("四、市场规模、细分、产业链与增长情景", "建立市场定义、历史规模、预测、TAM/SAM/SOM、细分、价值链和情景假设。"),
    ("五、用户类型、负荷与应用场景", "覆盖家庭、移动/离网、阳台光储、V2G/V2H、停电、出行和支付能力等代表性场景。"),
    ("六、产品系统架构、工程参数与区域合规", "分析电池、逆变器、双向功率、接口、协议、EMS/VPP、安全、安装、热设计和区域认证。"),
    ("七、竞争格局、玩家分类与精确型号对标", "按精确型号、区域版本、配置、认证和产品链接形成可追溯竞品矩阵。"),
    ("八、定价、渠道、安装与服务网络", "比较价格口径、促销、线上线下渠道、安装商、售后、质保、融资和本地服务能力。"),
    ("九、原始评论、用户痛点与购买驱动", "先保存原始评论，再进行主题编码、频次、严重度、典型原话、购买驱动和未满足需求分析。"),
    ("十、经济性、数学模型与敏感性", "呈现假设、符号、公式、约束、模型结果、NPV/IRR/回收期、敏感性、稳健性和限制。"),
    ("十一、V2G/V2H、VPP与试点项目", "对标项目业主、场景、规模、技术路线、平台、运营模式、实际成效、可复制性和瓶颈。"),
    ("十二、产品定义与市场进入策略", "输出目标客户、SKU、容量/功率、协议认证、价格带、渠道、服务和商业模式。"),
    ("十三、风险、路线图与行动计划", "给出风险、优先级、里程碑、试点、负责人、时间和下一步行动。"),
    ("十四、来源、假设、证据问题与附录", "集中列示来源台账、模型假设、证据冲突、原始数据和方法附录。"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_run_font(
    run,
    *,
    east_asia: str,
    latin: str = "Times New Roman",
    size: float,
    bold: bool = False,
    color: str = BLACK,
) -> None:
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


def clear_body(document: Document) -> None:
    body = document._body._element
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def set_fixed_line_spacing(paragraph_format, points: float) -> None:
    paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    paragraph_format.line_spacing = Pt(points)


def configure_style(
    style,
    *,
    east_asia: str,
    latin: str,
    size: float,
    bold: bool,
    alignment,
    before: float,
    after: float,
    line: float,
    first_line: float = 0,
    keep_with_next: bool = False,
    color: str = BLACK,
) -> None:
    style.font.name = latin
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor.from_string(color)
    r_pr = style._element.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), east_asia)
    r_fonts.set(qn("w:ascii"), latin)
    r_fonts.set(qn("w:hAnsi"), latin)
    style.paragraph_format.alignment = alignment
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.left_indent = Pt(0)
    style.paragraph_format.right_indent = Pt(0)
    style.paragraph_format.first_line_indent = Pt(first_line)
    # 清除基模板继承的字符单位缩进（Word 中 rightChars/firstLineChars 优先于
    # right/firstLine，残留 rightChars 会让居中标题在视觉上偏左）。
    p_pr = style._element.get_or_add_pPr()
    ind = p_pr.find(qn("w:ind"))
    if ind is not None:
        for attr in ("leftChars", "rightChars", "firstLineChars", "hangingChars"):
            ind.attrib.pop(qn(f"w:{attr}"), None)
    style.paragraph_format.keep_with_next = keep_with_next
    style.paragraph_format.keep_together = keep_with_next
    set_fixed_line_spacing(style.paragraph_format, line)


def ensure_styles(document: Document) -> None:
    styles = document.styles
    if "Title" not in [style.name for style in styles]:
        styles.add_style("Title", WD_STYLE_TYPE.PARAGRAPH)
    configure_style(
        styles["Title"],
        east_asia="黑体",
        latin="Times New Roman",
        size=22,
        bold=True,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        before=52,
        after=24,
        line=30,
        keep_with_next=True,
    )
    if "Cover Label" not in [style.name for style in styles]:
        styles.add_style("Cover Label", WD_STYLE_TYPE.PARAGRAPH)
    configure_style(
        styles["Cover Label"],
        east_asia="宋体",
        latin="Times New Roman",
        size=9,
        bold=False,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        before=30,
        after=16,
        line=14,
        keep_with_next=True,
        color=DEEP_BLUE,
    )
    configure_style(
        styles["Normal"],
        east_asia="宋体",
        latin="Times New Roman",
        size=12,
        bold=False,
        alignment=WD_ALIGN_PARAGRAPH.JUSTIFY,
        before=0,
        after=0,
        line=22,
        first_line=24,
    )
    configure_style(
        styles["Heading 1"],
        east_asia="黑体",
        latin="Times New Roman",
        size=22,
        bold=True,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        before=18,
        after=12,
        line=30,
        keep_with_next=True,
    )
    configure_style(
        styles["Heading 2"],
        east_asia="仿宋",
        latin="Times New Roman",
        size=14,
        bold=True,
        alignment=WD_ALIGN_PARAGRAPH.LEFT,
        before=6,
        after=6,
        line=24,
        keep_with_next=True,
    )
    configure_style(
        styles["Heading 3"],
        east_asia="仿宋",
        latin="Times New Roman",
        size=12,
        bold=True,
        alignment=WD_ALIGN_PARAGRAPH.LEFT,
        before=6,
        after=6,
        line=24,
        keep_with_next=True,
    )
    if "Heading 4" not in [style.name for style in styles]:
        styles.add_style("Heading 4", WD_STYLE_TYPE.PARAGRAPH)
    configure_style(
        styles["Heading 4"],
        east_asia="宋体",
        latin="Times New Roman",
        size=12,
        bold=False,
        alignment=WD_ALIGN_PARAGRAPH.JUSTIFY,
        before=0,
        after=0,
        line=24,
        first_line=24,
        keep_with_next=True,
    )
    if "四级标题" not in [style.name for style in styles]:
        styles.add_style("四级标题", WD_STYLE_TYPE.PARAGRAPH)
    configure_style(
        styles["四级标题"],
        east_asia="宋体",
        latin="Times New Roman",
        size=12,
        bold=False,
        alignment=WD_ALIGN_PARAGRAPH.JUSTIFY,
        before=0,
        after=0,
        line=24,
        first_line=24,
        keep_with_next=True,
    )
    for name, before, after in [
        ("Table Caption", 6, 0),
        ("Figure Caption", 0, 6),
        ("Source Note", 0, 6),
    ]:
        if name not in [style.name for style in styles]:
            styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        configure_style(
            styles[name],
            east_asia="宋体",
            latin="Times New Roman",
            size=10.5,
            bold=False,
            alignment=WD_ALIGN_PARAGRAPH.CENTER
            if name != "Source Note"
            else WD_ALIGN_PARAGRAPH.LEFT,
            before=before,
            after=after,
            line=12,
        )
    if "Figure Image" not in [style.name for style in styles]:
        styles.add_style("Figure Image", WD_STYLE_TYPE.PARAGRAPH)
    configure_style(
        styles["Figure Image"],
        east_asia="宋体",
        latin="Times New Roman",
        size=10.5,
        bold=False,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        before=6,
        after=0,
        # Never give an inline drawing an exact line height. Word and
        # LibreOffice both clip the drawing to that fixed line box, which
        # turns a full chart into a thin coloured strip. The paragraph gets
        # an explicit single/auto spacing rule immediately below.
        line=12,
        keep_with_next=True,
    )
    figure_style = styles["Figure Image"]
    figure_style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    figure_style.paragraph_format.line_spacing = 1.0
    # 一级标题不使用底部横线：横线横跨整栏而标题居中，视觉上标题像居左。


def get_or_add_paragraph_borders(p_pr):
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    return borders


def set_paragraph_bottom_border(target, *, color: str, size: str, space: str) -> None:
    p_pr = target._p.get_or_add_pPr()
    borders = get_or_add_paragraph_borders(p_pr)
    border = borders.find(qn("w:bottom"))
    if border is None:
        border = OxmlElement("w:bottom")
        borders.append(border)
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), size)
    border.set(qn("w:space"), space)
    border.set(qn("w:color"), color)


def set_paragraph_top_border(target, *, color: str, size: str, space: str) -> None:
    p_pr = target._p.get_or_add_pPr()
    borders = get_or_add_paragraph_borders(p_pr)
    border = borders.find(qn("w:top"))
    if border is None:
        border = OxmlElement("w:top")
        borders.append(border)
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), size)
    border.set(qn("w:space"), space)
    border.set(qn("w:color"), color)


def remove_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "nil")


def set_cell_border(
    cell,
    edge: str,
    *,
    value: str = "single",
    size: str = "8",
    color: str = TABLE_OUTER_RULE,
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    tag = borders.find(qn(f"w:{edge}"))
    if tag is None:
        tag = OxmlElement(f"w:{edge}")
        borders.append(tag)
    tag.set(qn("w:val"), value)
    tag.set(qn("w:sz"), size)
    tag.set(qn("w:color"), color)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    tr_pr.append(marker)


def set_table_geometry(table, widths: list[int] | None = None) -> None:
    column_count = len(table.columns)
    if widths is None:
        base_width = TABLE_WIDTH_DXA // column_count
        widths = [base_width] * column_count
        widths[-1] += TABLE_WIDTH_DXA - sum(widths)
    if len(widths) != column_count or sum(widths) != TABLE_WIDTH_DXA:
        raise ValueError(
            f"Table widths must have {column_count} values totaling {TABLE_WIDTH_DXA} DXA."
        )

    tbl_pr = table._tbl.tblPr
    table_width = tbl_pr.find(qn("w:tblW"))
    if table_width is None:
        table_width = OxmlElement("w:tblW")
        tbl_pr.append(table_width)
    table_width.set(qn("w:type"), "dxa")
    table_width.set(qn("w:w"), str(TABLE_WIDTH_DXA))

    table_indent = tbl_pr.find(qn("w:tblInd"))
    if table_indent is None:
        table_indent = OxmlElement("w:tblInd")
        tbl_pr.append(table_indent)
    table_indent.set(qn("w:type"), "dxa")
    table_indent.set(qn("w:w"), str(TABLE_INDENT_DXA))

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width))
        grid.append(column)

    for row in table.rows:
        for index, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            cell_width = tc_pr.find(qn("w:tcW"))
            if cell_width is None:
                cell_width = OxmlElement("w:tcW")
                tc_pr.append(cell_width)
            cell_width.set(qn("w:type"), "dxa")
            cell_width.set(qn("w:w"), str(widths[index]))


def style_table_text(cell, *, bold=False, center=True, color=BLACK) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_margins(cell)
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.line_spacing = 1
        for run in paragraph.runs:
            set_run_font(
                run,
                east_asia="宋体",
                latin="Times New Roman",
                size=9,
                bold=bold,
                color=color,
            )


def add_three_line_table(
    document: Document,
    headers: list[str],
    rows: list[list[str]],
    *,
    widths: list[int] | None = None,
) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    remove_table_borders(table)
    set_repeat_table_header(table.rows[0])
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = header
        set_cell_shading(cell, LIGHT_BLUE)
        set_cell_border(cell, "top", size="12", color=TABLE_OUTER_RULE)
        set_cell_border(cell, "bottom", size="8", color=TABLE_HEADER_RULE)
        style_table_text(cell, bold=True, center=True, color=DEEP_BLUE)
    for row_values in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row_values):
            cells[index].text = value
            style_table_text(cells[index], center=True)
    for cell in table.rows[-1].cells:
        set_cell_border(cell, "bottom", size="12", color=TABLE_OUTER_RULE)
    set_table_geometry(table, widths)


def clear_story(story) -> None:
    element = story._element
    for child in list(element):
        element.remove(child)
    element.append(OxmlElement("w:p"))


def add_field(paragraph, instruction: str, placeholder: str) -> None:
    begin_run = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run.append(begin)
    paragraph._p.append(begin_run)

    instruction_run = OxmlElement("w:r")
    instruction_text = OxmlElement("w:instrText")
    instruction_text.set(qn("xml:space"), "preserve")
    instruction_text.text = f" {instruction} "
    instruction_run.append(instruction_text)
    paragraph._p.append(instruction_run)

    separate_run = OxmlElement("w:r")
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run.append(separate)
    paragraph._p.append(separate_run)

    display_run = paragraph.add_run(placeholder)
    set_run_font(display_run, east_asia="宋体", size=9, color=COOL_GRAY)

    end_run = OxmlElement("w:r")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run.append(end)
    paragraph._p.append(end_run)


def configure_page_furniture(document: Document) -> None:
    settings = document.settings._element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "true")

    for section in document.sections:
        section.different_first_page_header_footer = True
        section.header_distance = Cm(1.15)
        section.footer_distance = Cm(1.15)

        clear_story(section.first_page_header)
        clear_story(section.first_page_footer)

        clear_story(section.header)
        header = section.header.paragraphs[0]
        header.alignment = WD_ALIGN_PARAGRAPH.LEFT
        header.paragraph_format.space_before = Pt(0)
        header.paragraph_format.space_after = Pt(2)
        header.paragraph_format.tab_stops.add_tab_stop(
            Cm(15.6), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.SPACES
        )
        left = header.add_run("四川动力电池产业创新中心")
        right = header.add_run("\t能源与电力设备专题研究")
        set_run_font(left, east_asia="宋体", size=9, color=DEEP_BLUE)
        set_run_font(right, east_asia="宋体", size=9, color=COOL_GRAY)
        set_paragraph_bottom_border(
            header, color=DEEP_BLUE, size="6", space="3"
        )

        clear_story(section.footer)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
        footer.paragraph_format.space_before = Pt(2)
        footer.paragraph_format.space_after = Pt(0)
        footer.paragraph_format.tab_stops.add_tab_stop(
            Cm(15.6), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.SPACES
        )
        disclaimer = footer.add_run("重要声明：本报告仅供内部研究与决策参考")
        prefix = footer.add_run("\t第 ")
        set_run_font(disclaimer, east_asia="宋体", size=9, color=COOL_GRAY)
        set_run_font(prefix, east_asia="宋体", size=9, color=COOL_GRAY)
        add_field(footer, "PAGE", "1")
        middle = footer.add_run(" 页 / 共 ")
        set_run_font(middle, east_asia="宋体", size=9, color=COOL_GRAY)
        add_field(footer, "NUMPAGES", "1")
        suffix = footer.add_run(" 页")
        set_run_font(suffix, east_asia="宋体", size=9, color=COOL_GRAY)
        set_paragraph_top_border(
            footer, color="D6D3CB", size="4", space="3"
        )


def add_text(document: Document, text: str, style: str = "Normal"):
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    if style == "Normal":
        set_run_font(run, east_asia="宋体", size=12)
    return paragraph


def add_cover(document: Document) -> None:
    overline = document.add_paragraph(style="Cover Label")
    overline.add_run("四川动力电池产业创新中心  |  MARKET & PRODUCT INTELLIGENCE")
    set_paragraph_bottom_border(overline, color=DEEP_BLUE, size="8", space="6")

    paragraph = document.add_paragraph(style="Title")
    paragraph.add_run("[[目标区域]][[产品/系统类别]]市场深度调研报告")

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(48)
    run = subtitle.add_run("政策 · 市场 · 产品 · 用户 · 经济性 · 商业化")
    set_run_font(run, east_asia="宋体", size=12, color=COOL_GRAY)

    add_three_line_table(
        document,
        ["文档信息", "内容"],
        [
            ["项目名称", "[[项目名称]]"],
            ["决策问题", "[[决策问题]]"],
            ["目标区域", "[[目标区域]]"],
            ["研究对象", "[[产品/系统类别]]"],
            ["版本/日期", "[[版本号]] / [[更新日期]]"],
            ["数据截止", "[[数据截止日期]]"],
            ["编制/审核", "[[编制人]] / [[审核人]]"],
        ],
        widths=[2200, 6644],
    )
    paragraph = document.add_paragraph()
    paragraph.add_run().add_break(WD_BREAK.PAGE)


def build_template(base_template: Path, output: Path, source_dir: Path, originals_dir: Path) -> dict:
    document = Document(base_template)
    clear_body(document)
    for section in document.sections:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2.6)
        section.bottom_margin = Cm(2.4)
        section.left_margin = Cm(2.8)
        section.right_margin = Cm(2.6)
    ensure_styles(document)
    configure_page_furniture(document)
    add_cover(document)

    add_text(document, "核心结论与证据状态", "Heading 1")
    add_text(
        document,
        "本节只放置经核验的核心结论。每条结论必须给出证据编号、数据类别、适用地区/型号、置信度和限制。",
    )
    add_text(document, "表0-1  核心结论与证据索引", "Table Caption")
    add_three_line_table(
        document,
        ["序号", "核心结论", "证据编号", "数据类别", "置信度/限制"],
        [["1", "[[核心结论]]", "[[EVIDENCE-ID]]", "[[观测/推导/估算/假设]]", "[[待确认]]"]],
        widths=[700, 3300, 1400, 1544, 1900],
    )
    add_text(document, "数据来源：[[来源台账范围]]；更新日期：[[更新日期]]。", "Source Note")

    for chapter_title, guidance in CHAPTERS:
        add_text(document, chapter_title, "Heading 1")
        add_text(document, guidance)
        add_text(document, "（1）本章关键问题", "四级标题")
        add_text(document, "[[根据批准大纲填写本章关键问题与判定标准]]")
        add_text(document, "（2）证据、分析与反证", "四级标题")
        add_text(document, "[[填写事实、计算、解释、反证和限制；所有结论绑定证据ID]]")
        add_text(document, "表X-X  本章证据与分析索引", "Table Caption")
        add_three_line_table(
            document,
            ["证据/分析项", "值或结论", "地区/型号/期间", "来源ID", "数据类别/限制"],
            [["[[项目]]", "[[值或结论]]", "[[范围]]", "[[SOURCE-ID]]", "[[类别与限制]]"]],
            widths=[1500, 2800, 1600, 1100, 1844],
        )
        add_text(
            document,
            "数据来源：[[来源URL或本地文件]]；访问/提取日期：[[日期]]；数据类别：[[类别]]；注：[[限制]]。",
            "Source Note",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)

    originals_dir.mkdir(parents=True, exist_ok=True)
    source_records = []
    for source_name in SOURCE_NAMES:
        source = source_dir / source_name
        if not source.exists():
            raise FileNotFoundError(f"Missing Word fusion source: {source}")
        destination = originals_dir / source_name
        shutil.copy2(source, destination)
        source_records.append(
            {
                "name": source_name,
                "source_path": f"assets/templates/reference_originals/word_fusion_sources/{source_name}",
                "retained_path": f"assets/templates/reference_originals/word_fusion_sources/{source_name}",
                "sha256": sha256(destination),
                "size_bytes": destination.stat().st_size,
            }
        )

    return {
        "template_version": "2.6-h1-centered-no-bottom-rule-no-front-matter",
        "generated_on": date.today().isoformat(),
        "base_template": {
            "path": "assets/templates/reference_originals/券商研报模板01.docx",
            "sha256": sha256(base_template),
        },
        "fused_template": {
            "path": "assets/templates/word/energy_market_research_report_template.docx",
            "sha256": sha256(output),
            "size_bytes": output.stat().st_size,
        },
        "source_documents": source_records,
        "chapter_count": len(CHAPTERS),
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
        "chart_theme_id": "kami-broker-v2",
        "centering_contract": {
            "heading_1": "center",
            "heading_1_left_indent_pt": 0,
            "heading_1_right_indent_pt": 0,
            "heading_1_first_line_indent_pt": 0,
            "all_table_text": "center",
            "figure_image": "inline-center",
            "figure_caption": "center",
            "max_figure_width_cm": 15.6,
        },
        "table_text_contract": {
            "font_size_pt": 9,
            "first_line_indent_pt": 0,
            "line_spacing": "single",
            "horizontal_alignment": "center",
            "vertical_alignment": "center"
        },
        "table_visual_contract": {
            "header_fill": f"#{LIGHT_BLUE}",
            "outer_rule_color": f"#{TABLE_OUTER_RULE}",
            "header_rule_color": f"#{TABLE_HEADER_RULE}",
            "top_bottom_line_pt": 1.5,
            "header_line_pt": 1.0,
            "vertical_rules": False,
            "body_internal_horizontal_rules": False
        },
        "data_source_label": "数据来源",
        "formal_pdf_rule": "Direct export from final DOCX only; Pandoc/HTML PDF is not allowed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the fused energy-market Word template.")
    parser.add_argument("--source-dir", required=True, help="Folder containing the five user-provided Word sources.")
    parser.add_argument(
        "--skill-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Root of the staged or installed overseas-energy-market-research Skill.",
    )
    args = parser.parse_args()

    skill_root = Path(args.skill_root).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()
    base_template = skill_root / "assets/templates/reference_originals/券商研报模板01.docx"
    output = skill_root / "assets/templates/word/energy_market_research_report_template.docx"
    originals_dir = skill_root / "assets/templates/reference_originals/word_fusion_sources"
    manifest_path = skill_root / "assets/templates/word/word_template_fusion_manifest.json"

    manifest = build_template(base_template, output, source_dir, originals_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Fused Word template: {output}")
    print(f"Fusion manifest: {manifest_path}")
    print(f"Retained sources: {originals_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
