from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from _common import read_csv
from figure_production import save_figure_bundle
from kami_broker_chart_theme import COLORS, FIGURE_SIZES, apply_kami_broker_theme, theme_series_colors


def load_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_kami_broker_theme()
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def parse_number(value: str) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def read_rows(project_dir: Path, filename: str) -> tuple[Path, list[dict[str, str]]]:
    path = project_dir / filename
    if not path.exists():
        return path, []
    _, rows = read_csv(path)
    return path, rows


def _draft_claim(text: str) -> str:
    return f"[AI-DRAFT — modeler must confirm: {text}]"


def market_trend(project_dir: Path, plt):
    source, rows = read_rows(project_dir, "01_Market_Scan.csv")
    points = []
    for row in rows:
        metric = (row.get("metric") or "market_size").strip().lower()
        if metric not in {"market_size", "market size", "市场规模"}:
            continue
        year = parse_number(row.get("year_period", "") or row.get("year", ""))
        size = parse_number(row.get("raw_value", "") or row.get("market_size", ""))
        if year is not None and size is not None:
            points.append((int(year), size, row.get("currency", "")))
    if len(points) < 2:
        return None
    points = sorted({year: (year, size, currency) for year, size, currency in points}.values())
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["standard"])
    years = [point[0] for point in points]
    values = [point[1] for point in points]
    ax.plot(years, values, color=COLORS["primary"], linewidth=2.2, marker="o", markersize=5)
    ax.fill_between(years, values, color=COLORS["secondary"], alpha=0.10)
    ax.margins(x=0.12)  # 年份刻度与相邻字形留白，避免 visual QA 文本重叠（同年份仅保留最新一条）
    ax.set_title("市场规模趋势")
    ax.set_xticks(years, [str(year) for year in years])
    ax.set_xlabel("年份")
    ax.set_ylabel(f"市场规模 {points[-1][2]}".strip())
    return fig, {
        "name": "market_trend",
        "title": "市场规模趋势",
        "figure_type": "trend-line",
        "role": "discovery",
        "source": source,
        "rows_used": len(points),
        "claim": _draft_claim(f"市场规模从 {years[0]} 年的 {values[0]:g} 变为 {years[-1]} 年的 {values[-1]:g}"),
        "data_provenance": "observed",
        "placement": {"section_heading": "四、市场规模、细分、产业链与增长情景", "caption": "市场规模趋势", "source_note": "数据来源：01_Market_Scan.csv。"},
    }


def price_capacity_scatter(project_dir: Path, plt):
    source, rows = read_rows(project_dir, "09_Integrated_Matrix.csv")
    points = []
    for row in rows:
        capacity = parse_number(row.get("capacity_kwh", ""))
        price = parse_number(row.get("price", ""))
        if capacity is not None and price is not None:
            label = row.get("exact_model", "") or row.get("brand", "")
            points.append((capacity, price, label))
    if len(points) < 2:
        return None
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    fig.subplots_adjust(left=0.10, right=0.74)  # 右侧预留图例位，避免图例越界（visual QA text_out_of_bounds）
    ax.scatter(
        [point[0] for point in points],
        [point[1] for point in points],
        s=70,
        color=COLORS["primary"],
        alpha=0.88,
        edgecolors=COLORS["neutral_dark"],
        linewidths=0.5,
    )
    # 点位标注改用图例：点间标注在相近坐标下必然字形重叠（final 视觉 QA material_text_overlap）。
    from matplotlib.lines import Line2D  # 懒导入：仅本构建器需要图例句柄

    handles = [
        Line2D([0], [0], marker="o", linestyle="", markersize=6,
               markerfacecolor=COLORS["primary"], markeredgecolor=COLORS["neutral_dark"],
               label=label[:16])
        for _, _, label in points[:12]
    ]
    ax.legend(handles=handles, fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False)
    ax.margins(x=0.22, y=0.18)  # 左下留白：避免角部 x 刻度与 y 刻度字形相碰
    ax.set_title("价格—容量竞争定位")
    ax.set_xlabel("容量（kWh）")
    ax.set_ylabel("价格")
    return fig, {
        "name": "price_capacity_scatter",
        "title": "价格—容量竞争定位",
        "figure_type": "scatter-positioning",
        "role": "comparison",
        "source": source,
        "rows_used": len(points),
        "claim": _draft_claim("样本产品在价格—容量坐标中形成可识别的竞争分层"),
        "data_provenance": "calculated",
        "placement": {"section_heading": "七、竞争格局、玩家分类与精确型号对标", "caption": "价格—容量竞争定位", "source_note": "数据来源：09_Integrated_Matrix.csv。"},
    }


