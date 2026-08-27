from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import pymupdf


PAGE_RE = re.compile(r"page-(\d+)\.png$", re.I)


def _page_number(path: Path) -> int:
    match = PAGE_RE.search(path.name)
    if not match:
        raise ValueError(f"Unexpected rendered-page filename: {path.name}")
    return int(match.group(1))


def build_contact_sheets(
    pages_dir: Path,
    output_dir: Path,
    *,
    columns: int = 4,
    rows: int = 4,
    thumb_width: int = 340,
) -> list[Path]:
    if columns <= 0 or rows <= 0 or thumb_width <= 0:
        raise ValueError("columns, rows, and thumb_width must be positive")
    pages = sorted(pages_dir.glob("page-*.png"), key=_page_number)
    if not pages:
        raise FileNotFoundError(f"No page-*.png files found in {pages_dir}")
    expected = list(range(1, len(pages) + 1))
    actual = [_page_number(path) for path in pages]
    if actual != expected:
        raise ValueError(f"Rendered page sequence is incomplete: {actual}")

    first = pymupdf.Pixmap(str(pages[0]))
    aspect = first.height / first.width
    thumb_height = int(round(thumb_width * aspect))
    margin = 24
    label_height = 28
    cell_width = thumb_width + margin
    cell_height = thumb_height + label_height + margin
    canvas_width = margin + columns * cell_width
    canvas_height = margin + rows * cell_height
    per_sheet = columns * rows
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for sheet_index in range(math.ceil(len(pages) / per_sheet)):
        document = pymupdf.open()
        canvas = document.new_page(width=canvas_width, height=canvas_height)
        canvas.draw_rect(canvas.rect, color=None, fill=(1, 1, 1))
        batch = pages[sheet_index * per_sheet : (sheet_index + 1) * per_sheet]
        for index, path in enumerate(batch):
            row, column = divmod(index, columns)
            left = margin + column * cell_width
            top = margin + row * cell_height
            rect = pymupdf.Rect(left, top, left + thumb_width, top + thumb_height)
            canvas.insert_image(rect, filename=str(path), keep_proportion=True)
            canvas.draw_rect(rect, color=(0.75, 0.78, 0.82), width=0.8)
            canvas.insert_text(
                (left, top + thumb_height + 18),
                f"Page {_page_number(path)}",
                fontsize=11,
                fontname="helv",
                color=(0.12, 0.16, 0.22),
            )
        target = output_dir / f"contact-{sheet_index + 1}.png"
        pixmap = canvas.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
        pixmap.save(target)
        document.close()
        outputs.append(target)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Create page contact sheets from PyMuPDF-rendered Office page PNGs.")
    parser.add_argument("pages_dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=340)
    args = parser.parse_args()
    outputs = build_contact_sheets(
        Path(args.pages_dir).resolve(),
        Path(args.output_dir).resolve(),
        columns=args.columns,
        rows=args.rows,
        thumb_width=args.thumb_width,
    )
    print(f"Contact sheets: {len(outputs)}")
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
