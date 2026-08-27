from __future__ import annotations

import re

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.text import Text


THEME_ID = "kami-broker-v2"
WORD_CONTENT_WIDTH_IN = 15.6 / 2.54

COLORS = {
    "primary": "#1B365D",
    "secondary": "#2D5A8A",
    "accent": "#C9A227",
    "teal": "#167C80",
    "neutral_dark": "#6B6A64",
    "neutral_mid": "#9C9A93",
    "neutral": "#B8B7B0",
    "neutral_light": "#D6D3CB",
    "surface_light": "#EEF2F7",
    "positive": "#2E7D32",
    "negative": "#B91C1C",
    "white": "#FFFFFF",
    "black": "#000000",
}

SERIES_COLORS = [
    COLORS["primary"],
    COLORS["secondary"],
    COLORS["teal"],
    COLORS["accent"],
    COLORS["neutral_dark"],
    COLORS["neutral_mid"],
    COLORS["neutral"],
]

FIGURE_SIZES = {
    "standard": (WORD_CONTENT_WIDTH_IN, 3.8),
    "ranking": (WORD_CONTENT_WIDTH_IN, 4.4),
    "multi_panel": (WORD_CONTENT_WIDTH_IN, 5.0),
}

# v9: unified font discovery lives in scripts/common/fonts.py (multi-level:
# matplotlib -> fontconfig -> filesystem; TTC-aware, SC-first policy).
from common.fonts import (  # noqa: F401
    CJK_FONT_CANDIDATES,
    register_font_for_matplotlib,
    require_cjk_font,
)


def _cjk_family() -> str:
    """Resolve the SC font and make it usable by matplotlib, then return its
    family name.  Raises (loudly, with guidance) when the SC font cannot be
    loaded by matplotlib — charts must never silently render tofu boxes.
    """
    resolved = require_cjk_font()
    if not register_font_for_matplotlib(resolved):
        raise RuntimeError(
            "SC 字体 %s 已由 %s 发现（%s），但 matplotlib 无法加载其 SC face"
            "（TTC 集合常只暴露 JP face）。请安装 SC 单文件字体（如"
            "NotoSerifCJKsc-Regular.otf），或显式配置"
            "require_simplified_chinese=False 使用区域变体。"
            % (resolved.family, resolved.source, resolved.path)
        )
    return resolved.family


def resolve_cjk_font() -> str:
    """Backward-compat alias for the old str-returning API (raises when no SC
    font is available).  Delegates to the shared multi-level resolver in
    scripts/common/fonts.py — no local candidate list, no local findfont.
    """
    return _cjk_family()


def apply_kami_broker_theme() -> None:
    cjk_font = _cjk_family()
    mpl.rcParams.update(
        {
            "figure.facecolor": COLORS["white"],
            "axes.facecolor": COLORS["white"],
            "savefig.facecolor": COLORS["white"],
            "savefig.transparent": False,
            "font.family": "serif",
            "font.serif": [
                "Times New Roman",
                cjk_font,
                "DejaVu Serif",
            ],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 9,
            "axes.titlesize": 13,
            "axes.titleweight": "normal",
            "axes.titlelocation": "center",
            "axes.labelsize": 10,
            "axes.labelcolor": COLORS["black"],
            "axes.edgecolor": COLORS["neutral_dark"],
            "axes.linewidth": 0.75,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "xtick.color": COLORS["neutral_dark"],
            "ytick.color": COLORS["neutral_dark"],
            "legend.fontsize": 9,
            "legend.frameon": False,
            "grid.color": COLORS["neutral_light"],
            "grid.linewidth": 0.5,
            "grid.alpha": 1.0,
            "lines.linewidth": 1.8,
            "patch.edgecolor": COLORS["white"],
            "patch.linewidth": 0.5,
        }
    )


def apply_kami_broker_theme_v2() -> None:
    """v2 visual layer (2026-08-10): v1 + readable hierarchy floor.

    - Chart titles: 16 pt (the 12 pt spec rendered too small at Word
      width), bold, ink blue `#1B365D` — use `title_block()` for the
      deck's top-left heading convention with accent underline.
    - Data labels: never below 8 pt (`bump_min_font` enforces on save).
    - Latin/digits: Times New Roman via `apply_mixed_text_fonts(fig)` —
      must be called before every savefig (v1 deck shipped SimSun-only,
      violating the dual-track font rule).
    """
    apply_kami_broker_theme()
    mpl.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 16,
            "axes.titleweight": "bold",
            "axes.titlecolor": COLORS["primary"],
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
        }
    )


def bump_min_font(fig, min_pt: float = 8.0) -> int:
    """Raise every text below min_pt to min_pt (Word 8 pt floor)."""
    bumped = 0
    for text in fig.findobj(match=Text):
        size = text.get_fontsize()
        if size and size < min_pt:
            text.set_fontsize(min_pt)
            bumped += 1
    return bumped


def title_block(fig, title: str | None = None, sub: str | None = None,
                max_chars: int = 32) -> str:
    """NO-OP (v2.2): top-of-figure text was REMOVED by user feedback.

    Word carries the title via its caption row ("图X-X 标题"), and any
    extra top note (gray note line) overlapped the axes in the Word render.
    Figures must be clean at the top — do not draw any in-figure title or
    note. Kept as a no-op for call compatibility; returns "".
    """
    return ""


def apply_mixed_text_fonts(fig) -> None:
    cjk_font = _cjk_family()
    text_artists = list(fig.findobj(match=Text))
    for ax in fig.get_axes():
        text_artists.extend(
            [
                ax.title,
                ax.xaxis.label,
                ax.yaxis.label,
                *ax.texts,
                *ax.get_xticklabels(),
                *ax.get_yticklabels(),
            ]
        )
        legend = ax.get_legend()
        if legend is not None:
            text_artists.extend(legend.get_texts())
    seen: set[int] = set()
    for text in text_artists:
        if id(text) in seen:
            continue
        seen.add(id(text))
        value = text.get_text() or ""
        if re.search(r"[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]", value):
            # Mixed CJK+latin strings: CJK first, digits/latin fall back to
            # Times New Roman per glyph (matplotlib >= 3.6 font fallback).
            text.set_fontfamily([cjk_font, "Times New Roman"])
        else:
            text.set_fontfamily("Times New Roman")


def style_axes(ax, *, horizontal_grid: bool = False) -> None:
    if "top" in ax.spines:
        ax.spines["top"].set_visible(False)
    if "right" in ax.spines:
        ax.spines["right"].set_visible(False)
    for key in ("left", "bottom"):
        if key in ax.spines:
            ax.spines[key].set_color(COLORS["neutral_dark"])
            ax.spines[key].set_linewidth(0.75)
    ax.set_axisbelow(True)
    ax.grid(False)
    if horizontal_grid:
        ax.grid(
            axis="y",
            color=COLORS["neutral_light"],
            linewidth=0.5,
            linestyle="-",
        )
    legend = ax.get_legend()
    if legend is not None:
        legend.set_frame_on(False)


def theme_series_colors(count: int) -> list[str]:
    if count <= 0:
        return []
    if count > len(SERIES_COLORS):
        raise ValueError(
            f"{THEME_ID} supports at most {len(SERIES_COLORS)} categorical series; "
            "reduce series or use small multiples."
        )
    return SERIES_COLORS[:count]

