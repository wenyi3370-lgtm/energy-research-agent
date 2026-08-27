from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from docx import Document

from _common import read_json, write_json
from check_word_char_count import collect_text
from figure_production import validate_figure_manifest
from scan_office_placeholders import scan_file
from validate_word_delivery import (
    REQUIRED_CHART_THEME,
    REQUIRED_FIGURE_ROUTING,
    REQUIRED_TABLE_HEADER_FILL,
    REQUIRED_TABLE_HEADER_RULE_COLOR,
    REQUIRED_TABLE_OUTER_RULE_COLOR,
    sha256,
    package_media_hashes,
    validate_centering_contract,
    validate_data_source_label,
    validate_table_caption_pagination_contract,
    validate_table_geometry_contract,
    validate_table_text_contract,
    validate_table_visual_contract,
)


WORD_PIPELINE_ID = "embedded-word-production-v1"
WORD_COMPONENTS = [
    "build_template_report.py",
    "polish_word_ib_style.py",
    "verify_word_ib_style.py",
    "validate_word_delivery.py",
    "libreoffice_render.py+pymupdf",
    "create_page_contact_sheet.py",
    "scan_office_placeholders.py",
    "figure_production.py",
    "validate_figure_delivery.py",
    "insert_approved_figures.py",
]


def _stored_path(path: Path, project_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def _render_pages(render_dir: Path) -> list[Path]:
    pages = sorted(
        render_dir.glob("page-*.png"),
        key=lambda path: int(path.stem.split("-")[-1]),
    )
    expected = list(range(1, len(pages) + 1))
    actual = [int(path.stem.split("-")[-1]) for path in pages]
    if actual != expected:
        raise ValueError(f"Rendered page sequence is incomplete: {actual}")
    if any(path.stat().st_size <= 0 for path in pages):
        raise ValueError("One or more rendered page PNGs are empty")
    return pages


def _run_structural_gates(docx: Path, report_path: Path, min_chars: int) -> int:
    gates = {
        "centering": validate_centering_contract,
        "table_text": validate_table_text_contract,
        "table_visual": validate_table_visual_contract,
        "table_caption": validate_table_caption_pagination_contract,
        "table_geometry": validate_table_geometry_contract,
        "data_source_label": validate_data_source_label,
    }
    failures: list[str] = []
    for name, gate in gates.items():
        problems = gate(docx)
        if problems:
            failures.append(f"{name}: " + " ".join(problems))
    placeholders = scan_file(docx)
    if placeholders:
        failures.append(
            "placeholders: "
            + ", ".join(f"{item['entry']}:{item['token']}" for item in placeholders[:20])
        )
    total_chars = len(collect_text(Document(docx)))
    if total_chars < min_chars:
        failures.append(f"character_count: {total_chars} < {min_chars}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).with_name("verify_word_ib_style.py")),
        str(docx),
        "--out",
        str(report_path),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        failures.append(f"verify_word_ib_style.py exited with {result.returncode}")
    if failures:
        raise ValueError("Word structural gates failed:\n- " + "\n- ".join(failures))
    return total_chars


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a final Word report produced entirely by the embedded pipeline.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--file", required=True, help="Final DOCX path")
    parser.add_argument("--render-dir", help="Directory containing page-1.png ... from libreoffice_render.py")
    parser.add_argument("--confirm-all-pages-inspected", action="store_true")
    parser.add_argument("--render-issue", action="append", default=[])
    parser.add_argument("--content-method", default="embedded-market-insight-five-views-v1")
    parser.add_argument("--figure-manifest", action="append", default=[])
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    parser.add_argument("--min-chars", type=int, default=15000)
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    skill_root = Path(__file__).resolve().parents[1]
    final_docx = Path(args.file)
    if not final_docx.is_absolute():
        final_docx = project_dir / final_docx
    final_docx = final_docx.resolve()
    if not final_docx.exists():
        raise FileNotFoundError(final_docx)

    fusion_path = skill_root / "assets/templates/word/word_template_fusion_manifest.json"
    fusion = json.loads(fusion_path.read_text(encoding="utf-8-sig"))
    template = skill_root / "assets/templates/word/energy_market_research_report_template.docx"
    expected_template_hash = fusion["fused_template"]["sha256"]
    if sha256(template) != expected_template_hash:
        raise ValueError("Installed fused Word template hash does not match its manifest")

    qa_root = project_dir / "intermediate" / "word_qa"
    report_path = qa_root / "ib_style_validation.md"
    total_chars = _run_structural_gates(final_docx, report_path, args.min_chars)

    render_dir = Path(args.render_dir).resolve() if args.render_dir else None
    pages = _render_pages(render_dir) if render_dir else []
    if args.mode == "final":
        if not pages:
            raise ValueError("Final registration requires --render-dir with non-empty page PNGs")
        if not args.confirm_all_pages_inspected:
            raise ValueError("Final registration requires --confirm-all-pages-inspected after actual page review")
        if args.render_issue:
            raise ValueError("Final registration cannot pass while render issues remain")
        if not args.figure_manifest:
            raise ValueError("Final registration requires at least one per-figure theme manifest")

    figure_manifests: list[str] = []
    embedded_media_hashes = package_media_hashes(final_docx)
    for raw_path in args.figure_manifest:
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_dir / path
        if not path.exists():
            raise FileNotFoundError(path)
        if args.mode == "final":
            figure_issues = validate_figure_manifest(path, project_dir=project_dir, final=True)
            failures = [issue for issue in figure_issues if issue["level"] == "fail"]
            if failures:
                raise ValueError("Final figure manifest failed validation: " + json.dumps(failures, ensure_ascii=False))
            figure_manifest = read_json(path, {})
            output_hashes = {
                record.get("sha256")
                for record in (figure_manifest.get("outputs") or {}).values()
                if isinstance(record, dict) and record.get("sha256")
            }
            if output_hashes and not (output_hashes & embedded_media_hashes):
                raise ValueError(f"Approved figure is not embedded in the final DOCX media package: {path}")
        figure_manifests.append(_stored_path(path, project_dir))

    pdf_path = render_dir / f"{final_docx.stem}.pdf" if render_dir else None
    manifest = {
        "template_path": "assets/templates/word/energy_market_research_report_template.docx",
        "template_sha256": expected_template_hash,
        "template_lineage_verified": True,
        "final_docx_path": _stored_path(final_docx, project_dir),
        "final_docx_sha256": sha256(final_docx),
        "word_pipeline_id": WORD_PIPELINE_ID,
        "word_components": WORD_COMPONENTS,
        "content_skill_used": args.content_method,
        "chart_theme_id": REQUIRED_CHART_THEME,
        "figure_routing": dict(REQUIRED_FIGURE_ROUTING),
        "heading_1_centered": True,
        "heading_1_left_indent_pt": 0,
        "heading_1_right_indent_pt": 0,
        "heading_1_first_line_indent_pt": 0,
        "table_text_centered": True,
        "table_font_size_pt": 9,
        "table_first_line_indent_pt": 0,
        "table_line_spacing": "single",
        "table_three_line_verified": True,
        "table_header_fill": f"#{REQUIRED_TABLE_HEADER_FILL}",
        "table_outer_rule_color": f"#{REQUIRED_TABLE_OUTER_RULE_COLOR}",
        "table_header_rule_color": f"#{REQUIRED_TABLE_HEADER_RULE_COLOR}",
        "table_top_bottom_line_pt": 1.5,
        "table_header_line_pt": 1.0,
        "table_width_cm": 15.6,
        "table_header_repeat": True,
        "data_source_label": "数据来源",
        "figures_inline_and_centered": True,
        "figure_theme_manifests": figure_manifests,
        "character_count": total_chars,
        "structural_report": _stored_path(report_path, project_dir),
        "rendering": {
            "status": "passed" if pages and args.confirm_all_pages_inspected else ("rendered" if pages else "not_run"),
            "page_count": len(pages),
            "pages_inspected": len(pages) if args.confirm_all_pages_inspected else 0,
            "render_dir": _stored_path(render_dir, project_dir) if render_dir else "",
            "issues": args.render_issue,
        },
        "pdf": {
            "delivered": False,
            "path": "",
            "direct_export_from_final_docx": False,
            "cross_format_consistency_passed": False,
            "qa_export_path": _stored_path(pdf_path, project_dir) if pdf_path and pdf_path.exists() else "",
        },
        "notes": "Registered by the embedded Word production pipeline.",
    }
    output = project_dir / "deliverables" / "word_production_manifest.json"
    write_json(output, manifest)
    print(f"Registered Word delivery: {output}")
    print(f"Pages: {len(pages)}; inspected: {manifest['rendering']['pages_inspected']}; characters: {total_chars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
