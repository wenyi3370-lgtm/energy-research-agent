# Chart Polish And Variety Guide

Companion to `chart-and-framework-components.md` and
`kami-broker-chart-theme.md`.  Fixes two production failures observed in
real projects:

1. **Overlapping labels** — matplotlib data labels stack on crowded panels
   when placed with a fixed offset.  Use the collision-aware
   `chart_polish.place_bar_labels` (no external `adjustText` dependency).
2. **Monotone chart types** — a report whose figures are almost all bars
   reads as low-effort.  Choose the figure type from the table below by the
   *shape of the evidence*, not by the default template.

## 1. Label-safe layout contract

- **Panel**: `chart_polish.panel(ax)` — pale background `#F7F9FC`, subtle
  horizontal grid `#D9E2EC`, no top/right spines, y-tick padding.
- **Bar/line data labels**: `chart_polish.place_bar_labels(...)` —
  alternating vertical offsets (4/14pt), then a smaller font on a higher
  line for collisions, dropping the label rather than stacking it.  The
  value stays visible on the axis grid even when dropped.
- **Axis titles**: give the y-axis label breathing room
  (`ax.yaxis.set_label_coords(-0.09..-0.11, 0.5)`); on narrow charts prefer
  dropping the axis title when the figure title already carries the
  semantics.
- **Scatter labels**: use short model names (e.g. "Huawei LUNA" instead of
  "LUNA2000-5/10/15-S0") and right-align with a leader offset; keep points
  away from the axes (`ax.set_xlim(xmin-3, xmax+3)`).
- **Heatmap row labels**: `ax.tick_params(axis="y", pad=16)` or shorten row
  labels so they cannot collide with the first data cell.

## 2. Figure-type selection matrix

| Evidence shape | Recommended type | When |
|---|---|---|
| Composition / share | **Donut** (`chart_polish.donut`) | e.g. source mix, segment shares |
| Wide-magnitude comparison | **Bubble (log scale)** | e.g. 0.06 GW vs 5.6 GW |
| Likelihood × impact | **2×2 risk matrix** (`chart_polish.risk_matrix`) | risk register |
| Tiered narrowing | **Funnel** (`chart_polish.funnel`) | e.g. evidence tiers, lead funnel |
| Value bridge / delta | **Waterfall** | baseline → policy → scenario |
| Trend over time | Line with area fill + point labels | policy timeline, market trend |
| Positioning | Scatter with zone shading + short labels | price–capacity |
| Coverage | Heatmap with cell counts | parameter/channel coverage |
| Capability | Radar (normalized axes) | competitor capability |
| Frequency | Pareto bar (label-safe) | pain points |
| Scenario | Grouped bar with low/base/high | forecast bands |

Record the chosen type in the theme manifest
(`figure_contract.figure_type`) so reviewers and the Word/PPT pipelines can
audit variety: a chapter block should not be all bars.

For text-only models, set `figure_type: auto`, state `visual_intent` and
`encoding.relationship`, and let `render_figure_from_spec.py` route the chart
deterministically. Generic `bar` is not a safe default. For six or more formal
figures, `validate_figure_delivery.py` enforces bar-family share ≤60% and at
least three actual chart families. See `text-only-chart-and-slide-design.md`.

Text-only models must not simulate visual inspection. Python owns chart selection,
layout, palette and label fitting, and `automated_visual_qa` must pass before
registration. Count visual families as well as type names: bar, ranking-bar,
grouped-bar, lollipop and dot-plot are one `single-axis-comparison` family and
may appear at most four times in one final report.
Across the complete final report, each canonical chart type may appear at most
twice. Aliases are normalized before counting, so renaming `trend-line` to
`line` does not create a new type. Once a type reaches two uses, choose a
different evidence relationship rather than a cosmetic relabel.

## 3. Manifest hygiene for polished figures

`chart_polish.save_manifest(...)` writes the full accepted manifest:
- `generator` (path + sha256) — without it, `register_figure_delivery.py`
  resolves the path to the project dir and fails with a confusing
  PermissionError.
- `source_data[].sha256 / size_bytes` — the validator compares these against
  the real files.
- `outputs.png/svg.sha256` — must match the saved bytes.
- `qa.mechanical_render_check` — status `passed`; the validator requires it
  for re-registration.

## 4. Regression checklist

Before registering figures:
- [ ] 0 real text overlaps (verify by parsing the SVG `<text>` boxes, not by
      eye)
- [ ] figure_type is accurate and the block is not bar-monotone
- [ ] for 6+ figures, bar-family share ≤60% and ≥3 chart families
- [ ] every canonical chart type appears no more than twice
- [ ] generator + source_data hashes + qa block present
- [ ] `register_figure_delivery.py` succeeds for every figure


## 5. 机械回归门禁（v2.2，注册/插入前必过）

`scripts/verify_chart_svg_quality.py --charts-dir deliverables/charts` 对每张 figN_*.svg 检查：

1. **字号下限**：所有文本 ≥ 8 pt（matplotlib SVG 中 px==pt）。
2. **色板白名单**：仅 kami-broker 色板 + 面板/网格 + 分区着色 + 热力蓝阶 + `#0EA5E9`；
   matplotlib 默认色板泄漏即失败。
3. **字体双轨（按内容判定）**：含中文必须有 SimSun（可作回退列表 `'SimSun','Times New Roman'`），
   含拉丁/数字必须有 Times New Roman；纯拉丁图（如全英文热力图）合法地无 SimSun。
4. **图内顶部零文字**：y<30 且 ≤12pt 的文本视为图内标题/图注残留（Word 图题行承载标题）。
5. **文本重叠**：解析器必须兼容 `<text style="font-size:.." x=.. y=..>` 与 `x=.. y=.. style=..`
   **两种属性顺序**（2026-08-10 教训：旧正则只匹配 x→y→font-size，fig5 底部 5 个标签全挤在
   x≈69-343 处互相重叠却被漏报）；宽度用 PIL 真实字形（回退 CJK 估算）。

写作层配套规则（生成时预控，不能只靠门禁兜底）：

- **底部刻度标签**：按柱间距预算截断——每格可用宽 ≈ 柱间距-5px，用
  `chart_polish.fit_label(text, slot_w, font_size)` 截断（"投资回报疑虑（是否值得装）"→
  "投资回报疑…"）。
- **类别轴禁止数据坐标装饰**：`axvspan(700,1080)`/`axhspan` 等在类别轴上会把 xlim 撑爆、
  刻度标签全部挤压重叠（fig8 教训）；类别轴区域强调用 axes 分数坐标或直接省略。
- **Pareto 柱顶**：数值标签入柱内白色，柱顶只留累计线（文字不压线）。
- **散点/矩阵标注**：标注必须带白底衬（bbox facecolor=white alpha≈0.9）+ 按象限偏移，
  防与分隔线/区域着色交叉糊字。