def _render_coverage_matrix(
    plt,
    matrix: dict[str, set[str]],
    *,
    name: str,
    title: str,
    row_label: str,
    col_label: str,
    claim: str,
    section_heading: str,
    sources,
    rows_used: int,
):
    models = list(matrix.keys())[:12]
    categories = sorted({value for model in models for value in matrix[model]})[:12]
    if not models or not categories:
        return None
    data = [[1 if category in matrix[model] else 0 for category in categories] for model in models]
    fig, ax = plt.subplots(
        figsize=(FIGURE_SIZES["standard"][0], max(3.8, len(models) * 0.34 + 1.6))
    )
    ax.imshow(data, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(categories)), labels=categories, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(models)), labels=models, fontsize=8)
    ax.set_xlabel(col_label)
    ax.set_ylabel(row_label)
    ax.set_title(title)
    for row_index, model in enumerate(models):
        for column_index, category in enumerate(categories):
            present = category in matrix[model]
            ax.text(
                column_index,
                row_index,
                "有" if present else "缺",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if present else COLORS["black"],
            )
    if isinstance(sources, (list, tuple)):
        source = sources[0] if sources else None
        source_note = f"数据来源：{'、'.join(sources)}。" if sources else ""
    else:
        source = sources
        source_note = f"数据来源：{sources}。"
    return fig, {
        "name": name,
        "title": title,
        "figure_type": "coverage-heatmap",
        "role": "comparison",
        "source": source,
        "rows_used": rows_used,
        "claim": _draft_claim(claim),
        "data_provenance": "calculated",
        "placement": {
            "section_heading": section_heading,
            "caption": title,
            "source_note": source_note,
        },
    }


def _coverage_heatmap(project_dir: Path, plt, *, filename: str, key: str, name: str, title: str):
    source, rows = read_rows(project_dir, filename)
    matrix: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        model = row.get("exact_model", "") or row.get("brand", "")
        value = row.get(key, "")
        if model and value:
            matrix[model].add(value)
    return _render_coverage_matrix(
        plt,
        matrix,
        name=name,
        title=title,
        row_label="产品型号",
        col_label="参数" if key == "parameter_name" else "渠道",
        claim=f"不同产品的{'参数证据' if key == 'parameter_name' else '渠道'}覆盖存在结构性差异",
        section_heading="六、产品系统架构、工程参数与区域合规" if key == "parameter_name" else "八、定价、渠道、安装与服务网络",
        sources=source,
        rows_used=len(rows),
    )


def parameter_heatmap(project_dir: Path, plt):
    return _coverage_heatmap(
        project_dir,
        plt,
        filename="04_Product_Parameters.csv",
        key="parameter_name",
        name="parameter_availability_heatmap",
        title="参数证据覆盖热力图",
    )


_CHANNEL_UNDISCLOSED = {"", "未披露", "未知", "N/A"}


def _brand_channel_matrix(project_dir: Path):
    """Brand x channel coverage built from every channel-bearing table.

    Generalizes across market surveys: brand-level channel evidence (06
    service table plus 05 pricing rows with attributed brands) is far more
    common than per-SKU channel disclosure.  Values may carry multiple
    channels joined by separators; "未披露" placeholders are dropped so the
    matrix only shows evidenced coverage.
    """
    matrix: dict[str, set[str]] = defaultdict(set)
    sources: list[str] = []
    rows_used = 0
    plan = (
        ("05_Pricing_Channel.csv", ("channel",)),
        ("06_Channel_Service.csv", ("online_channel", "offline_channel", "installation_service")),
    )
    for filename, keys in plan:
        path, rows = read_rows(project_dir, filename)
        if not rows:
            continue
        contributed = False
        for row in rows:
            brand = (row.get("brand") or "").strip()
            if brand in _CHANNEL_UNDISCLOSED:
                continue
            for key in keys:
                value = (row.get(key) or "").strip()
                if value in _CHANNEL_UNDISCLOSED:
                    continue
                for channel in re.split(r"[、，,;；/]+", value):
                    channel = channel.strip()
                    if channel and channel not in _CHANNEL_UNDISCLOSED:
                        matrix[brand].add(channel)
                        contributed = True
        if contributed:
            sources.append(filename)
            rows_used += len(rows)
    return matrix, sources, rows_used


