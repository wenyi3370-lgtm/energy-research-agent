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

from enterprise_energy_research.validation.consulting_narrative import (
    PublicationVisibleTextValidator, TOCValidator,
)
from enterprise_energy_research.validation.visual_qa import inspect_word_render


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
        if candidate and candidate.is_file():
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


def docx_heading_text(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    headings: list[str] = []
    for paragraph in root.findall(f".//{W}body/{W}p"):
        instruction = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instruction.strip().startswith("TOC"):
            continue
        style = paragraph.find(f"./{W}pPr/{W}pStyle")
        value = style.get(W + "val") if style is not None else ""
        if value not in {"Heading1", "1"}:
            continue
        text = "".join(node.text or "" for node in paragraph.findall(f".//{W}t")).strip()
        if text and text != "目录":
            headings.append(text)
    return headings


def heading_page_map(pdf_path: Path, headings: list[str]) -> list[tuple[str, int]]:
    completed = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, timeout=120)
    try:
        decoded = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        decoded = completed.stdout.decode(encoding if encoding.lower() != "utf-8" else "gb18030", errors="replace")
    pages = decoded.split("\f")
    entries = []
    for heading in headings:
        normalized = re.sub(r"\s+", "", heading)
        # A refreshed office document may already show a generated TOC.  The
        # first occurrence is then the TOC itself; the last occurrence is the
        # real body heading whose final page number must be published.
        matches = [index for index, text in enumerate(pages, start=1) if normalized in re.sub(r"\s+", "", text)]
        if matches:
            entries.append((heading, matches[-1]))
    return entries


def inject_static_toc_result(path: Path, entries: list[tuple[str, int]]) -> None:
    """Populate the existing TOC field result with final page numbers."""
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    root = ElementTree.fromstring(members["word/document.xml"])
    target = None
    for paragraph in root.findall(f".//{W}p"):
        instructions = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instructions.strip().startswith("TOC"):
            target = paragraph
            break
    if target is None:
        body = root.find(f".//{W}body")
        if body is None:
            raise RuntimeError("Word document body not found")
        body_children = list(body)
        for index, paragraph in enumerate(body_children):
            if paragraph.tag != W + "p":
                continue
            text_value = "".join(node.text or "" for node in paragraph.findall(f".//{W}t")).strip()
            if text_value == "目录":
                # LibreOffice can remove an empty TOC result paragraph.  Add
                # a dedicated paragraph after the title; never overwrite the
                # first real chapter heading.
                target = ElementTree.Element(W + "p")
                body.insert(index + 1, target)
                break
        if target is None:
            raise RuntimeError("TOC placement paragraph not found")
    # LibreOffice is free to split a complex field across several runs.  Do
    # not depend on its run boundaries: rebuild one canonical field/result in
    # the already-located TOC paragraph.  This also makes repeated QA passes
    # idempotent (the second pass replaces, rather than nests, static output).
    ppr = target.find(f"./{W}pPr")
    for child in list(target):
        if child is not ppr:
            target.remove(child)
    run = ElementTree.SubElement(target, W + "r")
    begin = ElementTree.SubElement(run, W + "fldChar")
    begin.set(W + "fldCharType", "begin")
    instruction = ElementTree.SubElement(run, W + "instrText")
    instruction.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instruction.text = 'TOC \\o "1-3" \\h \\z \\u'
    separate = ElementTree.SubElement(run, W + "fldChar")
    separate.set(W + "fldCharType", "separate")
    insert_at = len(run)
    for index, (heading, page) in enumerate(entries):
        if index:
            br = ElementTree.Element(W + "br")
            run.insert(insert_at, br)
            insert_at += 1
        text = ElementTree.Element(W + "t")
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = f"{heading}  ······  {page}"
        run.insert(insert_at, text)
        insert_at += 1
    end = ElementTree.Element(W + "fldChar")
    end.set(W + "fldCharType", "end")
    run.insert(insert_at, end)
    members["word/document.xml"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
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
    from enterprise_energy_research.validation.visual_qa import WordVisualValidation

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
            geometry = page.evaluate("""() => ({scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, sourceSections: [...document.querySelectorAll('h2')].filter(x => x.textContent.trim() === '来源与方法').length, chapterCount: document.querySelectorAll('.chapter').length, decisionFirst: !!document.querySelector('.judgement b')})""")
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
    pdf, pages = render_pdf_and_png(args.docx, output / "cycle-1", soffice)
    headings = docx_heading_text(args.docx)
    entries = heading_page_map(pdf, headings)
    if entries:
        inject_static_toc_result(args.docx, entries)

    # Fix cycle: populate final TOC result, rerender and inspect every page.
    final_pdf, final_pages = render_pdf_and_png(args.docx, output / "cycle-2", soffice)
    contact_sheet = make_contact_sheet(final_pages, output / "word-contact-sheet.png")
    word_render = inspect_word_render(final_pdf)
    if word_render.page_count == 0 and any("PyMuPDF" in item for item in word_render.findings):
        word_render = fallback_word_render_validation(final_pdf)
    visible = PublicationVisibleTextValidator()
    word_findings = visible.validate_text(visible.extract_docx(args.docx)) + TOCValidator().validate(args.docx)
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
