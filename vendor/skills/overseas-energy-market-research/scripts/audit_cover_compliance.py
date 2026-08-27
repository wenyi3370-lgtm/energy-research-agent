# -*- coding: utf-8 -*-
"""Audit the Path B light-consulting fallback cover against the spec.

This is the *real* cover-compliance audit for the EWO-unavailable fallback
route.  The final PPT validator (`validate_deliverables.py`) only checks the
boolean `cover_prompt_compliance` recorded in the production manifest, so
without this audit that boolean can silently drift from the actual cover
design.  Run this after the cover SVG is written and before
`register_high_fidelity_ppt_delivery.py`; the register step reads the audit
result (it no longer hard-codes True).

Path B spec (light consulting, per AGENTS.md global preference):
- pure white background (no deep-navy cover gradient)
- deep royal-blue side ribbon
- serif main title + sans-serif body
- conclusion-style action bar
- three-column meta info
- footer with source + date

Usage:
    python audit_cover_compliance.py --project-dir <project> [--cover <path>]

Exit code 0 when passed, 1 when any check fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from _common import find_presentation_project, now_iso, presentation_project_hint, read_json, write_json
except ImportError:  # pragma: no cover
    def now_iso() -> str:
        import datetime
        return datetime.datetime.now().isoformat(timespec="seconds")

    def read_json(path, default=None):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return default if default is not None else {}

    def write_json(path, data):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def find_presentation_project(project_dir, explicit=None):  # pragma: no cover
        legacy = Path(project_dir) / "presentation_project"
        if legacy.is_dir():
            return legacy
        return None

    def presentation_project_hint(project_dir):  # pragma: no cover
        return "candidates: presentation_project/"


def _right_side_illustration(svg: str) -> bool:
    """True when any <g> is translated into the right-side illustration region
    (x offset >= 500). Legit cover furniture (meta row, footer) sits at x < 500;
    the old energy-flow scene lived at translate(620/890, ...)."""
    for m in re.finditer(r'<g[^>]*transform="translate\(\s*([\d.]+)\s*,', svg):
        try:
            if float(m.group(1)) >= 500:
                return True
        except ValueError:
            continue
    return False


def audit_cover(svg: str) -> dict:
    """Check the cover SVG against the Path B light-consulting spec."""
    checks = {
        "white_background": bool(
            re.search(
                r'<rect[^>]*x="0"[^>]*y="0"[^>]*width="1280"[^>]*height="720"[^>]*fill="#FFFFFF"',
                svg,
            )
        ),
        # a deep-navy gradient cover belongs to Path A; reject it for Path B
        "no_navy_gradient_background": not (
            "coverGradient" in svg and 'stop-color="#0B1F4B"' in svg
        ),
        "royal_blue_ribbon": bool(
            (re.search(r'width="1[48]"[^>]*fill="#123A7A"', svg))
            or (re.search(r'width="1[48]"[^>]*fill="#1B365D"', svg))
        ),
        "serif_title": bool(
            re.search(r'<text[^>]*font-family="[^"]*(?:Georgia|SimSun)[^"]*"[^>]*font-size="(?:4[5-9]|5[0-9])', svg)
        ),
        "conclusion_bar": bool(
            re.search(r'<(?:rect|path)[^>]*fill="#F3F6FA"[^>]*stroke="#123A7A"', svg)
            or re.search(r'<(?:rect|path)[^>]*fill="url\(#[^)]*Gradient\)"', svg)
        ),
        "meta_columns": len(re.findall(r'font-size="1[12]" fill="#6B7280"', svg)) >= 3,
        "footer": "数据来源" in svg,
        # Path B is a clean consulting cover: NO illustration (no energy-flow
        # scene, no AI art, no hand-drawn graphic elements beyond the ribbon).
        # Detect by known illustration markers AND by any translated <g> group
        # placed in the right-side illustration region (x >= 500): the old
        # energy-flow scene sat at translate(620/890,...) with labels that
        # half-clip off-canvas. Legit elements (meta row) live at x < 500.
        "no_illustration": (
            not any(
                marker in svg for marker in (
                    "translate(620", "translate(890", "FBBF24", "sunGlow", "M 558",
                )
            )
            and not _right_side_illustration(svg)
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "audit_method": "path-b-light-consulting-spec-v1",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", default=".", help="Research project directory")
    parser.add_argument(
        "--cover",
        default=None,
        help="Cover SVG path (default: auto-detected presentation project's svg_output/slide_01_cover.svg)",
    )
    parser.add_argument(
        "--presentation-project",
        default=None,
        help="High-fidelity presentation directory (auto-detected when omitted; CHANGELOG v1.2.6).",
    )
    args = parser.parse_args()
    root = Path(args.project_dir).expanduser().resolve()
    if args.presentation_project:
        presentation = Path(args.presentation_project).expanduser().resolve()
        if not presentation.is_absolute():
            presentation = root / args.presentation_project
    else:
        presentation = find_presentation_project(root)
    if presentation is None:
        print("ERROR: presentation project directory not found; %s" % presentation_project_hint(root))
        return 2
    cover_path = Path(args.cover) if args.cover else (presentation / "svg_output" / "slide_01_cover.svg")
    if not cover_path.exists():
        print("ERROR: cover SVG not found: %s" % cover_path)
        return 2
    svg = cover_path.read_text(encoding="utf-8")
    result = audit_cover(svg)
    print("封面审计:", json.dumps(result, ensure_ascii=False, indent=1))
    if result["status"] != "passed":
        failed = [k for k, v in result["checks"].items() if not v]
        print("FAILED checks:", failed)
        return 1
    # persist into image acquisition manifest for the register step
    im_path = presentation / "image_acquisition_manifest.json"
    im = read_json(im_path, {})
    im["cover_compliance_audit"] = {
        "audited_at": now_iso(),
        "audit_method": result["audit_method"],
        "status": result["status"],
        "checks": result["checks"],
    }
    write_json(im_path, im)
    print("image_acquisition_manifest 已记录封面审计:", im_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
