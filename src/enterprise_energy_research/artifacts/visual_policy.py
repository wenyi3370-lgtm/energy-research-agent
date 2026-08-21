"""Visual policy loader (office_visual_policy.yaml).

Publishers (Word/HTML) are driven by this single source of truth so that
edits to ``config/office_visual_policy.yaml`` take effect without code
changes. Missing file or missing keys fall back to the built-in defaults
(which mirror the v0.9.0 quality contract), so behaviour is predictable in
the absence of a policy file.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from enterprise_energy_research.settings import load_yaml

DEFAULT_POLICY: dict[str, Any] = {
    "theme": {
        "name": "enterprise-consulting-diagram-design",
        "colors": {
            "white": "#FFFFFF",
            "black": "#1B1F26",
            "navy": "#1B365D",
            "cobalt": "#2D5A8A",
            "cool_gray": "#4A5568",
            "pale_gray": "#C9D4E0",
            "canvas": "#F7F8FA",
        },
        "minimum_chart_font_pt": 8,
    },
    "diagram_design": {
        # diagram-design semantic tokens, enterprise consulting adaptation
        "paper": "#FFFFFF",
        "ink": "#1B1F26",
        "muted": "#4A5568",
        "soft": "#7A8399",
        "accent": "#1B365D",
        "accent_tint": "rgba(27,54,93,0.08)",
        "font_sans": "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Source Han Sans SC, Arial, sans-serif",
        "font_serif": "Source Han Serif SC, Noto Serif CJK SC, SimSun, serif",
        "png_scale": 3,
        # per-chapter photograph budgets (P0 image count control)
        "image_budget_executive_summary": 2,
        "image_budget_factories": 6,
        "image_budget_products": 8,
        "image_budget_analysis": 4,
    },
    "word": {
        "page": "A4",
        "body_cjk_font": "SimSun",
        "body_latin_font": "Times New Roman",
        "body_size_pt": 12,
        "line_spacing_pt": 22,
        "first_line_indent_characters": 2,
        "heading_1_size_pt": 22,
        "heading_2_size_pt": 14,
        "heading_3_size_pt": 12,
        "table_size_pt": 9,
        "table_style": "three-line",
        "figure_png_dpi": 300,
        "maximum_figure_width_cm": 15.6,
        "minimum_analysis_characters_before_visual": 0,
    },
}

_REPOSITORY_ROOT: Path | None = None


def repository_root() -> Path:
    """Project root regardless of install layout (config/ lives there)."""
    global _REPOSITORY_ROOT
    if _REPOSITORY_ROOT is None:
        for parent in Path(__file__).resolve().parents:
            if (parent / "config" / "office_visual_policy.yaml").is_file():
                _REPOSITORY_ROOT = parent
                break
        else:
            _REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
    return _REPOSITORY_ROOT


@functools.lru_cache(maxsize=1)
def load_visual_policy() -> dict[str, Any]:
    """Load the visual policy, falling back to built-in defaults per key."""
    merged = _deep_merge(DEFAULT_POLICY, _load_yaml_or_empty(repository_root() / "config" / "office_visual_policy.yaml"))
    return merged


def _load_yaml_or_empty(path: Path) -> dict[str, Any]:
    try:
        return load_yaml(path)
    except FileNotFoundError:
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def colors() -> dict[str, str]:
    return dict(load_visual_policy()["theme"]["colors"])


def word_policy() -> dict[str, Any]:
    return dict(load_visual_policy()["word"])


def invalidate_cache() -> None:
    load_visual_policy.cache_clear()