def channel_heatmap(project_dir: Path, plt):
    matrix, sources, rows_used = _brand_channel_matrix(project_dir)
    cells = sum(len(values) for values in matrix.values())
    if len(matrix) >= 2 and cells >= 2:
        return _render_coverage_matrix(
            plt,
            matrix,
            name="channel_coverage_heatmap",
            title="品牌渠道覆盖热力图",
            row_label="品牌",
            col_label="渠道",
            claim="不同品牌的销售渠道覆盖存在结构性差异",
            section_heading="八、定价、渠道、安装与服务网络",
            sources=sources,
            rows_used=rows_used,
        )
    # Brand-level evidence too thin: keep the model-level view so chapter
    # eight never loses its mandatory figure.
    return _coverage_heatmap(
        project_dir,
        plt,
        filename="05_Pricing_Channel.csv",
        key="channel",
        name="channel_coverage_heatmap",
        title="渠道覆盖热力图",
    )


def pain_point_pareto(project_dir: Path, plt):
    source, rows = read_rows(project_dir, "08_Review_Coding.csv")
    aggregated: dict[str, float] = defaultdict(float)
    for row in rows:
        count = parse_number(row.get("frequency_count", ""))
        theme = row.get("theme", "")
        if count is not None and theme:
            aggregated[theme] += count
    points = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:10]
    if not points:
        return None
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["ranking"])
    labels = [point[0][:10] for point in reversed(points)]
    values = [point[1] for point in reversed(points)]
    colors = [COLORS["neutral_mid"]] * len(values)
    colors[-min(3, len(colors)) :] = [COLORS["primary"]] * min(3, len(colors))
    bars = ax.barh(labels, values, color=colors)
    ax.bar_label(bars, fmt="%g", padding=3, fontsize=8)
    ax.margins(x=0.16)  # 最长条形标签需要右侧留白，否则 text_out_of_bounds
    ax.set_title("用户痛点频次 Pareto")
    ax.set_xlabel("评论频次")
    ax.set_ylabel("痛点主题")
    fig.tight_layout()  # 长中文刻度/条形标签需整体布局收敛，否则 visual QA text_out_of_bounds
    return fig, {
        "name": "pain_point_pareto",
        "title": "用户痛点频次 Pareto",
        "figure_type": "evaluation-ranking",
        "role": "decision",
        "source": source,
        "rows_used": len(points),
        "claim": _draft_claim(f"高频用户痛点集中在 {points[0][0]} 等少数主题"),
        "data_provenance": "calculated",
        "placement": {"section_heading": "九、原始评论、用户痛点与购买驱动", "caption": "用户痛点频次 Pareto", "source_note": "数据来源：08_Review_Coding.csv。"},
    }


def capability_radar(project_dir: Path, plt):
    source, rows = read_rows(project_dir, "09_Integrated_Matrix.csv")
    metrics = ["capacity_kwh", "power_kw", "pv_input_w", "user_pain_score"]
    scored = []
    for row in rows:
        values = [parse_number(row.get(metric, "")) for metric in metrics]
        if all(value is not None for value in values):
            scored.append((row.get("exact_model", "") or row.get("brand", ""), values))
    if len(scored) < 2:
        return None
    maximums = [max(values[index] for _, values in scored) or 1 for index in range(len(metrics))]
    labels = ["容量", "功率", "PV输入", "口碑"]
    angles = [index / len(metrics) * 2 * math.pi for index in range(len(metrics))]
    angles += angles[:1]
    fig = plt.figure(figsize=(5.8, 5.2))
    ax = fig.add_subplot(111, polar=True)
    colors = theme_series_colors(min(5, len(scored)))
    for (label, values), color in zip(scored[:5], colors):
        normalized = [values[index] / maximums[index] for index in range(len(metrics))]
        normalized += normalized[:1]
        ax.plot(angles, normalized, linewidth=1.6, label=label[:16], color=color)
        ax.fill(angles, normalized, alpha=0.06, color=color)
    ax.set_xticks(angles[:-1], labels)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
    ax.set_title("竞品能力雷达图", pad=18)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=8)
    return fig, {
        "name": "capability_radar",
        "title": "竞品能力雷达图",
        "figure_type": "evaluation-comparison",
        "role": "comparison",
        "source": source,
        "rows_used": len(scored),
        "claim": _draft_claim("竞品在容量、功率、PV 输入和口碑维度呈现差异化能力组合"),
        "data_provenance": "calculated",
        "placement": {"section_heading": "七、竞争格局、玩家分类与精确型号对标", "caption": "竞品能力雷达图", "source_note": "数据来源：09_Integrated_Matrix.csv。"},
    }


