"""DiagramDesignAdapter (P0 refactor): one renderer for HTML (inline SVG) and Word (PNG).

Every visual is generated as a single ``<svg>`` following the diagram-design
editorial design system (tokens, 4px grid, hairline strokes, orthogonal
connectors, role/aria contract), wrapped in a small HTML file.  HTML
renderers inline that same SVG; Word renders a high-resolution PNG captured
from **the same HTML** (Playwright, falling back to Chrome/Edge headless).
There is no second charting implementation anywhere in the pipeline.

The enterprise consulting profile adapts the diagram-design default skin:
pure white paper, near-black ink, deep navy (#1B365D) accent, CJK font
stack (Microsoft YaHei / PingFang SC / Noto Sans CJK SC), no glow, no
heavy gradients.  See ``style_tokens()``.

Failure behaviour is explicit, never silent:
``rendered`` → the figure exists; ``fallback_table`` → the figure degraded to
a structured table drawn from the same VisualSpec data; ``failed`` → QA
recorded the error and the caller keeps the insight as prose.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .visuals import VisualSpec, VisualType

# ── Enterprise consulting profile (diagram-design semantic tokens) ──────────

ENTERPRISE_PROFILE: dict[str, str] = {
    # Semantic roles from diagram-design references/style-guide.md
    "paper": "#FFFFFF",                      # pure white (consulting print)
    "paper2": "#F7F8FA",                     # secondary fill / table header
    "ink": "#1B1F26",                        # near-black body text
    "muted": "#4A5568",                      # secondary text / axis labels
    "soft": "#7A8399",                       # sublabels / tertiary
    "rule": "rgba(27,54,93,0.14)",           # hairline borders
    "rule_solid": "#C9D4E0",                 # stronger borders / baselines
    "accent": "#1B365D",                     # deep royal navy — the one focal
    "accent_tint": "rgba(27,54,93,0.08)",    # fill for accent-bordered boxes
    "link": "#2E5AA8",                       # external/network arrows
    "series1": "#7C8F6F",                    # sage (multi-series charts only)
    "series2": "#5E7A9B",                    # dusty-blue
    "series3": "#B8915A",                    # mustard
    "series4": "#9C6B50",                    # rust-brown
    "series5": "#6E6479",                    # slate
    # Typography: serif title + sans body (consulting), CJK-first stack
    "font_sans": "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Source Han Sans SC, Arial, sans-serif",
    "font_serif": "Source Han Serif SC, Noto Serif CJK SC, SimSun, serif",
    "google_fonts_url": "",                  # enterprise profile uses system CJK fonts
}

# wide layouts vs standard layouts (diagram-design output-spec presets)
WIDE_TYPES: frozenset[VisualType] = frozenset({
    "process", "data_flow", "gantt", "journey", "timeline", "sankey",
    "architecture", "tree", "fishbone", "pyramid",
})
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "doc-inline": (960, 600),
    "doc-wide": (1280, 720),
}


class VisualRenderResult(BaseModel):
    """Result of one build_visual call — the contract publishers consume."""

    visual_id: str
    status: str  # rendered | fallback_table | failed
    visual_type: str
    html_path: Path | None = None
    svg_path: Path | None = None
    png_path: Path | None = None
    svg_markup: str | None = None
    png_status: str = "not_requested"  # ok | unavailable | failed
    fallback_reason: str | None = None
    error: str | None = None
    width: int = 0
    height: int = 0


# ── helpers ──────────────────────────────────────────────────────────────────

def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9 and abs(value) < 1e12:
            return f"{int(round(value)):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _nice_step(span: float, count: int = 5) -> float:
    raw = span / max(count, 1)
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 5, 10):
        if raw <= mult * mag:
            return mult * mag
    return 10 * mag


def _ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    step = _nice_step(hi - lo, count)
    start = math.ceil(lo / step) * step
    ticks: list[float] = []
    tick = start
    while tick <= hi + step / 2:
        ticks.append(round(tick, 10))
        tick += step
    return ticks


def _lines(text: str, max_chars: int, max_lines: int = 2) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    words = list(text)
    lines: list[str] = []
    current = ""
    for ch in text:
        if len(current) >= max_chars and current:
            lines.append(current)
            current = ""
        current += ch
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


# ── canvas ───────────────────────────────────────────────────────────────────

class _Canvas:
    """Collects SVG elements; emits a self-contained, accessible diagram."""

    def __init__(self, width: int, height: int, visual_id: str, title: str, desc: str) -> None:
        self.w = width
        self.h = height
        self.visual_id = visual_id
        self.title = title
        self.desc = desc
        self._parts: list[str] = []

    def _text_attrs(self, size: int, fill: str, weight: int, anchor: str, family: str, italic: bool) -> str:
        fam = family or ENTERPRISE_PROFILE["font_sans"]
        return (
            f'font-family="{fam}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}"'
            + (' font-style="italic"' if italic else "")
        )

    def text(
        self, x: float, y: float, content: str, *,
        size: int = 12, fill: str | None = None, weight: int = 600,
        anchor: str = "start", family: str | None = None, italic: bool = False,
    ) -> None:
        if content is None or content == "":
            return
        self._parts.append(
            f'<text x="{x:g}" y="{y:g}" {self._text_attrs(size, fill or ENTERPRISE_PROFILE["ink"], weight, anchor, family, italic)}>{_xml(content)}</text>'
        )

    def rect(
        self, x: float, y: float, w: float, h: float, *,
        fill: str | None = None, stroke: str | None = None,
        rx: float = 6, width: float = 1, dash: str | None = None,
    ) -> None:
        attrs = f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}"'
        attrs += f' fill="{fill or "none"}"'
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{width:g}"'
            if dash:
                attrs += f' stroke-dasharray="{dash}"'
        self._parts.append(f"<rect {attrs}/>")

    def line(
        self, x1: float, y1: float, x2: float, y2: float, *,
        stroke: str | None = None, width: float = 1, dash: str | None = None,
    ) -> None:
        attrs = f'x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{stroke or ENTERPRISE_PROFILE["rule_solid"]}" stroke-width="{width:g}"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        self._parts.append(f"<line {attrs}/>")

    def path(
        self, d: str, *,
        fill: str | None = None, stroke: str | None = None,
        width: float = 1, dash: str | None = None,
    ) -> None:
        attrs = f'd="{d}" fill="{fill or "none"}"'
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{width:g}" stroke-linejoin="round"'
            if dash:
                attrs += f' stroke-dasharray="{dash}"'
        self._parts.append(f"<path {attrs}/>")

    def polyline(self, points: list[tuple[float, float]], *, stroke: str, width: float = 2) -> None:
        pts = " ".join(f"{x:g},{y:g}" for x, y in points)
        self._parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width:g}" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    def circle(
        self, cx: float, cy: float, r: float, *,
        fill: str | None = None, stroke: str | None = None, width: float = 1.5,
    ) -> None:
        attrs = f'cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{fill or "none"}"'
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{width:g}"'
        self._parts.append(f"<circle {attrs}/>")

    def svg(self, *, background: bool = True) -> str:
        role = ' role="img"'
        labelledby = f' aria-labelledby="{self.visual_id}-title {self.visual_id}-desc"'
        title = f'<title id="{self.visual_id}-title">{_xml(self.title)}</title>'
        desc = f'<desc id="{self.visual_id}-desc">{_xml(self.desc)}</desc>'
        bg = f'<rect x="0" y="0" width="{self.w}" height="{self.h}" fill="{ENTERPRISE_PROFILE["paper"]}"/>' if background else ""
        body = "".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" font-family="{ENTERPRISE_PROFILE["font_sans"]}"{role}{labelledby}>'
            f"{bg}{title}{desc}{body}</svg>"
        )


def _grid(c: _Canvas, x0: float, y0: float, x1: float, y1: float) -> None:
    """Axis grid: axes + hairlines (4px grid is enforced by callers' coords)."""
    c.line(x0, y1, x1, y1, stroke=ENTERPRISE_PROFILE["rule_solid"])
    c.line(x0, y0, x0, y1, stroke=ENTERPRISE_PROFILE["rule_solid"])


def _arrow(c: _Canvas, x1: float, y1: float, x2: float, y2: float, *, stroke: str | None = None) -> None:
    stroke = stroke or ENTERPRISE_PROFILE["rule_solid"]
    c.line(x1, y1, x2, y2, stroke=stroke, width=1.2)
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 6
    ax = x2 - size * math.cos(angle - math.pi / 6)
    ay = y2 - size * math.sin(angle - math.pi / 6)
    bx = x2 - size * math.cos(angle + math.pi / 6)
    by = y2 - size * math.sin(angle + math.pi / 6)
    c.path(f"M{x2:g},{y2:g} L{ax:g},{ay:g} L{bx:g},{by:g} Z", fill=stroke)


def _ortho(c: _Canvas, x1: float, y1: float, x2: float, y2: float, *, stroke: str | None = None) -> None:
    """Orthogonal connector with 8px elbows (diagram-design rule)."""
    stroke = stroke or ENTERPRISE_PROFILE["rule_solid"]
    if x1 == x2 or y1 == y2:
        c.line(x1, y1, x2, y2, stroke=stroke, width=1.2)
        return
    r = 8
    mid_x = x1 + (x2 - x1) / 2
    path = (
        f"M{x1:g},{y1:g} L{mid_x - r:g},{y1:g} Q{mid_x:g},{y1:g} {mid_x:g},{y1 + r:g} "
        f"L{mid_x:g},{y2 - r:g} Q{mid_x:g},{y2:g} {mid_x + r:g},{y2:g} L{x2:g},{y2:g}"
    )
    c.path(path, stroke=stroke, width=1.2)


def _with_alpha(hex_color: str, alpha: float) -> str:
    """Convert a #RRGGBB token to rgba() with the given alpha."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "rgba(27,54,93,0.08)"
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "rgba(27,54,93,0.08)"
    return f"rgba({r},{g},{b},{alpha})"


def _node_fill(kind: str) -> tuple[str, str, str | None]:
    """diagram-design node treatment → (fill, stroke, dash)."""
    t = ENTERPRISE_PROFILE
    if kind == "focal":
        return t["accent_tint"], t["accent"], None
    if kind == "store":
        return "rgba(27,54,93,0.05)", t["muted"], None
    if kind == "external":
        return "rgba(27,54,93,0.03)", "rgba(27,54,93,0.30)", None
    if kind == "input":
        return "rgba(74,85,104,0.10)", t["soft"], None
    if kind == "optional":
        return "rgba(27,54,93,0.02)", "rgba(27,54,93,0.20)", "4,3"
    if kind == "security":
        return "rgba(27,54,93,0.05)", "rgba(27,54,93,0.50)", "4,4"
    return "#FFFFFF", t["ink"], None  # backend


# ── type generators ──────────────────────────────────────────────────────────

def _gen_line(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if isinstance(item.value, (int, float))]
    periods: list[str] = []
    for item in items:
        if item.period and item.period not in periods:
            periods.append(item.period)
    series: dict[str, list[tuple[str, float]]] = {}
    for item in items:
        name = item.series or "主序列"
        series.setdefault(name, []).append((item.period or "", float(item.value)))
    values = [v for _, lst in series.items() for _, v in lst]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.15 or max(abs(hi), 1) * 0.15
    y0, y1 = lo - pad, hi + pad
    x0, x1, ytop, ybot = 72.0, c.w - 24.0, 40.0, c.h - 48.0
    _grid(c, x0, ytop, x1, ybot)
    for tick in _ticks(y0, y1, 5):
        y = ybot - (tick - y0) / (y1 - y0) * (ybot - ytop)
        c.line(x0, y, x1, y, stroke=ENTERPRISE_PROFILE["rule"])
        c.text(x0 - 8, y + 4, _fmt_num(tick), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="end")
    n = len(periods)
    step_x = (x1 - x0) / max(n, 1)
    step_px = step_x / 2
    if n <= 10:
        for i, period in enumerate(periods):
            x = x0 + step_x * (i + 0.5)
            c.text(x, ybot + 20, period, size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="middle")
    series_colors = [
        ENTERPRISE_PROFILE["accent"], ENTERPRISE_PROFILE["series1"], ENTERPRISE_PROFILE["series2"],
        ENTERPRISE_PROFILE["series3"], ENTERPRISE_PROFILE["series4"], ENTERPRISE_PROFILE["series5"],
    ]
    legend_x = x0
    for idx, (name, points) in enumerate(series.items()):
        color = series_colors[idx % len(series_colors)]
        xs: dict[str, float] = {}
        for i, period in enumerate(periods):
            xs[period] = x0 + step_x * (i + 0.5)
        pts: list[tuple[float, float]] = []
        for period, value in points:
            x = xs.get(period, x0)
            y = ybot - (value - y0) / (y1 - y0) * (ybot - ytop)
            pts.append((x, y))
        if len(pts) > 1:
            c.polyline(pts, stroke=color, width=2.4 if idx == 0 else 2)
        for x, y in pts:
            c.circle(x, y, 4, fill=ENTERPRISE_PROFILE["paper"], stroke=color)
        if len(series) > 1:
            c.text(legend_x, ytop - 14, name, size=11, fill=color, weight=600)
            legend_x += len(name) * 14 + 40
    if spec.unit:
        c.text(x0, 20, f"单位：{spec.unit}", size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400)


def _gen_bar(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if isinstance(item.value, (int, float))]
    values = [float(item.value) for item in items]  # type: ignore[arg-type]
    lo, hi = 0.0, max(values)
    pad = hi * 0.12 or 1
    y0, y1 = lo - pad * 0, hi + pad
    x0, x1, ytop, ybot = 72.0, c.w - 32.0, 32.0, c.h - 56.0
    _grid(c, x0, ytop, x1, ybot)
    for tick in _ticks(y0, y1, 5):
        y = ybot - (tick - y0) / (y1 - y0) * (ybot - ytop)
        c.line(x0, y, x1, y, stroke=ENTERPRISE_PROFILE["rule"])
        c.text(x0 - 8, y + 4, _fmt_num(tick), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="end")
    n = len(items)
    slot = (x1 - x0) / n
    bar_w = min(slot * 0.62, 120)
    for i, item in enumerate(items):
        x = x0 + slot * i + (slot - bar_w) / 2
        h = (float(item.value) - y0) / (y1 - y0) * (ybot - ytop)
        c.rect(x, ybot - h, bar_w, h, fill=ENTERPRISE_PROFILE["accent"], rx=4)
        c.text(x + bar_w / 2, ybot - h - 8, f"{_fmt_num(item.value)}{item.unit or ''}", size=11, anchor="middle")
        label_lines = _lines(item.label, 8, 1)
        c.text(x + bar_w / 2, ybot + 20, label_lines[0], size=11, fill=ENTERPRISE_PROFILE["ink"], weight=500, anchor="middle")


def _gen_radar(c: _Canvas, spec: VisualSpec) -> None:
    items = spec.items
    axes: list[str] = []
    for item in items:
        if item.label not in axes:
            axes.append(item.label)
    n_axes = len(axes)
    if n_axes < 3:
        n_axes = max(n_axes, 3)
    cx, cy = c.w / 2, c.h / 2 + 8
    r = min(c.w, c.h) * 0.36
    lo, hi = 0.0, 100.0
    if items:
        vals = [v for v in (float(item.value) if isinstance(item.value, (int, float)) else 0.0) for item in items]
        hi = max(vals) if vals else 100.0
        hi = hi * 1.15 if hi > 0 else 100.0
    ring_count = 4
    for ring in range(1, ring_count + 1):
        rr = r * ring / ring_count
        pts = [
            (cx + rr * math.cos(2 * math.pi * i / n_axes - math.pi / 2),
             cy + rr * math.sin(2 * math.pi * i / n_axes - math.pi / 2))
            for i in range(n_axes)
        ]
        c.polyline(pts + [pts[0]], stroke=ENTERPRISE_PROFILE["rule"], width=1)
    for i in range(n_axes):
        angle = 2 * math.pi * i / n_axes - math.pi / 2
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        c.line(cx, cy, x, y, stroke=ENTERPRISE_PROFILE["rule"])
        lx = cx + (r + 28) * math.cos(angle)
        ly = cy + (r + 28) * math.sin(angle)
        c.text(lx, ly + 4, axes[i], size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
    series: dict[str, list[float]] = {}
    for item in items:
        name = item.series or "主序列"
        idx = axes.index(item.label) if item.label in axes else 0
        series.setdefault(name, [0.0] * n_axes)
        value = float(item.value) if isinstance(item.value, (int, float)) else 0.0
        series[name][idx] = max(series[name][idx], value)
    colors = [
        ENTERPRISE_PROFILE["accent"], ENTERPRISE_PROFILE["series1"], ENTERPRISE_PROFILE["series2"],
        ENTERPRISE_PROFILE["series3"], ENTERPRISE_PROFILE["series4"], ENTERPRISE_PROFILE["series5"],
    ]
    legend_x = cx - 60
    for idx, (name, scores) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        pts = [
            (cx + r * (score / hi) * math.cos(2 * math.pi * i / n_axes - math.pi / 2),
             cy + r * (score / hi) * math.sin(2 * math.pi * i / n_axes - math.pi / 2))
            for i, score in enumerate(scores)
        ]
        c.polyline(pts + [pts[0]], stroke=color, width=2.2 if idx == 0 else 1.6)
        c.path(
            "M" + " L".join(f"{x:g},{y:g}" for x, y in pts) + " Z",
            fill=_with_alpha(color, 0.14),
            stroke="none",
        )
        c.text(legend_x, 28 + idx * 18, name, size=11, fill=color, weight=600)
        legend_x += len(name) * 14 + 40


def _gen_quadrant(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if isinstance(item.x, (int, float)) and isinstance(item.y, (int, float))]
    xs = [float(item.x) for item in items]  # type: ignore[arg-type]
    ys = [float(item.y) for item in items]  # type: ignore[arg-type]
    x0, x1, ytop, ybot = 72.0, c.w - 32.0, 32.0, c.h - 48.0
    _grid(c, x0, ytop, x1, ybot)
    mid_x = x0 + (x1 - x0) / 2
    mid_y = ytop + (ybot - ytop) / 2
    c.line(mid_x, ytop, mid_x, ybot, stroke=ENTERPRISE_PROFILE["rule_solid"], dash="6,4")
    c.line(x0, mid_y, x1, mid_y, stroke=ENTERPRISE_PROFILE["rule_solid"], dash="6,4")
    x_label = spec.axes.get("x_label", "X 轴指标")
    y_label = spec.axes.get("y_label", "Y 轴指标")
    c.text(x0 + (x1 - x0) / 2, c.h - 16, x_label, size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
    c.text(16, mid_y, y_label, size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
    # quadrant titles when provided: keys tl/tr/bl/br
    quads = spec.axes.get("quadrants", {})
    c.text(x0 + 8, ytop + 18, str(quads.get("tl", "")), size=10, fill=ENTERPRISE_PROFILE["soft"], weight=500)
    c.text(x1 - 8, ytop + 18, str(quads.get("tr", "")), size=10, fill=ENTERPRISE_PROFILE["soft"], weight=500, anchor="end")
    c.text(x0 + 8, ybot - 8, str(quads.get("bl", "")), size=10, fill=ENTERPRISE_PROFILE["soft"], weight=500)
    c.text(x1 - 8, ybot - 8, str(quads.get("br", "")), size=10, fill=ENTERPRISE_PROFILE["soft"], weight=500, anchor="end")
    for item in items:
        x = x0 + (float(item.x) - min(xs)) / (max(xs) - min(xs) or 1) * (x1 - x0)
        y = ybot - (float(item.y) - min(ys)) / (max(ys) - min(ys) or 1) * (ybot - ytop)
        c.circle(x, y, 6, fill=ENTERPRISE_PROFILE["accent"], stroke=ENTERPRISE_PROFILE["paper"], width=2)
        c.text(x + 10, y + 4, item.label, size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600)


def _gen_scatter(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if isinstance(item.x, (int, float)) and isinstance(item.y, (int, float))]
    xs = [float(item.x) for item in items]  # type: ignore[arg-type]
    ys = [float(item.y) for item in items]  # type: ignore[arg-type]
    x0, x1, ytop, ybot = 72.0, c.w - 32.0, 32.0, c.h - 56.0
    _grid(c, x0, ytop, x1, ybot)
    for tick in _ticks(min(xs), max(xs) or 1, 5):
        x = x0 + (tick - min(xs)) / (max(xs) - min(xs) or 1) * (x1 - x0)
        c.line(x, ytop, x, ybot, stroke=ENTERPRISE_PROFILE["rule"])
        c.text(x, ybot + 20, _fmt_num(tick), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="middle")
    for tick in _ticks(min(ys), max(ys) or 1, 5):
        y = ybot - (tick - min(ys)) / (max(ys) - min(ys) or 1) * (ybot - ytop)
        c.line(x0, y, x1, y, stroke=ENTERPRISE_PROFILE["rule"])
        c.text(x0 - 8, y + 4, _fmt_num(tick), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="end")
    c.text(x0 + (x1 - x0) / 2, c.h - 16, str(spec.axes.get("x_label", "X")), size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
    c.text(16, ytop + (ybot - ytop) / 2, str(spec.axes.get("y_label", "Y")), size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
    for item in items:
        x = x0 + (float(item.x) - min(xs)) / (max(xs) - min(xs) or 1) * (x1 - x0)
        y = ybot - (float(item.y) - min(ys)) / (max(ys) - min(ys) or 1) * (ybot - ytop)
        c.circle(x, y, 5, fill=ENTERPRISE_PROFILE["accent_tint"], stroke=ENTERPRISE_PROFILE["accent"], width=1.5)
        c.text(x + 9, y + 4, item.label, size=10, fill=ENTERPRISE_PROFILE["ink"], weight=500)


def _gen_treemap(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if isinstance(item.weight, (int, float)) and item.weight > 0]
    total = sum(float(item.weight) for item in items)  # type: ignore[arg-type]
    x0, y0, x1, y1 = 32.0, 32.0, c.w - 32.0, c.h - 32.0
    cx, cy, cw, ch = x0, y0, x1 - x0, y1 - y0
    remaining = total
    horizontal = cw >= ch
    for item in items:
        weight = float(item.weight)  # type: ignore[arg-type]
        frac = weight / remaining if remaining else 0
        if horizontal:
            strip_w = cw * frac
            _treemap_cell(c, item, cx, cy, strip_w, ch, frac)
            cx += strip_w
            cw -= strip_w
        else:
            strip_h = ch * frac
            _treemap_cell(c, item, cx, cy, cw, strip_h, frac)
            cy += strip_h
            ch -= strip_h
        remaining -= weight
        horizontal = cw >= ch


def _treemap_cell(c: _Canvas, item: Any, x: float, y: float, w: float, h: float, frac: float) -> None:
    if w < 12 or h < 12:
        return
    c.rect(x, y, w, h, fill=ENTERPRISE_PROFILE["accent_tint"], stroke=ENTERPRISE_PROFILE["accent"], width=1)
    label = item.label
    if w >= 120 and h >= 44:
        lines = _lines(label, 10, 2)
        ty = y + 22
        for line in lines:
            c.text(x + 8, ty, line, size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600)
            ty += 16
        value = f"{_fmt_num(item.value)}{item.unit or ''} ({frac * 100:.0f}%)" if item.value is not None else f"{frac * 100:.0f}%"
        c.text(x + 8, y + h - 10, value, size=10, fill=ENTERPRISE_PROFILE["muted"], weight=500)


def _gen_timeline(c: _Canvas, spec: VisualSpec) -> None:
    items = [item for item in spec.items if item.period]
    x0, x1 = 56.0, c.w - 56.0
    mid_y = c.h / 2
    c.line(x0, mid_y, x1, mid_y, stroke=ENTERPRISE_PROFILE["rule_solid"], width=1.2)
    step = (x1 - x0) / max(len(items) - 1, 1)
    for i, item in enumerate(items):
        x = x0 + step * i
        c.circle(x, mid_y, 6, fill=ENTERPRISE_PROFILE["accent"], stroke=ENTERPRISE_PROFILE["paper"], width=2)
        if i % 2 == 0:
            c.text(x, mid_y - 22, item.period or "", size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
            c.text(x, mid_y + 34, item.label, size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
        else:
            c.text(x, mid_y + 26, item.period or "", size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
            c.text(x, mid_y - 30, item.label, size=11, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")
        if item.note and x + 8 < x1:
            c.text(x + 8, mid_y + 4, item.note, size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")


def _gen_process(c: _Canvas, spec: VisualSpec) -> None:
    stages = spec.stages
    n = len(stages)
    box_w = min(220, (c.w - 120 - (n - 1) * 72) / max(n, 1))
    box_h = 84
    y = c.h / 2 - box_h / 2
    x = 60.0
    for i, stage in enumerate(stages):
        c.rect(x, y, box_w, box_h, fill=ENTERPRISE_PROFILE["paper"], stroke=ENTERPRISE_PROFILE["ink"], rx=8)
        lines = _lines(stage.label, 12, 2)
        ty = y + 34
        for line in lines:
            c.text(x + box_w / 2, ty, line, size=13, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
            ty += 18
        if stage.note:
            c.text(x + box_w / 2, y + box_h + 20, stage.note, size=10, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")
        if i < n - 1:
            ax1 = x + box_w + 24
            ax2 = x + box_w + 48
            _arrow(c, ax1, y + box_h / 2, ax2, y + box_h / 2, stroke=ENTERPRISE_PROFILE["accent"])
            if stage.to_label and stage.from_label:
                c.text(ax1 + (ax2 - ax1) / 2, y + box_h / 2 - 10, f"{stage.from_label} → {stage.to_label}", size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")
            else:
                c.text(ax1 + (ax2 - ax1) / 2, y + box_h / 2 - 10, str(stage.weight or ""), size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")
        x += box_w + 72


def _gen_sankey(c: _Canvas, spec: VisualSpec) -> None:
    stages = [stage for stage in spec.stages if isinstance(stage.weight, (int, float)) and stage.weight > 0]
    sources: list[str] = []
    targets: list[str] = []
    for stage in stages:
        if stage.from_label and stage.from_label not in sources:
            sources.append(stage.from_label)
        if stage.to_label and stage.to_label not in targets:
            targets.append(stage.to_label)
    s_weights = {s: sum(float(st.weight) for st in stages if st.from_label == s) for s in sources}
    t_weights = {t: sum(float(st.weight) for st in stages if st.to_label == t) for t in targets}
    total = sum(s_weights.values()) or 1
    margin_y = 60.0
    avail = c.h - 2 * margin_y
    col_w = 26.0
    x1 = 96.0
    x2 = c.w - 96.0 - col_w
    y_off_s: dict[str, float] = {}
    y_off_t: dict[str, float] = {}
    ys = margin_y
    for s in sources:
        h = s_weights[s] / total * avail
        y_off_s[s] = ys
        ys += h + 14
    yt = margin_y
    for t in targets:
        h = t_weights[t] / total * avail
        y_off_t[t] = yt
        yt += h + 14
    for s in sources:
        h = s_weights[s] / total * avail
        c.rect(x1, y_off_s[s], col_w, h, fill=ENTERPRISE_PROFILE["accent"], rx=4)
        c.text(x1 - 10, y_off_s[s] + h / 2 + 4, s, size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="end")
        c.text(x1 - 10, y_off_s[s] + h / 2 + 18, _fmt_num(s_weights[s]), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400, anchor="end")
    for t in targets:
        h = t_weights[t] / total * avail
        c.rect(x2, y_off_t[t], col_w, h, fill=ENTERPRISE_PROFILE["muted"], rx=4)
        c.text(x2 + col_w + 10, y_off_t[t] + h / 2 + 4, t, size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600)
        c.text(x2 + col_w + 10, y_off_t[t] + h / 2 + 18, _fmt_num(t_weights[t]), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400)
    for stage in stages:
        s, t = stage.from_label, stage.to_label
        if not s or not t:
            continue
        w = float(stage.weight)  # type: ignore[arg-type]
        # stack ribbon offsets by target order
        offset_s = 0.0
        for st in stages:
            if st.from_label == s and st.to_label == t:
                break
            if st.from_label == s:
                offset_s += float(st.weight)
        offset_t = 0.0
        for st in stages:
            if st.to_label == t and st.from_label == s:
                break
            if st.to_label == t:
                offset_t += float(st.weight)
        sy1 = y_off_s[s] + offset_s
        ty1 = y_off_t[t] + offset_t
        sy2 = sy1 + w / total * avail
        ty2 = ty1 + w / total * avail
        dx = (x2 - x1) / 2
        c.path(
            f"M{x1 + col_w:g},{sy1:g} C{x1 + col_w + dx:g},{sy1:g} {x2 - dx:g},{ty1:g} {x2:g},{ty1:g} "
            f"L{x2:g},{ty2:g} C{x2 - dx:g},{ty2:g} {x1 + col_w + dx:g},{sy2:g} {x1 + col_w:g},{sy2:g} Z",
            fill="rgba(27,54,93,0.16)", stroke="rgba(27,54,93,0.30)", width=0.8,
        )


def _gen_gantt(c: _Canvas, spec: VisualSpec) -> None:
    stages = [stage for stage in spec.stages if stage.start and stage.end]
    n = len(stages)
    row_h = min(56, (c.h - 100) / max(n, 1))
    label_w = 220.0
    x0 = label_w + 16
    x1 = c.w - 40
    y_top = 44.0
    for i, stage in enumerate(stages):
        y = y_top + i * row_h
        c.text(label_w, y + row_h / 2 + 4, stage.label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="end")
        c.line(x0, y + row_h / 2, x1, y + row_h / 2, stroke=ENTERPRISE_PROFILE["rule"])
        xa = x0 + (x1 - x0) * 0.15
        xb = x0 + (x1 - x0) * 0.75
        if stage.note:
            c.text(xb + 10, y + row_h / 2 + 4, stage.note, size=10, fill=ENTERPRISE_PROFILE["soft"], weight=400)
        bar_w = max(8, xb - xa)
        c.rect(xa, y + row_h / 2 - 12, bar_w, 24, fill=ENTERPRISE_PROFILE["accent"], rx=6)
        c.text(xa + bar_w / 2, y + row_h / 2 + 4, f"{stage.start} – {stage.end}", size=10, fill=ENTERPRISE_PROFILE["paper"], weight=500, anchor="middle")
        c.text(x0, y + row_h - 4, stage.start or "", size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400)
        c.text(xb + 44, y + row_h - 4, stage.end or "", size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400)
    # months axis ticks
    months: list[str] = []
    for stage in stages:
        for m in (stage.start, stage.end):
            if m and m not in months:
                months.append(m)
    c.text(x0 + 8, c.h - 24, "时间：" + " / ".join(months), size=10, fill=ENTERPRISE_PROFILE["muted"], weight=400)


def _gen_pyramid(c: _Canvas, spec: VisualSpec) -> None:
    items = spec.items
    n = len(items)
    cx = c.w / 2
    top_y = 40.0
    layer_h = (c.h - 96) / max(n, 1)
    base_w = c.w - 200
    for i, item in enumerate(items):
        frac = 1.0 - (i / max(n, 1)) * 0.7
        half = base_w * frac / 2
        y = top_y + i * layer_h
        half_below = base_w * (1.0 - ((i + 1) / max(n, 1)) * 0.7) / 2
        c.path(
            f"M{cx - half:g},{y:g} L{cx + half:g},{y:g} L{cx + half_below:g},{y + layer_h:g} L{cx - half_below:g},{y + layer_h:g} Z",
            fill=ENTERPRISE_PROFILE["accent_tint"] if i == 0 else "rgba(27,54,93,0.04)",
            stroke=ENTERPRISE_PROFILE["accent"], width=1,
        )
        value = f"{_fmt_num(item.value)}{item.unit or ''}" if item.value is not None else ""
        c.text(cx - half - 12, y + layer_h / 2 + 4, item.label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="end")
        c.text(cx + half + 12, y + layer_h / 2 + 4, value, size=12, fill=ENTERPRISE_PROFILE["muted"], weight=600, anchor="start")
        if item.note:
            c.text(cx, y + layer_h - 8, item.note, size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")


def _gen_tree(c: _Canvas, spec: VisualSpec) -> None:
    nodes = spec.nodes
    children: dict[str, list[Any]] = {}
    roots: list[Any] = []
    ids = {node.id for node in nodes}
    for node in nodes:
        if node.parent and node.parent in ids:
            children.setdefault(node.parent, []).append(node)
        else:
            roots.append(node)
    depth_map: dict[str, int] = {}

    def assign(node: Any, depth: int) -> None:
        depth_map[node.id] = depth
        for child in children.get(node.id, []):
            assign(child, depth + 1)

    for root in roots:
        assign(root, 0)
    max_depth = max(depth_map.values(), default=0) + 1
    n_layers = max_depth
    col_w = (c.w - 80) / max(n_layers, 1)
    slot = (c.h - 80) / max(len(nodes), 1)
    node_w = min(col_w - 24, 260)
    node_h = min(slot - 12, 48)
    pos: dict[str, tuple[float, float]] = {}
    for i, node in enumerate(nodes):
        x = 40 + col_w * depth_map[node.id] + (col_w - node_w) / 2
        y = 40 + slot * i
        pos[node.id] = (x, y)
    for node in nodes:
        if node.parent and node.parent in pos:
            px, py = pos[node.parent]
            x, y = pos[node.id]
            _ortho(c, px + node_w, py + node_h / 2, x, y + node_h / 2, stroke=ENTERPRISE_PROFILE["rule_solid"])
    for node in nodes:
        x, y = pos[node.id]
        fill, stroke, dash = _node_fill(node.kind)
        c.rect(x, y, node_w, node_h, fill=fill, stroke=stroke, rx=8, dash=dash)
        label = _lines(node.label, 12, 1)[0]
        c.text(x + node_w / 2, y + node_h / 2 + 4, label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
        if node.sublabel:
            c.text(x + node_w / 2, y + node_h / 2 + 20, node.sublabel, size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")


def _gen_fishbone(c: _Canvas, spec: VisualSpec) -> None:
    nodes = spec.nodes
    focal = next((n for n in nodes if n.kind == "focal"), None)
    causes = [n for n in nodes if n.kind != "focal"]
    mid_y = c.h / 2
    spine_x0, spine_x1 = 48.0, c.w - 160.0
    c.line(spine_x0, mid_y, spine_x1, mid_y, stroke=ENTERPRISE_PROFILE["ink"], width=1.6)
    c.path(f"M{spine_x1:g},{mid_y - 10:g} L{spine_x1 + 16:g},{mid_y:g} L{spine_x1:g},{mid_y + 10:g} Z", fill=ENTERPRISE_PROFILE["ink"])
    if focal:
        c.rect(spine_x1 + 24, mid_y - 32, 120, 64, fill=ENTERPRISE_PROFILE["accent_tint"], stroke=ENTERPRISE_PROFILE["accent"], rx=8)
        c.text(spine_x1 + 84, mid_y + 4, focal.label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
    n_causes = len(causes)
    if n_causes:
        step = (spine_x1 - spine_x0) / max(n_causes, 1)
    for i, cause in enumerate(causes):
        top = i % 2 == 0
        x = spine_x0 + step * (i + 0.5)
        y = mid_y - 44 if top else mid_y + 44
        c.line(x, mid_y, x, y, stroke=ENTERPRISE_PROFILE["rule_solid"], width=1.2)
        c.path(f"M{x:g},{y:g} L{x - 6:g},{y - 8:g} L{x:g},{y - 12:g}", stroke=ENTERPRISE_PROFILE["rule_solid"], width=1.2)
        c.text(x, y + 4 if top else y + 12, cause.label, size=11, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
        if cause.sublabel:
            c.text(x, y - 18 if top else y + 24, cause.sublabel, size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")


def _gen_architecture(c: _Canvas, spec: VisualSpec) -> None:
    nodes = spec.nodes
    order = ["input", "external", "backend", "store", "security", "focal", "optional"]
    bands: list[str] = [kind for kind in order if any(n.kind == kind for n in nodes)]
    if not bands:
        bands = ["backend"]
    band_h = (c.h - 100) / max(len(bands), 1)
    y = 60.0
    prev_centers: list[float] = []
    for band in bands:
        members = [n for n in nodes if n.kind == band]
        c.rect(40, y, c.w - 80, band_h - 12, fill=ENTERPRISE_PROFILE["paper2"], stroke=ENTERPRISE_PROFILE["rule"], rx=8)
        c.text(56, y + 24, band, size=11, fill=ENTERPRISE_PROFILE["muted"], weight=600)
        slot_w = (c.w - 120) / max(len(members), 1)
        centers: list[float] = []
        for i, member in enumerate(members):
            x = 72 + slot_w * i + (slot_w - 180) / 2
            x = max(64, x)
            fill, stroke, dash = _node_fill(member.kind)
            c.rect(x, y + 36, 180, 40, fill=fill, stroke=stroke, rx=6, dash=dash)
            label = _lines(member.label, 16, 1)[0]
            c.text(x + 90, y + 60, label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
            centers.append(x + 90)
        if prev_centers:
            for px in prev_centers:
                cx = min(centers, key=lambda cxx: abs(cxx - px))
                _ortho(c, px, y - 12, cx, y + 36, stroke=ENTERPRISE_PROFILE["rule_solid"])
        prev_centers = centers
        y += band_h


def _gen_journey(c: _Canvas, spec: VisualSpec) -> None:
    stages = spec.stages
    n = len(stages)
    x0, x1 = 72.0, c.w - 72.0
    mid_y = c.h / 2 + 20
    c.line(x0, mid_y, x1, mid_y, stroke=ENTERPRISE_PROFILE["rule_solid"], width=1.4)
    step = (x1 - x0) / max(n - 1, 1)
    for i, stage in enumerate(stages):
        x = x0 + step * i
        c.circle(x, mid_y, 7, fill=ENTERPRISE_PROFILE["accent"], stroke=ENTERPRISE_PROFILE["paper"], width=2)
        box_w, box_h = 180.0, 64.0
        top = i % 2 == 0
        by = mid_y - box_h - 28 if top else mid_y + 28
        c.rect(x - box_w / 2, by, box_w, box_h, fill=ENTERPRISE_PROFILE["paper"], stroke=ENTERPRISE_PROFILE["ink"], rx=8)
        label = _lines(stage.label, 12, 1)[0]
        c.text(x, by + 28, label, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
        if stage.note:
            c.text(x, by + 46, _lines(stage.note, 16, 1)[0], size=9, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")
        c.line(x, mid_y - 7 if top else mid_y + 7, x, by + box_h if top else by, stroke=ENTERPRISE_PROFILE["rule_solid"], width=1)
        if stage.weight is not None:
            c.text(x, mid_y + (34 if top else -34), f"{_fmt_num(stage.weight)}", size=10, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="middle")


def _gen_kpi_cards(c: _Canvas, spec: VisualSpec) -> None:
    items = spec.items
    n = max(len(items), 1)
    card_w = min(300, (c.w - 48 - (n - 1) * 20) / n)
    card_h = min(180, c.h - 120)
    y = (c.h - card_h) / 2
    for i, item in enumerate(items):
        x = 24 + i * (card_w + 20)
        c.rect(x, y, card_w, card_h, fill=ENTERPRISE_PROFILE["paper2"], stroke=ENTERPRISE_PROFILE["rule"], rx=8)
        value = _fmt_num(item.value) if item.value is not None else "—"
        c.text(x + card_w / 2, y + 64, value, size=40, fill=ENTERPRISE_PROFILE["accent"], weight=600, anchor="middle")
        if item.unit:
            c.text(x + card_w / 2 + 8 * len(value) + 14, y + 64, item.unit, size=14, fill=ENTERPRISE_PROFILE["muted"], weight=500, anchor="start")
        label = _lines(item.label, 14, 1)[0]
        c.text(x + card_w / 2, y + 104, label, size=14, fill=ENTERPRISE_PROFILE["ink"], weight=600, anchor="middle")
        if item.note:
            note = _lines(item.note, 18, 1)[0]
            c.text(x + card_w / 2, y + 128, note, size=10, fill=ENTERPRISE_PROFILE["soft"], weight=400, anchor="middle")


def _gen_table(c: _Canvas, spec: VisualSpec) -> None:
    items = spec.items
    if not items:
        return
    x0, x1 = 32.0, c.w - 32.0
    row_h = 40.0
    header_h = 36.0
    col_ratios = [0.28, 0.18, 0.12, 0.12, 0.30]
    cols = ["指标", "数值", "单位", "期间", "说明"]
    widths = [max(80, (x1 - x0) * r) for r in col_ratios]
    total_w = sum(widths)
    offset = x0 + ((x1 - x0) - total_w) / 2
    x_positions: list[float] = []
    xx = offset
    for w in widths:
        x_positions.append(xx)
        xx += w
    c.rect(offset, 32, total_w, header_h, fill=ENTERPRISE_PROFILE["paper2"], stroke=ENTERPRISE_PROFILE["rule_solid"], rx=4)
    for i, col in enumerate(cols):
        c.text(x_positions[i] + 12, 32 + header_h / 2 + 4, col, size=12, fill=ENTERPRISE_PROFILE["ink"], weight=700)
    y = 32 + header_h
    for row_i, item in enumerate(items):
        if row_i % 2 == 1:
            c.rect(offset, y, total_w, row_h, fill="rgba(27,54,93,0.03)")
        cells = [
            item.label,
            _fmt_num(item.value) if item.value is not None else "",
            item.unit or "",
            item.period or "",
            item.note or "",
        ]
        for i, cell in enumerate(cells):
            c.text(x_positions[i] + 12, y + row_h / 2 + 4, _lines(cell, 22, 1)[0], size=11, fill=ENTERPRISE_PROFILE["ink"], weight=500)
        c.line(offset, y + row_h, offset + total_w, y + row_h, stroke=ENTERPRISE_PROFILE["rule"])
        y += row_h
    c.line(offset, 32, offset, y, stroke=ENTERPRISE_PROFILE["rule_solid"])
    c.line(offset + total_w, 32, offset + total_w, y, stroke=ENTERPRISE_PROFILE["rule_solid"])


GENERATORS: dict[VisualType, Callable[[_Canvas, VisualSpec], None]] = {
    "line": _gen_line,
    "bar": _gen_bar,
    "radar": _gen_radar,
    "quadrant": _gen_quadrant,
    "scatter": _gen_scatter,
    "treemap": _gen_treemap,
    "timeline": _gen_timeline,
    "process": _gen_process,
    "data_flow": _gen_process,
    "sankey": _gen_sankey,
    "gantt": _gen_gantt,
    "pyramid": _gen_pyramid,
    "tree": _gen_tree,
    "fishbone": _gen_fishbone,
    "architecture": _gen_architecture,
    "journey": _gen_journey,
    "kpi_cards": _gen_kpi_cards,
    "table": _gen_table,
}


# ── adapter ──────────────────────────────────────────────────────────────────

def _locate_diagram_design() -> Path | None:
    env = os.getenv("DIAGRAM_DESIGN_SKILL_ROOT")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser().resolve())
    root = Path(__file__).resolve().parents[3]  # skill root (e.g. .agents/skills/enterprise-energy-research)
    candidates.extend([
        root.parent / "diagram-design",
        root / "vendor" / "skills" / "diagram-design",
        root / "third_party" / "diagram-design",
    ])
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file() and (candidate / "LICENSE").is_file():
            return candidate
    return None


class DiagramDesignAdapter:
    """Renders VisualSpecs into SVG/HTML/PNG via the diagram-design system."""

    def __init__(self, skill_root: Path | None = None, profile: dict[str, str] | None = None) -> None:
        self.skill_root = skill_root or _locate_diagram_design()
        self.profile = dict(profile or ENTERPRISE_PROFILE)

    # ── introspection (QA / tests) ──
    def style_tokens(self) -> dict[str, str]:
        return dict(self.profile)

    def supported_types(self) -> set[VisualType]:
        return set(GENERATORS)

    def skill_available(self) -> bool:
        return self.skill_root is not None

    def license_path(self) -> Path | None:
        if not self.skill_root:
            return None
        return self.skill_root / "LICENSE"

    def size_for(self, visual_type: VisualType) -> tuple[int, int]:
        return SIZE_PRESETS["doc-wide" if visual_type in WIDE_TYPES else "doc-inline"]

    # ── rendering ──
    def build_visual_svg(self, spec: VisualSpec) -> str:
        generator = GENERATORS.get(spec.visual_type)
        if generator is None:
            raise ValueError(f"unsupported visual_type: {spec.visual_type}")
        width, height = self.size_for(spec.visual_type)
        desc = spec.subtitle or spec.business_thesis or spec.title
        canvas = _Canvas(width, height, spec.visual_id, spec.title, desc)
        generator(canvas, spec)
        return canvas.svg()

    def build_visual(
        self,
        spec: VisualSpec,
        output_dir: Path,
        *,
        destination: str = "html",
        png_scale: int = 3,
    ) -> VisualRenderResult:
        """Render one visual. Never silently drops a spec: failures degrade to
        ``fallback_table`` (structured table from the same data) or ``failed``."""
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            svg = self.build_visual_svg(spec)
        except Exception as exc:  # noqa: BLE001 - QA-visible, never silent
            return self._fallback_table(spec, output_dir, png_scale, reason=f"renderer error: {exc}")
        try:
            return self._emit(spec, svg, output_dir, destination, png_scale)
        except Exception as exc:  # noqa: BLE001
            return self._fallback_table(spec, output_dir, png_scale, reason=f"emission error: {exc}")

    def _emit(
        self, spec: VisualSpec, svg: str, output_dir: Path, destination: str, png_scale: int,
    ) -> VisualRenderResult:
        width, height = self.size_for(spec.visual_type)
        html_path = output_dir / f"{spec.visual_id}.html"
        html_path.write_text(self._wrap_html(spec, svg), encoding="utf-8")
        svg_path = output_dir / f"{spec.visual_id}.svg"
        svg_path.write_text(self.extract_svg(self._wrap_html(spec, svg)), encoding="utf-8")
        png_path: Path | None = None
        png_status = "not_requested"
        if destination in ("word", "both"):
            png_path = output_dir / f"{spec.visual_id}.png"
            ok = self.export_png(html_path, png_path, scale=png_scale)
            png_status = "ok" if ok else "unavailable"
        return VisualRenderResult(
            visual_id=spec.visual_id,
            status="rendered",
            visual_type=spec.visual_type,
            html_path=html_path,
            svg_path=svg_path,
            png_path=png_path if png_status == "ok" else None,
            svg_markup=svg,
            png_status=png_status,
            width=width,
            height=height,
        )

    def _fallback_table(self, spec: VisualSpec, output_dir: Path, png_scale: int, reason: str) -> VisualRenderResult:
        """Safe fallback: structured table drawn from the same VisualSpec data."""
        fallback = spec.model_copy(deep=True)
        fallback.visual_type = "table"
        fallback.semantic_pattern = "none"
        try:
            svg = self.build_visual_svg(fallback)
            result = self._emit(fallback, svg, output_dir, "both", png_scale)
            result.status = "fallback_table"
            result.fallback_reason = reason
            return result
        except Exception as exc:  # noqa: BLE001
            return VisualRenderResult(
                visual_id=spec.visual_id,
                status="failed",
                visual_type=spec.visual_type,
                error=f"{reason}; fallback failed: {exc}",
            )

    # ── HTML wrapper ──
    def _wrap_html(self, spec: VisualSpec, svg: str) -> str:
        title = _xml(spec.title)
        subtitle = _xml(spec.subtitle or spec.business_thesis or "")
        source = _xml(spec.source_note or "")
        fonts = self.profile.get("google_fonts_url", "")
        link = f'<link href="{fonts}" rel="stylesheet">' if fonts else ""
        font_sans = _xml(self.profile["font_sans"])
        font_serif = _xml(self.profile["font_serif"])
        return (
            "<!DOCTYPE html>\n"
            '<html lang="zh-CN">\n<head>\n'
            '<meta charset="utf-8">\n'
            f"<title>{title}</title>\n{link}\n"
            "<style>\n"
            "body{margin:0;background:#FFFFFF;color:#1B1F26;}\n"
            f".fig-header{{padding:24px 8px 4px 8px;font-family:{font_sans};}}\n"
            f".fig-header h1{{margin:0 0 4px 0;font-family:{font_serif};font-weight:600;font-size:22px;color:#1B1F26;}}\n"
            f".fig-header p{{margin:0;font-family:{font_sans};font-size:13px;color:#4A5568;}}\n"
            "figure{margin:0;padding:8px;}\n"
            # native-size rendering: the exported PNG must be exactly
            # viewBox × device_scale_factor (diagram-design export.md)
            "figure svg{width:auto;height:auto;max-width:100%;display:block;}\n"
            f".fig-source{{padding:4px 8px 16px 8px;font-family:{font_sans};font-size:11px;color:#7A8399;}}\n"
            "</style>\n</head>\n<body>\n"
            f'<header class="fig-header"><h1>{title}</h1><p>{subtitle}</p></header>\n'
            f"<figure>{svg}</figure>\n"
            f'<p class="fig-source">{source}</p>\n'
            "</body>\n</html>\n"
        )

    # ── SVG standalone export (diagram-design references/export.md) ──
    @staticmethod
    def extract_svg(html: str, google_fonts_url: str = "") -> str:
        match = re.search(r"<svg\b.*?</svg>", html, re.DOTALL)
        if not match:
            raise ValueError("no <svg> block found in html")
        svg = match.group(0)
        if "xmlns=" not in svg.split(">")[0]:
            svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        if "viewBox" not in svg.split(">")[0]:
            svg = svg.replace("<svg", ' viewBox="0 0 960 600"', 1)  # warn: best-effort
        if google_fonts_url and "<defs>" not in svg:
            inject = f"<defs><style>@import url('{google_fonts_url}');</style></defs>"
            svg = svg.replace(">", f">{inject}", 1)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg

    # ── PNG export: Playwright → Chrome/Edge headless (same HTML) ──
    def export_png(self, html_path: Path, png_path: Path, *, scale: int = 3) -> bool:
        try:
            if self._png_playwright(html_path, png_path, scale):
                return True
        except Exception:  # noqa: BLE001 - try browser fallback
            pass
        return self._png_browser(html_path, png_path, scale)

    @staticmethod
    def _png_playwright(html_path: Path, png_path: Path, scale: int) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError:
            return False
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(device_scale_factor=scale)
            page.goto(f"file://{html_path.resolve().as_posix()}")
            page.wait_for_load_state("networkidle")
            page.locator("svg").first.screenshot(path=str(png_path), omit_background=True)
            browser.close()
        return png_path.is_file() and png_path.stat().st_size > 0

    def _png_browser(self, html_path: Path, png_path: Path, scale: int) -> bool:
        browser = self._browser_executable()
        if not browser:
            return False
        html = html_path.read_text(encoding="utf-8")
        match = re.search(r'viewBox="0 0 (\d+) (\d+)"', html)
        if not match:
            return False
        width, height = int(match.group(1)), int(match.group(2))
        render_html = html_path.with_name(f"{html_path.stem}.render.html")
        # minimal SVG-only page: screenshot == SVG bounds at any DPR
        svg_match = re.search(r"<svg\b.*?</svg>", html, re.DOTALL)
        if not svg_match:
            return False
        render_html.write_text(
            f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>html,body{{margin:0;padding:0;background:#FFFFFF;}}</style></head>'
            f'<body>{svg_match.group(0)}</body></html>',
            encoding="utf-8",
        )
        cmd = [
            browser,
            "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--disable-extensions",
            f"--force-device-scale-factor={scale}",
            f"--window-size={width},{height}",
            f"--screenshot={png_path.resolve()}",
            f"file:///{render_html.resolve().as_posix()}",
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        except Exception:  # noqa: BLE001
            return False
        return png_path.is_file() and png_path.stat().st_size > 0

    @staticmethod
    def _browser_executable() -> str | None:
        local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
        home = Path.home()
        # playwright-managed browser caches (primary path when playwright exists)
        playwright_roots: list[Path] = []
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            playwright_roots.append(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
        playwright_roots.extend([
            local_appdata / "ms-playwright",
            home / ".cache" / "ms-playwright",
            home / "Library" / "Caches" / "ms-playwright",
        ])
        for root in playwright_roots:
            if not root.is_dir():
                continue
            chromium_dirs = sorted(root.glob("chromium*"), reverse=True)
            for directory in chromium_dirs:
                for relative in (
                    # modern playwright layout (1.5x+): 64-bit dirs
                    "chrome-win64/chrome.exe", "chrome-linux64/chrome",
                    "chrome-mac-x64/Chromium.app/Contents/MacOS/Chromium",
                    # legacy playwright layout
                    "chrome-win/chrome.exe", "chrome-linux/chrome",
                    "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
                ):
                    candidate = directory / relative
                    if candidate.is_file():
                        return str(candidate)
            for directory in sorted(root.glob("chromium_headless_shell*"), reverse=True):
                for relative in (
                    "chrome-headless-shell-win64/chrome-headless-shell.exe",
                    "chrome-headless-shell-linux64/chrome-headless-shell",
                    "chrome-headless-shell-mac-x64/chrome-headless-shell",
                    "chrome-win/headless_shell.exe", "chrome-linux/headless_shell",
                ):
                    candidate = directory / relative
                    if candidate.is_file():
                        return str(candidate)
        candidates = [
            os.getenv("CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            str(local_appdata / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(local_appdata / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium") or shutil.which("chromium-browser")
