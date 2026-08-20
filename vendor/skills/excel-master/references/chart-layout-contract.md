# Excel 图表与图注布局合同

## 目录

1. 强制规则
2. 推荐几何
3. 图例与数据标签
4. 创建流程
5. 已有工作簿修复
6. 验收

## 1. 强制规则

- 使用 `scripts/chart_layout_guard.py` 中的 `place_chart_block()` 放置正式图表。
- 使用 `TwoCellAnchor(editAs="twoCell")` 将图表绑定到明确的单元格矩形；禁止只给左上角坐标的自由浮动图表。
- 图表标题必须使用 Excel 原生 `chart.title`，并设置 `overlay=False`。
- 图例必须使用 Excel 原生 legend，默认放在底部并设置 `overlay=False`。
- 图注和资料来源必须写入图表正下方的工作表单元格，不得使用浮动文本框、形状或图片中的文字。
- 图注行使用命名样式 `Chart Caption`，水平居中；来源行使用 `Chart Source`，左对齐。
- 中文图注与来源默认使用 `Microsoft YaHei`；英文和数字由 Excel 字体回退处理。不要将中文图注强制设为仅支持西文的字体。
- 图表锚定区、图注行和来源行必须连续：图表结束行后的第 1 行为图注，第 2 行为来源。
- 同一工作表中的图表锚定区不得相交；图注区不得覆盖数据表、合并单元格或分页标题。
- 禁止手工设置 plot area 或 legend 的 factor/absolute manual layout。不同 Excel、WPS、LibreOffice 版本会对其作不同解释。

## 2. 推荐几何

- 单图宽版：`B6:N23`，图注 `B24:N24`，来源 `B25:N25`。
- 双图并排：左 `B6:H21`，右 `J6:P21`；分别使用独立图注和来源行。
- Dashboard 小图：每图至少 7 列 × 12 行；标题和图例必须保留独立空间。
- 图表上方至少留 1 行空白；图表下方固定留 2 行图注区。
- 创建完图表后再冻结窗格、设置打印区域和分页，避免后续插行改变视觉节奏。

## 3. 图例与数据标签

- 默认图例位置为底部 `b`。只有宽度不足且系列不超过 4 个时才允许右侧 `r`，并在审计记录中说明。
- 柱形/条形图：分类不超过 8 个时可显示数值；默认 `outEnd`。存在正负值时改为 `inEnd` 或关闭标签。
- 折线/散点图：默认不显示所有点标签。只标注端点、峰值、异常值；全点标签会随缩放重叠。
- 饼图/圆环图：分类不超过 6 个；使用 `bestFit`，标签只显示百分比或分类名之一。
- 组合图：数据标签只保留在决策所需的主系列；次轴必须有轴标题和单位。
- 不要使用空格或换行把标签“推”到某个位置；位置必须通过图表属性控制。

## 4. 创建流程

```python
from openpyxl.chart import BarChart, Reference
from chart_layout_guard import place_chart_block

chart = BarChart()
chart.add_data(Reference(ws, min_col=3, min_row=5, max_row=12), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=2, min_row=6, max_row=12))
ws.add_chart(chart)

place_chart_block(
    ws,
    chart,
    "B6:N23",
    "图1 目标市场容量与增速",
    "资料来源：公司数据库，2026-08-03；注：情景假设。",
    title="目标市场容量与增速",
    legend_position="b",
    data_label_position="outEnd",
    show_values=True,
)
```

图表必须先加入 `ws._charts`，再调用 `place_chart_block()`。工作簿只保存一次。

## 5. 已有工作簿修复

为每个图表建立 JSON manifest：

```json
{
  "sheets": {
    "Dashboard": [
      {
        "chart_index": 0,
        "anchor": "B6:N23",
        "title": "目标市场容量与增速",
        "caption": "图1 目标市场容量与增速",
        "source": "资料来源：公司数据库，2026-08-03",
        "legend_position": "b",
        "data_label_position": "outEnd",
        "show_values": true
      }
    ]
  }
}
```

执行：

```bash
python scripts/chart_layout_guard.py normalize input.xlsx --output fixed.xlsx --manifest chart_layout.json
python scripts/chart_layout_guard.py audit fixed.xlsx --json-out chart_layout_audit.json
```

不得对没有 manifest 的既有工作簿自动重排图表。图表顺序、布局和图注意图无法可靠猜测。

## 6. 验收

- `audit` 返回 `status: pass`，且图表数量与预期一致。
- 每个图表均为 `TwoCellAnchor`，有标题、图注和来源行。
- 无 `chart-overlap`、`floating-anchor`、`title-overlay`、`legend-overlay`。
- 用 Excel 或 LibreOffice 打开并导出 PDF/截图；分别检查 100% 和适合窗口缩放。
- 检查标题、图例、数据标签、图注和来源没有遮挡、截断或跨页漂移。
- 如果渲染失败，先缩短标题/图注或扩大锚定区；不得重新使用浮动文本框。