def _category_counts(project_dir: Path, filename: str, key: str, split=None):
    """证据表单列分类计数（可分隔符拆分）。返回 (source, points, total)。"""
    source, rows = read_rows(project_dir, filename)
    counts: Counter = Counter()
    for row in rows:
        raw = (row.get(key) or "").strip()
        if not raw:
            continue
        values = split(raw) if split else [raw]
        for value in values:
            value = value.strip()
            if value:
                counts[value] += 1
    # kami-broker-v2 主题最多支持 7 个分类色系，超出会报错；长尾类别不入图。
    points = counts.most_common(7)
    return source, points, sum(counts.values())


def _chapter_meta(*, name, title, caption, section_heading, filename, source,
                  figure_type, role, total, claim, rows_used=None):
    return {
        "name": name,
        "title": title,
        # 正式图集配额：同一 figure_type ≤2 张、同一视觉家族 ≤4 张；
        # 10 张章节图分属 8 个视觉家族、10 种语法，天然满足。
        "figure_type": figure_type,
        "role": role,
        "source": source,
        "rows_used": rows_used if rows_used is not None else total,
        "claim": _draft_claim(claim),
        "data_provenance": "calculated",
        "placement": {"section_heading": section_heading, "caption": caption, "source_note": f"数据来源：{filename}。"},
    }


def evidence_source_composition(project_dir: Path, plt):
    """证据来源类型构成（环形图，composition 家族）：只数占比，计数走图例。"""
    source, points, total = _category_counts(project_dir, "00_Source_Ledger.csv", "source_type")
    if not points:
        return None
    labels = [point[0][:14] for point in points]
    values = [point[1] for point in points]
    colors = theme_series_colors(len(points))
    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    wedges, _ = ax.pie(
        values, colors=colors, startangle=90, counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
    )
    ax.legend(wedges, [f"{label}（{value} 条）" for label, value in zip(labels, values)],
              loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8, frameon=False)
    ax.set_title("证据来源类型构成")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="evidence_source_composition", title="证据来源类型构成", caption="证据来源类型构成",
        section_heading="核心结论与证据状态", filename="00_Source_Ledger.csv", source=source,
        figure_type="donut", role="comparison", total=total,
        claim=f"共登记 {total} 条证据，来源类型以 {points[0][0]} 最多（{points[0][1]} 条）",
    )


def opportunity_priority_distribution(project_dir: Path, plt):
    """机会优先级 Pareto（frequency-and-priority 家族）：条形+累计占比线。"""
    source, points, total = _category_counts(project_dir, "10_SWOT_Opportunity.csv", "opportunity_priority")
    if not points:
        return None
    labels = [point[0][:12] for point in points]
    values = [point[1] for point in points]
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["standard"])
    bars = ax.bar(labels, values, color=COLORS["primary"])
    ax.bar_label(bars, fmt="%g", padding=2, fontsize=8)
    ax.set_ylim(0, max(values) * 1.25)
    cumulative, running = [], 0
    for value in values:
        running += value
        cumulative.append(running / total * 100)
    ax2 = ax.twinx()
    ax2.plot(labels, cumulative, color=COLORS["secondary"], marker="o", markersize=4, linewidth=1.6)
    ax2.tick_params(axis="x", labelbottom=False)  # twinx 会在顶部重复绘制同一批 x 刻度标签，形成成对字形重叠
    ax2.set_ylim(0, 110)
    ax2.set_ylabel("累计占比（%）", fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    ax.set_title("市场进入机会优先级分布（Pareto）")
    ax.set_ylabel("机会条目数")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="opportunity_priority_distribution", title="市场进入机会优先级分布", caption="市场进入机会优先级分布",
        section_heading="一、执行摘要与决策问题", filename="10_SWOT_Opportunity.csv", source=source,
        figure_type="pareto", role="decision", total=total,
        claim=f"共登记 {total} 条机会条目，优先级以 {points[0][0]} 最多（{points[0][1]} 条）",
    )


