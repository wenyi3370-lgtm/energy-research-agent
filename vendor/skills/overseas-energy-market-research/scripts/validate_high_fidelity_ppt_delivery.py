from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile
import json
from collections import Counter
from pathlib import Path

from pptx import Presentation

from _common import Issue, find_presentation_project, presentation_project_hint, print_report, read_json
from presentation_production import ALLOWED_FALLBACK_CODES, pptx_media_hashes


PIPELINE_ID = "embedded-pptmaster-svg-v1"
PLACEHOLDER_RE = re.compile(rb"\[\[[^\]]+\]\]|\{\{[^}]+\}\}|&lt;[^&]{1,60}&gt;")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stored_path(path: Path, project_dir: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _run_quality_checker(presentation_project: Path, canvas: str) -> tuple[int, str]:
    script = Path(__file__).resolve().parent / "svg_quality_checker.py"
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    result = subprocess.run(
        [sys.executable, str(script), str(presentation_project / "svg_output"), "--format", canvas],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def validate(project_dir: Path, pptx_path: Path, qa_render_dir: Path, mode: str = "final", presentation_project: Path | None = None) -> list[Issue]:
    issues: list[Issue] = []
    level = "fail" if mode == "final" else "warn"
    if presentation_project is None:
        presentation_project = find_presentation_project(project_dir)
    if presentation_project is None:
        return [
            Issue(
                "fail",
                "presentation",
                "presentation_project",
                f"Presentation project directory not found; {presentation_project_hint(project_dir)}",
            )
        ]
    required = {
        "design_spec": presentation_project / "design_spec.md",
        "spec_lock": presentation_project / "spec_lock.md",
        "svg_output": presentation_project / "svg_output",
        "svg_final": presentation_project / "svg_final",
        "notes": presentation_project / "notes",
        "image_acquisition_manifest": presentation_project / "image_acquisition_manifest.json",
        "evidence_map": presentation_project / "evidence_map.json",
    }
    for name, path in required.items():
        if not path.exists():
            issues.append(Issue(level, "presentation", name, f"Missing high-fidelity artifact: {path}"))
    evidence_map = read_json(presentation_project / "evidence_map.json", {})
    pages = evidence_map.get("pages") or []
    if mode == "final":
        if evidence_map.get("workflow") != "evidence-map-to-editable-ppt-v1":
            issues.append(Issue("fail", "presentation", "evidence_map.workflow", "Formal PPT requires the deterministic evidence-map workflow."))
        if len(pages) != len(list((presentation_project / "svg_output").glob("*.svg"))):
            issues.append(Issue("fail", "presentation", "evidence_map.pages", "Evidence-map page count must match SVG page count."))
        families = [str(page.get("layout_family") or "") for page in pages]
        if len(set(families)) < 4:
            issues.append(Issue("fail", "presentation", "layout_variety", "Formal PPT requires at least four layout families."))
        for index in range(max(0, len(families) - 2)):
            if len(set(families[index:index + 3])) == 1:
                issues.append(Issue("fail", "presentation", "layout_repetition", f"Pages {index + 1}-{index + 3} repeat the same layout family."))
                break
        for index, page in enumerate(pages, start=1):
            for field in ("answer_first_title", "question", "evidence", "so_what", "layout_family"):
                if not page.get(field):
                    issues.append(Issue("fail", f"presentation.page{index}", field, "Evidence-map field is required."))
    if not pptx_path.exists():
        return [*issues, Issue("fail", "presentation", "pptx", f"Missing PPTX: {pptx_path}")]

    try:
        prs = Presentation(pptx_path)
        slide_count = len(prs.slides)
    except Exception as exc:
        return [*issues, Issue("fail", "presentation", "pptx", f"Unreadable PPTX: {exc}")]

    source_svgs = sorted((presentation_project / "svg_output").glob("*.svg"))
    final_svgs = sorted((presentation_project / "svg_final").glob("*.svg"))
    notes = [presentation_project / "notes" / f"{svg.stem}.md" for svg in source_svgs]
    if not 10 <= slide_count <= 18:
        issues.append(Issue("fail", "presentation", "slide_count", f"Expected 10-18 slides, found {slide_count}"))
    if len(source_svgs) != slide_count:
        issues.append(Issue("fail", "presentation", "svg_output", f"SVG/PPTX count mismatch: {len(source_svgs)}/{slide_count}"))
    if len(final_svgs) != slide_count:
        issues.append(Issue("fail", "presentation", "svg_final", f"Final SVG/PPTX count mismatch: {len(final_svgs)}/{slide_count}"))
    note_count = sum(path.exists() for path in notes)
    if note_count != slide_count:
        issues.append(Issue(level, "presentation", "speaker_notes", f"Notes/PPTX count mismatch: {note_count}/{slide_count}"))

    if source_svgs:
        canvas = "ppt169"
        first = source_svgs[0].read_text(encoding="utf-8", errors="replace")
        if "viewBox=\"0 0 1024 768\"" in first:
            canvas = "ppt43"
        rc, output = _run_quality_checker(presentation_project, canvas)
        if rc:
            issues.append(Issue("fail", "presentation", "svg_quality", output[-2000:] or "SVG quality checker failed"))

    acquisition = read_json(presentation_project / "image_acquisition_manifest.json", {})
    cover = acquisition.get("cover_decision") or {}
    path_taken = str(cover.get("path_taken") or "")
    if path_taken == "A_ai_image":
        media_hashes = pptx_media_hashes(pptx_path)
        generated = [item for item in acquisition.get("requests", []) if item.get("role") == "cover" and item.get("status") == "generated"]
        if not generated:
            issues.append(Issue("fail", "presentation", "cover_path_a", "Path A has no generated cover request"))
        for item in generated:
            path = Path(str(item.get("path") or ""))
            if not path.is_absolute():
                path = project_dir / path
            expected = str(item.get("sha256") or "")
            if not path.exists() or not expected or sha256_file(path) != expected:
                issues.append(Issue("fail", "presentation", "cover_hash", f"Path A cover is missing or stale: {path}"))
            elif expected not in media_hashes:
                issues.append(Issue("fail", "presentation", "cover_embed", "Path A cover hash is not embedded in the final PPTX"))
    elif path_taken in {"B_fallback", "B_light_consulting"}:
        reason = cover.get("fallback_reason") or {}
        if str(reason.get("code") or "") not in ALLOWED_FALLBACK_CODES:
            issues.append(Issue("fail", "presentation", "cover_fallback", "Path B requires a normalized EWO fallback code"))
    else:
        issues.append(Issue(level, "presentation", "cover_decision", "Image acquisition manifest has no terminal A/B cover decision"))

    for item in acquisition.get("requests", []):
        status = str(item.get("status") or "")
        if status == "generated":
            path = Path(str(item.get("path") or item.get("requested_output") or ""))
            if not path.is_absolute():
                path = project_dir / path
            expected = str(item.get("sha256") or "")
            if not path.exists() or not expected or sha256_file(path) != expected:
                issues.append(Issue("fail", str(item.get("request_id") or "image"), "image_hash", f"Generated image is missing or stale: {path}"))
        elif status in {"fallback_light_cover", "fallback_vector"}:
            fallback = item.get("fallback") or {}
            if str(fallback.get("code") or "") not in ALLOWED_FALLBACK_CODES:
                issues.append(Issue("fail", str(item.get("request_id") or "image"), "fallback", "Fallback image request lacks a normalized reason"))
        else:
            issues.append(Issue(level, str(item.get("request_id") or "image"), "status", f"Image request is not terminal: {status or 'missing'}"))

    trace = Path(str(pptx_path) + ".trace.json")
    if not trace.exists():
        issues.append(Issue(level, "presentation", "conversion_trace", f"Missing native SVG conversion trace: {trace}"))

    try:
        with zipfile.ZipFile(pptx_path) as archive:
            slide_xml = [archive.read(name) for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            transition_count = sum(b"<p:transition" in xml for xml in slide_xml)
            timing_count = sum(b"<p:timing" in xml for xml in slide_xml)
            placeholder_hits = sum(len(PLACEHOLDER_RE.findall(xml)) for xml in slide_xml)
        if transition_count == 0:
            issues.append(Issue(level, "presentation", "transitions", "No slide transition XML was found"))
        if timing_count == 0:
            issues.append(Issue(level, "presentation", "animations", "No entrance-animation timing XML was found"))
        if placeholder_hits:
            issues.append(Issue("fail", "presentation", "placeholders", f"Found {placeholder_hits} unresolved placeholder token(s)"))
    except zipfile.BadZipFile as exc:
        issues.append(Issue("fail", "presentation", "pptx_zip", str(exc)))

    rendered = sorted(qa_render_dir.glob("page-*.png")) if qa_render_dir.exists() else []
    rendered_pdf = next(iter(sorted(qa_render_dir.glob("*.pdf"))), None) if qa_render_dir.exists() else None
    if len(rendered) != slide_count:
        issues.append(Issue(level, "presentation", "rendered_pages", f"Rendered/PPTX count mismatch: {len(rendered)}/{slide_count}"))
    if rendered_pdf is None or rendered_pdf.stat().st_size == 0:
        issues.append(Issue(level, "presentation", "rendered_pdf", "Rendered QA PDF is missing or empty"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an embedded PPT Master SVG delivery.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--qa-render-dir", required=True)
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    parser.add_argument(
        "--presentation-project",
        default=None,
        help="High-fidelity presentation directory (auto-detected when omitted; CHANGELOG v1.2.6).",
    )
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    pptx = Path(args.pptx)
    if not pptx.is_absolute():
        pptx = project_dir / pptx
    qa = Path(args.qa_render_dir)
    if not qa.is_absolute():
        qa = project_dir / qa
    presentation = None
    if args.presentation_project:
        presentation = Path(args.presentation_project).resolve()
        if not presentation.is_absolute():
            presentation = project_dir / presentation
    issues = validate(project_dir, pptx.resolve(), qa.resolve(), args.mode, presentation)
    return print_report("High-fidelity PPT delivery", issues)


if __name__ == "__main__":
    raise SystemExit(main())
