from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import shutil


PYTHON_DEPENDENCIES = {
    "openpyxl": "openpyxl",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "matplotlib": "matplotlib",
    "PyMuPDF": "pymupdf",
    "PyYAML": "yaml",
    "Pillow": "PIL",
    "numpy": "numpy",
    "Flask": "flask",
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "edge-tts": "edge_tts",
    "mammoth": "mammoth",
    "markdownify": "markdownify",
    "EbookLib": "ebooklib",
    "nbconvert": "nbconvert",
    "markitdown": "markitdown",
    "svglib": "svglib",
    "reportlab": "reportlab",
}


def check() -> dict:
    packages = {}
    missing = []
    for distribution, module in PYTHON_DEPENDENCIES.items():
        try:
            imported = importlib.import_module(module)
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = str(getattr(imported, "__version__", "installed-unregistered"))
            packages[distribution] = {"status": "ok", "version": version}
        except ImportError as exc:
            packages[distribution] = {"status": "missing", "detail": str(exc)}
            missing.append(distribution)
    soffice = shutil.which("soffice.com") or shutil.which("soffice.exe") or shutil.which("soffice")
    if not soffice:
        for candidate in (
            r"C:\Program Files\LibreOffice\program\soffice.com",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
        ):
            if shutil.which(candidate) or __import__("pathlib").Path(candidate).exists():
                soffice = candidate
                break
    return {
        "status": "ok" if not missing and soffice else "missing_dependencies",
        "python_packages": packages,
        "libreoffice": soffice or "missing",
        "missing_python_packages": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the standalone runtime dependencies bundled by the energy-market Skill.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = check()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Runtime dependency check: {report['status']}")
        for name, item in report["python_packages"].items():
            print(f"  {name}: {item['status']} {item.get('version', '')}".rstrip())
        print(f"  LibreOffice: {report['libreoffice']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
