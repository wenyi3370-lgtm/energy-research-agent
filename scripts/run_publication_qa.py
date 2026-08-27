from __future__ import annotations

"""Final Word/HTML render, inspect, fix and rerender workflow."""

import argparse
import json
import locale
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from energy_research_agent.validation.consulting_narrative import (
    PublicationVisibleTextValidator, TOCValidator,
)
from energy_research_agent.validation.visual_qa import inspect_word_render


NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % NS


def find_soffice() -> Path:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    candidates = [
        Path(found) if found else None,
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        # Windows resolves the bare name through PATHEXT and can hand us the
        # soffice.COM shim; the real binary is the .exe next to it.
        if candidate.suffix.lower() == ".com" and candidate.with_suffix(".exe").is_file():
            candidate = candidate.with_suffix(".exe")
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("LibreOffice was not found")


def convert(source: Path, destination: Path, fmt: str, soffice: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(soffice), "--headless", "--convert-to", fmt, "--outdir", str(destination), str(source)],
        capture_output=True, text=True, timeout=300,
    )
    expected = destination / f"{source.stem}.{fmt.split(':', 1)[0]}"
    if completed.returncode or not expected.is_file():
        raise RuntimeError(f"LibreOffice conversion failed: {completed.stdout}\n{completed.stderr}")
    return expected


def refresh_docx(path: Path, soffice: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="eer-lo-refresh-") as temp:
        refreshed = convert(path, Path(temp), "docx", soffice)
        shutil.copy2(refreshed, path)


def _lo_profile_dir() -> Path | None:
    """LibreOffice user profile (for the headless TOC-update macro)."""
    import os
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "LibreOffice" / "4" / "user",
        Path.home() / "AppData" / "Roaming" / "LibreOffice" / "4" / "user",
        Path.home() / ".config" / "libreoffice" / "4" / "user",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def update_toc_via_macro(docx: Path, soffice: Path) -> bool:
    """Let LibreOffice update the TOC field with REAL page numbers.

    The PDF text in this environment is not extractable (embedded CJK fonts
    lack ToUnicode maps), so page numbers cannot be recovered from the PDF.
    LibreOffice itself knows the pagination: a headless Basic macro opens
    the document, updates the document indexes (TOC 1/2/3 styles, which we
    defined LEFT-aligned with dot leaders) and stores it back.
    """
    profile = _lo_profile_dir()
    if profile is None:
        return False
    library_dir = profile / "basic" / "Standard"
    library_dir.mkdir(parents=True, exist_ok=True)
    macro = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">\n'
        '<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">\n'
        'Sub UpdateTOC()\n'
        '  Dim oDesktop, oDoc, oArgs(0) As New com.sun.star.beans.PropertyValue\n'
        '  oDesktop = createUnoService("com.sun.star.frame.Desktop")\n'
        '  oArgs(0).Name = "Hidden" : oArgs(0).Value = True\n'
        f'  oDoc = oDesktop.loadComponentFromURL(ConvertToURL("{docx.as_posix()}"), "_blank", 0, oArgs())\n'
        '  oDoc.refresh()\n'
        '  Dim i As Integer\n'
        '  For i = 0 To oDoc.getDocumentIndexes().getCount() - 1\n'
        '    oDoc.getDocumentIndexes().getByIndex(i).update()\n'
        '  Next i\n'
        '  oDoc.store()\n'
        '  oDoc.close(False)\n'
        'End Sub\n'
        '</script:module>\n'
    )
    (library_dir / "Module1.xba").write_text(macro, encoding="utf-8")
    (library_dir / "script.xlb").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">\n'
        '<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">\n'
        '<library:element library:name="Module1"/>\n'
        '</library:library>\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(soffice), "--headless", "--norestore", "--invisible",
            "vnd.sun.star.script:Standard.Module1.UpdateTOC?language=Basic&location=application",
        ],
        capture_output=True, text=True, timeout=180,
    )
    if completed.returncode:
        return False
    # A successful update materializes TOC text paragraphs into the docx.
    with zipfile.ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    return "TOC" in xml and len(re.findall(r"Contents \d|TOC\d", xml)) > 0


