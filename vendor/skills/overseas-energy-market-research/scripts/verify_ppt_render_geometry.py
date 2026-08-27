# -*- coding: utf-8 -*-
"""Verify the rendered PPT geometry: span-level overlaps and canvas overflow.

Learned from production (v1.0.5): the SVG text gate (`wrap_slide_text.py
--check`) validates widths against the *model*, but the *renderer* can still
rewrap or misplace text:

- LibreOffice ignores `spAutoFit` and wraps text at the frame width, so a
  frame sized from the 0.55em estimate can split single-line KPI numbers
  ("540 MWh" -> "540"/"MWh").
- A wrapped multi-line block can grow downward into the element below
  ("详见第 X 页" links, next card row), producing 5-15px glyph overlaps.
- Right-edge frames (end-anchored footers) can land past the 1280px canvas
  and get clipped.

This script renders the FINAL pptx (or accepts a pre-rendered PDF), extracts
span-level text geometry with PyMuPDF and fails on any text-text overlap
(> 3pt x 3pt) or canvas boundary violation (x1 > 962pt, x0 < -2pt, where
960pt = 1280 SVG px at the 0.75 ppt->pdf scale). Run it after export and
before `register_high_fidelity_ppt_delivery.py`.

Usage:
    python verify_ppt_render_geometry.py --project-dir <project> [--pptx PATH]
                                          [--pdf PATH] [--render-dir DIR]

Exit 0 = clean, 1 = issues found (blocking), 2 = environment error.
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil

from _common import find_presentation_project
import subprocess
import sys
from pathlib import Path

# 1280x720 SVG -> 960x540 pt PDF (0.75 scale). Allow 2pt slop for font
# metric differences between renderers.
PAGE_W = 960.0
CANVAS_MAX_X = PAGE_W + 2.0
CANVAS_MIN_X = -2.0
OVERLAP_IX = 3.0
OVERLAP_IY = 3.0


def _find_pptx(project_dir: Path, presentation_project: Path | None = None) -> Path | None:
    candidates = [
        project_dir / "deliverables" / "市场调研内部宣讲PPT-最终版.pptx",
        project_dir / "deliverables" / "市场调研内部宣讲PPT.pptx",
    ]
    if presentation_project is not None:
        candidates.append(presentation_project / "exports" / "市场调研内部宣讲PPT.pptx")
    for c in candidates:
        if c.exists():
            return c
    hits = sorted((project_dir / "deliverables").glob("*.pptx")) if (project_dir / "deliverables").exists() else []
    if presentation_project is not None and (presentation_project / "exports").exists():
        hits += sorted((presentation_project / "exports").glob("*.pptx"))
    return hits[0] if hits else None


def _render_pdf(pptx: Path, render_dir: Path) -> Path | None:
    """Convert pptx -> pdf with LibreOffice headless (isolated profile)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        win = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
        if win.exists():
            soffice = str(win)
    if soffice is None:
        print("ERROR: LibreOffice (soffice) not found; pass --pdf with a pre-rendered file")
        return None
    render_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(render_dir), str(pptx)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        print("ERROR: LibreOffice conversion failed:", proc.stderr[-500:])
        return None
    pdfs = sorted(render_dir.glob("*.pdf"))
    return pdfs[-1] if pdfs else None


def _extract_spans(pdf_path: Path) -> tuple[dict[int, list], int]:
    """Return {page_no: [span...]} with span = (y0, x0, y1, x1, text)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover
        print("ERROR: PyMuPDF (fitz) not installed:", e)
        raise SystemExit(2)
    doc = fitz.open(str(pdf_path))
    out: dict[int, list] = {}
    for i in range(doc.page_count):
        spans = []
        for block in doc[i].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, y0, x1, y1 = span["bbox"]
                    if span["text"].strip():
                        spans.append([round(y0), round(x0), round(y1), round(x1), span["text"]])
        out[i + 1] = spans
    return out, doc.page_count


def _check(spans: dict[int, list], page_count: int) -> tuple[list[str], int]:
    issues: list[str] = []
    total_overlaps = 0
    for pno in range(1, page_count + 1):
        page_spans = spans.get(pno, [])
        for i in range(len(page_spans)):
            a = page_spans[i]
            for j in range(i + 1, len(page_spans)):
                b = page_spans[j]
                ix = min(a[3], b[3]) - max(a[1], b[1])
                iy = min(a[2], b[2]) - max(a[0], b[0])
                if ix > OVERLAP_IX and iy > OVERLAP_IY:
                    total_overlaps += 1
                    if total_overlaps <= 10:
                        issues.append("页%d 文本重叠 %.0fx%.0fpt: [%s] vs [%s]" % (
                            pno, ix, iy, a[4][:24], b[4][:24]))
            for s in page_spans:
                if s[3] > CANVAS_MAX_X:
                    issues.append("页%d 右越界 x1=%.0fpt (>%.0f): %r" % (pno, s[3], CANVAS_MAX_X, s[4][:26]))
                if s[1] < CANVAS_MIN_X:
                    issues.append("页%d 左越界 x0=%.0fpt (<%.0f): %r" % (pno, s[1], CANVAS_MIN_X, s[4][:26]))
    return issues, total_overlaps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-dir", default=".", help="Research project directory")
    parser.add_argument("--pptx", help="Path to the final PPTX (auto-detected if omitted)")
    parser.add_argument("--pdf", help="Path to a pre-rendered PDF (skips LibreOffice)")
    parser.add_argument(
        "--render-dir",
        default=None,
        help="Render output directory (default: <presentation_project>/render; CHANGELOG v1.2.6)",
    )
    parser.add_argument(
        "--presentation-project",
        default=None,
        help="High-fidelity presentation directory (auto-detected when omitted).",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    pdf_path = Path(args.pdf).expanduser().resolve() if args.pdf else None

    presentation_project = None
    if args.presentation_project:
        presentation_project = Path(args.presentation_project).expanduser().resolve()
        if not presentation_project.is_absolute():
            presentation_project = project_dir / presentation_project
    else:
        presentation_project = find_presentation_project(project_dir)

    if pdf_path is None:
        pptx = Path(args.pptx).expanduser().resolve() if args.pptx else _find_pptx(project_dir, presentation_project)
        if pptx is None or not pptx.exists():
            print("ERROR: PPTX not found under", project_dir)
            return 2
        render_dir = project_dir / args.render_dir if args.render_dir else (
            (presentation_project or project_dir / "presentation_project") / "render"
        )
        pdf_path = _render_pdf(pptx, render_dir)
        if pdf_path is None:
            return 2
    elif not pdf_path.exists():
        print("ERROR: PDF not found:", pdf_path)
        return 2

    spans, page_count = _extract_spans(pdf_path)
    issues, total_overlaps = _check(spans, page_count)
    print("PDF: %s | 页数: %d | span 级重叠: %d" % (pdf_path.name, page_count, total_overlaps))
    for it in issues:
        print("  ", it)
    if issues:
        print("校验失败：渲染几何存在 %d 处问题（重叠/越界）" % len(issues))
        return 1
    print("校验通过：渲染几何干净（0 重叠、0 越界）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
