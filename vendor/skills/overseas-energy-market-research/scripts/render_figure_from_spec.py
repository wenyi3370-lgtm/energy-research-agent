from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from figure_production import save_figure_bundle
from kami_broker_chart_theme import COLORS, apply_kami_broker_theme, apply_mixed_text_fonts, theme_series_colors
from chart_polish import donut, funnel, place_bar_labels, risk_matrix


BAR_TYPES = {"bar", "ranking-bar", "grouped-bar", "diverging-bar"}
TEXT_ONLY_SAFE_TYPES = {
    "bar", "ranking-bar", "lollipop", "dot-plot", "diverging-bar", "grouped-bar",
    "line", "scatter", "heatmap", "radar", "donut", "waterfall", "timeline",
    "funnel", "risk-matrix", "scenario-range", "bubble-ranking", "kpi-cards",
    "scorecards", "rating-tiles", "decision-cards", "risk-tiles", "pareto", "sensitivity", "forecast",
}


def _values(rows, field):
    return [number(row[field], field) for row in rows]


def _labels(rows, field):
    return [str(row[field]) for row in rows]


def infer_figure_type(spec: dict, rows: list[dict[str, str]]) -> str:
    """Select a semantic chart from the evidence relationship.

    This is deliberately deterministic so text-only models such as DeepSeek
    can obtain professional chart variety without seeing reference images.
    Explicit non-generic ``figure_type`` always wins; ``auto`` and ``bar``
    may be upgraded when the role/encoding states a stronger relationship.
    """
    requested = str(spec.get("figure_type") or "auto").strip().lower()
    encoding = spec.get("encoding") or {}
    intent = " ".join(
        str(value or "")
        for value in (
            spec.get("visual_intent"),
            encoding.get("relationship"),
            spec.get("role"),
            spec.get("figure_id"),
            spec.get("title"),
            spec.get("core_claim"),
        )
    ).lower()
    if requested not in {"auto", "bar"}:
        return requested
    if encoding.get("date") and encoding.get("label"):
        return "timeline"
    if all(encoding.get(k) for k in ("x", "y", "label")):
        return "scatter"
    if all(encoding.get(k) for k in ("likelihood", "impact", "label")):
        return "risk-matrix"
    if encoding.get("row_label") and encoding.get("value_columns"):
        return "heatmap"
    if encoding.get("series") and len(encoding.get("series") or []) > 1:
        return "grouped-bar"
    if any(word in intent for word in ("trend", "forecast", "time", "growth")) and encoding.get("x"):
        return "line"
    if any(word in intent for word in ("share", "mix", "composition", "占比", "结构", "来源分层")):
        return "donut"
    if any(word in intent for word in ("bridge", "waterfall", "contribution", "增量", "价值桥")):
        return "waterfall"
    if any(word in intent for word in ("funnel", "narrow", "tier", "漏斗", "转化")):
        return "funnel"
    if any(word in intent for word in ("sensitivity", "tornado", "敏感性", "弹性")):
        return "diverging-bar"
    if any(word in intent for word in ("ranking", "priority", "comparison", "decision", "rank", "对比", "排序", "优先级", "策略", "风险")):
        return "lollipop" if len(rows) <= 9 else "ranking-bar"
    return requested if requested != "auto" else "bar"


def resolve_figure_type(spec: dict, rows: list[dict[str, str]]) -> str:
    """Resolve visual grammar without relying on model vision.

    Text-only models may declare the evidence relationship, but they do not
    receive final authority over styling. The Python resolver deterministically
    converts the relationship and data shape into a supported visual grammar.
    """
    chart_type = infer_figure_type(spec, rows)
    if chart_type not in TEXT_ONLY_SAFE_TYPES:
        raise ValueError(f"Unsupported text-only-safe figure_type: {chart_type}")
    return chart_type