def collection_task_status(project_dir: Path, plt):
    """采集任务状态时间线（time-and-change 家族）：按流程顺序排布节点。"""
    source, points, total = _category_counts(project_dir, "02_Web_Collection_Tasks.csv", "status")
    if not points:
        return None
    flow_order = ["pending", "queued", "running", "in_progress", "retry", "failed", "completed", "done"]

    def rank(label: str) -> int:
        lowered = label.lower()
        return next((index for index, token in enumerate(flow_order) if token in lowered), len(flow_order))

    points = sorted(points, key=lambda point: (rank(point[0]), -point[1]))
    labels = [point[0][:10] for point in points]
    values = [point[1] for point in points]
    max_value = max(values)
    colors = theme_series_colors(len(points))
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    xs = list(range(len(points)))
    ax.hlines(0, -0.45, len(points) - 0.55, color=COLORS["neutral_mid"], linewidth=1.6)
    for index, ((label, value), color) in enumerate(zip(zip(labels, values), colors)):
        size = 160 + 340 * value / max_value
        ax.scatter([index], [0], s=size, color=color,
                   edgecolors=COLORS["neutral_dark"], linewidths=0.5, zorder=3)
        offset_y = 26 if index % 2 == 0 else -40  # 上下交替标注，避免相邻字形重叠
        ax.annotate(f"{label}\n{value} 项", (index, 0), xytext=(0, offset_y),
                    textcoords="offset points", ha="center", fontsize=8)
    ax.set_xlim(-0.6, len(points) - 0.4)
    ax.set_ylim(-1.1, 1.1)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.set_title("证据采集任务完成状态（流程时间线）")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="collection_task_status", title="证据采集任务完成状态", caption="证据采集任务完成状态",
        section_heading="二、调研边界、方法与证据体系", filename="02_Web_Collection_Tasks.csv", source=source,
        figure_type="timeline", role="validation", total=total,
        claim=f"共登记 {total} 项采集任务，状态以 {points[0][0]} 最多（{points[0][1]} 项）",
    )


def market_evidence_metric_composition(project_dir: Path, plt):
    """证据指标构成（rating-tiles 信息设计）：色深映射登记量的瓦片网格。"""
    from matplotlib.patches import Rectangle  # 懒导入：仅瓦片类构建器需要

    source, points, total = _category_counts(project_dir, "01_Market_Scan.csv", "metric")
    if not points:
        return None
    cols = min(4, len(points))
    rows_n = math.ceil(len(points) / cols)
    max_value = max(point[1] for point in points)
    fig, ax = plt.subplots(figsize=(7.4, max(3.2, rows_n * 1.1 + 0.9)))
    for idx, (label, value) in enumerate(points):
        row, col = divmod(idx, cols)
        alpha = 0.25 + 0.65 * value / max_value
        ax.add_patch(Rectangle((col + 0.03, rows_n - 1 - row + 0.05), 0.94, 0.9,
                               facecolor=COLORS["primary"], alpha=alpha,
                               edgecolor=COLORS["neutral_mid"], linewidth=0.6))
        ax.text(col + 0.5, rows_n - row - 0.40, label[:10], ha="center", fontsize=8)
        ax.text(col + 0.5, rows_n - row - 0.70, f"{value} 条", ha="center", fontsize=8,
                color=COLORS["neutral_dark"])
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows_n)
    ax.axis("off")
    ax.set_title("宏观与市场证据指标构成")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="market_evidence_metric_composition", title="宏观与市场证据指标构成", caption="宏观与市场证据指标构成",
        section_heading="三、宏观电力环境、政策、电价与市场准入", filename="01_Market_Scan.csv", source=source,
        figure_type="rating-tiles", role="comparison", total=total,
        claim=f"共登记 {total} 条市场观测，指标以 {points[0][0]} 最多（{points[0][1]} 条）",
    )


def product_form_distribution(project_dir: Path, plt):
    """产品形态漏斗（composition 家族）：按登记量降序居中条形。"""
    source, points, total = _category_counts(project_dir, "09_Integrated_Matrix.csv", "product_type")
    if not points:
        return None
    labels = [point[0][:12] for point in points]
    values = [point[1] for point in points]
    max_value = max(values)
    positions = list(range(len(points) - 1, -1, -1))
    colors = theme_series_colors(len(points))
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["standard"])
    ax.barh(positions, values, left=[(max_value - value) / 2 for value in values],
            color=colors, height=0.62)
    ax.set_yticks(positions, [f"{label}（{value} 型号）" for label, value in zip(labels, values)], fontsize=8)
    for position, value in zip(positions, values):
        ax.text(max_value / 2, position, str(value), ha="center", va="center", fontsize=8, color="white")
    ax.set_xlim(0, max_value * 1.05)
    ax.set_xticks([])
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)
    ax.set_title("样本产品形态分布（登记量漏斗）")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="product_form_distribution", title="样本产品形态分布", caption="样本产品形态分布",
        section_heading="五、用户类型、负荷与应用场景", filename="09_Integrated_Matrix.csv", source=source,
        figure_type="funnel", role="comparison", total=total,
        claim=f"共登记 {total} 个型号，产品形态以 {points[0][0]} 最多（{points[0][1]} 个）",
    )


