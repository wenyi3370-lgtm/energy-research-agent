from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from _common import Issue, add_common_args, print_report, read_json
from figure_production import OWNER_BY_CLASS, validate_figure_manifest
from scan_office_placeholders import scan_file


REQUIRED_WORD_PIPELINE_ID = "embedded-word-production-v1"
REQUIRED_WORD_COMPONENTS = {
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
}
REQUIRED_CHART_THEME = "kami-broker-v2"
REQUIRED_FIGURE_ROUTING = {
    "market-insight": OWNER_BY_CLASS["market-insight"],
    "modeling": OWNER_BY_CLASS["modeling"],
    "backend": "python",
    "one_owner_per_figure": True,
    "ppt_policy": "reuse-approved-or-embedded-native-slide-visual",
}
REQUIRED_TABLE_HEADER_FILL = "D9E2EC"
REQUIRED_TABLE_OUTER_RULE_COLOR = "000000"
REQUIRED_TABLE_HEADER_RULE_COLOR = "1B365D"
REQUIRED_TABLE_WIDTH_DXA = 8844
TABLE_CAPTION_RE = re.compile(r"^\s*表\s*[0-9一二三四五六七八九十Xx]+[-－—–][0-9Xx]+")
CHAPTER_HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_part_hash(path: Path, part: str) -> str:
    with ZipFile(path) as archive:
        return hashlib.sha256(archive.read(part)).hexdigest()


def package_media_hashes(path: Path) -> set[str]:
    with ZipFile(path) as archive:
        return {
            hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        }


def unresolved_placeholders(path: Path) -> list[str]:
    return sorted({item["entry"] for item in scan_file(path)})


def iter_paragraphs(parent):
    for paragraph in parent.paragraphs:
        yield paragraph
    for table in parent.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from iter_paragraphs(cell)


def is_effectively_centered(paragraph) -> bool:
    if paragraph.alignment is not None:
        return paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    return paragraph.style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER


def is_effectively_true(paragraph, attribute: str) -> bool:
    value = getattr(paragraph.paragraph_format, attribute)
    if value is not None:
        return value is True
    if paragraph.style is None:
        return False
    return getattr(paragraph.style.paragraph_format, attribute) is True


def effective_indent_points(paragraph, attribute: str) -> float:
    """Resolve a paragraph indent through its style chain; absent means zero."""
    value = getattr(paragraph.paragraph_format, attribute)
    if value is not None:
        return value.pt
    style = paragraph.style
    while style is not None:
        value = getattr(style.paragraph_format, attribute)
        if value is not None:
            return value.pt
        style = style.base_style
    return 0.0


def has_zero_heading_indents(paragraph) -> bool:
    return all(
        abs(effective_indent_points(paragraph, attribute)) <= 0.01
        for attribute in ("left_indent", "right_indent", "first_line_indent")
    )


