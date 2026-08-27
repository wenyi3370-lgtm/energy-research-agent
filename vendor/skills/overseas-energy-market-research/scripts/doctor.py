# -*- coding: utf-8 -*-
"""FIX-05: unified runtime doctor with strict readiness gate.

Consolidates the scattered environment checks (verify_install,
check_runtime_dependencies, web_collection doctor, presentation doctor)
into ONE command with consistent output and exit-code semantics:

    python scripts/doctor.py            # diagnostic; WARN allowed, exit 0
    python scripts/doctor.py --strict   # any required capability missing -> exit != 0

Capability domains: CORE / WEB_COLLECTION / MODELING / WORD / EXCEL / PPT /
IMAGE / DELIVERY. Each domain prints PASS / WARN / FAIL with a reason.
Exit codes: 0 = ready (or ready-with-warnings), 1 = not ready (strict or
hard failure), 2 = environment error (cannot even run the checks).

Optional services (Kimi WebBridge, EWO, AnySearch API key) are WARN-only:
business execution degrades gracefully without them.
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from common.fonts import (  # noqa: E402
    CJK_FONT_CANDIDATES,
    find_regional_variant,
    register_font_for_matplotlib,
    resolve_cjk_font,
)
from common.requirements import core_packages, optional_packages  # noqa: E402

# FIX round-2 P2-9: dependency source is requirements.txt (single truth) —
# no hand-maintained package list that drifts from the install manifests.
CORE_PACKAGES = core_packages()
OPTIONAL_PACKAGES = optional_packages()

STATUS = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}


def _pkg(module: str) -> str | None:
    try:
        mod = importlib.import_module(module)
        return getattr(mod, "__version__", "ok")
    except Exception:  # noqa: BLE001
        return None


def _check(name: str, ok: bool, detail: str, *, warn_only: bool = False) -> tuple[str, str]:
    status = STATUS["PASS"] if ok else (STATUS["WARN"] if warn_only else STATUS["FAIL"])
    return status, "%s: %s" % (status, detail)


def _libreoffice() -> Path | None:
    for cand in (shutil.which("soffice"), shutil.which("libreoffice"),
                 r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if cand and Path(cand).exists():
            return Path(cand)
    return None


def _probe_service(name: str, url: str, env_key: str | None, timeout: float = 3.0) -> str:
    """FIX round-2 P2-10: real reachability probe for optional services.

    Credential-less GET; unreachable/unauthorized -> WARN (optional capability).
    """
    if env_key and not os.environ.get(env_key):
        return "%s: 未配置 %s" % (name, env_key)
    try:
        import urllib.request  # noqa: PLC0415

        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "doctor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "%s: 可达 (HTTP %s)" % (name, resp.status)
    except Exception as exc:  # noqa: BLE001
        return "%s: 不可达 (%s)" % (name, type(exc).__name__)


def _writable(p: Path) -> bool:
    try:
        probe = p / ("doctor_write_probe_%d" % os.getpid())
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def run_checks(strict: bool) -> tuple[list[tuple[str, str, str]], bool]:
    """Return [(domain, status, detail)] and overall readiness."""
    rows: list[tuple[str, str, str]] = []
    hard_fail = False

    # ---- CORE ----
    py_ok = sys.version_info >= (3, 10)
    missing = [m for m in CORE_PACKAGES if _pkg(m) is None]
    temp_ok = _writable(Path(tempfile.gettempdir()))
    if not py_ok:
        hard_fail = True
    rows.append(("CORE", *((STATUS["PASS"], "Python %s + 核心包齐全 + 临时目录可写" % ".".join(map(str, sys.version_info[:3])))
                           if py_ok and not missing and temp_ok else
                           (STATUS["FAIL"], "Python=%s 缺失包=%s 临时目录可写=%s" % (
                               ".".join(map(str, sys.version_info[:3])), missing, temp_ok)))))
    if not (py_ok and not missing and temp_ok):
        hard_fail = True

    # ---- OFFICE (WORD/EXCEL/PPT share LibreOffice) ----
    lo = _libreoffice()
    lo_ok = lo is not None
    rows.append(("OFFICE", STATUS["PASS"] if lo_ok else STATUS["FAIL"],
                 "LibreOffice: %s" % (str(lo) if lo else "MISSING (Word/Excel/PPT 渲染必需)")))
    if not lo_ok:
        hard_fail = True
    for domain, pkgs in (("WORD", ["docx", "fitz"]), ("EXCEL", ["openpyxl"]),
                         ("PPT", ["pptx", "fitz"])):
        missing = [m for m in pkgs if _pkg(m) is None]
        ok = not missing and lo_ok
        rows.append((domain, STATUS["PASS"] if ok else STATUS["FAIL"],
                     "依赖 %s %s" % (pkgs, "" if ok else "缺失: %s" % missing)))
        if not ok:
            hard_fail = True

    # ---- FONTS (v9 multi-level discovery; Case A/B/C) ----
    # Case B: Matplotlib 找不到但 Fontconfig 找到 SC 字体 -> PASS（含
    # family/source/path），不得误报 "No supported Chinese font was found"。
    # Case C: 仅存在非简体区域变体（如 Noto Serif CJK JP）-> WARN，
    # 不得静默当作 SC PASS（strict 下按 §23 视为无合格 SC -> FAIL）。
    # Case A: 真正没有任何 CJK 字体 -> MISSING（normal WARN / strict FAIL）。
    resolved = resolve_cjk_font()
    if resolved is not None:
        usable = register_font_for_matplotlib(resolved)
        detail = "CJK_FONT PASS: family=%s source=%s path=%s" % (
            resolved.family, resolved.source, resolved.path or "-")
        if not usable:
            detail += "（matplotlib 未注册该 SC face，图表渲染可能失败；建议安装 SC 单文件字体）"
        rows.append(("IMAGE", STATUS["PASS"], detail))
    else:
        rv = find_regional_variant()
        if rv:
            rows.append(("IMAGE", STATUS["FAIL"] if strict else STATUS["WARN"],
                         "CJK_FONT %s: 仅发现非简体区域变体 %s（SC 字体缺失，未静默使用）"
                         % (STATUS["FAIL"] if strict else STATUS["WARN"], rv)))
            if strict:
                hard_fail = True
        else:
            rows.append(("IMAGE", STATUS["FAIL"] if strict else STATUS["WARN"],
                         "CJK_FONT MISSING: 候选 %s" % "/".join(CJK_FONT_CANDIDATES)))
            if strict:
                hard_fail = True

    # ---- MODELING ----
    missing = [m for m in ("numpy", "matplotlib") if _pkg(m) is None]
    ok = not missing
    rows.append(("MODELING", STATUS["PASS"] if ok else STATUS["FAIL"], "建模依赖 %s" % ("" if ok else "缺失: %s" % missing)))
    if not ok:
        hard_fail = True

    # ---- WEB_COLLECTION ----
    anysearch_cli = SCRIPTS / "anysearch" / "anysearch_cli.py"
    anysearch_ok = anysearch_cli.is_file()
    manifest = SKILL_ROOT / "references" / "anysearch_manifest.json"
    manifest_ok = manifest.is_file()
    missing = [m for m in ("requests", "bs4", "mammoth", "markdownify") if _pkg(m) is None]
    if anysearch_ok and manifest_ok and not missing:
        rows.append(("WEB_COLLECTION", STATUS["PASS"],
                     "embedded AnySearch CLI + manifest + 采集包齐全"))
    else:
        detail = "embedded CLI=%s manifest=%s 缺失包=%s" % (anysearch_ok, manifest_ok, missing)
        rows.append(("WEB_COLLECTION", STATUS["FAIL"] if (not anysearch_ok or not manifest_ok) else STATUS["WARN"], detail))
        if not anysearch_ok or not manifest_ok:
            hard_fail = True

    # ---- DELIVERY ----
    templates = SKILL_ROOT / "assets" / "templates"
    disk = shutil.disk_usage(SKILL_ROOT)
    disk_ok = disk.free > 500 * 1024 * 1024  # 500 MB headroom
    rows.append(("DELIVERY", STATUS["PASS"] if templates.is_dir() and disk_ok else STATUS["WARN"],
                 "模板目录=%s 磁盘剩余=%.1f GB" % (templates.is_dir(), disk.free / 1024 ** 3)))

    # ---- OPTIONAL packages (WARN only — degradation paths exist) ----
    missing_optional = [m for m in OPTIONAL_PACKAGES if _pkg(m) is None]
    if missing_optional:
        rows.append(("OPTIONAL", STATUS["WARN"],
                     "可选增强缺失（有降级路径）: %s" % ", ".join(missing_optional)))

    # ---- OPTIONAL services (WARN only, REAL probes) ----
    services = []
    if not os.environ.get("ANYSEARCH_API_KEY"):
        services.append("AnySearch API key 未配置（匿名额度可用）")
    services.append(_probe_service("Kimi WebBridge", "http://127.0.0.1:10086/command", env_key=None))
    ewo_origin = os.environ.get("EWO_ORIGIN", "http://127.0.0.1:18799").strip().rstrip("/")
    services.append(_probe_service("EWO 生图", ewo_origin, env_key="EWO_KEY"))
    rows.append(("OPTIONAL", STATUS["WARN"], "；".join(services)))

    ready = not hard_fail
    return rows, ready


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="Any required capability missing -> exit != 0")
    args = parser.parse_args()

    try:
        rows, ready = run_checks(strict=args.strict)
    except Exception as exc:  # noqa: BLE001
        print("DOCTOR ERROR: %s" % exc)
        return 2

    for domain, status, detail in rows:
        print("%-14s %-5s %s" % (domain, status, detail))

    if ready:
        print("Overall: READY" + ("" if not any(s == "WARN" for _, s, _ in rows) else "_WITH_WARNINGS"))
        return 0
    print("Overall: NOT_READY")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
