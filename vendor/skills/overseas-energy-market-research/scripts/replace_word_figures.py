from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from build_template_report import format_image_paragraphs


CAPTION_RE = re.compile(r"^\s*图\s*(\d+)[-－—–](\d+)")


def _resolve_png(manifest_path: Path, manifest: dict, project_dir: Path | None) -> Path:
    raw = Path(str((((manifest.get("outputs") or {}).get("png") or {}).get("path")) or ""))
    candidates = [raw] if raw.is_absolute() else []
    if project_dir is not None:
        candidates.append(project_dir / raw)
    candidates.append(manifest_path.parent / raw.name)
    return next((path.resolve() for path in candidates if path.exists()), candidates[-1].resolve())


def manifest_by_chapter(charts_dir: Path, project_dir: Path | None) -> dict[int, Path]:
    mapping: dict[int, Path] = {}
    for manifest_path in sorted(charts_dir.glob("fig*.theme.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        placement = manifest.get("word_placement") or {}
        chapter = placement.get("chapter_number")
        if chapter is None:
            match = re.match(r"^fig(\d+)_", manifest_path.name, flags=re.IGNORECASE)
            chapter = int(match.group(1)) if match else None
        if chapter is None:
            continue
        chapter = int(chapter)
        if chapter in mapping:
            raise ValueError(f"More than one replacement figure declared for chapter {chapter}")
        mapping[chapter] = _resolve_png(manifest_path, manifest, project_dir)
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace existing inline Word figures by chapter while preserving captions and layout.")
    parser.add_argument("docx")
    parser.add_argument("--charts-dir", required=True)
    parser.add_argument("--project-dir")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = Path(args.docx).resolve()
    charts_dir = Path(args.charts_dir).resolve()
    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    output = Path(args.out).resolve()
    replacements = manifest_by_chapter(charts_dir, project_dir)
    if not replacements:
        raise ValueError("No replacement manifests found")

    doc = Document(source)
    paragraphs = list(doc.paragraphs)
    replaced: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        blips = paragraph._p.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        if not blips:
            continue
        caption = next((p.text.strip() for p in paragraphs[index + 1 : index + 4] if CAPTION_RE.match(p.text.strip())), "")
        match = CAPTION_RE.match(caption)
        if not match:
            continue
        chapter = int(match.group(1))
        png = replacements.get(chapter)
        if png is None:
            continue
        if not png.exists():
            raise FileNotFoundError(png)
        old_blip = blips[0]
        old_rid = old_blip.get(qn("r:embed"))
        new_rid, _ = doc.part.get_or_add_image(str(png))
        old_blip.set(qn("r:embed"), new_rid)
        replaced.add(chapter)

    missing = sorted(set(replacements) - replaced)
    if missing:
        raise ValueError(f"Replacement figures could not be mapped to Word chapters: {missing}")
    format_image_paragraphs(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    print(f"Replaced {len(replaced)} Word figures by chapter: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
