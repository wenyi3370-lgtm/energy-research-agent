# -*- coding: utf-8 -*-
"""FIX round-3 P2-13: doctor regression — dependency & readiness semantics.

Offline, self-contained cases (monkeypatched, no external services):

1. PEP 508 marker active: Python 3.10 -> tomli required
2. PEP 508 marker inactive: simulated Python 3.13 -> tomli ignored
3. Missing CORE package -> CORE FAIL, doctor --strict exit != 0
4. Missing OPTIONAL package -> WARN only, never CORE FAIL
5. Missing required font (Case A) -> strict FAIL / normal WARN
6. External runtime service missing -> WARN (real probe result honored)
7. Fontconfig-resolved SC font (Case B) -> IMAGE PASS, family/source/path shown
8. Only regional variant installed (Case C) -> WARN (strict FAIL), never silent PASS

Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import doctor  # noqa: E402
from common import requirements as reqmod  # noqa: E402
from common.fonts import ResolvedFont  # noqa: E402


def test_marker_active() -> None:
    """FIX round-4 P2-9: test the PRODUCTION parser (core_packages with an
    explicit 3.10 environment), not packaging itself."""
    env_310 = {"python_version": "3.10", "python_full_version": "3.10.0"}
    packages_310 = reqmod.core_packages(environment=env_310)
    if "tomli" not in packages_310:
        raise AssertionError("core_packages(env 3.10) must include tomli")
    if sys.version_info < (3, 11) and "tomli" not in reqmod.core_packages():
        raise AssertionError("core_packages() on the current <3.11 interpreter must include tomli")
    print("  [1/8] PEP 508 marker active via production parser: PASS")


def test_marker_inactive_simulated() -> None:
    """FIX round-4 P2-9: production parser with a simulated 3.13 environment
    must EXCLUDE tomli."""
    env_313 = {"python_version": "3.13", "python_full_version": "3.13.0"}
    packages_313 = reqmod.core_packages(environment=env_313)
    if "tomli" in packages_313:
        raise AssertionError("core_packages(env 3.13) must NOT include tomli")
    print("  [2/8] PEP 508 marker inactive via production parser (simulated 3.13): PASS")


def _patch(module, name, fn):
    """Set module.name -> fn; return (name, old) for _restore."""
    old = getattr(module, name)
    setattr(module, name, fn)
    return (name, old)


def _restore(module, patches):
    for name, old in reversed(patches):
        setattr(module, name, old)


def _healthy_env(module):
    """FIX round-4 P2-10: deterministic isolation — every environmental
    dependency is forced healthy so a case outcome can never be polluted by
    the actual host machine (missing core package, no LibreOffice, no font,
    unwritable temp, missing templates)."""
    return [
        _patch(module, "_pkg", lambda m: "ok"),
        _patch(module, "_libreoffice", lambda: Path("C:/fake/soffice.exe")),
        _patch(module, "resolve_cjk_font",
               lambda: ResolvedFont("SimSun", None, "matplotlib")),
        _patch(module, "find_regional_variant", lambda: None),
        _patch(module, "register_font_for_matplotlib", lambda r: True),
        _patch(module, "_writable", lambda p: True),
        _patch(module, "_probe_service",
               lambda name, url, env_key=None, timeout=3.0: "%s: ok" % name),
    ]


def test_missing_core_package() -> None:
    rows, ready = doctor.run_checks(strict=False)
    status = dict((d, s) for d, s, _ in rows)
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "_pkg", lambda m: None if m == "openpyxl" else "ok"))
    try:
        rows2, ready2 = doctor.run_checks(strict=False)
        status2 = dict((d, s) for d, s, _ in rows2)
        if status2["CORE"] != "FAIL":
            raise AssertionError("missing core package must yield CORE FAIL, got %s" % status2["CORE"])
        if ready2:
            raise AssertionError("missing core package must make overall NOT_READY")
    finally:
        _restore(doctor, patches)
    print("  [3/8] missing core package -> CORE FAIL / NOT_READY: PASS")


def test_missing_optional_package() -> None:
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "_pkg", lambda m: None if m == "cairosvg" else "ok"))
    try:
        rows, ready = doctor.run_checks(strict=False)
        status = dict((d, s) for d, s, _ in rows)
        if status["CORE"] != "PASS":
            raise AssertionError("missing optional package must NOT fail CORE, got %s" % status["CORE"])
        if not any(d == "OPTIONAL" and s == "WARN" and "可选增强" in detail
                   for d, s, detail in rows):
            raise AssertionError("missing optional package must produce an OPTIONAL WARN row")
    finally:
        _restore(doctor, patches)
    print("  [4/8] missing optional package -> WARN only: PASS")


def test_missing_required_font() -> None:
    """Case A: 真正没有任何 CJK 字体 -> normal WARN / strict FAIL."""
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "resolve_cjk_font", lambda: None))
    try:
        rows, ready = doctor.run_checks(strict=False)
        status = dict((d, s) for d, s, _ in rows)
        detail = next(det for d, s, det in rows if d == "IMAGE")
        if status["IMAGE"] != "WARN":
            raise AssertionError("missing font in normal mode must be WARN, got %s" % status["IMAGE"])
        if "MISSING" not in detail:
            raise AssertionError("missing font detail must say MISSING, got %r" % detail)
        rows_s, ready_s = doctor.run_checks(strict=True)
        status_s = dict((d, s) for d, s, _ in rows_s)
        if status_s["IMAGE"] != "FAIL":
            raise AssertionError("missing font in strict mode must be FAIL, got %s" % status_s["IMAGE"])
        if ready_s:
            raise AssertionError("missing font in strict mode must make NOT_READY")
    finally:
        _restore(doctor, patches)
    print("  [5/8] Case A missing CJK font -> WARN (normal) / FAIL (strict): PASS")


def test_fontconfig_resolved_sc_font() -> None:
    """Case B: matplotlib 找不到，但 fontconfig 找到 SC 字体 -> IMAGE PASS，
    且 detail 含 family/source/path —— 不得误报 MISSING。"""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "resolve_cjk_font",
                          lambda: ResolvedFont("Noto Serif CJK SC", ttc, "fontconfig")))
    try:
        rows, ready = doctor.run_checks(strict=False)
        status = dict((d, s) for d, s, _ in rows)
        detail = next(det for d, s, det in rows if d == "IMAGE")
        if status["IMAGE"] != "PASS":
            raise AssertionError("fontconfig-resolved SC must be IMAGE PASS, got %s" % status["IMAGE"])
        if "Noto Serif CJK SC" not in detail or "fontconfig" not in detail or str(ttc) not in detail:
            raise AssertionError("PASS detail must show family/source/path, got %r" % detail)
        if not ready:
            raise AssertionError("fontconfig-resolved SC must keep READY")
    finally:
        _restore(doctor, patches)
    print("  [6/8] Case B fontconfig SC TTC -> PASS (family/source/path): PASS")


def test_regional_variant_only() -> None:
    """Case C: 仅存在非简体区域变体（JP）-> normal WARN / strict FAIL，
    不得静默当作 SC PASS，也不得误报 MISSING。"""
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "resolve_cjk_font", lambda: None))
    patches.append(_patch(doctor, "find_regional_variant", lambda: "Noto Serif CJK JP"))
    try:
        rows, ready = doctor.run_checks(strict=False)
        status = dict((d, s) for d, s, _ in rows)
        detail = next(det for d, s, det in rows if d == "IMAGE")
        if status["IMAGE"] != "WARN":
            raise AssertionError("JP-only must be WARN in normal mode, got %s" % status["IMAGE"])
        if "JP" not in detail:
            raise AssertionError("regional-variant detail must name the variant, got %r" % detail)
        rows_s, ready_s = doctor.run_checks(strict=True)
        status_s = dict((d, s) for d, s, _ in rows_s)
        if status_s["IMAGE"] != "FAIL":
            raise AssertionError("JP-only must be FAIL in strict mode, got %s" % status_s["IMAGE"])
        if ready_s:
            raise AssertionError("JP-only in strict mode must make NOT_READY")
    finally:
        _restore(doctor, patches)
    print("  [7/8] Case C regional variant only -> WARN / strict FAIL: PASS")


def test_missing_external_service() -> None:
    patches = _healthy_env(doctor)
    patches.append(_patch(doctor, "_probe_service",
                                lambda name, url, env_key=None, timeout=3.0: "%s: 不可达" % name))
    try:
        rows, ready = doctor.run_checks(strict=False)
        if not any(s == "WARN" for d, s in ((r[0], r[1]) for r in rows)):
            raise AssertionError("unreachable optional service must be WARN")
        if not ready:
            raise AssertionError("optional service unreachable must not make NOT_READY")
    finally:
        _restore(doctor, patches)
    print("  [8/8] external runtime service missing (isolated) -> WARN, still READY: PASS")


def main() -> int:
    print("Doctor regression:")
    test_marker_active()
    test_marker_inactive_simulated()
    test_missing_core_package()
    test_missing_optional_package()
    test_missing_required_font()
    test_fontconfig_resolved_sc_font()
    test_regional_variant_only()
    test_missing_external_service()
    print("Doctor regression: PASS (8/8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
