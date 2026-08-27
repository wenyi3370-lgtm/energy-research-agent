# -*- coding: utf-8 -*-
"""
为 Excel 工作簿添加原生内置图表（券商风格），锚定在数据表右侧。

规则（format-and-visual-style.md 验证版）：
- 使用 openpyxl.chart 原生图表（BarChart/ScatterChart/RadarChart/DoughnutChart/PieChart），不用 PNG 图片。
- 券商配色：数据系列 水蓝 #4472C4 / 墨绿 #538135，标题深蓝 #123A7A，网格线浅灰。
- 图表锚定在数据表右侧（anchor 在数据最后一列 +2 的位置），同 sheet 多图垂直错开（如 09 散点行2/雷达行20），不放独立 sheet。
- 每个 sheet 的图表数量与数据行数匹配；数据不足时不画图（记录跳过）。
- 可重复运行：先 ws._charts.clear() 清除旧图表，防叠加（曾出现重复运行导致同位置 2 图叠加重叠）。
- 防重叠要点：散点图去掉 y 轴标题（与图表标题冲突）；雷达图系列≤5 + 图例置底；环形图关数据标签（品牌+计数在图例）；数据标签字号 8pt 放 outEnd。

用法:
    python scripts/add_excel_native_charts.py --project-dir <proj> [--workbook deliverables/市场调研数据与模型.xlsx]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.chart import (
    AreaChart, BarChart, DoughnutChart, LineChart, PieChart, RadarChart,
    Reference, ScatterChart, Series,
)
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.legend import Legend
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.series import SeriesLabel
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Font, NamedStyle, PatternFill
from openpyxl.utils import get_column_letter, range_boundaries

# 券商配色
BRAND = "4472C4"    # 水蓝（表头同色）
OLIVE = "538135"    # 墨绿
TITLE = "123A7A"    # 深蓝（标题）
GRID = "D9E2F3"     # 浅灰蓝网格
CAPTION_STYLE = "Chart Caption"
SOURCE_STYLE = "Chart Source"


def _ensure_chart_styles(wb) -> None:
    if CAPTION_STYLE not in wb.named_styles:
        wb.add_named_style(NamedStyle(
            name=CAPTION_STYLE,
            font=Font(name="Microsoft YaHei", size=10.5, bold=True, color="1F1F1F"),
            alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
        ))
    if SOURCE_STYLE not in wb.named_styles:
        wb.add_named_style(NamedStyle(
            name=SOURCE_STYLE,
            font=Font(name="Microsoft YaHei", size=9, color="666666"),
            alignment=Alignment(horizontal="left", vertical="center", wrap_text=True),
        ))


def _write_merged_row(ws, min_col: int, max_col: int, row: int, value: str, style: str) -> None:
    cell_range = f"{get_column_letter(min_col)}{row}:{get_column_letter(max_col)}{row}"
    if cell_range not in {str(item) for item in ws.merged_cells.ranges}:
        ws.merge_cells(cell_range)
    cell = ws.cell(row=row, column=min_col)
    cell.value = value
    cell.style = style


def place_chart_block(
    ws, chart, anchor_range: str, caption: str, source: str, *, title: str,
    legend_position: str = "b", data_label_position: str | None = None,
    show_values: bool | None = None,
) -> None:
    """Bind a chart and its caption/source to a portable cell rectangle."""
    _ensure_chart_styles(ws.parent)
    min_col, min_row, max_col, max_row = range_boundaries(anchor_range)
    chart.anchor = TwoCellAnchor(
        editAs="twoCell",
        _from=AnchorMarker(col=min_col - 1, row=min_row - 1, colOff=0, rowOff=0),
        to=AnchorMarker(col=max_col, row=max_row, colOff=0, rowOff=0),
    )
    chart.title = title
    chart.title.overlay = False
    if chart.legend is None:
        chart.legend = Legend()
    chart.legend.position = legend_position
    chart.legend.overlay = False
    chart.legend.layout = None
    chart.layout = None
    if data_label_position is not None or show_values is not None:
        if getattr(chart, "dLbls", None) is None:
            chart.dLbls = DataLabelList()
        if data_label_position is not None:
            chart.dLbls.dLblPos = data_label_position
        if show_values is not None:
            chart.dLbls.showVal = show_values
    _write_merged_row(ws, min_col, max_col, max_row + 1, caption, CAPTION_STYLE)
    _write_merged_row(ws, min_col, max_col, max_row + 2, source, SOURCE_STYLE)
    ws.row_dimensions[max_row + 1].height = 18
    ws.row_dimensions[max_row + 2].height = 18


def _style_chart(chart, title: str, series_colors: list[str]) -> None:
    """券商风格图表样式：标题深蓝、系列色、浅灰网格、无图例边框。"""
    chart.title = title
    chart.title.font = Font(size=11, bold=True, color=TITLE)
    chart.height = 7
    chart.width = 12
    chart.gapWidth = 60
    # 网格线浅灰（PieChart 无轴，跳过；openpyxl 默认已有网格线，仅尝试着色）
    for axis_name in ("y_axis", "x_axis"):
        axis = getattr(chart, axis_name, None)
        if axis is None:
            continue
        try:
            if axis.majorGridlines is not None and axis.majorGridlines.spPr is not None:
                line = axis.majorGridlines.spPr.line
                line.solidFill = GRID
        except Exception:
            pass
        axis.delete = False
    # 系列配色
    for idx, series in enumerate(chart.series):
        if idx < len(series_colors):
            series.graphicalProperties.solidFill = series_colors[idx]
            series.graphicalProperties.line.solidFill = series_colors[idx]
    # 数据标签（字号 8pt 防与坐标轴重叠）
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.numFmt = "0"
    chart.dataLabels.dLblPos = "outEnd"


# metric 代码 → 中文标签（价格类）
PRICE_LABELS = {
    "price_2000w_with_storage": "2000W套装",
    "price_anker_solix_bundle": "Anker含储能",
    "price_1920w_anker_solix": "1920W+SOLIX",
    "price_2000w_storage_1799": "2000W+储能",
    "entry_price_band_low": "入门下限",
    "entry_price_band_high": "入门上限",
}


def add_price_chart(ws, data_start_row: int, data_end_row: int, anchor: str) -> BarChart:
    """01_Market_Scan 价格对比柱状图。

    只取价格类行（metric 含 'price' 或 'entry_price'）——过滤量纲不同的行
    （indexed_storage_systems=2300000 套、tracked_gw=2.4GW 与 EUR 价格混画会把价格柱压扁）。
    中文分类标签写到图表锚点左侧的辅助列（不影响原数据表结构）。
    """
    headers = [c.value for c in ws[1]]
    metric_col = headers.index("metric") + 1 if "metric" in headers else 8
    value_col = headers.index("raw_value") + 1 if "raw_value" in headers else 10

    # 筛选价格类行
    price_rows = []
    for r in range(data_start_row, data_end_row + 1):
        metric = str(ws.cell(row=r, column=metric_col).value or "")
        if "price" in metric or "entry_price" in metric:
            price_rows.append(r)
    if not price_rows:
        return None

    # 中文标签辅助列：放在图表锚点右侧（数据表 max_column+4，远离数据区，避免污染数据列）
    label_col = ws.max_column + 4
    ws.cell(row=1, column=label_col, value="中文标签")
    for i, r in enumerate(price_rows):
        metric = str(ws.cell(row=r, column=metric_col).value or "")
        ws.cell(row=r, column=label_col, value=PRICE_LABELS.get(metric, metric))

    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    title = "德国阳台储能价格对比 (EUR)"
    cats = Reference(ws, min_col=label_col, min_row=price_rows[0], max_row=price_rows[-1])
    data = Reference(ws, min_col=value_col, min_row=price_rows[0], max_row=price_rows[-1])
    chart.add_data(data, titles_from_data=False)
    chart.set_categories(cats)
    _style_chart(chart, title, [BRAND, OLIVE])
    ws.add_chart(chart)
    place_chart_block(
        ws, chart, anchor, "图：德国阳台储能价格对比",
        "数据来源：01_Market_Scan；完整口径见 99_来源与口径。",
        title=title, data_label_position="outEnd", show_values=True,
    )
    return chart


def add_rating_chart(ws, data_start_row: int, data_end_row: int, anchor: str) -> BarChart:
    """08_Review_Coding 评分柱状图。"""
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    title = "评论主题频次"
    headers = [c.value for c in ws[1]]
    theme_col = headers.index("theme") + 1 if "theme" in headers else 1
    freq_col = headers.index("frequency_count") + 1 if "frequency_count" in headers else 5
    cats = Reference(ws, min_col=theme_col, min_row=data_start_row, max_row=data_end_row)
    data = Reference(ws, min_col=freq_col, min_row=data_start_row, max_row=data_end_row)
    chart.add_data(data, titles_from_data=False)
    chart.set_categories(cats)
    _style_chart(chart, title, [BRAND])
    ws.add_chart(chart)
    place_chart_block(
        ws, chart, anchor, "图：评论主题频次",
        "数据来源：08_Review_Coding；完整口径见 99_来源与口径。",
        title=title, data_label_position="outEnd", show_values=True,
    )
    return chart


def add_pie_chart(ws, data_start_row: int, data_end_row: int, anchor: str) -> PieChart:
    """12_Model_Assumptions 假设分布饼图（value_class 占比）。"""
    chart = PieChart()
    chart.style = 10
    title = "模型假设类型分布"
    headers = [c.value for c in ws[1]]
    name_col = headers.index("parameter_name") + 1 if "parameter_name" in headers else 4
    base_col = headers.index("base_value") + 1 if "base_value" in headers else 6
    cats = Reference(ws, min_col=name_col, min_row=data_start_row, max_row=data_end_row)
    data = Reference(ws, min_col=base_col, min_row=data_start_row, max_row=data_end_row)
    chart.add_data(data, titles_from_data=False)
    chart.set_categories(cats)
    _style_chart(chart, title, [BRAND, OLIVE, "6B7280"])
    ws.add_chart(chart)
    place_chart_block(
        ws, chart, anchor, "图：模型假设类型分布",
        "数据来源：12_Model_Assumptions；完整口径见 99_来源与口径。",
        title=title, data_label_position="bestFit", show_values=False,
    )
    return chart


def add_charts(workbook_path: Path) -> list[str]:
    wb = load_workbook(workbook_path)
    added: list[str] = []
    # 清除已有图表（脚本可重复运行，避免新旧图表叠加导致标签重叠）
    for ws in wb.worksheets:
        ws._charts.clear()

    # 01_Market_Scan：价格对比柱状图（数据行 2..N）
    if "01_Market_Scan" in wb.sheetnames:
        ws = wb["01_Market_Scan"]
        max_row = ws.max_row
        if max_row >= 3:
            # 只取价格类行（含 price 的 metric），无则全量
            anchor_col = ws.max_column + 2
            anchor = f"{get_column_letter(anchor_col)}2:{get_column_letter(anchor_col + 11)}17"
            add_price_chart(ws, 2, max_row, anchor)
            added.append("01_Market_Scan: 价格柱状图")

    # 05_Pricing_Channel：价格条形图
    if "05_Pricing_Channel" in wb.sheetnames:
        ws = wb["05_Pricing_Channel"]
        max_row = ws.max_row
        if max_row >= 3:
            anchor_col = ws.max_column + 2
            anchor = f"{get_column_letter(anchor_col)}2:{get_column_letter(anchor_col + 11)}17"
            chart = BarChart()
            chart.type = "bar"  # 水平条形
            chart.style = 10
            headers = [c.value for c in ws[1]]
            config_col = headers.index("configuration") + 1 if "configuration" in headers else 9
            price_col = None
            for h, name in enumerate(headers):
                if name in ("discounted_price", "list_price"):
                    price_col = h + 1
                    break
            if price_col is None:
                price_col = 10
            cats = Reference(ws, min_col=config_col, min_row=2, max_row=max_row)
            data = Reference(ws, min_col=price_col, min_row=2, max_row=max_row)
            chart.add_data(data, titles_from_data=False)
            chart.set_categories(cats)
            _style_chart(chart, "配置价格对比 (EUR)", [BRAND])
            ws.add_chart(chart)
            place_chart_block(
                ws, chart, anchor, "图：配置价格对比",
                "数据来源：05_Pricing_Channel；完整口径见 99_来源与口径。",
                title="配置价格对比 (EUR)", data_label_position="outEnd", show_values=True,
            )
            added.append("05_Pricing_Channel: 价格条形图")

    # 08_Review_Coding：评分柱状图
    if "08_Review_Coding" in wb.sheetnames:
        ws = wb["08_Review_Coding"]
        max_row = ws.max_row
        if max_row >= 3:
            anchor_col = ws.max_column + 2
            anchor = f"{get_column_letter(anchor_col)}2:{get_column_letter(anchor_col + 11)}17"
            add_rating_chart(ws, 2, max_row, anchor)
            added.append("08_Review_Coding: 频次柱状图")

    # 12_Model_Assumptions：假设饼图
    if "12_Model_Assumptions" in wb.sheetnames:
        ws = wb["12_Model_Assumptions"]
        max_row = ws.max_row
        if max_row >= 3:
            anchor_col = ws.max_column + 2
            anchor = f"{get_column_letter(anchor_col)}2:{get_column_letter(anchor_col + 11)}17"
            add_pie_chart(ws, 2, max_row, anchor)
            added.append("12_Model_Assumptions: 假设饼图")

    # 09_Integrated_Matrix：价格-容量散点图（ScatterChart，对应 embedded-modeling-figure-v1 的 prediction-fit 类型）
    if "09_Integrated_Matrix" in wb.sheetnames:
        ws = wb["09_Integrated_Matrix"]
        max_row = ws.max_row
        headers = [c.value for c in ws[1]]
        cap_col = headers.index("capacity_kwh") + 1 if "capacity_kwh" in headers else 4
        price_col = headers.index("price") + 1 if "price" in headers else 8
        if max_row >= 3:
            anchor_col = ws.max_column + 2
            anchor = f"{get_column_letter(anchor_col)}2:{get_column_letter(anchor_col + 11)}17"
            chart = ScatterChart()
            chart.style = 10
            chart.title = "竞品价格-容量散点 (EUR vs kWh)"
            chart.title.font = Font(size=11, bold=True, color=TITLE)
            chart.height, chart.width = 7, 12
            # X=容量, Y=价格
            xref = Reference(ws, min_col=cap_col, min_row=2, max_row=max_row)
            yref = Reference(ws, min_col=price_col, min_row=2, max_row=max_row)
            series = Series(yref, xref, title="价格-容量")
            series.marker = Marker(symbol="circle", size=7)
            series.graphicalProperties.solidFill = BRAND
            chart.series.append(series)
            # 轴标题字号调小并仅保留 x 轴（y 轴标题与图表标题在 LibreOffice 渲染会重叠）
            chart.x_axis.title = "容量 (kWh)"
            chart.x_axis.title.font = Font(size=9, color="6B7280")
            ws.add_chart(chart)
            place_chart_block(
                ws, chart, anchor, "图：竞品价格—容量散点",
                "数据来源：09_Integrated_Matrix；完整口径见 99_来源与口径。",
                title="竞品价格-容量散点 (EUR vs kWh)", show_values=False,
            )
            added.append("09_Integrated_Matrix: 价格-容量散点图")

    # 02_Competitor_List：竞品品牌分布环形图（DoughnutChart，对应 Kami donut-chart）
    # 跳过：该表无数值列（brand/parent_company 等均为文本），环形图需数值数据源；
    # 写辅助计数列会污染数据表结构（曾导致单元格位移）。按"数据不足跳过"规则处理。
    # 品牌分布如需可视化，由 09_Integrated_Matrix 的数值列承担。

    # 09_Integrated_Matrix：竞品能力雷达图（RadarChart，对应 embedded-modeling-figure-v1 的 evaluation-comparison 类型）
    if "09_Integrated_Matrix" in wb.sheetnames:
        ws = wb["09_Integrated_Matrix"]
        max_row = ws.max_row
        headers = [c.value for c in ws[1]]
        # 雷达维度：channel_coverage / smart_features / user_pain_score（数值列）
        dims = []
        for h in ("channel_coverage", "smart_features", "user_pain_score", "capacity_kwh"):
            if h in headers:
                dims.append(headers.index(h) + 1)
        brand_col = headers.index("brand") + 1 if "brand" in headers else 1
        if max_row >= 3 and len(dims) >= 3:
            anchor_col = ws.max_column + 2
            # 垂直错开并为第一张图的图注/来源保留两行。
            anchor = f"{get_column_letter(anchor_col)}22:{get_column_letter(anchor_col + 11)}37"
            chart = RadarChart()
            chart.style = 10
            chart.title = "竞品能力雷达"
            chart.title.font = Font(size=11, bold=True, color=TITLE)
            chart.height, chart.width = 7, 12
            # 每个竞品一个系列，维度=列；最多 5 个系列避免标签重叠
            cats = Reference(ws, min_col=dims[0], max_col=dims[-1], min_row=1, max_row=1)
            for r in range(2, min(max_row + 1, 7)):
                brand = ws.cell(row=r, column=brand_col).value or f"竞品{r-1}"
                vals = Reference(ws, min_col=dims[0], max_col=dims[-1], min_row=r, max_row=r)
                s = Series(vals, title=str(brand))
                chart.series.append(s)
            chart.set_categories(cats)
            chart.legend = Legend(legendPos="b")
            ws.add_chart(chart)
            place_chart_block(
                ws, chart, anchor, "图：竞品能力雷达",
                "数据来源：09_Integrated_Matrix；完整口径见 99_来源与口径。",
                title="竞品能力雷达", legend_position="b", show_values=False,
            )
            added.append("09_Integrated_Matrix: 竞品能力雷达图")

    wb.save(workbook_path)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Add native Excel charts (brokerage style) beside data tables.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--workbook", default="deliverables/市场调研数据与模型.xlsx")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    wb_path = project_dir / args.workbook
    if not wb_path.exists():
        print(f"Workbook not found: {wb_path}")
        return 1
    added = add_charts(wb_path)
    print(f"Added {len(added)} native charts to {wb_path.name}:")
    for a in added:
        print(f"  - {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
