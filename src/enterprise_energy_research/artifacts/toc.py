"""Headless-safe Word table-of-contents materialization.

The Word publisher writes a real TOC field, but Word/LibreOffice may leave its
cached result empty until a desktop field refresh occurs.  A formal handoff
must still show the report structure, so the publisher seeds one visible,
left-aligned paragraph per Heading 1/2.  Final render QA may replace the blank
page-number slots with pagination obtained from the office renderer.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from lxml import etree as ElementTree


NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % NS
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def heading_levels(path: Path) -> list[tuple[str, int]]:
    """Return Heading 1/2 entries in document order, excluding the TOC title."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    entries: list[tuple[str, int]] = []
    style_levels = {
        "Heading1": 1, "Heading 1": 1, "1": 1,
        "Heading2": 2, "Heading 2": 2, "2": 2,
    }
    for paragraph in root.findall(f".//{W}body/{W}p"):
        instruction = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instruction.strip().startswith("TOC"):
            continue
        style = paragraph.find(f"./{W}pPr/{W}pStyle")
        value = style.get(W + "val") if style is not None else ""
        level = style_levels.get(value)
        if level is None:
            continue
        text = "".join(node.text or "" for node in paragraph.findall(f".//{W}t")).strip()
        if text and text != "目录":
            entries.append((text, level))
    return entries


def _entry(level: int, heading: str, page: int, *, first: bool, last: bool):
    paragraph = ElementTree.Element(W + "p")
    ppr = ElementTree.SubElement(paragraph, W + "pPr")
    style = ElementTree.SubElement(ppr, W + "pStyle")
    style.set(W + "val", f"TOC{level}")
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
        page_text.text = str(page)
    if last:
        run = ElementTree.SubElement(paragraph, W + "r")
        end = ElementTree.SubElement(run, W + "fldChar")
        end.set(W + "fldCharType", "end")
    return paragraph


def materialize_toc(path: Path, entries: list[tuple[str, int, int]]) -> None:
    """Replace the TOC cached result with visible entries.

    Each tuple is ``(heading, page, level)``.  ``page=0`` deliberately leaves
    the page slot blank for the later office-render refresh while preserving a
    readable directory in every renderer.
    """
    normalized = [(heading, page, min(max(level, 1), 2)) for heading, page, level in entries if heading]
    if not normalized:
        raise ValueError("TOC requires at least one Heading 1/2 entry")
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    root = ElementTree.fromstring(members["word/document.xml"])
    body = root.find(f".//{W}body")
    if body is None:
        raise RuntimeError("Word document body not found")
    children = list(body)
    start = None
    for index, paragraph in enumerate(children):
        if paragraph.tag != W + "p":
            continue
        instructions = "".join(node.text or "" for node in paragraph.findall(f".//{W}instrText"))
        if instructions.strip().startswith("TOC"):
            start = index
            break
    if start is None:
        raise RuntimeError("TOC field paragraph not found")
    end = start
    for index in range(start, len(children)):
        if children[index].tag != W + "p":
            continue
        if any(node.get(W + "fldCharType") == "end" for node in children[index].findall(f".//{W}fldChar")):
            end = index
            break
    for paragraph in children[start:end + 1]:
        body.remove(paragraph)
    for offset, (heading, page, level) in enumerate(normalized):
        body.insert(start + offset, _entry(
            level, heading, page,
            first=offset == 0,
            last=offset == len(normalized) - 1,
        ))
    # lxml preserves the package's existing ``w:``/``r:`` prefixes.  The
    # stdlib ElementTree serializer rewrites them to ``ns0:``/``ns1:``, which
    # Word can read but breaks downstream OOXML tooling that correctly treats
    # the conventional prefixes as part of its compatibility contract.
    members["word/document.xml"] = ElementTree.tostring(
        root, encoding="utf-8", xml_declaration=True, standalone=True,
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx", dir=path.parent) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