def load_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_kami_broker_theme()
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def read_records(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: object, field: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError as exc:
        raise ValueError(f"Field {field!r} contains a non-numeric value: {value!r}") from exc


def require(spec: dict, *keys: str) -> None:
    missing = [key for key in keys if key not in spec or spec[key] in (None, "", [])]
    if missing:
        raise ValueError("Figure spec is missing: " + ", ".join(missing))


def plot_bar(ax, rows: list[dict[str, str]], encoding: dict, *, ranking: bool = False) -> None:
    require(encoding, "category", "value", "xlabel", "ylabel")
    pairs = [(row[encoding["category"]], number(row[encoding["value"]], encoding["value"])) for row in rows]
    if ranking:
        pairs.sort(key=lambda item: item[1], reverse=True)
        labels = [item[0] for item in reversed(pairs)]
        values = [item[1] for item in reversed(pairs)]
        colors = [COLORS["neutral_mid"]] * len(values)
        colors[-min(3, len(colors)) :] = theme_series_colors(min(3, len(colors)))
        bars = ax.barh(labels, values, color=colors)
        ax.bar_label(bars, fmt="%.3g", padding=3, fontsize=8)
    else:
        labels = [item[0] for item in pairs]
        values = [item[1] for item in pairs]
        palette = [COLORS["neutral_mid"]] * len(values)
        if values:
            palette[values.index(max(values))] = COLORS["primary"]
        bars = ax.bar(labels, values, color=palette)
        place_bar_labels(ax, bars, values, "%.3g")
        ax.tick_params(axis="x", labelrotation=25)
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])


