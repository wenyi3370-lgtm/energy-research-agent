# -*- coding: utf-8 -*-
"""Mechanical quality gate for Word/PPT chart SVGs (kami-broker v2).

Learned from the 2026-08-10 beautification rework (user feedback loop):
the figures looked right in code review but shipped with overlapping labels,
sub-8pt text, SimSun-only fonts, and stale in-figure titles. This gate turns
every one of those lessons into a mechanical check on the produced SVGs:

1. **Font-size floor**: every text >= 8 pt (px == pt in matplotlib SVG output).
2. **Palette whitelist**: only kami-broker colors + allowed shading/heat
   accents (matplotlib default colors leak => fail).
3. **Dual-track fonts**: each SVG must reference BOTH Times New Roman and
   SimSun (pure-latin text uses TNR; mixed strings carry the
   'SimSun','Times New Roman' fallback list). Judged by actual content:
   CJK text needs a Song-family, latin/digits need Times New Roman.
4. **No top-of-figure text**: in-figure titles / gray note lines were removed
   by user feedback (the Word caption row carries the title).
5. **No text-text overlap**: `<text>` nodes are parsed with
   `xml.etree.ElementTree` (FIX-03, v2.0: regex parsing was order-dependent
   and silently missed `style="font-size:.." x=.. y=..` layouts — false
   PASS). Attribute order never matters; width is measured with PIL when
   available (SimSun/Times New Roman), else the CJK-aware estimator.

Run `--self-test` to verify the parser against 5 acceptance fixtures
(attribute orders x->y->style / style->x->y / y->style->x, full overlap =>
FAIL, separated => PASS).

Usage:
    python verify_chart_svg_quality.py --charts-dir deliverables/charts [--self-test]

Exit 0 = all clean, 1 = issues found (blocking), 2 = environment error.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# kami-broker v2 whitelist: theme palette + panel/grid + region shading +
# heat blues + emphasis light blue. Anything else (incl. matplotlib defaults
# #1f77b4/#ff7f0e/...) fails.
ALLOWED_COLORS = {
    "#1b365d", "#2d5a8a", "#6b6a64", "#9c9a93", "#b8b7b0", "#d6d3cb",
    "#eef2f7", "#2e7d32", "#b91c1c", "#ffffff", "#000000",
    "#f7f9fc", "#d9e2ec",
    "#eaf3e8", "#f3e8e8", "#fde8e8", "#fef3c7",
    "#b8c7dc", "#7a94bd", "#4a6a9c",
    "#0ea5e9",
    "#c9a227", "#167c80",
}

# v9: unified CJK font acceptance (multi-level discovery, SC-first) lives in
# scripts/common/fonts.py — is_approved_cjk_family() keeps this QA anchored
# to the declared SC universe across platforms.
from common.fonts import CJK_FONT_CANDIDATES, is_approved_cjk_family  # noqa: E402

MIN_FONT_PT = 8.0
TOP_STRIP_Y = 30.0
TOP_STRIP_MAX_FONT = 12.0
OVERLAP_TOL_PX = 1.0

_PIL = None
try:  # real glyph metrics when available (Windows has Times New Roman/SimSun)
    from PIL import ImageFont

    _TNR = ImageFont.truetype(r"C:\Windows\Fonts\times.ttf", 100)
    _SIM = ImageFont.truetype(r"C:\Windows\Fonts\simsun.ttc", 100)
    _PIL = True
except Exception:  # pragma: no cover
    _PIL = False


def _style_props(style: str) -> dict[str, str]:
    """Parse an SVG style="k:v;k:v" attribute into a dict (order-free)."""
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = v.strip()
    return out


def parse_text_nodes(svg_text: str) -> list[dict]:
    """Extract <text> nodes via XML parser — attribute order never matters.

    Returns [{x, y, font_size, font_family, text, anchor, style}] for every
    text node (namespace-tolerant tag match). `anchor` is 'start'|'middle'|
    'end' (from the text-anchor style/property, default 'start') so overlap
    boxes are computed on the real glyph extent (end-anchored tick labels
    extend LEFT of x, not right).
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise ValueError("SVG is not well-formed XML: %s" % exc) from exc
    nodes: list[dict] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1] if isinstance(elem.tag, str) else ""
        if tag != "text":
            continue
        style = _style_props(elem.attrib.get("style", ""))
        try:
            x = float(elem.attrib.get("x") or style.get("x", ""))
            y = float(elem.attrib.get("y") or style.get("y", ""))
        except ValueError:
            continue  # positional text without coordinates (e.g. <tspan>) — skip
        font_size = float(style.get("font-size", "").rstrip("px") or 9.0)
        font_family = style.get("font-family", "")
        anchor = style.get("text-anchor", elem.attrib.get("text-anchor", "start"))
        vertical = False
        fill = style.get("fill", elem.attrib.get("fill", ""))
        m = re.search(r"rotate\(\s*([-+]?\d+(?:\.\d+)?)", elem.attrib.get("transform", "") or "")
        if m and abs(abs(float(m.group(1))) - 90) < 1.0:
            vertical = True  # 90°-rotated ylabel: glyphs run vertically
        nodes.append({
            "x": x, "y": y, "font_size": font_size,
            "font_family": font_family, "text": (elem.text or "").strip(),
            "anchor": anchor, "vertical": vertical, "fill": fill,
        })
    return nodes


