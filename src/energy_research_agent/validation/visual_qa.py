from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field


class HtmlVisualValidation(BaseModel):
    status: str
    checked_widths: list[int] = Field(default_factory=list)
    screenshot_paths: dict[int, str] = Field(default_factory=dict)
    remote_dependency_count: int = Field(default=0, ge=0)
    broken_inline_image_count: int = Field(default=0, ge=0)
    missing_source_count: int = Field(default=0, ge=0)
    placeholder_count: int = Field(default=0, ge=0)
    findings: list[str] = Field(default_factory=list)


def inspect_html_visual(
    html_path: Path,
    *,
    screenshots: dict[int, Path] | None = None,
    required_widths: tuple[int, ...] = (360, 768, 1440, 1920),
) -> HtmlVisualValidation:
    """Fail closed unless static offline checks and four rendered screenshots exist."""
    text = html_path.read_text(encoding="utf-8")
    screenshots = screenshots or {}
    remote_dependencies = re.findall(r"<(?:script|link|img)\b[^>]+(?:src|href)=[\"']https?://", text, flags=re.I)
    inline_images = re.findall(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", text)
    broken_inline = sum(not payload or len(payload) < 16 for payload in inline_images)
    missing_source = len(re.findall(r"(?:数据来源|分析依据)：?\s*(?:</|$)", text))
    placeholders = len(re.findall(r"\b(?:lorem ipsum|placeholder|TODO|TBD)\b", text, flags=re.I))
    valid_shots = {width: str(path) for width, path in screenshots.items() if width in required_widths and path.is_file() and path.stat().st_size > 0}
    findings: list[str] = []
    if remote_dependencies:
        findings.append("Remote runtime/image/font dependencies are forbidden")
    if broken_inline:
        findings.append(f"Detected {broken_inline} malformed inline image(s)")
    if missing_source:
        findings.append(f"Detected {missing_source} visual source note(s) without content")
    if placeholders:
        findings.append(f"Detected {placeholders} unresolved placeholder token(s)")
    missing_widths = sorted(set(required_widths) - set(valid_shots))
    if missing_widths:
        findings.append("Rendered screenshot QA missing widths: " + ", ".join(map(str, missing_widths)))
    return HtmlVisualValidation(
        status="PASS" if not findings else "BLOCKED",
        checked_widths=sorted(valid_shots), screenshot_paths=valid_shots,
        remote_dependency_count=len(remote_dependencies), broken_inline_image_count=broken_inline,
        missing_source_count=missing_source, placeholder_count=placeholders, findings=findings,
    )


class WordVisualValidation(BaseModel):
    status: str
    page_count: int = Field(ge=0)
    blank_pages: list[int] = Field(default_factory=list)
    oversized_whitespace_pages: list[int] = Field(default_factory=list)
    clipped_block_pages: list[int] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


def inspect_word_render(pdf_path: Path) -> WordVisualValidation:
    """Inspect rendered pages; PDF render is the authority for pagination QA."""
    try:
        import fitz
    except ImportError:
        return WordVisualValidation(status="BLOCKED", page_count=0, findings=["PyMuPDF is required for Word visual QA"])
    document = fitz.open(pdf_path)
    blank, whitespace, clipped = [], [], []
    for index, page in enumerate(document, start=1):
        blocks = page.get_text("blocks")
        drawings = page.get_drawings()
        images = page.get_images(full=True)
        if not blocks and not drawings and not images:
            blank.append(index)
            continue
        occupied = 0.0
        for block in blocks:
            x0, y0, x1, y1 = block[:4]
            occupied += max(0, x1 - x0) * max(0, y1 - y0)
            if x0 < -1 or y0 < -1 or x1 > page.rect.width + 1 or y1 > page.rect.height + 1:
                clipped.append(index)
        ratio = min(1.0, occupied / max(page.rect.width * page.rect.height, 1))
        if ratio < 0.08 and not images:
            whitespace.append(index)
    findings = []
    if blank:
        findings.append("Blank rendered pages: " + ", ".join(map(str, blank)))
    if whitespace:
        findings.append("Pages with oversized whitespace: " + ", ".join(map(str, whitespace)))
    if clipped:
        findings.append("Pages with clipped blocks: " + ", ".join(map(str, sorted(set(clipped)))))
    return WordVisualValidation(status="PASS" if not findings else "BLOCKED", page_count=len(document), blank_pages=blank, oversized_whitespace_pages=whitespace, clipped_block_pages=sorted(set(clipped)), findings=findings)


def write_visual_validation(report: BaseModel, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