def plot_lollipop(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    pairs = sorted(((str(r[encoding["category"]]), number(r[encoding["value"]], encoding["value"])) for r in rows), key=lambda x: x[1])
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    y = list(range(len(values)))
    ax.hlines(y, 0, values, color=COLORS["neutral_light"], linewidth=2.2)
    colors = [COLORS["secondary"]] * len(values)
    if values:
        colors[-1] = COLORS["primary"]
    ax.scatter(values, y, s=74, color=colors, edgecolors="white", linewidths=1.1, zorder=3)
    for yi, value in zip(y, values):
        ax.annotate(f"{value:.3g}", (value, yi), xytext=(7, 0), textcoords="offset points", va="center", fontsize=8, fontweight="bold")
    ax.set_yticks(y, labels)
    ax.set_xlabel(encoding["ylabel"])
    ax.set_ylabel(encoding["xlabel"])


def plot_dot_plot(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    pairs = sorted(((str(r[encoding["category"]]), number(r[encoding["value"]], encoding["value"])) for r in rows), key=lambda x: x[1])
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    y = list(range(len(values)))
    ax.scatter(values, y, s=62, color=COLORS["primary"], edgecolors="white", linewidths=1.0, zorder=3)
    ax.set_yticks(y, labels)
    if values:
        spread = max(values) - min(values)
        pad = max(max(values) * 0.18, spread * 0.18, 1.0)
        upper = max(values) + pad
        lower = min(0, min(values) - pad)
        ax.set_xlim(lower, upper)
        ax.set_xticks([tick for tick in ax.get_xticks() if lower - 1e-6 <= tick <= upper + 1e-6])
    for yi, value in zip(y, values):
        ax.annotate(f"{value:.3g}", (value, yi), xytext=(7, 0), textcoords="offset points", va="center", fontsize=8, fontweight="bold")
    ax.grid(axis="x", color=COLORS["neutral_light"], linewidth=0.7)
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.08)
    ax.set_xlabel(encoding["ylabel"])
    ax.set_ylabel(encoding["xlabel"])


def plot_scenario_range(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    labels = _labels(rows, encoding["category"])
    values = _values(rows, encoding["value"])
    x = list(range(len(values)))
    if values:
        ax.fill_between(x, values, [min(values)] * len(values), color=COLORS["secondary"], alpha=0.10)
        ax.plot(x, values, color=COLORS["primary"], linewidth=2.2, marker="o", markersize=7)
        baseline = int(encoding.get("baseline_index", 1 if len(values) == 3 else 0))
        baseline = min(max(baseline, 0), len(values) - 1)
        ax.scatter([baseline], [values[baseline]], s=135, color=COLORS["secondary"], edgecolors="white", linewidths=1.5, zorder=4)
    for xi, value in zip(x, values):
        ax.annotate(f"{value:,.3g}", (xi, value), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
    ax.set_xticks(x, labels)
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])


def plot_bubble_ranking(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    pairs = sorted(((str(r[encoding["category"]]), number(r[encoding["value"]], encoding["value"])) for r in rows), key=lambda x: x[1], reverse=True)
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    x = list(range(len(values)))
    maximum = max(values) if values else 1
    sizes = [280 + 1050 * (value / maximum) ** 0.8 for value in values]
    colors = theme_series_colors(max(1, min(5, len(values))))
    ax.scatter(x, [0] * len(values), s=sizes, c=[colors[i % len(colors)] for i in x], alpha=0.9, edgecolors="white", linewidths=1.5)
    for xi, (label, value) in enumerate(zip(labels, values)):
        ax.text(xi, 0, f"{value:,.3g}", ha="center", va="center", color="white", fontsize=8, fontweight="bold")
        ax.text(xi, -0.62, label, ha="center", va="top", fontsize=8)
    ax.set_xlim(-0.65, max(0.65, len(values) - 0.35))
    ax.set_ylim(-1.05, 0.85)
    ax.axis("off")


def _plot_metric_tiles(ax, rows, encoding, *, mode="scorecards"):
    require(encoding, "category", "value")
    labels = _labels(rows, encoding["category"])
    values = _values(rows, encoding["value"])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    count = len(values)
    columns = min(3, max(1, count))
    rows_count = math.ceil(count / columns)
    palette = theme_series_colors(max(1, min(5, count)))
    for index, (label, value) in enumerate(zip(labels, values)):
        row, column = divmod(index, columns)
        cell_w, cell_h = 0.94 / columns, 0.84 / rows_count
        x0 = 0.03 + column * cell_w
        y0 = 0.92 - (row + 1) * cell_h
        color = palette[index % len(palette)]
        rect = __import__("matplotlib.patches").patches.FancyBboxPatch(
            (x0 + 0.015, y0 + 0.03), cell_w - 0.03, cell_h - 0.06,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            facecolor="#F7F9FC", edgecolor="#D5DCE5", linewidth=0.9,
        )
        ax.add_patch(rect)
        ax.add_patch(__import__("matplotlib.patches").patches.Rectangle((x0 + 0.015, y0 + 0.03), 0.012, cell_h - 0.06, facecolor=color, edgecolor="none"))
        ax.text(x0 + cell_w / 2, y0 + cell_h * 0.61, f"{value:,.3g}", ha="center", va="center", fontsize=15, fontweight="bold", color=COLORS["primary"])
        ax.text(x0 + cell_w / 2, y0 + cell_h * 0.34, label, ha="center", va="center", fontsize=8, color=COLORS["neutral_dark"], wrap=True)
        if mode == "rating-tiles":
            maximum = float(encoding.get("maximum", 5))
            filled = int(round(maximum * value / maximum))
            ax.text(x0 + cell_w / 2, y0 + cell_h * 0.16, "●" * filled + "○" * (int(maximum) - filled), ha="center", va="center", fontsize=8, color=color)


def plot_kpi_cards(ax, rows, encoding):
    _plot_metric_tiles(ax, rows, encoding, mode="kpi-cards")


def plot_scorecards(ax, rows, encoding):
    _plot_metric_tiles(ax, rows, encoding, mode="scorecards")


def plot_rating_tiles(ax, rows, encoding):
    _plot_metric_tiles(ax, rows, encoding, mode="rating-tiles")


def plot_decision_cards(ax, rows, encoding):
    _plot_metric_tiles(ax, rows, encoding, mode="decision-cards")


def plot_risk_tiles(ax, rows, encoding):
    require(encoding, "category", "value")
    labels = _labels(rows, encoding["category"])
    values = _values(rows, encoding["value"])
    order = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(values))
    ax.axis("off")
    for row_index, source_index in enumerate(order):
        value, label = values[source_index], labels[source_index]
        y = len(values) - row_index - 0.7
        color = COLORS["negative"] if value >= 4 else COLORS["accent"] if value >= 3 else COLORS["positive"]
        ax.add_patch(__import__("matplotlib.patches").patches.FancyBboxPatch((0.04, y - 0.18), 0.92, 0.56, boxstyle="round,pad=0.012,rounding_size=0.02", facecolor="#F7F9FC", edgecolor="#D5DCE5", linewidth=0.8))
        ax.add_patch(__import__("matplotlib.patches").patches.FancyBboxPatch((0.06, y - 0.05), 0.12, 0.30, boxstyle="round,pad=0.01,rounding_size=0.03", facecolor=color, edgecolor="none"))
        ax.text(0.12, y + 0.10, f"{value:.0f}", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        ax.text(0.22, y + 0.10, label, ha="left", va="center", fontsize=9, fontweight="bold", color=COLORS["primary"])


def plot_pareto(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    pairs = sorted(((str(r[encoding["category"]]), number(r[encoding["value"]], encoding["value"])) for r in rows), key=lambda x: x[1], reverse=True)
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    x = list(range(len(values)))
    bars = ax.bar(x, values, color=[COLORS["primary"] if index < 2 else COLORS["neutral_mid"] for index in x])
    place_bar_labels(ax, bars, values, "%.3g")
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])
    total = sum(values) or 1
    cumulative, running = [], 0.0
    for value in values:
        running += value
        cumulative.append(running / total * 100)
    right = ax.twinx()
    right.plot(x, cumulative, color=COLORS["secondary"], marker="o", linewidth=1.8, markersize=4)
    right.set_ylim(0, 108)
    right.set_yticks([0, 20, 40, 60, 80, 100])
    right.set_ylabel("累计占比（%）")
    right.tick_params(axis="x", bottom=False, labelbottom=False)
    right.grid(False)


def plot_diverging_bar(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    labels = _labels(rows, encoding["category"])
    values = _values(rows, encoding["value"])
    colors = [COLORS["negative"] if v < 0 else COLORS["positive"] for v in values]
    y = list(range(len(values)))
    ax.barh(y, values, color=colors, alpha=0.9)
    ax.axvline(0, color=COLORS["neutral_dark"], linewidth=0.8)
    ax.set_yticks(y, labels)
    for yi, v in zip(y, values):
        ax.annotate(f"{v:+.3g}", (v, yi), xytext=(5 if v >= 0 else -5, 0), textcoords="offset points", ha="left" if v >= 0 else "right", va="center", fontsize=8)
    ax.set_xlabel(encoding["ylabel"])
    ax.set_ylabel(encoding["xlabel"])


def plot_waterfall(ax, rows, encoding):
    require(encoding, "category", "value", "xlabel", "ylabel")
    labels = _labels(rows, encoding["category"])
    changes = _values(rows, encoding["value"])
    starts, running = [], 0.0
    for change in changes:
        starts.append(running if change >= 0 else running + change)
        running += change
    colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in changes]
    bars = ax.bar(labels, [abs(v) for v in changes], bottom=starts, color=colors)
    for i in range(1, len(changes)):
        level = starts[i]
        ax.plot([i - 0.42, i - 0.58], [level, level], color=COLORS["neutral_dark"], linewidth=0.7)
    for bar, change, start in zip(bars, changes, starts):
        endpoint = start + abs(change) if change >= 0 else start
        ax.annotate(
            f"{change:+.3g}",
            (bar.get_x() + bar.get_width() / 2, endpoint),
            xytext=(0, 4 if change >= 0 else -11),
            textcoords="offset points",
            ha="center",
            va="bottom" if change >= 0 else "top",
            fontsize=8,
            fontweight="bold",
            color=COLORS["primary"],
        )
    ax.axhline(0, color=COLORS["neutral_dark"], linewidth=0.8)
    ax.tick_params(axis="x", labelrotation=25)
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])