def _text_width(text: str, font_size: float) -> float:
    if _PIL:
        w = 0.0
        for ch in text:
            try:
                w += (_SIM if ord(ch) > 0x2E80 else _TNR).getlength(ch)
            except Exception:
                w += font_size
        return w / 100.0 * font_size
    w = 0.0
    for ch in text:
        w += 1.0 if ord(ch) > 0x2E80 else (0.5 if ch == " " else 0.62)
    return w * font_size


def _color_from_style(style: str) -> str | None:
    props = _style_props(style)
    for key in ("fill", "stroke"):
        v = props.get(key, "")
        if v.startswith("#") and len(v) == 7:
            return v.lower()
    return None


def verify_svg(path: Path) -> list[str]:
    svg_text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    try:
        nodes = parse_text_nodes(svg_text)
    except ValueError as exc:
        return ["SVG XML 解析失败: %s" % exc]

    # 1) font-size floor
    sizes = [n["font_size"] for n in nodes]
    if sizes and min(sizes) < MIN_FONT_PT:
        issues.append("字号下限: 最小 %.1f < %s pt" % (min(sizes), MIN_FONT_PT))

    # 2) palette whitelist (XML-based, order-free)
    root = ET.fromstring(svg_text)
    colors: set[str] = set()
    for elem in root.iter():
        c = _color_from_style(elem.attrib.get("style", ""))
        if c:
            colors.add(c)
    bad = sorted(c for c in colors if c not in ALLOWED_COLORS)
    if bad:
        issues.append("色板白名单违规: %s" % ", ".join(bad))

    # 3) dual-track fonts, judged by content (FIX-09 unified candidates)
    fams: set[str] = set()
    for n in nodes:
        for part in n["font_family"].split(","):
            fams.add(part.strip().strip("'"))
    has_cjk = any(re.search(r"[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]", n["text"]) for n in nodes)
    has_latin = any(re.search(r"[A-Za-z0-9]", n["text"]) for n in nodes)
    if has_latin and not any("Times New Roman" in x for x in fams):
        issues.append("字体双轨缺失: 含拉丁/数字文本但无 Times New Roman")
    if has_cjk and not any(is_approved_cjk_family(x) for x in fams):
        issues.append("字体双轨缺失: 含中文文本但无合法中文字体（%s）" % "/".join(CJK_FONT_CANDIDATES))

    # 4) no top-of-figure text: a leftover in-figure title/note is GRAY
    #    (title_block #6B6A64) and sits top-LEFT (x < 80). Legends, tick
    #    labels and data annotations are black and exempt.
    GRAY_FILLS = {"#6b6a64", "#9c9a93", "#8c8c8c", "#6b7280"}
    for n in nodes:
        if (n["y"] < TOP_STRIP_Y and n["font_size"] <= TOP_STRIP_MAX_FONT
                and len(n["text"]) >= 2 and n["anchor"] != "end"
                and n["x"] < 80 and n["fill"].lower() in GRAY_FILLS):
            issues.append("顶部文字残留 y=%.0f: %s" % (n["y"], n["text"][:20]))
            break

    # 5) text-text overlap (XML parser — attribute order independent;
    #    anchor-aware: end-aligned tick labels extend LEFT of x)
    boxes = []
    for n in nodes:
        if not n["text"]:
            continue
        w = _text_width(n["text"], n["font_size"])
        if n["vertical"]:
            # 90°-rotated (ylabel): horizontal extent is the font size,
            # vertical extent is the text length.
            x0, x1 = n["x"] - n["font_size"] * 0.5, n["x"] + n["font_size"] * 0.5
            y0, y1 = n["y"] - w, n["y"]
        elif n["anchor"] == "end":
            x0, x1 = n["x"] - w, n["x"]
            y0, y1 = n["y"] - n["font_size"] * 0.85, n["y"] + n["font_size"] * 0.2
        elif n["anchor"] == "middle":
            x0, x1 = n["x"] - w / 2, n["x"] + w / 2
            y0, y1 = n["y"] - n["font_size"] * 0.85, n["y"] + n["font_size"] * 0.2
        else:
            x0, x1 = n["x"], n["x"] + w
            y0, y1 = n["y"] - n["font_size"] * 0.85, n["y"] + n["font_size"] * 0.2
        boxes.append((x0, y0, x1, y1, n["text"], x0, n["y"]))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix > OVERLAP_TOL_PX and iy > OVERLAP_TOL_PX:
                issues.append(
                    "文本重叠 %.0fx%.0fpx: [%s]@(%.0f,%.0f) vs [%s]@(%.0f,%.0f)"
                    % (ix, iy, a[4][:14], a[5], a[6], b[4][:14], b[5], b[6])
                )
                break  # one per pair cluster is enough
    return issues


