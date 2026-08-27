from __future__ import annotations

import argparse
from pathlib import Path

from pptx import Presentation

from _common import find_presentation_project, now_iso, read_json, write_json
from validate_high_fidelity_ppt_delivery import PIPELINE_ID, sha256_file, stored_path, validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Register an embedded PPT Master SVG delivery after visual QA.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--qa-render-dir", required=True)
    parser.add_argument("--pages-inspected", type=int, required=True)
    parser.add_argument("--confirm-all-pages-inspected", action="store_true")
    parser.add_argument("--visual-fix-cycle-count", type=int, required=True)
    parser.add_argument("--visual-inspection-notes", required=True)
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
    pptx = pptx.resolve()
    qa = Path(args.qa_render_dir)
    if not qa.is_absolute():
        qa = project_dir / qa
    qa = qa.resolve()
    slide_count = len(Presentation(pptx).slides)
    if not args.confirm_all_pages_inspected:
        raise ValueError("Final registration requires --confirm-all-pages-inspected")
    if args.pages_inspected != slide_count:
        raise ValueError(f"Inspected page count {args.pages_inspected} does not match slide count {slide_count}")
    if args.visual_fix_cycle_count < 1:
        raise ValueError("At least one render-inspect-fix-rerender cycle is required")
    if len(args.visual_inspection_notes.strip()) < 20:
        raise ValueError("Visual inspection notes must record the actual review and fix outcome")

    presentation_project = None
    if args.presentation_project:
        presentation_project = Path(args.presentation_project).resolve()
        if not presentation_project.is_absolute():
            presentation_project = project_dir / presentation_project
    issues = validate(project_dir, pptx, qa, mode="final", presentation_project=presentation_project)
    failures = [issue for issue in issues if issue.level == "fail"]
    if failures:
        detail = "; ".join(f"{item.field}: {item.message}" for item in failures[:12])
        raise ValueError("High-fidelity PPT validation failed before registration: " + detail)

    if presentation_project is None:
        presentation_project = find_presentation_project(project_dir)
    if presentation_project is None:
        raise ValueError("Presentation project directory not found after validation")
    acquisition = read_json(presentation_project / "image_acquisition_manifest.json", {})
    summary = presentation_project / "qa" / "final_qa_summary.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        "# Final High-Fidelity Presentation QA Summary\n\n"
        f"- Pipeline: {PIPELINE_ID}\n"
        f"- PPTX: {stored_path(pptx, project_dir)}\n"
        f"- Slides rendered and inspected: {slide_count}\n"
        f"- Fix-and-verify cycles: {args.visual_fix_cycle_count}\n"
        f"- Inspection notes: {args.visual_inspection_notes.strip()}\n"
        "- SVG quality, native conversion trace, animations, placeholders, and page rendering: passed\n",
        encoding="utf-8",
    )
    manifest = {
        "registered_at": now_iso(),
        "status": "passed",
        "pipeline_id": PIPELINE_ID,
        "renderer_id": "pptmaster-native-drawingml",
        "formal_route": "handwritten-svg",
        "fallback_route": False,
        "external_presentation_skill_required": False,
        "legacy_quality_lineage": ["ppt-master", "pptx", "ewo-image-generate"],
        "final_pptx_path": stored_path(pptx, project_dir),
        "final_pptx_sha256": sha256_file(pptx),
        "slide_count": slide_count,
        "sequential_main_agent_svg_generation_required": True,
        "spec_lock_reread_per_page_required": True,
        "svg_quality_gate": "passed",
        "native_conversion_trace": stored_path(Path(str(pptx) + ".trace.json"), project_dir),
        "cover_prompt_compliance": bool(
            (acquisition.get("cover_compliance_audit") or {}).get("status") == "passed"
        ),
        "cover_path_decision": acquisition.get("cover_decision"),
        "image_requests": acquisition.get("requests", []),
        "pages_inspected": args.pages_inspected,
        "rendered_page_count": len(list(qa.glob("page-*.png"))),
        "visual_fix_cycle_count": args.visual_fix_cycle_count,
        "visual_inspection_notes": args.visual_inspection_notes.strip(),
        "qa_render_dir": stored_path(qa, project_dir),
        "artifacts": {
            "design_spec": stored_path(presentation_project / "design_spec.md", project_dir),
            "spec_lock": stored_path(presentation_project / "spec_lock.md", project_dir),
            "svg_output": stored_path(presentation_project / "svg_output", project_dir),
            "svg_final": stored_path(presentation_project / "svg_final", project_dir),
            "speaker_notes": stored_path(presentation_project / "notes", project_dir),
            "image_acquisition_manifest": stored_path(presentation_project / "image_acquisition_manifest.json", project_dir),
            "evidence_map": stored_path(presentation_project / "evidence_map.json", project_dir),
            "final_qa_summary": stored_path(summary, project_dir),
        },
    }
    output = project_dir / "deliverables" / "ppt_production_manifest.json"
    write_json(output, manifest)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
