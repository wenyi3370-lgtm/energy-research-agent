from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from _common import Issue, add_common_args, print_report, read_json
from presentation_production import (
    ALLOWED_FALLBACK_CODES,
    PIPELINE_ID,
    PLACEHOLDER_RE,
    pptx_media_hashes,
    resolve_path,
    sha256_file,
    slide_count,
    validate_raster,
)


def shape_area(shape) -> int:
    return max(0, int(shape.width)) * max(0, int(shape.height))


def is_visual_shape(shape, slide_area: int) -> bool:
    if shape.shape_type in {MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.GROUP, MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.TABLE}:
        return True
    if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
        area = shape_area(shape)
        if area <= 0 or area > slide_area * 0.92:
            return False
        return area >= slide_area * 0.004
    return False


def text_overlap_ratio(a, b) -> float:
    left = max(a.left, b.left)
    top = max(a.top, b.top)
    right = min(a.left + a.width, b.left + b.width)
    bottom = min(a.top + a.height, b.top + b.height)
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    return overlap / max(1, min(shape_area(a), shape_area(b)))


def validate(
    project_dir: Path,
    pptx_path: Path,
    qa_render_dir: Path,
    *,
    mode: str,
) -> list[Issue]:
    issues: list[Issue] = []
    presentation_project = project_dir / "presentation_project"
    required = {
        "design_spec": presentation_project / "design_spec.md",
        "spec_lock": presentation_project / "spec_lock.json",
        "slide_registry": presentation_project / "slide_registry.json",
        "build_manifest": presentation_project / "build_manifest.json",
        "image_manifest": presentation_project / "image_acquisition_manifest.json",
    }
    for name, path in required.items():
        if not path.exists():
            issues.append(Issue("fail", "presentation", name, f"Missing embedded presentation artifact: {path}"))
    if not pptx_path.exists():
        return [*issues, Issue("fail", "presentation", "pptx", f"Missing PPTX: {pptx_path}")]
    try:
        prs = Presentation(pptx_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return [*issues, Issue("fail", "presentation", "pptx", f"Unreadable PPTX: {exc}")]
    slides = list(prs.slides)
    if mode == "final" and not 10 <= len(slides) <= 18:
        issues.append(Issue("fail", "presentation", "slide_count", "Final executive deck must contain 10-18 slides"))

    registry = read_json(required["slide_registry"], {}).get("slides", []) if required["slide_registry"].exists() else []
    if len(registry) != len(slides):
        issues.append(Issue("fail", "presentation", "slide_registry", "Slide registry count differs from PPTX slide count"))
    build_manifest = read_json(required["build_manifest"], {}) if required["build_manifest"].exists() else {}
    if build_manifest.get("pipeline_id") != PIPELINE_ID:
        issues.append(Issue("fail", "presentation", "pipeline_id", f"Expected {PIPELINE_ID}"))
    if not build_manifest.get("serial_slide_generation"):
        issues.append(Issue("fail", "presentation", "serial_generation", "Serial slide generation was not recorded"))
    if build_manifest.get("output_sha256") != sha256_file(pptx_path):
        issues.append(Issue("fail", "presentation", "build_hash", "PPTX differs from the registered build artifact"))

    slide_area = int(prs.slide_width) * int(prs.slide_height)
    total_chars = 0
    for index, slide in enumerate(slides, start=1):
        text_shapes = []
        slide_text = []
        visual_count = 0
        for shape in slide.shapes:
            if shape.left < -1000 or shape.top < -1000 or shape.left + shape.width > prs.slide_width + 1000 or shape.top + shape.height > prs.slide_height + 1000:
                issues.append(Issue("fail", f"slide-{index}", "bounds", f"Shape extends beyond the slide: {shape.name}"))
            if is_visual_shape(shape, slide_area):
                visual_count += 1
            text = str(getattr(shape, "text", "") or "").strip()
            if text:
                slide_text.append(text)
                if PLACEHOLDER_RE.search(text):
                    issues.append(Issue("fail", f"slide-{index}", "placeholder", f"Placeholder text remains: {text[:80]}"))
                if getattr(shape, "has_text_frame", False):
                    text_shapes.append(shape)
                    for paragraph in shape.text_frame.paragraphs:
                        for run in paragraph.runs:
                            if run.text.strip() and run.font.size and run.font.size.pt < 7:
                                issues.append(Issue("fail", f"slide-{index}", "font_size", f"Text below 7 pt: {run.text[:40]}"))
        total_chars += sum(len(value) for value in slide_text)
        record = registry[index - 1] if index - 1 < len(registry) else {}
        if not str(record.get("visual_kind") or "").strip() or visual_count == 0:
            issues.append(Issue("fail", f"slide-{index}", "visual", "Every slide must contain a substantive visual element"))
        if index not in {1, len(slides)}:
            if not record.get("answer_first"):
                issues.append(Issue("fail", f"slide-{index}", "answer_first", "Content slide is not registered as answer-first"))
            if str(record.get("title") or "") not in "\n".join(slide_text):
                issues.append(Issue("fail", f"slide-{index}", "title", "Registered answer-first title is not present on slide"))
            if "来源：" not in "\n".join(slide_text):
                issues.append(Issue("fail", f"slide-{index}", "source_footer", "Content slide is missing the source/update/limitation footer"))
        for left_index, left in enumerate(text_shapes):
            for right in text_shapes[left_index + 1 :]:
                if text_overlap_ratio(left, right) > 0.20:
                    issues.append(Issue("fail", f"slide-{index}", "text_overlap", f"Text boxes materially overlap: {left.name} / {right.name}"))
                    break

    if mode == "final" and total_chars < len(slides) * 150:
        issues.append(Issue("fail", "presentation", "content_density", "Deck text density is below the executive-report floor"))

    media_hashes = pptx_media_hashes(pptx_path)
    for record in registry:
        for image in record.get("used_images") or []:
            image_path = resolve_path(str(image.get("path") or ""), project_dir)
            if not image_path.exists():
                issues.append(Issue("fail", record.get("slide_id", "slide"), "image", f"Registered image is missing: {image_path}"))
                continue
            digest = sha256_file(image_path)
            if digest != image.get("sha256") or digest not in media_hashes:
                issues.append(Issue("fail", record.get("slide_id", "slide"), "image_hash", "Registered image hash is stale or not embedded in the PPTX"))

    acquisition = read_json(required["image_manifest"], {}) if required["image_manifest"].exists() else {}
    cover = acquisition.get("cover_decision") or {}
    if cover.get("default_path") != "A_ai_image":
        issues.append(Issue("fail", "cover", "default_path", "Cover default must remain A_ai_image"))
    path_taken = cover.get("path_taken")
    if path_taken == "A_ai_image":
        request_id = str(cover.get("ai_image_request_id") or "")
        request = next((item for item in acquisition.get("requests", []) if item.get("request_id") == request_id), None)
        if not request or request.get("status") != "generated":
            issues.append(Issue("fail", "cover", "ai_image", "Path A requires a successful generated cover request"))
        else:
            image_path = resolve_path(str(request.get("path") or ""), project_dir)
            try:
                _, digest = validate_raster(image_path)
                if digest not in media_hashes:
                    issues.append(Issue("fail", "cover", "embedded_image", "Path A image is not embedded in the PPTX"))
            except (OSError, ValueError) as exc:
                issues.append(Issue("fail", "cover", "ai_image", str(exc)))
    elif path_taken == "B_light_consulting":
        fallback = cover.get("fallback_reason") or {}
        if fallback.get("code") not in ALLOWED_FALLBACK_CODES or not str(fallback.get("detail") or "").strip():
            issues.append(Issue("fail", "cover", "fallback_reason", "Path B requires a normalized EWO failure reason"))
    else:
        issues.append(Issue("fail", "cover", "path_taken", "Cover path must be A_ai_image or B_light_consulting"))
    for request in acquisition.get("requests", []):
        status = request.get("status")
        if status not in {"generated", "fallback_vector", "fallback_light_cover"}:
            issues.append(Issue("fail", request.get("request_id", "image"), "status", "Image request did not reach a terminal state"))
        if status and status.startswith("fallback"):
            fallback = request.get("fallback") or {}
            if fallback.get("code") not in ALLOWED_FALLBACK_CODES:
                issues.append(Issue("fail", request.get("request_id", "image"), "fallback", "Invalid fallback reason code"))

    rendered = sorted(qa_render_dir.glob("page-*.png")) if qa_render_dir.exists() else []
    if mode == "final":
        if len(rendered) != len(slides):
            issues.append(Issue("fail", "presentation", "rendered_pages", "Every slide must have a current rendered QA page"))
        pdfs = [path for path in qa_render_dir.glob("*.pdf") if path.stat().st_size > 0] if qa_render_dir.exists() else []
        if not pdfs:
            issues.append(Issue("fail", "presentation", "rendered_pdf", "Rendered QA PDF is missing or empty"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the embedded executive-presentation production contract.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--qa-render-dir", required=True)
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    add_common_args(parser)
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    pptx_path = resolve_path(args.pptx, project_dir)
    qa_render_dir = resolve_path(args.qa_render_dir, project_dir)
    issues = validate(project_dir, pptx_path, qa_render_dir, mode=args.mode)
    return print_report("PPT delivery validation", issues, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
