from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def find_soffice(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit else []
    discovered = shutil.which("soffice") or shutil.which("libreoffice")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend([
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ])
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise FileNotFoundError("LibreOffice soffice was not found")


def render_pdf(pptx: Path, output_dir: Path, soffice: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(soffice), "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(pptx)],
        check=False, capture_output=True, text=True, timeout=240,
    )
    pdf = output_dir / f"{pptx.stem}.pdf"
    if completed.returncode != 0 or not pdf.is_file():
        raise RuntimeError(f"LibreOffice PDF render failed: {completed.stderr or completed.stdout}")
    return pdf


def intersection(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float]:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])), max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def inspect_pdf(pdf: Path, tolerance_pt: float = 3.0, minimum_font_pt: float = 8.0) -> dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for the PPT geometry gate") from exc
    document = fitz.open(pdf)
    findings: list[dict[str, Any]] = []
    overlap_count = font_count = boundary_count = 0
    for page_index, page in enumerate(document, start=1):
        width, height = page.rect.width, page.rect.height
        spans: list[dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        spans.append(span)
        for span in spans:
            x0, y0, x1, y1 = span["bbox"]
            if x0 < -tolerance_pt or y0 < -tolerance_pt or x1 > width + tolerance_pt or y1 > height + tolerance_pt:
                boundary_count += 1
                findings.append({"page": page_index, "type": "boundary", "text": span["text"], "bbox": span["bbox"]})
            if float(span.get("size", 0)) + 0.01 < minimum_font_pt:
                font_count += 1
                findings.append({"page": page_index, "type": "font_below_minimum", "text": span["text"], "size": span.get("size")})
        for left_index, left in enumerate(spans):
            for right in spans[left_index + 1:]:
                overlap_x, overlap_y = intersection(tuple(left["bbox"]), tuple(right["bbox"]))
                if overlap_x > tolerance_pt and overlap_y > tolerance_pt:
                    # Spans generated from the same text line may share a baseline; only flag material two-dimensional overlap.
                    if abs(float(left["bbox"][1]) - float(right["bbox"][1])) <= 1 and abs(float(left["bbox"][3]) - float(right["bbox"][3])) <= 1:
                        continue
                    overlap_count += 1
                    findings.append({"page": page_index, "type": "overlap", "left": left["text"], "right": right["text"], "overlap_pt": [overlap_x, overlap_y]})
    page_count = len(document)
    document.close()
    return {
        "status": "PASS" if not findings else "BLOCKED",
        "rendered_slide_count": page_count,
        "page_count": page_count,
        "overflow_count": boundary_count,
        "overlap_over_3pt_count": overlap_count,
        "chart_font_below_8pt_count": font_count,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a PPTX and block geometry/font defects")
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--soffice", type=Path)
    parser.add_argument("--tolerance-pt", type=float, default=3.0)
    parser.add_argument("--minimum-font-pt", type=float, default=8.0)
    args = parser.parse_args()
    if args.pdf:
        pdf = args.pdf
        result = inspect_pdf(pdf, args.tolerance_pt, args.minimum_font_pt)
    else:
        with tempfile.TemporaryDirectory() as temp:
            pdf = render_pdf(args.pptx, Path(temp), find_soffice(args.soffice))
            result = inspect_pdf(pdf, args.tolerance_pt, args.minimum_font_pt)
    result["pptx"] = str(args.pptx.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
