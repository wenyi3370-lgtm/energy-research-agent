from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from _common import Issue, add_common_args, print_report
from presentation_production import ALLOWED_FALLBACK_CODES, PIPELINE_ID


STAGE_FILES = {
    "0": ["project_manifest.json", "policy_snapshot/collection_quantity_policy.yaml", "research_outline.md", "00_Research_Approval.csv", "00_Source_Ledger.csv", "02_Web_Collection_Tasks.csv", "11_Evidence_Issues.csv"],
    "1": ["00_Source_Ledger.csv", "01_Market_Scan.csv"],
    "2": ["02_Competitor_List.csv", "03_Model_Identifier_Check.csv"],
    "3": ["04_Product_Parameters.csv"],
    "4": ["00_Source_Ledger.csv", "05_Pricing_Channel.csv", "06_Channel_Service.csv", "07_Raw_Reviews.csv", "08_Review_Coding.csv"],
    "5": ["deliverables/*.xlsx"],
    "6": ["12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"],
    "7": ["09_Integrated_Matrix.csv", "10_SWOT_Opportunity.csv", "deliverables/*.docx"],
    "8": ["00_Source_Ledger.csv", "09_Integrated_Matrix.csv"],
}


def detect_raster_format(path: Path) -> str | None:
    with path.open("rb") as handle:
        header = handle.read(12)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def parse_stages(value: str) -> list[str]:
    value = value.strip()
    if "-" in value:
        start, end = value.split("-", 1)
        return [str(i) for i in range(int(start), int(end) + 1)]
    return [part.strip() for part in value.split(",") if part.strip()]


def validate(project_dir: Path, stages: list[str], strict_final_files: bool) -> list[Issue]:
    issues: list[Issue] = []
    for stage in stages:
        for filename in STAGE_FILES.get(stage, []):
            if "*" in filename:
                if not any(project_dir.glob(filename)):
                    issues.append(Issue("fail", f"stage-{stage}", filename, "Required stage artifact is missing"))
            else:
                path = project_dir / filename
                if not path.exists():
                    issues.append(Issue("fail", f"stage-{stage}", filename, "Required stage artifact is missing"))

    if strict_final_files:
        deliverables = project_dir / "deliverables"
        required_suffixes = [".docx", ".xlsx", ".pptx"]
        for suffix in required_suffixes:
            if not any(deliverables.glob(f"*{suffix}")):
                issues.append(Issue("fail", "final", suffix, f"No final deliverable with suffix {suffix} found in deliverables/"))
        ppt_manifest_path = deliverables / "ppt_production_manifest.json"
        if not ppt_manifest_path.exists():
            issues.append(Issue("fail", "final", "ppt_production_manifest.json", "Missing embedded presentation QA manifest"))
        else:
            try:
                manifest = json.loads(ppt_manifest_path.read_text(encoding="utf-8-sig"))
                ppt_files = [path for path in deliverables.glob("*.pptx")
                             if "draft" not in path.stem.lower() and not path.name.startswith("~$")]
                if manifest.get("status") != "passed":
                    issues.append(Issue("fail", "final", "ppt_manifest_status", "PPT QA manifest is not passed"))
                if manifest.get("pipeline_id") != PIPELINE_ID:
                    issues.append(Issue("fail", "final", "ppt_pipeline", f"Final PPT was not registered through {PIPELINE_ID}"))
                if manifest.get("external_presentation_skill_required") is not False:
                    issues.append(Issue("fail", "final", "ppt_self_contained", "Final PPT still declares an external presentation Skill dependency"))
                if not manifest.get("cover_prompt_compliance"):
                    issues.append(Issue("fail", "final", "ppt_cover", "Cover prompt compliance is not passed"))
                cover_decision = manifest.get("cover_path_decision") or {}
                cover_path = cover_decision.get("path_taken")
                if cover_decision.get("default_path") != "A_ai_image":
                    issues.append(Issue("fail", "final", "ppt_cover_default", "Cover policy must record A_ai_image as the default path"))
                if cover_path == "A_ai_image":
                    request_id = str(cover_decision.get("ai_image_request_id") or "").strip()
                    ai_image = next(
                        (item for item in manifest.get("image_requests", []) if item.get("request_id") == request_id),
                        {},
                    )
                    image_path_raw = str(ai_image.get("path") or "").strip()
                    image_hash = str(ai_image.get("sha256") or "").strip()
                    image_format = str(ai_image.get("format") or "").strip()
                    if not image_path_raw or not image_hash:
                        issues.append(Issue("fail", "final", "ppt_cover_ai_image", "Path A must record the AI cover image path and SHA256"))
                    else:
                        image_path = Path(image_path_raw)
                        if not image_path.is_absolute():
                            image_path = project_dir / image_path
                        format_by_suffix = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
                        expected_format = format_by_suffix.get(image_path.suffix.lower())
                        if expected_format is None or image_format != expected_format:
                            issues.append(Issue("fail", "final", "ppt_cover_format", "Path A cover must be a registered PNG/JPEG/WebP raster image"))
                        elif not image_path.exists():
                            issues.append(Issue("fail", "final", "ppt_cover_ai_image", "Registered AI cover image is missing"))
                        elif detect_raster_format(image_path) != expected_format:
                            issues.append(Issue("fail", "final", "ppt_cover_format", "Registered cover bytes do not match the PNG/JPEG/WebP format"))
                        elif hashlib.sha256(image_path.read_bytes()).hexdigest() != image_hash:
                            issues.append(Issue("fail", "final", "ppt_cover_ai_image", "Registered AI cover image hash has changed"))
                elif cover_path == "B_light_consulting":
                    fallback_reason = cover_decision.get("fallback_reason") or {}
                    if fallback_reason.get("code") not in ALLOWED_FALLBACK_CODES or not str(fallback_reason.get("detail") or "").strip():
                        issues.append(Issue("fail", "final", "ppt_cover_fallback", "Path B must record a specific AI generation failure reason"))
                else:
                    issues.append(Issue("fail", "final", "ppt_cover_path", "Cover path must be A_ai_image or B_light_consulting"))
                if ppt_files:
                    pptx = ppt_files[0]
                    digest = hashlib.sha256(pptx.read_bytes()).hexdigest()
                    if digest != manifest.get("final_pptx_sha256"):
                        issues.append(Issue("fail", "final", "ppt_hash", "PPT hash differs from registered QA artifact"))
                    with zipfile.ZipFile(pptx) as archive:
                        slides = sum(1 for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
                    if manifest.get("pages_inspected") != slides or manifest.get("rendered_page_count") != slides:
                        issues.append(Issue("fail", "final", "ppt_page_inspection", "Every slide must be rendered and inspected"))
                    if int(manifest.get("visual_fix_cycle_count") or 0) < 1:
                        issues.append(Issue("fail", "final", "ppt_visual_fix_cycle", "At least one render-inspect-fix-rerender cycle is required"))
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                issues.append(Issue("fail", "final", "ppt_production_manifest.json", f"Invalid PPT QA manifest: {exc}"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate required stage artifacts exist.")
    parser.add_argument("--project-dir", default=".", help="Project directory.")
    parser.add_argument("--stages", default="0-8", help="Stage range or list, e.g. 0-8 or 1,2,3,6.")
    parser.add_argument("--strict-final-files", action="store_true", help="Require final .docx, .xlsx, and .pptx in deliverables/.")
    add_common_args(parser)
    args = parser.parse_args()

    issues = validate(Path(args.project_dir).resolve(), parse_stages(args.stages), args.strict_final_files)
    return print_report("Deliverable validation", issues, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
