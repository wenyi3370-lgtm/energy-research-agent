# -*- coding: utf-8 -*-
"""FIX round-2 P2-9: machine-readable capability definitions.

Single source of truth for runtime dependency checks: doctor.py and
verify_install.py (and any future precheck) parse requirements.txt /
requirements-optional.txt through this module instead of maintaining
hand-written module lists that drift from the real install manifests.
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SKILL_ROOT = SCRIPTS_DIR.parent

# pip package name -> import module name(s)
_PACKAGE_TO_MODULE = {
    "openpyxl": ["openpyxl"],
    "python-docx": ["docx"],
    "python-pptx": ["pptx"],
    "matplotlib": ["matplotlib"],
    "pymupdf": ["fitz", "pymupdf"],
    "pyyaml": ["yaml"],
    "pillow": ["PIL"],
    "numpy": ["numpy"],
    "flask": ["flask"],
    "requests": ["requests"],
    "beautifulsoup4": ["bs4"],
    "edge-tts": ["edge_tts"],
    "mammoth": ["mammoth"],
    "markdownify": ["markdownify"],
    "ebooklib": ["ebooklib"],
    "nbconvert": ["nbconvert"],
    "markitdown": ["markitdown"],
    "svglib": ["svglib"],
    "reportlab": ["reportlab"],
    "tomli": ["tomli"],
    "cairosvg": ["cairosvg"],
    "curl-cffi": ["curl_cffi"],
    "playwright": ["playwright"],
    "google-genai": ["google.genai"],
    "nbformat": ["nbformat"],
    "urllib3": ["urllib3"],
    "tldextract": ["tldextract"],
}


def parse_requirement_line(line: str, *, environment: dict | None = None):
    """FIX round-4 P2-5/6: PEP 508 line parser (single implementation).

    Returns the packaging Requirement when its environment marker evaluates
    TRUE for `environment` (default = current interpreter), else None.
    Blank/comment lines return None. The Requirement object keeps name /
    specifier / extras / marker intact.
    """
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    line = line.strip()
    if not line or line.startswith("#"):
        return None
    try:
        req = Requirement(line)
    except Exception:  # noqa: BLE001 - tolerate malformed/legacy lines
        return None
    env = environment if environment is not None else default_environment()
    if req.marker is not None and not req.marker.evaluate(environment=env):
        return None
    return req


def _package_names(text: str, *, environment: dict | None = None) -> list[str]:
    """PEP 508 names via parse_requirement_line (never hand-split on ";")."""
    names = []
    for line in text.splitlines():
        req = parse_requirement_line(line, environment=environment)
        if req is not None:
            names.append(req.name.lower())
    return names


def core_packages(environment: dict | None = None) -> list[str]:
    """Import module names declared in CORE requirements.txt, PEP 508 markers
    evaluated against `environment` (default = current interpreter)."""
    path = SKILL_ROOT / "requirements.txt"
    if not path.exists():
        return []
    out: list[str] = []
    for pkg in _package_names(path.read_text(encoding="utf-8"), environment=environment):
        for mod in _PACKAGE_TO_MODULE.get(pkg, [pkg.replace("-", "_")]):
            out.append(mod)
    return out


def optional_packages(environment: dict | None = None) -> list[str]:
    """Import module names declared in requirements-optional.txt, PEP 508
    markers evaluated against `environment` (default = current interpreter)."""
    path = SKILL_ROOT / "requirements-optional.txt"
    if not path.exists():
        return []
    out: list[str] = []
    for pkg in _package_names(path.read_text(encoding="utf-8"), environment=environment):
        for mod in _PACKAGE_TO_MODULE.get(pkg, [pkg.replace("-", "_")]):
            out.append(mod)
    return out
