from __future__ import annotations

from pathlib import Path

from _common import Issue, read_json
from presentation_production import resolve_path, sha256_file
from validate_high_fidelity_ppt_delivery import PIPELINE_ID as HIGH_FIDELITY_PIPELINE_ID
from validate_high_fidelity_ppt_delivery import validate as validate_high_fidelity
from validate_ppt_delivery import validate as validate_native_fallback


def validate(project_dir: Path, mode: str) -> list[Issue]:
    manifest_path = project_dir / "deliverables" / "ppt_production_manifest.json"
    if not manifest_path.exists():
        return [Issue("fail" if mode == "final" else "warn", "presentation", "delivery_manifest", "Missing PPT production manifest")]
    manifest = read_json(manifest_path, {})
    if manifest.get("status") != "passed":
        return [Issue("fail", "presentation", "status", "PPT production manifest is not passed")]
    pptx = resolve_path(str(manifest.get("final_pptx_path") or ""), project_dir)
    qa = resolve_path(str(manifest.get("qa_render_dir") or ""), project_dir)
    if not pptx.exists():
        return [Issue("fail", "presentation", "pptx", f"Registered PPTX is missing: {pptx}")]
    if manifest.get("final_pptx_sha256") != sha256_file(pptx):
        return [Issue("fail", "presentation", "hash", "Registered PPTX hash is stale")]
    pipeline = str(manifest.get("pipeline_id") or "")
    if pipeline == HIGH_FIDELITY_PIPELINE_ID:
        issues = validate_high_fidelity(project_dir, pptx, qa, mode=mode)
    else:
        issues = validate_native_fallback(project_dir, pptx, qa, mode=mode)
        if not manifest.get("fallback_route"):
            issues.append(Issue("fail", "presentation", "route", "Non-SVG PPT must be explicitly registered as a fallback route"))
    if int(manifest.get("pages_inspected") or 0) != int(manifest.get("slide_count") or -1):
        issues.append(Issue("fail", "presentation", "inspection", "Not every registered slide was inspected"))
    if int(manifest.get("visual_fix_cycle_count") or 0) < 1:
        issues.append(Issue("fail", "presentation", "fix_cycle", "At least one visual fix-and-rerender cycle is required"))
    return issues
