from __future__ import annotations

import argparse
import json
from pathlib import Path

from figure_production import validate_figure_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Register explicit visual inspection for an embedded figure bundle.")
    parser.add_argument("manifest", help="Path to one .theme.json manifest")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--confirm-visual-inspected", action="store_true")
    parser.add_argument("--accept-automated-visual-qa", action="store_true", help="Use deterministic geometry QA when the executing model has no vision")
    parser.add_argument("--issue", action="append", default=[])
    args = parser.parse_args()

    if not (args.confirm_visual_inspected or args.accept_automated_visual_qa):
        raise ValueError("Registration requires human visual inspection or --accept-automated-visual-qa")
    if args.issue:
        raise ValueError("A final figure cannot be registered while visual issues remain")

    project_dir = Path(args.project_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = project_dir / manifest_path
    manifest_path = manifest_path.resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)

    draft_issues = validate_figure_manifest(manifest_path, project_dir=project_dir, final=False)
    failures = [issue for issue in draft_issues if issue["level"] == "fail"]
    if failures:
        raise ValueError("Figure cannot be registered: " + json.dumps(failures, ensure_ascii=False))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    qa = manifest.setdefault("qa", {})
    if args.confirm_visual_inspected:
        qa["visual_inspection"] = {
            "status": "passed",
            "inspector_confirmed": True,
            "issues": [],
        }
    else:
        automated = qa.get("automated_visual_qa") or {}
        if automated.get("status") != "passed" or automated.get("issues"):
            raise ValueError("Automated visual QA has not passed; text-only registration is forbidden")
        qa["visual_inspection"] = {
            "status": "not_applicable_text_only",
            "inspector_confirmed": False,
            "issues": [],
            "substitute": "qa.automated_visual_qa",
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    final_issues = validate_figure_manifest(manifest_path, project_dir=project_dir, final=True)
    failures = [issue for issue in final_issues if issue["level"] == "fail"]
    if failures:
        raise ValueError("Registered figure still fails final validation: " + json.dumps(failures, ensure_ascii=False))
    print(f"Registered figure delivery: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
