from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"


def run(script: str, *args: str) -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    command = [sys.executable, str(SCRIPTS / script), *args]
    print("+ " + " ".join(command))
    return subprocess.run(command, env=env, check=False).returncode


def doctor() -> int:
    required_paths = [
        SCRIPTS / "project_manager.py",
        SCRIPTS / "svg_quality_checker.py",
        SCRIPTS / "svg_editor" / "server.py",
        SCRIPTS / "finalize_svg.py",
        SCRIPTS / "svg_to_pptx.py",
        SKILL_ROOT / "templates" / "design_spec_reference.md",
        SKILL_ROOT / "templates" / "spec_lock_reference.md",
        SKILL_ROOT / "references" / "strategist.md",
        SKILL_ROOT / "references" / "executor-consultant-top.md",
    ]
    modules = {
        "python-pptx": "pptx",
        "PyMuPDF": "fitz",
        "Pillow": "PIL",
        "numpy": "numpy",
        "Flask": "flask",
        "requests": "requests",
        "beautifulsoup4": "bs4",
        "edge-tts": "edge_tts",
        "svglib": "svglib",
        "reportlab": "reportlab",
    }
    failures: list[str] = []
    for path in required_paths:
        if not path.exists():
            failures.append(f"missing path: {path}")
    for distribution, module in modules.items():
        try:
            importlib.import_module(module)
        except ImportError as exc:
            failures.append(f"missing package: {distribution} ({exc})")
    if failures:
        print("Embedded PPT Master doctor: FAIL")
        for failure in failures:
            print("- " + failure)
        return 1
    print("Embedded PPT Master doctor: OK")
    print(f"- skill root: {SKILL_ROOT}")
    print(f"- templates: {sum(1 for p in (SKILL_ROOT / 'templates').rglob('*') if p.is_file())} files")
    return 0


def project_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def validate(project: Path, canvas: str) -> int:
    rc = run("project_manager.py", "validate", str(project))
    if rc:
        return rc
    return run("svg_quality_checker.py", str(project / "svg_output"), "--format", canvas)


def ensure_notes(project: Path) -> int:
    total = project / "total.md"
    if total.exists():
        return run("total_md_split.py", str(project))
    svg_files = sorted((project / "svg_output").glob("*.svg"))
    matched_notes = [project / "notes" / f"{svg.stem}.md" for svg in svg_files]
    svg_count = len(svg_files)
    note_count = sum(path.exists() for path in matched_notes)
    if svg_count and note_count == svg_count:
        print(f"Speaker notes already split: {note_count}/{svg_count}")
        return 0
    print(f"Speaker notes incomplete: {note_count}/{svg_count}; add total.md or one note per SVG")
    return 1


def finalize(project: Path, canvas: str) -> int:
    rc = validate(project, canvas)
    if rc:
        return rc
    rc = ensure_notes(project)
    if rc:
        return rc
    rc = run("finalize_svg.py", str(project))
    if rc:
        return rc
    return run("svg_quality_checker.py", str(project / "svg_final"), "--format", canvas)


def export(project: Path, output: Path, canvas: str, transition: str, animation: str) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    return run(
        "svg_to_pptx.py",
        str(project),
        "--source",
        "final",
        "--output",
        str(output),
        "--format",
        canvas,
        "--only",
        "native",
        "--transition",
        transition,
        "--animation",
        animation,
        "--conversion-trace",
    )


def qa(pptx: Path, output_dir: Path) -> int:
    rc = run(
        "libreoffice_render.py",
        str(pptx),
        "--output-dir",
        str(output_dir),
        "--render-pages",
        "--timeout-seconds",
        "120",
    )
    if rc:
        return rc
    rc = run("create_page_contact_sheet.py", str(output_dir), "--output-dir", str(output_dir / "contact_sheets"))
    if rc:
        return rc
    return run("scan_office_placeholders.py", str(pptx))


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the embedded high-fidelity PPT Master pipeline without generating slide SVGs in bulk.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")

    init_p = sub.add_parser("init")
    init_p.add_argument("project_name")
    init_p.add_argument("--format", default="ppt169")
    init_p.add_argument("--dir", default="projects")

    validate_p = sub.add_parser("validate")
    validate_p.add_argument("project")
    validate_p.add_argument("--format", default="ppt169")

    finalize_p = sub.add_parser("finalize")
    finalize_p.add_argument("project")
    finalize_p.add_argument("--format", default="ppt169")

    preview_p = sub.add_parser("preview")
    preview_p.add_argument("project")
    preview_p.add_argument("--port", default="5050")
    preview_p.add_argument("--no-browser", action="store_true")

    export_p = sub.add_parser("export")
    export_p.add_argument("project")
    export_p.add_argument("--output", required=True)
    export_p.add_argument("--format", default="ppt169")
    export_p.add_argument("--transition", default="fade")
    export_p.add_argument("--animation", default="auto")

    qa_p = sub.add_parser("qa")
    qa_p.add_argument("pptx")
    qa_p.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    if args.command == "doctor":
        return doctor()
    if args.command == "init":
        return run("project_manager.py", "init", args.project_name, "--format", args.format, "--dir", args.dir)
    if args.command == "validate":
        return validate(project_path(args.project), args.format)
    if args.command == "finalize":
        return finalize(project_path(args.project), args.format)
    if args.command == "preview":
        extra = [str(project_path(args.project)), "--port", args.port, "--live"]
        if args.no_browser:
            extra.append("--no-browser")
        return run("svg_editor/server.py", *extra)
    if args.command == "export":
        return export(project_path(args.project), Path(args.output).expanduser().resolve(), args.format, args.transition, args.animation)
    if args.command == "qa":
        return qa(Path(args.pptx).expanduser().resolve(), Path(args.output_dir).expanduser().resolve())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
