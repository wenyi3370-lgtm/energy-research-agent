from __future__ import annotations

import re
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pydantic import BaseModel, Field


class WordDepthResult(BaseModel):
    status: str
    character_count: int = Field(ge=0)
    rendered_pages: int | None = Field(default=None, ge=0)
    heading_1_count: int = Field(default=0, ge=0)
    heading_2_count: int = Field(default=0, ge=0)
    tables: int = Field(default=0, ge=0)
    figures: int = Field(default=0, ge=0)
    embedded_images: int = Field(default=0, ge=0)
    figure_source_notes: int = Field(default=0, ge=0)
    visual_family_count: int = Field(default=0, ge=0)
    bar_family_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    three_line_table_count: int = Field(default=0, ge=0)
    selected_evidence_images: int = Field(default=0, ge=0)
    evidence_image_captions: int = Field(default=0, ge=0)
    evidence_image_source_notes: int = Field(default=0, ge=0)
    core_chapter_visual_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    visuals_per_rendered_page: float = Field(default=0.0, ge=0.0)
    findings: list[str] = Field(default_factory=list)


def count_pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page\b", data))


def inspect_word_depth(
    docx_path: Path,
    *,
    rendered_pdf: Path | None = None,
    min_characters: int = 15_000,
    min_pages: int = 30,
    min_heading_1: int = 13,
    min_figures: int = 0,
    min_visual_families: int = 0,
    max_bar_family_ratio: float = 0.75,
    visual_manifest: Path | None = None,
    image_manifest: Path | None = None,
) -> WordDepthResult:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(docx_path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = root.findall(".//w:body/w:p", ns)
    text = "".join("".join(node.text or "" for node in p.findall(".//w:t", ns)) for p in paragraphs)
    characters = len(re.sub(r"\s+", "", text))
    heading_1 = heading_2 = figures = figure_source_notes = evidence_image_captions = evidence_image_source_notes = 0
    for paragraph in paragraphs:
        style = paragraph.find("./w:pPr/w:pStyle", ns)
        style_value = style.get(f"{{{ns['w']}}}val") if style is not None else ""
        if style_value in {"Heading1", "1"}:
            heading_1 += 1
        elif style_value in {"Heading2", "2"}:
            heading_2 += 1
        paragraph_text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns)).strip()
        if re.match(r"^图\s*\d+[-－—]\d+", paragraph_text):
            figures += 1
        if paragraph_text.startswith("数据来源："):
            figure_source_notes += 1
        if re.match(r"^图\s*\d+-P\d+", paragraph_text):
            evidence_image_captions += 1
        if paragraph_text.startswith("图片来源："):
            evidence_image_source_notes += 1
    tables = len(root.findall(".//w:tbl", ns))
    embedded_images = len(root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"))
    three_line_tables = 0
    for table in root.findall(".//w:tbl", ns):
        borders = table.find("./w:tblPr/w:tblBorders", ns)
        if borders is None:
            continue
        top = borders.find("./w:top", ns)
        bottom = borders.find("./w:bottom", ns)
        inside_v = borders.find("./w:insideV", ns)
        if top is not None and bottom is not None and inside_v is not None and inside_v.get(f"{{{ns['w']}}}val") == "nil":
            three_line_tables += 1
    if visual_manifest is None:
        candidate = docx_path.parent / f"{docx_path.stem}_assets" / "visual_manifest.json"
        visual_manifest = candidate if candidate.is_file() else None
    families: list[str] = []
    visual_chapters: set[str] = set()
    if visual_manifest and visual_manifest.is_file():
        payload = json.loads(visual_manifest.read_text(encoding="utf-8"))
        families = [str(item.get("family", "")) for item in payload.get("visuals", []) if item.get("family")]
        visual_chapters = {str(item.get("chapter_key")) for item in payload.get("visuals", []) if item.get("chapter_key")}
    visual_family_count = len(set(families))
    bar_family_ratio = (sum(family == "horizontal_bar" for family in families) / len(families)) if families else 0.0
    if image_manifest is None:
        candidate = docx_path.parent / f"{docx_path.stem}_assets" / "image_publication_manifest.json"
        image_manifest = candidate if candidate.is_file() else None
    selected_evidence_images = 0
    selected_cover_images = 0
    if image_manifest and image_manifest.is_file():
        image_payload = json.loads(image_manifest.read_text(encoding="utf-8"))
        selected_ids = image_payload.get("artifact_selections", {}).get("word", [])
        prepared_by_id = {item.get("image_id"): item for item in image_payload.get("prepared_images", [])}
        selected_evidence_images = len(selected_ids)
        selected_cover_images = sum(prepared_by_id.get(image_id, {}).get("chapter_key") == "cover" for image_id in selected_ids)
    rendered_pages = count_pdf_pages(rendered_pdf) if rendered_pdf and rendered_pdf.is_file() else None
    core_chapters = {
        "executive_summary", "research_scope", "entity_overview", "products", "factories",
        "operating_metrics", "core_evidence", "energy", "epc", "zero_carbon", "storage_odm",
        "overseas", "cooperation", "roadmap", "risks", "conclusion",
    }
    core_coverage = len(core_chapters & visual_chapters) / len(core_chapters)
    visuals_per_page = len(families) / rendered_pages if rendered_pages else 0.0
    findings: list[str] = []
    if characters < min_characters:
        findings.append(f"Report has {characters} non-whitespace characters; minimum is {min_characters}")
    if rendered_pages is None:
        findings.append("Rendered PDF is required for the page-count and pagination gate")
    elif rendered_pages < min_pages:
        findings.append(f"Rendered report has {rendered_pages} pages; minimum is {min_pages}")
    if heading_1 < min_heading_1:
        findings.append(f"Report has {heading_1} Heading 1 sections; minimum is {min_heading_1}")
    if figures < min_figures or embedded_images < min_figures:
        findings.append(f"Report requires at least {min_figures} formal figures; found {figures} captions and {embedded_images} embedded images")
    if figure_source_notes < figures:
        findings.append("Every formal figure requires an adjacent data-source note")
    if visual_family_count < min_visual_families:
        findings.append(f"Visual manifest requires at least {min_visual_families} families; found {visual_family_count}")
    if bar_family_ratio > max_bar_family_ratio:
        findings.append(f"Bar-family ratio {bar_family_ratio:.1%} exceeds {max_bar_family_ratio:.0%}")
    if tables and three_line_tables < tables:
        findings.append("Every formal Word table must use the three-line table contract")
    if selected_evidence_images and embedded_images < figures + selected_evidence_images:
        findings.append("Every selected verified evidence image must be embedded in the Word package")
    expected_gallery_images = selected_evidence_images - selected_cover_images
    if evidence_image_captions < expected_gallery_images or evidence_image_source_notes < expected_gallery_images:
        findings.append("Every non-cover evidence image requires an adjacent caption and original-page source note")
    return WordDepthResult(
        status="PASS" if not findings else "BLOCKED",
        character_count=characters,
        rendered_pages=rendered_pages,
        heading_1_count=heading_1,
        heading_2_count=heading_2,
        tables=tables,
        figures=figures,
        embedded_images=embedded_images,
        figure_source_notes=figure_source_notes,
        visual_family_count=visual_family_count,
        bar_family_ratio=bar_family_ratio,
        three_line_table_count=three_line_tables,
        selected_evidence_images=selected_evidence_images,
        evidence_image_captions=evidence_image_captions,
        evidence_image_source_notes=evidence_image_source_notes,
        core_chapter_visual_coverage=core_coverage,
        visuals_per_rendered_page=visuals_per_page,
        findings=findings,
    )


class PptVisualDeliveryRecord(BaseModel):
    slide_count: int = Field(ge=0)
    rendered_slide_count: int = Field(ge=0)
    all_pages_inspected: bool = False
    contact_sheet_exists: bool = False
    visual_fix_cycle_count: int = Field(default=0, ge=0)
    action_title_count: int = Field(default=0, ge=0)
    visual_slide_count: int = Field(default=0, ge=0)
    sourced_slide_count: int = Field(default=0, ge=0)
    layout_family_count: int = Field(default=0, ge=0)
    overflow_count: int = Field(default=0, ge=0)
    placeholder_count: int = Field(default=0, ge=0)
    storyline_exists: bool = False
    evidence_map_exists: bool = False
    maximum_consecutive_same_layout: int = Field(default=0, ge=0)
    wrapped_kpi_unit_count: int = Field(default=0, ge=0)
    wrapped_page_number_count: int = Field(default=0, ge=0)
    overlap_over_3pt_count: int = Field(default=0, ge=0)
    chart_font_below_8pt_count: int = Field(default=0, ge=0)
    full_rerender_after_fix: bool = False
    required_verified_image_count: int = Field(default=0, ge=0)
    embedded_verified_image_count: int = Field(default=0, ge=0)
    image_caption_source_count: int = Field(default=0, ge=0)


def inspect_ppt_visual_delivery(record: PptVisualDeliveryRecord) -> list[str]:
    findings: list[str] = []
    if not 15 <= record.slide_count <= 20:
        findings.append("PPT must contain 15-20 slides")
    if record.rendered_slide_count != record.slide_count:
        findings.append("Every slide must have a final render")
    if not record.all_pages_inspected or not record.contact_sheet_exists:
        findings.append("A contact sheet and explicit all-slide visual inspection are required")
    if record.visual_fix_cycle_count < 1:
        findings.append("At least one visual fix and full rerender cycle is required")
    if record.action_title_count < max(record.slide_count - 2, 0):
        findings.append("All substantive slides require answer-first action titles")
    if record.visual_slide_count != record.slide_count:
        findings.append("Text-only slides are not allowed")
    if record.sourced_slide_count < max(record.slide_count - 1, 0):
        findings.append("Every substantive slide requires source/date/bias context")
    if record.layout_family_count < 4:
        findings.append("Use at least four layout families to avoid repetitive card grids")
    if not record.storyline_exists or not record.evidence_map_exists:
        findings.append("PPT requires both storyline.json and presentation_evidence_map.json")
    if record.maximum_consecutive_same_layout > 2:
        findings.append("The same layout family may not appear on three consecutive slides")
    if record.wrapped_kpi_unit_count:
        findings.append(f"Detected {record.wrapped_kpi_unit_count} wrapped KPI value/unit pairs")
    if record.wrapped_page_number_count:
        findings.append(f"Detected {record.wrapped_page_number_count} wrapped page numbers or badges")
    if record.overlap_over_3pt_count:
        findings.append(f"Detected {record.overlap_over_3pt_count} text/shape overlaps greater than 3 pt")
    if record.chart_font_below_8pt_count:
        findings.append(f"Detected {record.chart_font_below_8pt_count} chart labels below 8 pt")
    if record.visual_fix_cycle_count >= 1 and not record.full_rerender_after_fix:
        findings.append("A visual fix must be followed by a full-deck rerender")
    if record.embedded_verified_image_count != record.required_verified_image_count:
        findings.append("Every selected verified image must be embedded in its contracted PPT chapter")
    if record.image_caption_source_count < record.required_verified_image_count:
        findings.append("Every selected verified PPT image requires a caption and source-page reference")
    if record.overflow_count:
        findings.append(f"Detected {record.overflow_count} overflow or clipping issues")
    if record.placeholder_count:
        findings.append(f"Detected {record.placeholder_count} unresolved placeholders")
    return findings
