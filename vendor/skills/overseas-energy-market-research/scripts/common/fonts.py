# -*- coding: utf-8 -*-
"""v9 cross-platform CJK font discovery — single source of truth.

Solves the Linux/macOS False Negative where a Simplified-Chinese font IS
installed (often inside a .ttc collection, e.g.
/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc) but matplotlib's
font cache only exposes a different face of the collection (commonly
"Noto Serif CJK JP"), so findfont("Noto Serif CJK SC") fails even though
Fontconfig resolves it.

Principles (per spec):
    font discovery  !=  font semantic selection
    system font exists  !=  matplotlib cache knows the exact family name

Discovery levels, in order:
  Level 1  matplotlib native discovery (findfont, fallback_to_default=False)
  Level 2  Fontconfig via `fc-match` (where the binary exists; TTC-aware).
           The returned file must exist and the returned family must
           reasonably match the requested SC family — unrelated fallbacks
           (e.g. DejaVu Sans) are NOT accepted as a match.
  Level 3  filesystem scan of platform font directories for SC-specific
           files (last-resort fallback; only approved SC patterns).

SC-first policy: regional variants (Noto Serif CJK JP/KR/TC/HK, Source Han
JP, ...) never silently pass as SC.  `require_simplified_chinese=False` is
the explicit opt-in that returns a regional variant; Doctor reports it as
WARN, never as PASS.

Every module that resolves or validates fonts (chart theme, chart polish,
figure generation, Word rendering, SVG QA, Doctor) MUST import from here —
no module maintains its own candidate list or calls findfont directly.
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from matplotlib import font_manager


# --------------------------------------------------------------------------
# Approved family lists
# --------------------------------------------------------------------------

# Union of approved Simplified-Chinese families (also the discovery universe;
# platform-specific preference ordering is applied in _PLATFORM_PREFERENCE).
CJK_FONT_CANDIDATES = [
    "SimSun",
    "STSong",
    "Noto Serif CJK SC",
    "Noto Serif SC",
    "Source Han Serif SC",
    "Microsoft YaHei",
]

# Additional explicitly approved SC families (QA acceptance only; discovery
# still anchors on CJK_FONT_CANDIDATES so the resolved family stays in the
# declared universe).
_EXTRA_SC_FAMILIES = ("Noto Sans CJK SC", "PingFang SC", "Songti SC", "SimHei")

# CJK-capable but NON-Simplified regional variants (for Case-C detection and
# the explicit opt-in fallback; never silently used as SC).
REGIONAL_VARIANT_CANDIDATES = [
    "Noto Serif CJK JP",
    "Noto Serif CJK KR",
    "Noto Serif CJK TC",
    "Noto Serif CJK HK",
    "Source Han Serif JP",
    "Source Han Serif KR",
    "Source Han Serif TC",
    "Source Han Serif HK",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Noto Sans CJK TC",
    "Noto Sans CJK HK",
    "Microsoft JhengHei",
]

# Platform preference order (doc §10): Windows 1.SimSun 2.YaHei; macOS
# 1.STSong 2.Noto Serif SC 3.Source Han Serif SC; Linux 1.Noto Serif CJK SC
# 2.Noto Serif SC 3.Source Han Serif SC.  macOS additionally ships PingFang SC
# and Songti SC (inside /System/Library/Fonts/*.ttc) — approved system SC
# fonts appended after the documented three.  Rest of the union follows.
_PLATFORM_PREFERENCE: dict[str, list[str]] = {
    "Windows": ["SimSun", "Microsoft YaHei"],
    "Darwin": ["STSong", "Noto Serif SC", "Source Han Serif SC",
               "PingFang SC", "Songti SC"],
    "Linux": ["Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC"],
}
for _pf, _head in _PLATFORM_PREFERENCE.items():
    _PLATFORM_PREFERENCE[_pf] = _head + [c for c in CJK_FONT_CANDIDATES if c not in _head]


# --------------------------------------------------------------------------
# Result object
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedFont:
    """Logical resolution result: family (SC semantics) + real file + source.

    `regional_variant=True` marks a non-SC regional variant (JP/KR/TC/HK)
    returned ONLY through the explicit `require_simplified_chinese=False`
    opt-in — never as a silent SC substitute.
    """

    family: str
    path: Path | None = None
    source: str = "matplotlib"  # "matplotlib" | "fontconfig" | "filesystem"
    regional_variant: bool = False


# --------------------------------------------------------------------------
# Family classification
# --------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


_SC_TOKENS = (
    "simsun", "simhei", "yahei", "stsong", "songti sc", "pingfang sc",
    "noto serif sc", "noto sans sc", "source han serif sc",
    "source han sans sc", "cjk sc",
)
_REGIONAL_TOKENS = (
    "cjk jp", "cjk kr", "cjk tc", "cjk hk",
    "han jp", "han kr", "han tc", "han hk",
    "jhenghei", "mingliu",
)


def _is_sc(family: str) -> bool:
    """True when `family` is a Simplified-Chinese font."""
    f = _norm(family).replace("-", " ")
    return any(tok in f for tok in _SC_TOKENS)


def _is_regional_variant(family: str) -> bool:
    """True when `family` is CJK-capable but NOT Simplified (JP/KR/TC/HK...)."""
    f = _norm(family).replace("-", " ")
    return any(tok in f for tok in _REGIONAL_TOKENS)


def _families_match(requested: str, returned: str) -> bool:
    """Reasonable family match: equal, or one contains the other.

    Fontconfig performs fallback substitution — an unrelated family (e.g.
    DejaVu Sans) must NOT be accepted for a requested SC family.
    """
    a, b = _norm(requested), _norm(returned)
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def is_approved_cjk_family(family: str) -> bool:
    """QA acceptance: True when `family` is an approved SC font.

    Anchored to the declared candidate universe (plus the extra approved SC
    list) so SVG-quality checks stay deterministic across platforms.
    """
    f = (family or "").strip()
    if not f or not _is_sc(f):
        return False
    if f in CJK_FONT_CANDIDATES or f in _EXTRA_SC_FAMILIES:
        return True
    return any(c in f or f in c for c in CJK_FONT_CANDIDATES)


# --------------------------------------------------------------------------
# Discovery levels
# --------------------------------------------------------------------------

def _matplotlib_find(family: str) -> Path | None:
    """Level 1: matplotlib native discovery. None when the family is not in
    the matplotlib font cache (fallback_to_default=False keeps fontconfig
    substitutions OUT of the result — that is exactly what we want to detect).
    """
    try:
        p = font_manager.findfont(
            font_manager.FontProperties(family=family),
            fallback_to_default=False,
        )
        return Path(p)
    except ValueError:
        return None


def _fontconfig_match(family: str) -> tuple[str, Path] | None:
    """Level 2: `fc-match` the family. Returns (matched_family, file) when
    the match is sane: file exists AND family reasonably matches the request.

    Subprocess discipline: no shell, capture stderr, 3s timeout, command
    missing -> None (macOS may not ship fc-match; that must never raise).
    """
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-f", "%{family}\n%{file}\n", family],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    fam_line, file_line = lines[0], lines[-1]
    fpath = Path(file_line)
    if not fpath.is_file():
        return None
    for cand in fam_line.split(","):
        cand = cand.strip()
        if cand and _families_match(family, cand):
            return cand, fpath
    return None


# SC-specific filename patterns per candidate family (filesystem fallback).
_FS_SC_PATTERNS: dict[str, tuple[str, ...]] = {
    "Noto Serif CJK SC": ("notoserifcjksc-", "notoserifcjk-", "notoserifcjkcn-"),
    "Noto Serif SC": ("notoserifsc-",),
    "Source Han Serif SC": ("sourcehanserifsc-", "sourcehanserifcn-", "sourcehanserif-"),
    "SimSun": ("simsun",),
    "Microsoft YaHei": ("msyh",),
    "STSong": ("stsong", "stsongti-sc", "songti"),
    "PingFang SC": ("pingfang",),
    "Songti SC": ("songti", "stsongti-sc"),
}

_FS_DIRS: dict[str, tuple[str, ...]] = {
    "Windows": (r"C:\Windows\Fonts",),
    "Linux": (
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/opt/homebrew/share/fonts",
        "~/.fonts",
        "~/.local/share/fonts",
    ),
    "Darwin": (
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "/Library/Fonts",
        "~/Library/Fonts",
    ),
}


def _filesystem_find(family: str) -> Path | None:
    """Level 3: scan platform font directories for an SC-specific file.

    Last-resort fallback only; accepts known SC filename patterns and never
    guesses a family from an unrelated file.
    """
    patterns = _FS_SC_PATTERNS.get(family)
    if not patterns:
        return None
    for d in _FS_DIRS.get(platform.system(), ()):
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            low = f.name.lower()
            if any(p in low for p in patterns):
                return f
    return None


# --------------------------------------------------------------------------
# TTC SC-face extraction (rendering path)
# --------------------------------------------------------------------------

def _ttc_family_name(name_table) -> str | None:
    """First non-empty family name (typographic nameID 16 preferred, then 1)."""
    for name_id in (16, 1):
        for rec in name_table.names:
            if rec.nameID != name_id:
                continue
            try:
                val = rec.toUnicode().strip()
            except Exception:  # noqa: BLE001
                continue
            if val:
                return val
    return None


def _sc_face_cache_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "overseas_energy_market_research_cjk_faces"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover
        pass
    return base


def _extract_sc_face(ttc_path: Path, family: str) -> Path | None:
    """Extract the SC face of a TTC into a standalone temp font via fontTools
    (already a hard dependency of matplotlib — no new installs).

    matplotlib's addfont on a TTC only registers its FIRST face (commonly the
    JP face of Noto CJK TTCs), so the exact SC face is saved to a cache file
    and registered separately.  Returns None when fontTools is missing, the
    file is not a TTC, or no SC face matches.
    """
    if not str(ttc_path).lower().endswith(".ttc"):
        return None
    try:
        from fontTools.ttLib import TTCollection
    except Exception:  # noqa: BLE001
        return None
    try:
        coll = TTCollection(str(ttc_path), lazy=True)
    except Exception:  # noqa: BLE001
        return None
    for idx, face in enumerate(coll.fonts):
        try:
            fam = _ttc_family_name(face["name"])
        except Exception:  # noqa: BLE001
            continue
        # Face selection must be an EXACT normalized match — the loose
        # substring rule used for fc-match validation would let "SimSun"
        # match an "NSimSun" request and extract the wrong face.
        if not fam or not _is_sc(fam) or _norm(fam) != _norm(family):
            continue
        out = _sc_face_cache_dir() / ("%s_%d.otf" % (
            re.sub(r"[^A-Za-z0-9]+", "_", fam).strip("_").lower() or "sc_face", idx))
        if not out.exists():
            try:
                face.save(str(out))
            except Exception:  # noqa: BLE001
                return None
        return out
    return None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def resolve_cjk_font(*, require_simplified_chinese: bool = True) -> ResolvedFont | None:
    """Multi-level SC font discovery (matplotlib -> fontconfig -> filesystem).

    Returns None when no qualified Simplified-Chinese font is found.  With
    `require_simplified_chinese=False` a regional variant (JP/KR/TC/HK) may
    be returned, explicitly marked `regional_variant=True` — the opt-in path
    that Doctor reports as WARN, never as silent PASS.
    """
    system = platform.system()
    candidates = _PLATFORM_PREFERENCE.get(system, CJK_FONT_CANDIDATES)
    regional: tuple[str, Path] | None = None
    for family in candidates:
        # Level 1: matplotlib already knows this family (lightest path).
        p = _matplotlib_find(family)
        if p is not None:
            return ResolvedFont(family=family, path=p, source="matplotlib")
        # Level 2: Fontconfig (TTC-aware; only when fc-match exists).
        m = _fontconfig_match(family)
        if m is not None:
            fam, fpath = m
            if _is_sc(fam) and _families_match(family, fam):
                return ResolvedFont(family=fam, path=fpath, source="fontconfig")
            if _is_regional_variant(fam) and regional is None:
                regional = (fam, fpath)  # note it; never pass as SC
        # Level 3: filesystem scan for SC-specific files.
        fp = _filesystem_find(family)
        if fp is not None:
            return ResolvedFont(family=family, path=fp, source="filesystem")
    if not require_simplified_chinese and regional is not None:
        fam, fpath = regional
        return ResolvedFont(family=fam, path=fpath, source="fontconfig",
                            regional_variant=True)
    return None


def require_cjk_font(*, require_simplified_chinese: bool = True) -> ResolvedFont:
    """Like resolve_cjk_font but raises when no qualified font exists."""
    resolved = resolve_cjk_font(require_simplified_chinese=require_simplified_chinese)
    if resolved is None:
        raise RuntimeError(
            "No supported Chinese font was found. Install one of: "
            + ", ".join(CJK_FONT_CANDIDATES)
        )
    return resolved


def resolve_cjk_font_family(*, require_simplified_chinese: bool = True) -> str | None:
    """Convenience: the resolved SC family name, or None."""
    resolved = resolve_cjk_font(require_simplified_chinese=require_simplified_chinese)
    return resolved.family if resolved is not None else None


def resolve_cjk_font_path() -> Path | None:
    """Convenience: the resolved font file path, or None."""
    resolved = resolve_cjk_font()
    return resolved.path if resolved is not None else None


def register_font_for_matplotlib(resolved: ResolvedFont | None) -> bool:
    """Make the resolved font usable by matplotlib; True when its SC family
    resolves through matplotlib after registration.

    For TTC collections matplotlib's addfont registers only the FIRST face
    (commonly the JP face of Noto CJK TTCs) — behaviour differs across
    matplotlib/FreeType versions, so we never assume success: (1) try the
    direct file, (2) verify, (3) fall back to extracting the exact SC face
    from the TTC via fontTools (matplotlib's own dependency) into a cached
    standalone font and registering that, (4) verify again — then honestly
    report success/failure.
    """
    if resolved is None:
        return False
    if _matplotlib_find(resolved.family) is not None:
        return True
    if resolved.path is None:
        return False
    try:
        font_manager.fontManager.addfont(str(resolved.path))
    except Exception:  # noqa: BLE001 — registration is best-effort
        pass
    if _matplotlib_find(resolved.family) is not None:
        return True
    extracted = _extract_sc_face(resolved.path, resolved.family)
    if extracted is None:
        return False
    try:
        font_manager.fontManager.addfont(str(extracted))
    except Exception:  # noqa: BLE001
        return False
    return _matplotlib_find(resolved.family) is not None


def find_regional_variant() -> str | None:
    """CJK-capable but non-SC regional variant installed (JP/KR/TC/HK...).

    Used by Doctor for Case C: the system HAS Chinese fonts, but no SC
    family — must be WARN, never a silent PASS and never MISSING.
    """
    system = platform.system()
    for family in REGIONAL_VARIANT_CANDIDATES:
        if _matplotlib_find(family) is not None:
            return family
        m = _fontconfig_match(family)
        if m is not None and _families_match(family, m[0]):
            return m[0]
    return None