def plot_donut(ax, rows, encoding):
    require(encoding, "category", "value")
    labels = _labels(rows, encoding["category"])
    values = _values(rows, encoding["value"])
    total = sum(values)
    donut(ax.figure, ax, labels, values, None, encoding.get("center_label", "Total"), encoding.get("center_value", f"{total:.3g}"), fmt="%.3g")


def plot_funnel(ax, rows, encoding):
    require(encoding, "category", "value")
    funnel(ax, _labels(rows, encoding["category"]), _values(rows, encoding["value"]))


def plot_timeline(ax, rows, encoding):
    require(encoding, "date", "label")
    dates = _labels(rows, encoding["date"])
    labels = _labels(rows, encoding["label"])
    x = list(range(len(rows)))
    levels = [0.55 if i % 2 == 0 else -0.55 for i in x]
    ax.axhline(0, color=COLORS["primary"], linewidth=1.5)
    for i, (date, label, level) in enumerate(zip(dates, labels, levels)):
        color = theme_series_colors(min(5, len(rows)))[i % min(5, len(rows))]
        ax.vlines(i, 0, level, color=color, linewidth=1.2)
        ax.scatter(i, 0, s=62, color=color, edgecolors="white", zorder=3)
        ax.text(i, level, f"{date}\n{label}", ha="center", va="bottom" if level > 0 else "top", fontsize=8)
    ax.set_xlim(-0.5, len(rows) - 0.5)
    ax.set_ylim(-1.05, 1.05)
    ax.axis("off")