def is_table_caption(paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style is not None else ""
    return style_name == "Table Caption" or bool(TABLE_CAPTION_RE.match(paragraph.text or ""))


def validate_centering_contract(path: Path) -> list[str]:
    document = Document(path)
    problems: list[str] = []
    heading_style = document.styles["Heading 1"]
    if heading_style.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.CENTER:
        problems.append("Heading 1 style is not centered.")
    for attribute in ("left_indent", "right_indent", "first_line_indent"):
        value = getattr(heading_style.paragraph_format, attribute)
        if value is None or abs(value.pt) > 0.01:
            problems.append(f"Heading 1 style {attribute} is not explicitly zero.")
    figure_style = document.styles["Figure Image"]
    if figure_style.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.CENTER:
        problems.append("Figure Image style is not centered.")
    style_spacing = figure_style.paragraph_format.line_spacing
    if (
        figure_style.paragraph_format.line_spacing_rule != WD_LINE_SPACING.SINGLE
        or not isinstance(style_spacing, float)
        or abs(style_spacing - 1.0) > 0.01
    ):
        problems.append("Figure Image style must use single/auto spacing; fixed line height clips charts.")
    caption_style = document.styles["Figure Caption"]
    if caption_style.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.CENTER:
        problems.append("Figure Caption style is not centered.")

    for index, paragraph in enumerate(iter_paragraphs(document), start=1):
        style_name = paragraph.style.name
        is_heading_1 = style_name == "Heading 1" or bool(CHAPTER_HEADING_RE.match(paragraph.text or ""))
        if is_heading_1 and not is_effectively_centered(paragraph):
            problems.append(f"Heading 1 paragraph {index} is not centered.")
        if is_heading_1 and not has_zero_heading_indents(paragraph):
            problems.append(f"Heading 1 paragraph {index} has a non-zero left/right/first-line indent.")
        if style_name == "Figure Caption" and not is_effectively_centered(paragraph):
            problems.append(f"Figure caption paragraph {index} is not centered.")
        if paragraph._p.xpath(".//w:drawing"):
            if not is_effectively_centered(paragraph):
                problems.append(f"Figure paragraph {index} is not centered.")
            if style_name != "Figure Image":
                problems.append(
                    f"Figure paragraph {index} does not use the Figure Image style."
                )
            spacing = paragraph.paragraph_format.line_spacing
            rule = paragraph.paragraph_format.line_spacing_rule
            if rule != WD_LINE_SPACING.SINGLE or not isinstance(spacing, float) or abs(spacing - 1.0) > 0.01:
                problems.append(
                    f"Figure paragraph {index} must use single/auto spacing; fixed line height clips charts."
                )
        if paragraph._p.xpath(".//wp:anchor"):
            problems.append(
                f"Figure paragraph {index} contains a floating anchor; inline figures are required."
            )
    return problems


def validate_table_text_contract(path: Path) -> list[str]:
    """Require direct table formatting so Normal-style body indents cannot leak into cells."""
    document = Document(path)
    problems: list[str] = []
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            for cell_index, cell in enumerate(row.cells, start=1):
                location = f"table {table_index}, row {row_index}, cell {cell_index}"
                if cell.vertical_alignment != WD_ALIGN_VERTICAL.CENTER:
                    problems.append(f"{location} is not vertically centered.")
                for paragraph_index, paragraph in enumerate(cell.paragraphs, start=1):
                    p_location = f"{location}, paragraph {paragraph_index}"
                    if paragraph.alignment != WD_ALIGN_PARAGRAPH.CENTER:
                        problems.append(f"{p_location} is not horizontally centered.")
                    indent = paragraph.paragraph_format.first_line_indent
                    if indent is None or abs(indent.pt) > 0.01:
                        problems.append(f"{p_location} does not have zero first-line indent.")
                    spacing = paragraph.paragraph_format.line_spacing
                    if not isinstance(spacing, float) or abs(spacing - 1.0) > 0.01:
                        problems.append(f"{p_location} is not single-spaced.")
                    for run_index, run in enumerate(paragraph.runs, start=1):
                        if not run.text:
                            continue
                        if run.font.size is None or abs(run.font.size.pt - 9.0) > 0.01:
                            problems.append(
                                f"{p_location}, run {run_index} is not 9 pt (小五)."
                            )
    return problems


def validate_table_visual_contract(path: Path) -> list[str]:
    """Require black outer rules, a blue header rule, and blue-shaded headers."""
    document = Document(path)
    problems: list[str] = []
    for table_index, table in enumerate(document.tables, start=1):
        borders = table._tbl.tblPr.find(qn("w:tblBorders"))
        if borders is None:
            problems.append(f"table {table_index} has no direct three-line border definition.")
            continue
        for edge in ("top", "bottom"):
            element = borders.find(qn(f"w:{edge}"))
            if element is None or element.get(qn("w:val")) != "single":
                problems.append(f"table {table_index} {edge} rule is missing or not single.")
                continue
            if element.get(qn("w:sz")) != "12":
                problems.append(f"table {table_index} {edge} rule is not 1.5 pt.")
            if (element.get(qn("w:color")) or "").upper() != REQUIRED_TABLE_OUTER_RULE_COLOR:
                problems.append(
                    f"table {table_index} {edge} rule color is not #{REQUIRED_TABLE_OUTER_RULE_COLOR}."
                )
        for edge in ("left", "right", "insideH", "insideV"):
            element = borders.find(qn(f"w:{edge}"))
            if element is None or element.get(qn("w:val")) not in {"none", "nil"}:
                problems.append(f"table {table_index} contains a forbidden {edge} rule.")

        if not table.rows:
            continue
        for cell_index, cell in enumerate(table.rows[0].cells, start=1):
            tc_pr = cell._tc.get_or_add_tcPr()
            shading = tc_pr.find(qn("w:shd"))
            fill = "" if shading is None else (shading.get(qn("w:fill")) or "").upper()
            if fill != REQUIRED_TABLE_HEADER_FILL:
                problems.append(
                    f"table {table_index} header cell {cell_index} fill is not #{REQUIRED_TABLE_HEADER_FILL}."
                )
            # 表头文字必须深蓝 #1B365D（2026-08-07 教训固化：曾 T3-T16 表头黑字）
            for para in cell.paragraphs:
                for run in para.runs:
                    r_pr = run._element.find(qn("w:rPr"))
                    color = None if r_pr is None else r_pr.find(qn("w:color"))
                    if color is None or (color.get(qn("w:val")) or "").upper() != REQUIRED_TABLE_HEADER_RULE_COLOR:
                        problems.append(
                            f"table {table_index} header cell {cell_index} text color is not "
                            f"#{REQUIRED_TABLE_HEADER_RULE_COLOR}."
                        )
            tc_borders = tc_pr.find(qn("w:tcBorders"))
            bottom = None if tc_borders is None else tc_borders.find(qn("w:bottom"))
            if bottom is None or bottom.get(qn("w:val")) != "single":
                problems.append(f"table {table_index} header cell {cell_index} bottom rule is missing.")
            else:
                if bottom.get(qn("w:sz")) != "8":
                    problems.append(f"table {table_index} header cell {cell_index} bottom rule is not 1 pt.")
                if (bottom.get(qn("w:color")) or "").upper() != REQUIRED_TABLE_HEADER_RULE_COLOR:
                    problems.append(
                        f"table {table_index} header cell {cell_index} bottom rule color is not #{REQUIRED_TABLE_HEADER_RULE_COLOR}."
                    )
            if tc_borders is not None:
                for edge in ("top", "left", "right"):
                    element = tc_borders.find(qn(f"w:{edge}"))
                    if element is None or element.get(qn("w:val")) not in {"none", "nil"}:
                        problems.append(
                            f"table {table_index} header cell {cell_index} contains a forbidden {edge} rule."
                        )
        for row_index, row in enumerate(table.rows[1:], start=2):
            for cell_index, cell in enumerate(row.cells, start=1):
                tc_pr = cell._tc.get_or_add_tcPr()
                shading = tc_pr.find(qn("w:shd"))
                fill = "" if shading is None else (shading.get(qn("w:fill")) or "").upper()
                if fill not in {"", "AUTO", "FFFFFF"}:
                    problems.append(
                        f"table {table_index} body row {row_index} cell {cell_index} has fill #{fill}; body must stay white."
                    )
                tc_borders = tc_pr.find(qn("w:tcBorders"))
                for edge in ("top", "left", "right", "bottom"):
                    element = None if tc_borders is None else tc_borders.find(qn(f"w:{edge}"))
                    if element is None or element.get(qn("w:val")) not in {"none", "nil"}:
                        problems.append(
                            f"table {table_index} body row {row_index} cell {cell_index} contains a forbidden {edge} rule."
                        )
    return problems


def validate_table_caption_pagination_contract(path: Path) -> list[str]:
    """Require centered table titles with keepNext/keepLines to prevent orphan captions."""
    document = Document(path)
    problems: list[str] = []
    try:
        style = document.styles["Table Caption"]
        if style.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.CENTER:
            problems.append("Table Caption style is not centered.")
        if style.paragraph_format.keep_with_next is not True:
            problems.append("Table Caption style does not set keep_with_next=true.")
        if style.paragraph_format.keep_together is not True:
            problems.append("Table Caption style does not set keep_together=true.")
    except KeyError:
        problems.append("Table Caption style is missing.")

    for index, paragraph in enumerate(document.paragraphs, start=1):
        if not is_table_caption(paragraph):
            continue
        if not is_effectively_centered(paragraph):
            problems.append(f"Table caption paragraph {index} is not centered.")
        if not is_effectively_true(paragraph, "keep_with_next"):
            problems.append(f"Table caption paragraph {index} does not keep with the following table.")
        if not is_effectively_true(paragraph, "keep_together"):
            problems.append(f"Table caption paragraph {index} does not keep its lines together.")

    # Structural contract: every body table has exactly one immediately
    # preceding caption, and a caption must belong to exactly one table.
    blocks = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            style_name = paragraph.style.name if paragraph.style is not None else ""
            if is_table_caption(paragraph):
                kind = "caption"
            elif style_name == "Heading 1" or CHAPTER_HEADING_RE.match(paragraph.text or ""):
                kind = "heading"
            else:
                kind = "paragraph"
            blocks.append((kind, paragraph))
        elif child.tag == qn("w:tbl"):
            blocks.append(("table", Table(child, document)))
    report_started = False
    for index, (kind, item) in enumerate(blocks):
        if kind == "heading":
            report_started = True
        if kind == "caption":
            if index + 1 >= len(blocks) or blocks[index + 1][0] != "table":
                problems.append(f"Orphan or duplicate table caption is not immediately followed by a table: {item.text.strip()!r}.")
        elif kind == "table":
            if not report_started:
                continue  # cover/control tables intentionally have no caption
            if index == 0 or blocks[index - 1][0] != "caption":
                problems.append(f"Report table at block {index + 1} has no unique immediately preceding caption.")
    caption_numbers = [
        f"表{match.group(1)}-{match.group(2)}"
        for kind, item in blocks
        if kind == "caption" and (match := re.match(r"^\s*表\s*(\d+)[-－—–](\d+)", item.text or ""))
    ]
    duplicates = sorted({number for number in caption_numbers if caption_numbers.count(number) > 1})
    if duplicates:
        problems.append("Duplicate table caption numbers: " + ", ".join(duplicates) + ".")
    return problems


def validate_table_geometry_contract(path: Path) -> list[str]:
    """Require 15.6 cm DXA geometry, matching grids/cells, and repeating headers."""
    document = Document(path)
    problems: list[str] = []
    for table_index, table in enumerate(document.tables, start=1):
        tblW = table._tbl.tblPr.find(qn("w:tblW"))
        if tblW is None or tblW.get(qn("w:type")) != "dxa" or tblW.get(qn("w:w")) != str(REQUIRED_TABLE_WIDTH_DXA):
            problems.append(f"table {table_index} width is not {REQUIRED_TABLE_WIDTH_DXA} DXA (15.6 cm).")
        grid_widths = [int(col.get(qn("w:w")) or 0) for col in table._tbl.tblGrid.gridCol_lst]
        if len(grid_widths) != len(table.columns) or sum(grid_widths) != REQUIRED_TABLE_WIDTH_DXA:
            problems.append(f"table {table_index} grid widths do not reconcile to 15.6 cm.")
            continue
        if table.rows:
            trPr = table.rows[0]._tr.get_or_add_trPr()
            repeat = trPr.find(qn("w:tblHeader"))
            if repeat is None or (repeat.get(qn("w:val")) or "true").lower() not in {"true", "1", "on"}:
                problems.append(f"table {table_index} header row is not marked to repeat.")
        for row_index, row in enumerate(table.rows, start=1):
            for column_index, cell in enumerate(row.cells):
                tcW = cell._tc.get_or_add_tcPr().find(qn("w:tcW"))
                expected = grid_widths[min(column_index, len(grid_widths) - 1)]
                if tcW is None or tcW.get(qn("w:type")) != "dxa" or int(tcW.get(qn("w:w")) or 0) != expected:
                    problems.append(f"table {table_index}, row {row_index}, cell {column_index + 1} width does not match tblGrid.")
    return problems


def validate_data_source_label(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        xml_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        )
    problems: list[str] = []
    if "资料来源：" in xml_text or "数来源：" in xml_text:
        problems.append("Source notes must use 数据来源：, not 资料来源： or 数来源：.")
    return problems


def validate(project_dir: Path, skill_root: Path, *, allow_draft: bool) -> list[Issue]:
    issues: list[Issue] = []
    manifest_path = project_dir / "deliverables" / "word_production_manifest.json"
    if not manifest_path.exists():
        level = "warn" if allow_draft else "fail"
        return [
            Issue(
                level,
                "word-delivery",
                "word_production_manifest",
                f"Missing {manifest_path}; copy assets/templates/json/word_production_manifest_template.json and complete it.",
            )
        ]

    manifest = read_json(manifest_path, {})
    fusion_manifest_path = (
        skill_root / "assets/templates/word/word_template_fusion_manifest.json"
    )
    if not fusion_manifest_path.exists():
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "fusion_manifest",
                f"Missing fused-template manifest: {fusion_manifest_path}",
            )
        )
        return issues
    fusion_manifest = json.loads(fusion_manifest_path.read_text(encoding="utf-8"))
    template_path = skill_root / "assets/templates/word/energy_market_research_report_template.docx"
    expected_template_hash = fusion_manifest["fused_template"]["sha256"]

    if manifest.get("template_sha256") != expected_template_hash:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "template_sha256",
                "Word production manifest does not match the installed fused template.",
            )
        )
    if not manifest.get("template_lineage_verified"):
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "template_lineage_verified",
                "Template lineage must be verified before final delivery.",
            )
        )

    if manifest.get("word_pipeline_id") != REQUIRED_WORD_PIPELINE_ID:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "word_pipeline_id",
                f"Word production must use {REQUIRED_WORD_PIPELINE_ID}; external Word Skills are not runtime dependencies.",
            )
        )
    components = set(manifest.get("word_components") or [])
    missing_components = sorted(REQUIRED_WORD_COMPONENTS - components)
    if missing_components:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "word_components",
                f"Embedded Word pipeline is incomplete: {', '.join(missing_components)}",
            )
        )

    final_path_raw = str(manifest.get("final_docx_path") or "").strip()
    if not final_path_raw:
        issues.append(
            Issue("fail", "word-delivery", "final_docx_path", "Final DOCX path is empty.")
        )
        return issues
    final_docx = Path(final_path_raw)
    if not final_docx.is_absolute():
        final_docx = project_dir / final_docx
    if not final_docx.exists():
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "final_docx_path",
                f"Final DOCX does not exist: {final_docx}",
            )
        )
        return issues

    actual_final_hash = sha256(final_docx)
    if manifest.get("final_docx_sha256") != actual_final_hash:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "final_docx_sha256",
                "Final DOCX hash differs from the production manifest.",
            )
        )
    if package_part_hash(final_docx, "word/theme/theme1.xml") != package_part_hash(
        template_path, "word/theme/theme1.xml"
    ):
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "template_theme",
                "Final DOCX does not retain the fused template theme lineage.",
            )
        )
    centering_problems = validate_centering_contract(final_docx)
    if centering_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "centering_contract",
                " ".join(centering_problems),
            )
        )
    table_problems = validate_table_text_contract(final_docx)
    if table_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_text_contract",
                " ".join(table_problems),
            )
        )
    table_visual_problems = validate_table_visual_contract(final_docx)
    if table_visual_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_visual_contract",
                " ".join(table_visual_problems),
            )
        )
    table_caption_problems = validate_table_caption_pagination_contract(final_docx)
    if table_caption_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_caption_pagination_contract",
                " ".join(table_caption_problems),
            )
        )
    table_geometry_problems = validate_table_geometry_contract(final_docx)
    if table_geometry_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_geometry_contract",
                " ".join(table_geometry_problems),
            )
        )
    data_source_problems = validate_data_source_label(final_docx)
    if data_source_problems:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "data_source_label",
                " ".join(data_source_problems),
            )
        )
    if manifest.get("chart_theme_id") != REQUIRED_CHART_THEME:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "chart_theme_id",
                f"Word production must record chart_theme_id={REQUIRED_CHART_THEME}.",
            )
        )
    routing = manifest.get("figure_routing") or {}
    for key, expected in REQUIRED_FIGURE_ROUTING.items():
        if routing.get(key) != expected:
            issues.append(
                Issue(
                    "fail" if not allow_draft else "warn",
                    "word-delivery",
                    f"figure_routing.{key}",
                    f"Figure routing must record {key}={expected!r}.",
                )
            )

    figure_manifests = manifest.get("figure_theme_manifests") or []
    if not figure_manifests:
        issues.append(
            Issue(
                "fail" if not allow_draft else "warn",
                "word-delivery",
                "figure_theme_manifests",
                "Final Word delivery must list the per-figure .theme.json manifests.",
            )
        )
    embedded_media_hashes = package_media_hashes(final_docx)
    for raw_path in figure_manifests:
        figure_manifest_path = Path(str(raw_path))
        if not figure_manifest_path.is_absolute():
            figure_manifest_path = project_dir / figure_manifest_path
        if not figure_manifest_path.exists():
            issues.append(Issue("fail", str(raw_path), "figure_manifest", "Figure manifest is missing."))
            continue
        for figure_issue in validate_figure_manifest(
            figure_manifest_path,
            project_dir=project_dir,
            final=not allow_draft,
        ):
            issues.append(
                Issue(
                    figure_issue["level"],
                    str(raw_path),
                    f"figure.{figure_issue['field']}",
                    figure_issue["message"],
                )
            )
        figure_manifest = read_json(figure_manifest_path, {})
        output_hashes = {
            record.get("sha256")
            for record in (figure_manifest.get("outputs") or {}).values()
            if isinstance(record, dict) and record.get("sha256")
        }
        if output_hashes and not (output_hashes & embedded_media_hashes):
            issues.append(
                Issue(
                    "fail" if not allow_draft else "warn",
                    str(raw_path),
                    "figure.embedding",
                    "Neither the approved SVG nor PNG output is embedded in the final DOCX media package.",
                )
            )
    if not manifest.get("heading_1_centered"):
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "heading_1_centered",
                "Word production manifest must confirm centered Heading 1 paragraphs.",
            )
        )
    for key in (
        "heading_1_left_indent_pt",
        "heading_1_right_indent_pt",
        "heading_1_first_line_indent_pt",
    ):
        if manifest.get(key) != 0:
            issues.append(
                Issue(
                    "fail",
                    "word-delivery",
                    key,
                    f"Word production manifest must record {key}=0.",
                )
            )
    if not manifest.get("table_text_centered"):
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_text_centered",
                "Word production manifest must confirm all table text is centered.",
            )
        )
    if manifest.get("table_font_size_pt") != 9:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_font_size_pt",
                "Word production manifest must record table_font_size_pt=9.",
            )
        )
    if manifest.get("table_first_line_indent_pt") != 0:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_first_line_indent_pt",
                "Word production manifest must record table_first_line_indent_pt=0.",
            )
        )
    if manifest.get("table_line_spacing") != "single":
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_line_spacing",
                "Word production manifest must record table_line_spacing=single.",
            )
        )
    if not manifest.get("table_three_line_verified"):
        issues.append(
            Issue("fail", "word-delivery", "table_three_line_verified", "Manifest must confirm the three-line table contract.")
        )
    if manifest.get("table_header_fill") != f"#{REQUIRED_TABLE_HEADER_FILL}":
        issues.append(
            Issue("fail", "word-delivery", "table_header_fill", f"Manifest must record table_header_fill=#{REQUIRED_TABLE_HEADER_FILL}.")
        )
    if manifest.get("table_outer_rule_color") != f"#{REQUIRED_TABLE_OUTER_RULE_COLOR}":
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_outer_rule_color",
                f"Manifest must record table_outer_rule_color=#{REQUIRED_TABLE_OUTER_RULE_COLOR}.",
            )
        )
    if manifest.get("table_header_rule_color") != f"#{REQUIRED_TABLE_HEADER_RULE_COLOR}":
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "table_header_rule_color",
                f"Manifest must record table_header_rule_color=#{REQUIRED_TABLE_HEADER_RULE_COLOR}.",
            )
        )
    if manifest.get("table_top_bottom_line_pt") != 1.5:
        issues.append(
            Issue("fail", "word-delivery", "table_top_bottom_line_pt", "Manifest must record 1.5 pt top/bottom rules.")
        )
    if manifest.get("table_header_line_pt") != 1.0:
        issues.append(
            Issue("fail", "word-delivery", "table_header_line_pt", "Manifest must record a 1.0 pt header rule.")
        )
    if manifest.get("table_width_cm") != 15.6:
        issues.append(Issue("fail", "word-delivery", "table_width_cm", "Manifest must record table_width_cm=15.6."))
    if not manifest.get("table_header_repeat"):
        issues.append(Issue("fail", "word-delivery", "table_header_repeat", "Manifest must confirm repeating table headers."))
    if manifest.get("data_source_label") != "数据来源":
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "data_source_label",
                "Word production manifest must record data_source_label=数据来源.",
            )
        )
    if not manifest.get("figures_inline_and_centered"):
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "figures_inline_and_centered",
                "Word production manifest must confirm inline and centered figures.",
            )
        )
    placeholder_parts = unresolved_placeholders(final_docx)
    if placeholder_parts:
        issues.append(
            Issue(
                "fail",
                "word-delivery",
                "placeholders",
                "Unresolved Word template placeholders remain in: "
                + ", ".join(placeholder_parts),
            )
        )

    rendering = manifest.get("rendering") or {}
    if not allow_draft:
        if rendering.get("status") != "passed":
            issues.append(
                Issue(
                    "fail",
                    "word-delivery",
                    "rendering.status",
                    "Final DOCX must pass the embedded LibreOffice/PyMuPDF render and page inspection.",
                )
            )
        page_count = int(rendering.get("page_count") or 0)
        inspected = int(rendering.get("pages_inspected") or 0)
        if page_count <= 0 or inspected != page_count:
            issues.append(
                Issue(
                    "fail",
                    "word-delivery",
                    "rendering.pages_inspected",
                    "Every rendered DOCX page must be inspected.",
                )
            )

    pdf = manifest.get("pdf") or {}
    if pdf.get("delivered"):
        if not pdf.get("direct_export_from_final_docx"):
            issues.append(
                Issue(
                    "fail",
                    "word-delivery",
                    "pdf.direct_export_from_final_docx",
                    "Formal PDF must be exported directly from the final DOCX.",
                )
            )
        if not pdf.get("cross_format_consistency_passed"):
            issues.append(
                Issue(
                    "fail",
                    "word-delivery",
                    "pdf.cross_format_consistency_passed",
                    "Delivered PDF must pass DOCX/PDF consistency checks.",
                )
            )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the embedded Word production manifest and final DOCX.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    add_common_args(parser)
    args = parser.parse_args()
    return print_report(
        "Word delivery validation",
        validate(
            Path(args.project_dir).resolve(),
            Path(__file__).resolve().parents[1],
            allow_draft=args.mode == "draft",
        ),
        json_output=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