def docx_heading_text(path: Path) -> list[str]:
    """Heading 1 texts in document order (compat helper)."""
    return [text for text, level in docx_heading_levels(path) if level == 1]


def docx_heading_levels(path: Path) -> list[tuple[str, int]]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    entries: list[tuple[str, int]] = []
    style_levels = (
        ("Heading1", 1), ("Heading 1", 1), ("1", 1),
        ("Heading2", 2), ("Heading 2", 2), ("2", 2),
        ("Heading3", 3), ("Heading 3", 3), ("3", 3),
    )
    for paragraph in root.findall(f".//{W}body/{W}p"):
        instruction = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instruction.strip().startswith("TOC"):
            continue
        style = paragraph.find(f"./{W}pPr/{W}pStyle")
        value = style.get(W + "val") if style is not None else ""
        level = next((level for name, level in style_levels if value == name), None)
        if level is None:
            continue
        text = "".join(node.text or "" for node in paragraph.findall(f".//{W}t")).strip()
        if text and text != "目录":
            entries.append((text, level))
    return entries


def heading_page_map(pdf_path: Path, headings: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
    completed = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, timeout=120)
    try:
        decoded = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        decoded = completed.stdout.decode(encoding if encoding.lower() != "utf-8" else "gb18030", errors="replace")
    pages = decoded.split("\f")
    entries = []
    for heading, level in headings:
        normalized = re.sub(r"\s+", "", heading)
        # A refreshed office document may already show a generated TOC.  The
        # first occurrence is then the TOC itself; the last occurrence is the
        # real body heading whose final page number must be published.
        matches = [index for index, text in enumerate(pages, start=1) if normalized in re.sub(r"\s+", "", text)]
        if matches:
            entries.append((heading, matches[-1], level))
    return entries


XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _toc_entry_paragraph(level: int, heading: str, page: int, *, first: bool, last: bool):
    """One TOC entry = ONE paragraph: LEFT alignment, right dot-leader tab.

    The old implementation cached every entry into a single Normal-styled
    paragraph separated by <w:br> plus hand-typed dots, so JUSTIFY
    distributed the CJK glyphs ("执 行 摘 要 与 决 策 建 议").  Each entry
    is now its own paragraph with explicit LEFT alignment and a real right
    tab stop with a dot leader — no manual dots, no <br> separators.
    """
    paragraph = ElementTree.Element(W + "p")
    ppr = ElementTree.SubElement(paragraph, W + "pPr")
    style = ElementTree.SubElement(ppr, W + "pStyle")
    style.set(W + "val", f"TOC{min(max(level, 1), 3)}")
    jc = ElementTree.SubElement(ppr, W + "jc")
    jc.set(W + "val", "left")
    ind = ElementTree.SubElement(ppr, W + "ind")
    ind.set(W + "left", str((level - 1) * 240))
    ind.set(W + "firstLine", "0")
    tabs = ElementTree.SubElement(ppr, W + "tabs")
    tab = ElementTree.SubElement(tabs, W + "tab")
    tab.set(W + "val", "right")
    tab.set(W + "leader", "dot")
    tab.set(W + "pos", "9000")
    if first:
        run = ElementTree.SubElement(paragraph, W + "r")
        begin = ElementTree.SubElement(run, W + "fldChar")
        begin.set(W + "fldCharType", "begin")
        instruction = ElementTree.SubElement(run, W + "instrText")
        instruction.set(XML_SPACE, "preserve")
        instruction.text = 'TOC \\o "1-2" \\h \\z \\u'
        separate = ElementTree.SubElement(run, W + "fldChar")
        separate.set(W + "fldCharType", "separate")
    run = ElementTree.SubElement(paragraph, W + "r")
    text = ElementTree.SubElement(run, W + "t")
    text.set(XML_SPACE, "preserve")
    text.text = heading
    ElementTree.SubElement(run, W + "tab")
    if page > 0:
        page_run = ElementTree.SubElement(paragraph, W + "r")
        page_text = ElementTree.SubElement(page_run, W + "t")
        page_text.set(XML_SPACE, "preserve")
        page_text.text = str(page)
    if last:
        run = ElementTree.SubElement(paragraph, W + "r")
        end = ElementTree.SubElement(run, W + "fldChar")
        end.set(W + "fldCharType", "end")
    return paragraph