def unit_price_comparison(project_dir: Path, plt):
    """经济性章证据图：样本型号单位容量价格点阵（dot-plot），为回收测算提供口径。"""
    source, rows = read_rows(project_dir, "09_Integrated_Matrix.csv")
    points = []
    for row in rows:
        price = parse_number(row.get("price", ""))
        capacity = parse_number(row.get("capacity_kwh", ""))
        if price is not None and capacity is not None and capacity > 0:
            label = row.get("exact_model", "") or row.get("brand", "")
            if label:
                points.append((label[:12], round(price / capacity, 1)))
    if len(points) < 2:
        return None
    points.sort(key=lambda point: point[1])
    currency = next((row.get("currency", "") for row in rows if (row.get("currency") or "").strip()), "")
    values = [point[1] for point in points]
    ys = list(range(len(points)))
    fig, ax = plt.subplots(figsize=(FIGURE_SIZES["standard"][0], max(3.6, len(points) * 0.44 + 1.4)))
    ax.scatter(values, ys, s=60, color=COLORS["secondary"],
               edgecolors=COLORS["neutral_dark"], linewidths=0.5, zorder=3)
    for value, y in zip(values, ys):
        ax.text(value, y, f" {value:g}", va="center", fontsize=8)  # 数值标在点右侧，与点不重叠
    ax.set_yticks(ys, [point[0] for point in points], fontsize=8)
    ax.set_ylim(-0.6, len(points) - 0.4)
    ax.margins(x=0.18)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title("单位容量价格对比")
    ax.set_xlabel(f"单位容量价格（{currency or '元'}/kWh）")
    fig.tight_layout()
    lowest, highest = points[0], points[-1]
    return fig, {
        "name": "unit_price_comparison",
        "title": "单位容量价格对比",
        "figure_type": "dot-plot",
        "role": "decision",
        "source": source,
        "rows_used": len(points),
        "claim": _draft_claim(f"样本单位容量价格介于 {lowest[1]:g} 与 {highest[1]:g} {currency}/kWh 之间"),
        "data_provenance": "calculated",
        "placement": {"section_heading": "十、经济性、数学模型与敏感性", "caption": "单位容量价格对比", "source_note": "数据来源：09_Integrated_Matrix.csv。"},
    }


def vpp_protocol_coverage(project_dir: Path, plt):
    """VPP 协议覆盖棒糖图（lollipop）：每个协议涉及的型号数。"""
    source, points, total = _category_counts(
        project_dir, "09_Integrated_Matrix.csv", "vpp_protocols",
        split=lambda raw: [token for token in re.split(r"[;；,，、/]", raw)],
    )
    if not points:
        return None
    labels = [point[0][:12] for point in points]
    values = [point[1] for point in points]
    ys = list(range(len(points) - 1, -1, -1))
    fig, ax = plt.subplots(figsize=(FIGURE_SIZES["standard"][0], max(3.6, len(points) * 0.44 + 1.4)))
    ax.hlines(ys, 0, values, color=COLORS["neutral_mid"], linewidth=1.4)
    ax.scatter(values, ys, s=70, color=COLORS["primary"],
               edgecolors=COLORS["neutral_dark"], linewidths=0.5, zorder=3)
    for value, y in zip(values, ys):
        ax.text(value, y, f" {value}", va="center", fontsize=8)
    ax.set_yticks(ys, labels, fontsize=8)
    ax.set_ylim(-0.6, len(points) - 0.4)
    ax.set_xlim(0, max(values) * 1.35)  # 右侧显式留白：值标签在最大点右侧，margins 不足以容纳文本宽
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title("VPP协议支持覆盖")
    ax.set_xlabel("涉及型号数")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="vpp_protocol_coverage", title="VPP协议支持覆盖", caption="VPP协议支持覆盖",
        section_heading="十一、V2G/V2H、VPP与试点项目", filename="09_Integrated_Matrix.csv", source=source,
        figure_type="lollipop", role="comparison", total=total,
        claim=f"样本共登记 {total} 项协议覆盖记录，以 {points[0][0]} 涉及型号最多（{points[0][1]} 个）",
    )