def plot_risk(ax, rows, encoding):
    require(encoding, "label", "likelihood", "impact")
    names = _labels(rows, encoding["label"])
    prob = {name: number(row[encoding["likelihood"]], encoding["likelihood"]) for name, row in zip(names, rows)}
    impact = {name: number(row[encoding["impact"]], encoding["impact"]) * 5 for name, row in zip(names, rows)}
    risk_matrix(ax, impact, prob, names)


def plot_grouped_bar(ax, rows: list[dict[str, str]], encoding: dict) -> None:
    require(encoding, "category", "series", "xlabel", "ylabel")
    categories = [row[encoding["category"]] for row in rows]
    series = list(encoding["series"])
    colors = theme_series_colors(len(series))
    x = list(range(len(categories)))
    width = 0.8 / len(series)
    for index, (field, color) in enumerate(zip(series, colors)):
        offset = (index - (len(series) - 1) / 2) * width
        values = [number(row[field], field) for row in rows]
        label = (encoding.get("series_labels") or {}).get(field, field.replace("_", " "))
        ax.bar([value + offset for value in x], values, width, label=label, color=color)
    ax.set_xticks(x, categories, rotation=25, ha="right")
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])
    ax.legend()


def plot_line(ax, rows: list[dict[str, str]], encoding: dict) -> None:
    if not encoding.get("x") and encoding.get("category"):
        encoding = {**encoding, "x": encoding["category"]}
    if not encoding.get("series") and encoding.get("value"):
        encoding = {**encoding, "series": [encoding["value"]]}
    require(encoding, "x", "series", "xlabel", "ylabel")
    x_labels = [row[encoding["x"]] for row in rows]
    numeric_x = True
    try:
        x = [number(value, encoding["x"]) for value in x_labels]
    except ValueError:
        numeric_x = False
        x = list(range(len(rows)))
    series = list(encoding["series"])
    colors = theme_series_colors(len(series))
    for field, color in zip(series, colors):
        values = [number(row[field], field) for row in rows]
        label = (encoding.get("series_labels") or {}).get(field, field.replace("_", " "))
        ax.plot(x, values, color=color, linewidth=2, marker="o", markersize=4.5, label=label)
        lower = (encoding.get("lower") or {}).get(field)
        upper = (encoding.get("upper") or {}).get(field)
        if lower and upper:
            lows = [number(row[lower], lower) for row in rows]
            highs = [number(row[upper], upper) for row in rows]
            ax.fill_between(x, lows, highs, color=color, alpha=0.12)
    if numeric_x:
        ax.set_xticks(x, [f"{value:g}" for value in x])
    else:
        ax.set_xticks(x, x_labels, rotation=25, ha="right")
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])
    ax.legend()