def _ensure_toc_styles(members: dict) -> None:
    """Register TOC1/2/3 paragraph styles with LEFT alignment.

    Word/LibreOffice materialize a TOC field through the document's TOC
    styles; without them the entries inherit Normal (JUSTIFY), which
    distributes CJK characters.  Adding LEFT-aligned styles keeps every
    path — static injection AND live field refresh — visually correct.
    """
    styles_root = ElementTree.fromstring(members["word/styles.xml"])
    existing = {node.get(W + "styleId") for node in styles_root if node.tag == W + "style"}
    for style_id, size in (("TOC1", "22"), ("TOC2", "21"), ("TOC3", "20")):
        if style_id in existing:
            continue
        style = ElementTree.Element(W + "style")
        style.set(W + "type", "paragraph")
        style.set(W + "styleId", style_id)
        name = ElementTree.SubElement(style, W + "name")
        name.set(W + "val", f"toc {style_id[-1]}")
        ppr = ElementTree.SubElement(style, W + "pPr")
        jc = ElementTree.SubElement(ppr, W + "jc")
        jc.set(W + "val", "left")
        tabs = ElementTree.SubElement(ppr, W + "tabs")
        tab = ElementTree.SubElement(tabs, W + "tab")
        tab.set(W + "val", "right")
        tab.set(W + "leader", "dot")
        tab.set(W + "pos", "9000")
        rpr = ElementTree.SubElement(style, W + "rPr")
        sz = ElementTree.SubElement(rpr, W + "sz")
        sz.set(W + "val", size)
        styles_root.append(style)
    members["word/styles.xml"] = ElementTree.tostring(styles_root, encoding="utf-8", xml_declaration=True)