# ---------------------------------------------------------------------------
# FIX-03 acceptance self-test: attribute-order independence + overlap verdicts
# ---------------------------------------------------------------------------

def _fixture(attrs_style: str, x: float, y: float, text: str) -> str:
    """Build a single <text> node with a given attribute order in `attrs`."""
    return '<text %s>%s</text>' % (attrs_style, text)


def _svg_of(*text_nodes: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            + "".join(text_nodes) + "</svg>")


def run_self_test() -> int:
    failures: list[str] = []

    def parse_ok(label: str, svg: str, expect: list[tuple[float, float, str]]) -> None:
        nodes = parse_text_nodes(svg)
        got = [(n["x"], n["y"], n["text"]) for n in nodes]
        if got != expect:
            failures.append("%s: 解析结果 %s != 期望 %s" % (label, got, expect))

    # Test A: x -> y -> style
    parse_ok("A(x->y->style)",
             _svg_of(_fixture('x="10" y="100" style="font-size: 9px"', 0, 0, "甲")),
             [(10.0, 100.0, "甲")])
    # Test B: style -> x -> y
    parse_ok("B(style->x->y)",
             _svg_of(_fixture('style="font-size: 9px" x="10" y="100"', 0, 0, "乙")),
             [(10.0, 100.0, "乙")])
    # Test C: y -> style -> x
    parse_ok("C(y->style->x)",
             _svg_of(_fixture('y="100" style="font-size: 9px" x="10"', 0, 0, "丙")),
             [(10.0, 100.0, "丙")])
    # Test D: two fully-overlapping texts -> overlap issue detected
    d_svg = _svg_of(
        _fixture('x="10" y="100" style="font-size: 9px"', 0, 0, "完全重叠甲"),
        _fixture('style="font-size: 9px" x="10" y="100"', 0, 0, "完全重叠乙"),
    )
    d_path = Path(__file__).with_name("_selftest_d.svg")
    d_path.write_text(d_svg, encoding="utf-8")
    d_issues = verify_svg(d_path)
    d_path.unlink()
    if not any("文本重叠" in it for it in d_issues):
        failures.append("D(完全重叠): 期望检出重叠，实际 %s" % d_issues)
    # Test E: two far-apart texts -> no overlap issue
    e_svg = _svg_of(
        _fixture('x="10" y="100" style="font-size: 9px"', 0, 0, "左侧文本"),
        _fixture('style="font-size: 9px" x="80" y="100"', 0, 0, "右侧文本"),
    )
    e_path = Path(__file__).with_name("_selftest_e.svg")
    e_path.write_text(e_svg, encoding="utf-8")
    e_issues = verify_svg(e_path)
    e_path.unlink()
    if any("文本重叠" in it for it in e_issues):
        failures.append("E(分离文本): 期望无重叠，实际 %s" % e_issues)

    # Test F: 90°-rotated ylabel must NOT collide with an end-anchored tick
    f_svg = _svg_of(
        "<text x=\"-10\" y=\"113\" transform=\"rotate(-90 -10 113)\" "
        "style=\"font-size: 9px; font-family: 'SimSun', 'Times New Roman'\">关键政策数</text>",
        "<text x=\"30\" y=\"117\" style=\"font-size: 9px; text-anchor: end; "
        "font-family: 'Times New Roman'\">2.0</text>",
    )
    f_path = Path(__file__).with_name("_selftest_f.svg")
    f_path.write_text(f_svg, encoding="utf-8")
    f_issues = verify_svg(f_path)
    f_path.unlink()
    if any("文本重叠" in it for it in f_issues):
        failures.append("F(竖直ylabel): 期望不重叠，实际 %s" % f_issues)

    if failures:
        print("SELF-TEST FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("SELF-TEST PASS (A/B/C 属性顺序无关解析、D 完全重叠检出、E 分离放行)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--charts-dir", default="deliverables/charts",
                        help="Directory containing figN_*.svg")
    parser.add_argument("--self-test", action="store_true",
                        help="Run FIX-03 acceptance fixtures and exit")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    charts = Path(args.charts_dir).resolve()
    if not charts.exists():
        print("ERROR: charts dir not found:", charts)
        return 2
    total_issues = 0
    for f in sorted(charts.glob("fig*.svg")):
        issues = verify_svg(f)
        if issues:
            total_issues += len(issues)
            print("FAIL %s" % f.name)
            for it in issues:
                print("   ", it)
        else:
            print("OK   %s" % f.name)
    if total_issues:
        print("校验失败：%d 处问题（%s）" % (total_issues, charts.name))
        return 1
    print("校验通过：全部图表 SVG 满足 kami-broker-v2 机械规则")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