def plot_scatter(ax, rows: list[dict[str, str]], encoding: dict) -> None:
    require(encoding, "x", "y", "xlabel", "ylabel")
    x_values = [number(row[encoding["x"]], encoding["x"]) for row in rows]
    y_values = [number(row[encoding["y"]], encoding["y"]) for row in rows]
    ax.scatter(x_values, y_values, color=COLORS["primary"], s=55, alpha=0.85, edgecolors="white")
    label_field = encoding.get("label")
    if label_field:
        for index, row in enumerate(rows):
            offset = (5, 6) if index % 2 == 0 else (5, -11)
            ax.annotate(row[label_field][:20], (x_values[index], y_values[index]), xytext=offset, textcoords="offset points", fontsize=8)
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])


def plot_heatmap(ax, rows: list[dict[str, str]], encoding: dict) -> None:
    require(encoding, "row_label", "value_columns", "xlabel", "ylabel")
    columns = list(encoding["value_columns"])
    matrix = [[number(row[field], field) for field in columns] for row in rows]
    image = ax.imshow(matrix, cmap=encoding.get("cmap", "RdBu_r"), aspect="auto")
    ax.figure.colorbar(image, ax=ax, label=encoding.get("colorbar_label", "值"))
    ax.set_xticks(range(len(columns)), columns, rotation=30, ha="right")
    ax.set_yticks(range(len(rows)), [row[encoding["row_label"]] for row in rows])
    ax.set_xlabel(encoding["xlabel"])
    ax.set_ylabel(encoding["ylabel"])
    if encoding.get("annotate", True):
        for row_index, values in enumerate(matrix):
            for column_index, value in enumerate(values):
                ax.text(column_index, row_index, f"{value:.2g}", ha="center", va="center", fontsize=8)


def plot_radar(fig, rows: list[dict[str, str]], encoding: dict):
    require(encoding, "label", "metrics")
    metrics = list(encoding["metrics"])
    angles = [index / len(metrics) * 2 * math.pi for index in range(len(metrics))]
    angles += angles[:1]
    ax = fig.add_subplot(111, polar=True)
    maxima = [max(number(row[field], field) for row in rows) or 1 for field in metrics]
    colors = theme_series_colors(min(len(rows), 5))
    for row, color in zip(rows[:5], colors):
        values = [number(row[field], field) / maxima[index] for index, field in enumerate(metrics)]
        values += values[:1]
        ax.plot(angles, values, color=color, linewidth=1.7, label=row[encoding["label"]][:20])
        ax.fill(angles, values, color=color, alpha=0.06)
    ax.set_xticks(angles[:-1], metrics)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=8)
    return ax