def inject_static_toc_result(path: Path, entries: list[tuple[str, int] | tuple[str, int, int]]) -> None:
    """Populate the existing TOC field result with final page numbers.

    Entries are (heading, page) or (heading, page, level).  Every entry is
    a separate LEFT-aligned paragraph with a real right tab stop + dot
    leader — never a <br>-joined Normal paragraph with manual dots.
    """
    normalized_entries: list[tuple[str, int, int]] = [
        (heading, page, level) for heading, page, level in [
            (entry[0], entry[1], entry[2] if len(entry) > 2 else 1) for entry in entries
        ] if level <= 2
    ]
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    root = ElementTree.fromstring(members["word/document.xml"])
    body = root.find(f".//{W}body")
    if body is None:
        raise RuntimeError("Word document body not found")
    body_children = list(body)
    start = None
    for index, paragraph in enumerate(body_children):
        if paragraph.tag != W + "p":
            continue
        instructions = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instructions.strip().startswith("TOC"):
            start = index
            break
    if start is None:
        # LibreOffice's docx roundtrip may drop an EMPTY TOC field result
        # paragraph.  Insert the entries right after the 目录 heading so the
        # final document always carries a real, populated TOC field.
        for index, paragraph in enumerate(body_children):
            if paragraph.tag != W + "p":
                continue
            text_value = "".join(node.text or "" for node in paragraph.findall(f".//{W}t")).strip()
            if text_value == "目录":
                start = index + 1
                break
    if start is None:
        raise RuntimeError("TOC field paragraph not found")
    # A previous injection may span several paragraphs: remove from the
    # first entry through the paragraph carrying the field end.
    end = start
    for index in range(start, len(body_children)):
        if body_children[index].tag != W + "p":
            continue
        if any(
            node.get(W + "fldCharType") == "end"
            for node in body_children[index].findall(f".//{W}fldChar")
        ):
            end = index
            break
    for paragraph in body_children[start:end + 1]:
        body.remove(paragraph)
    paragraphs = [
        _toc_entry_paragraph(level, heading, page, first=(index == 0), last=(index == len(normalized_entries) - 1))
        for index, (heading, page, level) in enumerate(normalized_entries)
    ]
    for offset, paragraph in enumerate(paragraphs):
        body.insert(start + offset, paragraph)
    members["word/document.xml"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    _ensure_toc_styles(members)
    settings = ElementTree.fromstring(members["word/settings.xml"])
    if settings.find(f"./{W}updateFields") is None:
        update_fields = ElementTree.SubElement(settings, W + "updateFields")
        update_fields.set(W + "val", "true")
    members["word/settings.xml"] = ElementTree.tostring(settings, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx", dir=path.parent) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def render_pdf_and_png(docx: Path, output: Path, soffice: Path) -> tuple[Path, list[Path]]:
    pdf = convert(docx, output, "pdf", soffice)
    page_dir = output / "word_pages"
    # Clean the raster dir: leftover PNGs from a previous cycle must never
    # mix with this cycle's numbering.
    if page_dir.exists():
        shutil.rmtree(page_dir)
    page_dir.mkdir(parents=True, exist_ok=True)
    prefix = page_dir / "page"
    completed = subprocess.run(["pdftoppm", "-png", "-r", "144", str(pdf), str(prefix)], capture_output=True, text=True, timeout=300)
    if completed.returncode:
        raise RuntimeError(f"PDF page rasterization failed: {completed.stderr}")
    raw_pages = sorted(page_dir.glob("page-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
    pages = []
    for index, source in enumerate(raw_pages, start=1):
        target = page_dir / f"page-{index:03d}.png"
        if source != target:
            source.replace(target)
        pages.append(target)
    return pdf, pages


def fallback_word_render_validation(pdf_path: Path):
    from energy_research_agent.validation.visual_qa import WordVisualValidation

    completed = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, timeout=120)
    pages = completed.stdout.decode("utf-8", errors="ignore").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    blank = [index for index, text in enumerate(pages, start=1) if not text.strip()]
    findings = ["Blank rendered pages: " + ", ".join(map(str, blank))] if blank else []
    return WordVisualValidation(status="PASS" if not findings else "BLOCKED", page_count=len(pages), blank_pages=blank, findings=findings)


def screenshot_html(html_path: Path, output: Path) -> dict:
    from playwright.sync_api import sync_playwright

    viewports = [(1366, 768), (1920, 1080), (390, 844)]
    screenshots: dict[str, str] = {}
    checks: dict[str, dict] = {}
    rendered_visible_text = ""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in viewports:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            errors: list[str] = []
            page.on("pageerror", lambda error, bucket=errors: bucket.append(str(error)))
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(500)
            if not rendered_visible_text:
                rendered_visible_text = page.locator("body").inner_text()
            target = output / f"html-{width}x{height}.png"
            page.screenshot(path=str(target), full_page=True)
            geometry = page.evaluate("""() => ({scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, sourceSections: document.querySelectorAll('.workspace.sources').length, chapterCount: document.querySelectorAll('.chapter').length, decisionFirst: !!document.querySelector('.judgement b')})""")
            screenshots[f"{width}x{height}"] = str(target)
            checks[f"{width}x{height}"] = {**geometry, "pageErrors": errors, "horizontalOverflow": geometry["scrollWidth"] > geometry["clientWidth"] + 2}
            page.close()
        browser.close()
    return {"screenshots": screenshots, "checks": checks, "_rendered_visible_text": rendered_visible_text}


def make_contact_sheet(page_paths: list[Path], target: Path, columns: int = 4) -> Path:
    from PIL import Image, ImageDraw

    thumbs = []
    width = 240
    for index, path in enumerate(page_paths, start=1):
        with Image.open(path) as source:
            image = source.convert("RGB")
            height = round(image.height * width / image.width)
            image = image.resize((width, height))
        canvas = Image.new("RGB", (width, height + 24), "white")
        canvas.paste(image, (0, 24))
        ImageDraw.Draw(canvas).text((8, 5), f"Page {index}", fill="#1B365D")
        thumbs.append(canvas)
    rows = (len(thumbs) + columns - 1) // columns
    cell_height = max(image.height for image in thumbs)
    sheet = Image.new("RGB", (columns * width, rows * cell_height), "#D9E2EC")
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % columns) * width, (index // columns) * cell_height))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    soffice = find_soffice()

    # Cycle 1: refresh, render and inspect.
    refresh_docx(args.docx, soffice)
    # Preferred path: LibreOffice updates the real TOC field (page numbers
    # come from LO's own pagination — the PDF text is not extractable here).
    try:
        toc_macro_ok = update_toc_via_macro(args.docx, soffice)
    except subprocess.TimeoutExpired:
        toc_macro_ok = False
    pdf, pages = render_pdf_and_png(args.docx, output / "cycle-1", soffice)
    headings = docx_heading_levels(args.docx)
    entries = heading_page_map(pdf, headings)
    if entries:
        inject_static_toc_result(args.docx, entries)
    elif not toc_macro_ok:
        # Static fallback: one LEFT-aligned paragraph per entry with a real
        # dot-leader tab.  Page numbers stay blank when the PDF text cannot
        # be extracted and the macro did not run.
        inject_static_toc_result(args.docx, [(heading, 0, level) for heading, level in headings])

    # Fix cycle: populate final TOC result, rerender and inspect every page.
    final_pdf, final_pages = render_pdf_and_png(args.docx, output / "cycle-2", soffice)
    contact_sheet = make_contact_sheet(final_pages, output / "word-contact-sheet.png")
    word_render = inspect_word_render(final_pdf)
    if word_render.page_count == 0 and any("PyMuPDF" in item for item in word_render.findings):
        word_render = fallback_word_render_validation(final_pdf)
    visible = PublicationVisibleTextValidator()
    word_findings = visible.validate_text(visible.extract_docx(args.docx)) + TOCValidator().validate(args.docx, require_page_numbers=True)
    html_result = screenshot_html(args.html, output)
    rendered_html_text = html_result.pop("_rendered_visible_text", "")
    html_findings = visible.validate_text(rendered_html_text)
    report = {
        "status": "PASS" if not word_findings and not html_findings and word_render.status == "PASS" and all(not value["horizontalOverflow"] and not value["pageErrors"] and value["sourceSections"] == 1 and value["decisionFirst"] for value in html_result["checks"].values()) else "BLOCKED",
        "fix_cycles": 1,
        "word": {
            "docx": str(args.docx.resolve()), "pdf": str(final_pdf), "page_count": len(final_pages),
            "page_pngs": [str(path) for path in final_pages], "toc_entries": entries,
            "contact_sheet": str(contact_sheet),
            "visible_text_findings": word_findings, "render_validation": word_render.model_dump(mode="json"),
        },
        "html": {
            **html_result,
            "rendered_visible_cjk_char_count": len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", rendered_html_text)),
            "visible_text_findings": html_findings,
        },
    }
    (output / "publication_qa_notes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "publication_qa_notes.md").write_text(
        f"# Publication QA Notes\n\n- Status: {report['status']}\n- Fix cycles: 1\n- Word pages: {len(final_pages)}\n- TOC entries: {len(entries)}\n- Word findings: {word_findings + word_render.findings}\n- HTML findings: {html_findings}\n- HTML viewports: {', '.join(html_result['checks'])}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