def strategic_judgment_distribution(project_dir: Path, plt):
    """竞品战略判断气泡排名（bubble-ranking / positioning 家族）。"""
    from matplotlib.lines import Line2D  # 懒导入：仅本构建器需要图例句柄

    source, points, total = _category_counts(project_dir, "09_Integrated_Matrix.csv", "strategic_judgment")
    if not points:
        return None
    max_value = max(point[1] for point in points)
    colors = theme_series_colors(len(points))
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["standard"])
    for rank, ((label, value), color) in enumerate(zip(points, colors), start=1):
        ax.scatter(rank, value, s=160 + 520 * value / max_value, color=color, alpha=0.85,
                   edgecolors=COLORS["neutral_dark"], linewidths=0.5, zorder=3)
    handles = [
        Line2D([0], [0], marker="o", linestyle="", markersize=7, markerfacecolor=color,
               markeredgecolor=COLORS["neutral_dark"], label=f"{label[:10]}（{value} 型号）")
        for (label, value), color in zip(points, colors)
    ]
    ax.legend(handles=handles, fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    ax.set_xticks(range(1, len(points) + 1))
    ax.margins(0.22)
    ax.set_title("竞品战略判断分布（气泡排名）")
    ax.set_xlabel("登记量排名（1 为最多）")
    ax.set_ylabel("型号数量")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="strategic_judgment_distribution", title="竞品战略判断分布", caption="竞品战略判断分布",
        section_heading="十二、产品定义与市场进入策略", filename="09_Integrated_Matrix.csv", source=source,
        figure_type="bubble-ranking", role="decision", total=total,
        claim=f"共登记 {total} 条战略判断，以 {points[0][0]} 最多（{points[0][1]} 个型号）",
    )


def risk_level_distribution(project_dir: Path, plt):
    """风险等级分布（risk-matrix / variance-and-risk 家族）：按严重度着色。"""
    source, points, total = _category_counts(project_dir, "10_SWOT_Opportunity.csv", "risk_level")
    if not points:
        return None

    def severity_rank(label: str) -> int:
        lowered = label.lower()
        if "高" in label or "high" in lowered:
            return 2
        if "中" in label or "mid" in lowered or "medium" in lowered:
            return 1
        return 0

    def severity_color(label: str) -> str:
        rank = severity_rank(label)
        return ("#4C9F70", "#E0A83C", "#C0504D")[rank]  # 低→绿、中→琥珀、高→红，不入主题主色避免混淆数据系
    points = sorted(points, key=lambda point: (severity_rank(point[0]), -point[1]))
    labels = [point[0][:12] for point in points]
    values = [point[1] for point in points]
    fig, ax = plt.subplots(figsize=FIGURE_SIZES["standard"])
    bars = ax.bar(labels, values, color=[severity_color(label) for label in labels])
    ax.bar_label(bars, fmt="%g", padding=2, fontsize=8)
    ax.set_ylim(0, max(values) * 1.25)
    plt.setp(ax.get_xticklabels(), rotation=18, ha="right", fontsize=8)
    ax.set_title("风险等级分布")
    ax.set_ylabel("条目数量")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="risk_level_distribution", title="风险等级分布", caption="风险等级分布",
        section_heading="十三、风险、路线图与行动计划", filename="10_SWOT_Opportunity.csv", source=source,
        figure_type="risk-matrix", role="robustness", total=total,
        claim=f"共登记 {total} 条风险条目，等级以 {points[0][0]} 最多（{points[0][1]} 条）",
    )


