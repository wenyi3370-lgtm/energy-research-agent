# -*- coding: utf-8 -*-
"""v9 font discovery regression — CJK Font Discovery False Negative.

The core bug under test: on Linux/macOS a SC font EXISTS inside a .ttc
collection (e.g. /usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc)
that Fontconfig resolves as "Noto Serif CJK SC", but matplotlib's font cache
only exposes another face of the collection (commonly "Noto Serif CJK JP"),
so findfont("...SC") fails and the skill reported "No supported Chinese font
was found" even though the system HAS the font.

Every case patches the discovery primitives (_matplotlib_find /
_fontconfig_match / _filesystem_find) so results are deterministic on ANY
host (Windows CI included). Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import fonts  # noqa: E402


def _patch(module, name, fn):
    old = getattr(module, name)
    setattr(module, name, fn)
    return (name, old)


def _restore(module, patches):
    for name, old in reversed(patches):
        setattr(module, name, old)


def _mock(ml=None, fc=None, fs=None):
    """Install discovery mocks; returns the patch list."""
    patches = [_patch(fonts, "_matplotlib_find", ml or (lambda f: None)),
               _patch(fonts, "_fontconfig_match", fc or (lambda f: None)),
               _patch(fonts, "_filesystem_find", fs or (lambda f: None))]
    return patches


def test_matplotlib_direct_simsun() -> None:
    """Case 1: Matplotlib 直接找到 SimSun -> source=matplotlib, PASS."""
    patches = _mock(ml=lambda f: Path("C:/Windows/Fonts/simsun.ttc") if f == "SimSun" else None)
    try:
        res = fonts.resolve_cjk_font()
        if res is None or res.family != "SimSun" or res.source != "matplotlib":
            raise AssertionError("expected SimSun via matplotlib, got %r" % (res,))
    finally:
        _restore(fonts, patches)
    print("  [1/10] matplotlib 直接发现 SimSun -> PASS (source=matplotlib)")


def test_fontconfig_finds_sc_ttc() -> None:
    """Case 2: matplotlib 找不到，fc-match 找到 SC TTC -> PASS (source=fontconfig)."""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    patches = _mock(
        ml=lambda f: None,
        fc=lambda f: (("Noto Serif CJK SC", ttc) if f == "Noto Serif CJK SC" else None),
    )
    try:
        res = fonts.resolve_cjk_font()
        if res is None:
            raise AssertionError("fontconfig SC TTC must resolve, got None")
        if res.family != "Noto Serif CJK SC":
            raise AssertionError("family must be Noto Serif CJK SC, got %r" % res.family)
        if res.path != ttc:
            raise AssertionError("path must be %s, got %s" % (ttc, res.path))
        if res.source != "fontconfig":
            raise AssertionError("source must be fontconfig, got %r" % res.source)
        if res.regional_variant:
            raise AssertionError("SC result must not be marked regional")
    finally:
        _restore(fonts, patches)
    print("  [2/10] fc-match 找到 SC TTC -> PASS (family/path/source=fontconfig)")


def test_fontconfig_unrelated_fallback_rejected() -> None:
    """Case 3: fc-match fallback 到无关字体（DejaVu Sans）-> 不得 PASS，继续搜索."""
    patches = _mock(
        ml=lambda f: None,
        fc=lambda f: (("DejaVu Sans", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
                      if f == "Noto Serif CJK SC" else None),
    )
    try:
        res = fonts.resolve_cjk_font()
        if res is not None:
            raise AssertionError("unrelated fallback must NOT pass, got %r" % (res,))
        if fonts._is_sc("DejaVu Sans"):
            raise AssertionError("DejaVu Sans must not classify as SC")
    finally:
        _restore(fonts, patches)
    print("  [3/10] fc-match 无关 fallback (DejaVu Sans) -> 不 PASS")


def test_regional_variant_only() -> None:
    """Case 4: 系统只有 JP variant -> SC resolver 不得静默 PASS; WARN/None 策略."""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    patches = _mock(
        ml=lambda f: None,
        fc=lambda f: (("Noto Serif CJK JP", ttc)),
    )
    try:
        res = fonts.resolve_cjk_font()
        if res is not None:
            raise AssertionError("JP-only system must not silently pass as SC, got %r" % (res,))
        rv = fonts.find_regional_variant()
        if rv is None:
            raise AssertionError("JP variant must be detectable for Doctor WARN")
        if "JP" not in rv:
            raise AssertionError("regional variant name must carry JP, got %r" % rv)
        # explicit opt-in returns the variant, clearly marked
        opt = fonts.resolve_cjk_font(require_simplified_chinese=False)
        if opt is None or not opt.regional_variant or "JP" not in opt.family:
            raise AssertionError("explicit opt-in must return marked JP variant, got %r" % (opt,))
    finally:
        _restore(fonts, patches)
    print("  [4/10] 仅 JP variant -> SC 不静默 PASS; opt-in 显式标记区域变体")


def test_no_fonts_at_all() -> None:
    """Case 5: 没有任何字体 -> resolve 返回 None（Doctor 报 MISSING）."""
    patches = _mock()
    try:
        if fonts.resolve_cjk_font() is not None:
            raise AssertionError("empty system must resolve to None")
        if fonts.find_regional_variant() is not None:
            raise AssertionError("empty system must have no regional variant either")
    finally:
        _restore(fonts, patches)
    print("  [5/10] 无任何字体 -> None (MISSING 语义保留)")


def test_ttc_sc_exists_matplotlib_jp_only() -> None:
    """Case 6 (核心回归): SC TTC 存在 + fontconfig 说 SC + matplotlib 只暴露 JP
    -> 字体存在性必须 PASS，不得误报 MISSING。"""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    patches = _mock(
        ml=lambda f: None,  # matplotlib cache 只认识 JP face，SC 查询失败
        fc=lambda f: (("Noto Serif CJK SC", ttc) if f == "Noto Serif CJK SC" else None),
    )
    try:
        res = fonts.resolve_cjk_font()
        if res is None:
            raise AssertionError("SC exists in TTC + fontconfig resolves it -> must PASS, not MISSING")
        if res.family != "Noto Serif CJK SC" or res.source != "fontconfig" or res.path != ttc:
            raise AssertionError("wrong resolution: %r" % (res,))
    finally:
        _restore(fonts, patches)
    print("  [6/10] TTC SC 存在 + matplotlib JP-only -> 存在性 PASS（核心 False Negative 修复）")


def test_register_font_honest_face_check() -> None:
    """Case 7: register_font_for_matplotlib 必须实际验证 SC face 是否注册——
    addfont(TTC) 只暴露 JP face 时诚实返回 False，绝不假定成功。"""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    from matplotlib import font_manager as fm

    orig_addfont = fm.fontManager.addfont
    calls = {"addfont": 0}
    try:
        # scenario A: addfont 后 SC face 出现 -> True
        state = {"n": 0}

        def sc_after_add(family):
            state["n"] += 1
            return ttc if state["n"] >= 2 else None

        def fake_addfont(p):
            calls["addfont"] += 1

        fm.fontManager.addfont = fake_addfont
        patches = [_patch(fonts, "_matplotlib_find", sc_after_add)]
        try:
            ok = fonts.register_font_for_matplotlib(
                fonts.ResolvedFont("Noto Serif CJK SC", ttc, "fontconfig"))
            if not ok or calls["addfont"] != 1:
                raise AssertionError("SC face registered after addfont must yield True")
        finally:
            _restore(fonts, patches)

        # scenario B: addfont 后仍只暴露 JP face -> False（诚实）
        calls["addfont"] = 0
        patches = [_patch(fonts, "_matplotlib_find", lambda f: None)]
        try:
            ok = fonts.register_font_for_matplotlib(
                fonts.ResolvedFont("Noto Serif CJK SC", ttc, "fontconfig"))
            if ok or calls["addfont"] != 1:
                raise AssertionError("JP-only-after-addfont must honestly return False")
        finally:
            _restore(fonts, patches)
    finally:
        fm.fontManager.addfont = orig_addfont
    print("  [7/10] register_font_for_matplotlib 实际验证 TTC SC face（诚实 False）")


def test_approved_family_qa_classification() -> None:
    """Case 8: QA 判定 —— SC 家族接受，JP/无关家族拒绝。"""
    ok = ["SimSun", "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC",
          "Microsoft YaHei", "STSong", "PingFang SC", "Noto Sans CJK SC", "SimHei"]
    bad = ["Noto Serif CJK JP", "Noto Serif CJK KR", "DejaVu Sans", "Times New Roman",
           "Arial", ""]
    for fam in ok:
        if not fonts.is_approved_cjk_family(fam):
            raise AssertionError("SC family %r must be approved" % fam)
    for fam in bad:
        if fonts.is_approved_cjk_family(fam):
            raise AssertionError("non-SC family %r must be rejected" % fam)
    print("  [8/10] is_approved_cjk_family 分类正确（SC 接受 / JP+DejaVu 拒绝）")


def test_ttc_sc_face_extraction_register() -> None:
    """Case 9: addfont(TTC) 只注册首个 face（常为 JP）时，fontTools 提取 SC
    face 并注册 -> True；无可用 SC face 时诚实返回 False。"""
    ttc = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
    extracted = Path("/tmp/overseas_energy_market_research_cjk_faces/noto_serif_cjk_sc_3.otf")
    from matplotlib import font_manager as fm

    orig_addfont = fm.fontManager.addfont
    added: list[str] = []
    state = {"n": 0}

    def fake_addfont(p):
        added.append(str(p))

    try:
        # scenario A: 提取成功 -> [ttc, extracted] 依次注册，最终 SC face 可用
        def lookup_a(family):
            state["n"] += 1
            return extracted if state["n"] >= 3 else None

        fm.fontManager.addfont = fake_addfont
        patches = [
            _patch(fonts, "_matplotlib_find", lookup_a),
            _patch(fonts, "_extract_sc_face", lambda p, family: extracted),
        ]
        try:
            ok = fonts.register_font_for_matplotlib(
                fonts.ResolvedFont("Noto Serif CJK SC", ttc, "fontconfig"))
            if not ok:
                raise AssertionError("TTC SC extraction must register successfully")
            if added != [str(ttc), str(extracted)]:
                raise AssertionError("addfont sequence must be [ttc, extracted], got %r" % added)
        finally:
            _restore(fonts, patches)

        # scenario B: 提取不可用（无 fontTools / 无 SC face）-> 诚实 False
        added.clear()
        state["n"] = 0
        patches = [
            _patch(fonts, "_matplotlib_find", lambda f: None),
            _patch(fonts, "_extract_sc_face", lambda p, family: None),
        ]
        try:
            ok = fonts.register_font_for_matplotlib(
                fonts.ResolvedFont("Noto Serif CJK SC", ttc, "fontconfig"))
            if ok:
                raise AssertionError("no extractable SC face must return False")
            if added != [str(ttc)]:
                raise AssertionError("only direct ttc addfont attempted, got %r" % added)
        finally:
            _restore(fonts, patches)
    finally:
        fm.fontManager.addfont = orig_addfont
    print("  [9/10] TTC SC face 提取注册 -> True / 不可提取诚实 False")


def test_macos_system_fonts_discovery() -> None:
    """Case 10: macOS 系统字体（PingFang SC / Songti SC）纳入发现（追加在文档
    规定的 STSong → Noto Serif SC → Source Han Serif SC 之后），且 QA 审批通过。"""
    pref = fonts._PLATFORM_PREFERENCE["Darwin"]
    for first3 in ("STSong", "Noto Serif SC", "Source Han Serif SC"):
        if pref.index(first3) >= pref.index("PingFang SC"):
            raise AssertionError("doc priority broken: %s must precede PingFang SC" % first3)
    if "PingFang SC" not in pref or "Songti SC" not in pref:
        raise AssertionError("macOS system fonts must be discovery candidates")
    if "pingfang" not in fonts._FS_SC_PATTERNS.get("PingFang SC", ()):
        raise AssertionError("PingFang filesystem pattern missing")
    for fam in ("PingFang SC", "Songti SC"):
        if not fonts.is_approved_cjk_family(fam):
            raise AssertionError("%r must be QA-approved" % fam)
    # 端到端：Darwin 下 STSong/Noto 缺失、PingFang 存在 -> 经 matplotlib 解析
    patches = [
        _patch(fonts.platform, "system", lambda: "Darwin"),
        _patch(fonts, "_matplotlib_find",
               lambda f: Path("/System/Library/Fonts/PingFang.ttc") if f == "PingFang SC" else None),
        _patch(fonts, "_fontconfig_match", lambda f: None),
        _patch(fonts, "_filesystem_find", lambda f: None),
    ]
    try:
        res = fonts.resolve_cjk_font()
        if res is None or res.family != "PingFang SC" or res.source != "matplotlib":
            raise AssertionError("Darwin must resolve PingFang SC via matplotlib, got %r" % (res,))
    finally:
        _restore(fonts, patches)
    print("  [10/10] macOS 系统字体（PingFang SC/Songti SC）发现与优先级")


def main() -> int:
    print("Font discovery regression:")
    test_matplotlib_direct_simsun()
    test_fontconfig_finds_sc_ttc()
    test_fontconfig_unrelated_fallback_rejected()
    test_regional_variant_only()
    test_no_fonts_at_all()
    test_ttc_sc_exists_matplotlib_jp_only()
    test_register_font_honest_face_check()
    test_approved_family_qa_classification()
    test_ttc_sc_face_extraction_register()
    test_macos_system_fonts_discovery()
    print("Font discovery regression: PASS (10/10)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