def build_figure(plt, spec: dict, rows: list[dict[str, str]]):
    chart_type = resolve_figure_type(spec, rows)
    spec["figure_type"] = chart_type
    figsize = tuple(spec.get("figsize", [6.1417, 4.2]))
    if chart_type == "radar":
        fig = plt.figure(figsize=figsize)
        ax = plot_radar(fig, rows, spec["encoding"])
    else:
        fig, ax = plt.subplots(figsize=figsize)
        handlers = {
            "bar": lambda: plot_bar(ax, rows, spec["encoding"]),
            "ranking-bar": lambda: plot_bar(ax, rows, spec["encoding"], ranking=True),
            "lollipop": lambda: plot_lollipop(ax, rows, spec["encoding"]),
            "dot-plot": lambda: plot_dot_plot(ax, rows, spec["encoding"]),
            "scenario-range": lambda: plot_scenario_range(ax, rows, spec["encoding"]),
            "bubble-ranking": lambda: plot_bubble_ranking(ax, rows, spec["encoding"]),
            "kpi-cards": lambda: plot_kpi_cards(ax, rows, spec["encoding"]),
            "scorecards": lambda: plot_scorecards(ax, rows, spec["encoding"]),
            "rating-tiles": lambda: plot_rating_tiles(ax, rows, spec["encoding"]),
            "decision-cards": lambda: plot_decision_cards(ax, rows, spec["encoding"]),
            "risk-tiles": lambda: plot_risk_tiles(ax, rows, spec["encoding"]),
            "pareto": lambda: plot_pareto(ax, rows, spec["encoding"]),
            "diverging-bar": lambda: plot_diverging_bar(ax, rows, spec["encoding"]),
            "grouped-bar": lambda: plot_grouped_bar(ax, rows, spec["encoding"]),
            "line": lambda: plot_line(ax, rows, spec["encoding"]),
            "forecast": lambda: plot_line(ax, rows, spec["encoding"]),
            "sensitivity": lambda: plot_line(ax, rows, spec["encoding"]),
            "scatter": lambda: plot_scatter(ax, rows, spec["encoding"]),
            "heatmap": lambda: plot_heatmap(ax, rows, spec["encoding"]),
            "donut": lambda: plot_donut(ax, rows, spec["encoding"]),
            "waterfall": lambda: plot_waterfall(ax, rows, spec["encoding"]),
            "timeline": lambda: plot_timeline(ax, rows, spec["encoding"]),
            "funnel": lambda: plot_funnel(ax, rows, spec["encoding"]),
            "risk-matrix": lambda: plot_risk(ax, rows, spec["encoding"]),
        }
        if chart_type not in handlers:
            raise ValueError(f"Unsupported declarative figure_type: {chart_type}")
        handlers[chart_type]()
    # Word owns the caption and PPT owns the answer-first slide title.  A
    # duplicate in-chart title wastes plotting area and causes dense slides.
    if spec.get("show_title", False):
        ax.set_title(spec["title"])
    # Apply CJK/Latin font routing before geometry is frozen so a text-only
    # run gets the same bounding boxes later used by automated visual QA.
    apply_mixed_text_fonts(fig)
    fig.tight_layout(pad=1.0)
    return fig


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one embedded market/modeling figure from a declarative JSON spec.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--mode", choices=("draft", "final"), default="draft")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = project_dir / spec_path
    spec_path = spec_path.resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    require(
        spec,
        "figure_id",
        "title",
        "figure_class",
        "figure_type",
        "archetype",
        "role",
        "core_claim",
        "claim_confirmed",
        "panel_map",
        "source_data",
        "data_provenance",
        "encoding",
        "output_stem",
        "report_placement",
    )
    data_path = Path(spec["source_data"])
    if not data_path.is_absolute():
        data_path = project_dir / data_path
    data_path = data_path.resolve()
    rows = read_records(data_path)
    if not rows:
        raise ValueError(f"Source data contains no rows: {data_path}")

    output_stem = Path(spec["output_stem"])
    if not output_stem.is_absolute():
        output_stem = project_dir / output_stem
    plt = load_matplotlib()
    fig = build_figure(plt, spec, rows)
    try:
        manifest = save_figure_bundle(
            fig,
            output_stem,
            project_dir=project_dir,
            figure_id=spec["figure_id"],
            title=spec["title"],
            figure_class=spec["figure_class"],
            figure_type=spec["figure_type"],
            archetype=spec["archetype"],
            role=spec["role"],
            core_claim=spec["core_claim"],
            claim_confirmed=bool(spec["claim_confirmed"]),
            panel_map=spec["panel_map"],
            source_data_paths=[data_path, spec_path],
            data_provenance=spec["data_provenance"],
            statistics=spec.get("statistics", {}),
            simulation=spec.get("simulation", {}),
            report_placement=spec["report_placement"],
            generator_script=Path(__file__),
            dpi=int(spec.get("dpi", 300)),
            min_font_size_pt=float(spec.get("minimum_font_size_pt", 8)),
            final=args.mode == "final",
        )
    finally:
        plt.close(fig)
    print(f"Rendered embedded figure bundle: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