def source_reliability_composition(project_dir: Path, plt):
    """来源核验状态记分卡（scorecards / information-design）：已核/未核分色。"""
    from matplotlib.patches import Rectangle  # 懒导入：仅瓦片类构建器需要

    source, points, total = _category_counts(project_dir, "00_Source_Ledger.csv", "verification_status")
    if not points:
        return None
    cols = min(3, len(points))
    rows_n = math.ceil(len(points) / cols)
    fig, ax = plt.subplots(figsize=(7.0, max(3.0, rows_n * 1.35 + 0.8)))
    for idx, (label, value) in enumerate(points):
        row, col = divmod(idx, cols)
        verified = "verified" in label.lower() and "unverified" not in label.lower()
        face = COLORS["secondary"] if verified else "#E0A83C"
        ax.add_patch(Rectangle((col + 0.04, rows_n - 1 - row + 0.06), 0.92, 0.88,
                               facecolor=face, alpha=0.88,
                               edgecolor=COLORS["neutral_mid"], linewidth=0.6))
        ax.text(col + 0.5, rows_n - row - 0.38, str(value), ha="center", fontsize=14, fontweight="bold")
        ax.text(col + 0.5, rows_n - row - 0.68, label[:12], ha="center", fontsize=8)
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows_n)
    ax.axis("off")
    ax.set_title("来源核验状态构成")
    fig.tight_layout()
    return fig, _chapter_meta(
        name="source_reliability_composition", title="来源核验状态构成", caption="来源核验状态构成",
        section_heading="十四、来源、假设、证据问题与附录", filename="00_Source_Ledger.csv", source=source,
        figure_type="scorecards", role="validation", total=total,
        claim=f"共登记 {total} 条来源，核验状态以 {points[0][0]} 最多（{points[0][1]} 条）",
    )


CHART_BUILDERS = [
    market_trend,
    price_capacity_scatter,
    parameter_heatmap,
    channel_heatmap,
    pain_point_pareto,
    capability_radar,
    evidence_source_composition,
    opportunity_priority_distribution,
    collection_task_status,
    market_evidence_metric_composition,
    product_form_distribution,
    unit_price_comparison,
    vpp_protocol_coverage,
    strategic_judgment_distribution,
    risk_level_distribution,
    source_reliability_composition,
]


def load_claim_registry(path: str | None, project_dir: Path) -> dict[str, dict]:
    if not path:
        return {}
    registry_path = Path(path)
    if not registry_path.is_absolute():
        registry_path = project_dir / registry_path
    data = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Claim registry must be a JSON object keyed by chart name")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Render embedded market-evidence SVG/PNG figure bundles from project CSVs.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--output-dir", default="deliverables/charts")
    parser.add_argument("--claim-registry", help="JSON object keyed by chart name with core_claim and claim_confirmed")
    parser.add_argument("--mode", choices=("draft", "final"), default="draft")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    claims = load_claim_registry(args.claim_registry, project_dir)

    plt = load_matplotlib()
    charts: list[dict] = []
    skipped: list[dict] = []
    for figure_number, builder in enumerate(CHART_BUILDERS, start=1):
        built = builder(project_dir, plt)
        if built is None:
            skipped.append({"chart": builder.__name__, "reason": "insufficient_market_evidence"})
            continue
        fig, metadata = built
        claim_record = claims.get(metadata["name"], {})
        core_claim = claim_record.get("core_claim", metadata["claim"])
        claim_confirmed = bool(claim_record.get("claim_confirmed", False))
        try:
            manifest_path = save_figure_bundle(
                fig,
                output_dir / f"fig{figure_number}_{metadata['name']}",
                project_dir=project_dir,
                figure_id=metadata["name"],
                title=metadata["title"],
                figure_class="market-insight",
                figure_type=metadata["figure_type"],
                archetype="single-evidence-chart",
                role=metadata["role"],
                core_claim=core_claim,
                claim_confirmed=claim_confirmed,
                panel_map={"a": metadata["title"]},
                source_data_paths=[metadata["source"]],
                data_provenance=metadata["data_provenance"],
                report_placement=metadata["placement"],
                generator_script=Path(__file__),
                dpi=300,
                min_font_size_pt=8,
                final=args.mode == "final",
            )
        except ValueError as exc:
            # 断言未确认/契约不满足的图不进入交付集：与证据缺口同等对待，
            # 不让单张图阻断整个渲染批次（编排模式无人可补确认）。
            skipped.append({"chart": builder.__name__, "reason": f"figure_contract: {exc}"})
            continue
        finally:
            plt.close(fig)
        charts.append(
            {
                "name": metadata["name"],
                "manifest": str(manifest_path.relative_to(project_dir)),
                "rows_used": metadata["rows_used"],
            }
        )

    from common.chart_manifest import save_chart_manifest  # FIX round-2: unified writer

    save_chart_manifest(output_dir / "chart_manifest.json", charts, skipped, mode=args.mode)
    print(f"Rendered {len(charts)} embedded figure bundles into: {output_dir}")
    if skipped:
        print(
            "Skipped market charts due to evidence gaps: "
            + "; ".join(f"{item['chart']} ({item['reason']})" for item in skipped)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
