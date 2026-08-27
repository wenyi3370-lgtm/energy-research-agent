from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document

from build_template_report import format_image_paragraphs, insert_charts


def main() -> int:
    parser = argparse.ArgumentParser(description="Insert approved embedded-figure bundles after substantive Word analysis paragraphs.")
    parser.add_argument("docx", help="Narrative-complete DOCX")
    parser.add_argument("--charts-dir", required=True, help="Directory containing figN_*.theme.json and matching PNGs")
    parser.add_argument("--out", help="Output DOCX; defaults to in-place")
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    args = parser.parse_args()

    source = Path(args.docx).resolve()
    charts_dir = Path(args.charts_dir).resolve()
    output = Path(args.out).resolve() if args.out else source
    if not source.exists():
        raise FileNotFoundError(source)
    manifests = sorted(charts_dir.glob("fig*.theme.json"))
    if args.mode == "final" and not manifests:
        raise ValueError("Final Word figure insertion requires figN_*.theme.json manifests")

    doc = Document(source)
    inserted = insert_charts(doc, charts_dir)
    format_image_paragraphs(doc)
    if args.mode == "final" and inserted != len(manifests):
        raise ValueError(
            f"Only {inserted} of {len(manifests)} approved figures could be placed after substantive analysis paragraphs"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    print(f"Inserted {inserted} approved figures: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
