from __future__ import annotations

import argparse
from pathlib import Path

from _common import now_iso, read_json, write_json
from presentation_production import PIPELINE_ID, RENDERER_ID, resolve_path, sha256_file, slide_count, stored_path
from validate_ppt_delivery import validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Register an embedded presentation deliverable after full visual QA.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--qa-render-dir", required=True)
    parser.add_argument("--pages-inspected", type=int, required=True)
    parser.add_argument("--confirm-all-pages-inspected", action="store_true")
    parser.add_argument(
        "--visual-fix-cycle-count",
        type=int,
        required=True,
        help="Number of completed render-inspect-fix-rerender cycles; final registration requires at least one.",
    )
    parser.add_argument("--visual-inspection-notes", required=True)
    parser.add_argument(
        "--fallback-reason",
        required=True,
        help="Concrete reason the formal handwritten-SVG route could not be used, or that the user explicitly requested this fallback.",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    pptx_path = resolve_path(args.pptx, project_dir)
    qa_render_dir = resolve_path(args.qa_render_dir, project_dir)
    if not args.confirm_all_pages_inspected:
        raise ValueError("Final registration requires --confirm-all-pages-inspected")
    slides = slide_count(pptx_path)
    if args.pages_inspected != slides:
        raise ValueError(f"Inspected page count {args.pages_inspected} does not match slide count {slides}")
    if args.visual_fix_cycle_count < 1:
        raise ValueError("At least one render-inspect-fix-rerender cycle is required")
    if len(args.visual_inspection_notes.strip()) < 20:
        raise ValueError("Visual inspection notes must record the actual review/fix outcome")
    if len(args.fallback_reason.strip()) < 12:
        raise ValueError("Fallback reason must concretely explain why the formal handwritten-SVG route was not used")

    issues = validate(project_dir, pptx_path, qa_render_dir, mode="final")
    fails = [issue for issue in issues if issue.level == "fail"]
    if fails:
        detail = "; ".join(f"{item.row}/{item.field}: {item.message}" for item in fails[:12])
        raise ValueError("PPT validation failed before registration: " + detail)

    presentation_project = project_dir / "presentation_project"
    acquisition = read_json(presentation_project / "image_acquisition_manifest.json", {})
    build_manifest = read_json(presentation_project / "build_manifest.json", {})
    rendered = sorted(qa_render_dir.glob("page-*.png"))
    artifacts = {
        "design_spec": presentation_project / "design_spec.md",
        "spec_lock": presentation_project / "spec_lock.json",
        "slide_registry": presentation_project / "slide_registry.json",
        "build_manifest": presentation_project / "build_manifest.json",
        "image_acquisition_manifest": presentation_project / "image_acquisition_manifest.json",
        "final_qa_summary": presentation_project / "qa" / "final_qa_summary.md",
    }
    artifacts["final_qa_summary"].parent.mkdir(parents=True, exist_ok=True)
    artifacts["final_qa_summary"].write_text(
        "# Final Presentation QA Summary\n\n"
        f"- PPTX: {stored_path(pptx_path, project_dir)}\n"
        f"- Slides rendered and inspected: {slides}\n"
        f"- Fix-and-verify cycles: {args.visual_fix_cycle_count}\n"
        f"- Inspection notes: {args.visual_inspection_notes.strip()}\n"
        "- Mechanical validation: passed\n"
        "- Placeholder scan: passed\n",
        encoding="utf-8",
    )
    manifest = {
        "registered_at": now_iso(),
        "status": "passed",
        "pipeline_id": PIPELINE_ID,
        "renderer_id": RENDERER_ID,
        "formal_route": "python-native-fallback",
        "fallback_route": True,
        "fallback_reason": args.fallback_reason.strip(),
        "embedded_components": [
            "resolve_presentation_images.py",
            "build_executive_presentation.py",
            "validate_ppt_delivery.py",
            "libreoffice_render.py",
            "create_page_contact_sheet.py",
            "scan_office_placeholders.py",
        ],
        "legacy_quality_lineage": ["ppt-master", "pptx", "ewo-image-generate"],
        "external_presentation_skill_required": False,
        "final_pptx_path": stored_path(pptx_path, project_dir),
        "final_pptx_sha256": sha256_file(pptx_path),
        "slide_count": slides,
        "serial_pipeline": bool(build_manifest.get("serial_slide_generation")),
        "cover_prompt_compliance": True,
        "cover_path_decision": acquisition.get("cover_decision"),
        "image_requests": acquisition.get("requests", []),
        "pages_inspected": args.pages_inspected,
        "rendered_page_count": len(rendered),
        "visual_fix_cycle_count": args.visual_fix_cycle_count,
        "visual_inspection_notes": args.visual_inspection_notes.strip(),
        "qa_render_dir": stored_path(qa_render_dir, project_dir),
        "artifacts": {name: stored_path(path, project_dir) for name, path in artifacts.items()},
    }
    output = project_dir / "deliverables" / "ppt_production_manifest.json"
    write_json(output, manifest)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
