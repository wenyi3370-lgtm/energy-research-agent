# Kami Broker Chart Theme

Use this theme for every analytical, market, engineering, economic, sensitivity, competitor, and strategy chart that enters Word, Excel, PPT, or PDF.

## Theme identity

- Theme ID: `kami-broker-v2` (2026-08-10 视觉层升级；v1 为历史 ID，旧图清单可保留)
- Implementation: `scripts/kami_broker_chart_theme.py`
- 应用入口：`apply_kami_broker_theme_v2()`；每张图保存前**必须**依次执行
  `bump_min_font(fig, 8)`（8 pt 下限）与 `apply_mixed_text_fonts(fig)`
  （中英双轨字体），否则视为违规
- Page background: pure white.
- Primary accent: ink blue `#1B365D`.
- Secondary blue: `#2D5A8A`.
- Neutral series: warm gray `#6B6A64`, `#9C9A93`, `#B8B7B0`, `#D6D3CB`.
- Light emphasis: `#EEF2F7`.
- Positive and negative colors are reserved for signed meaning: `#2E7D32` and `#B91C1C`.
- Do not introduce a different palette per chart.

## Typography

- Chinese labels: 宋体 or an available Song-family fallback.
- Latin text and numbers: Times New Roman or a metrically compatible serif fallback.
- Chart title: 12 pt, centered.
- Axis title: 10 pt.
- Tick labels and legend: 9 pt.
- Data labels: 8.5-9 pt; never below 8 pt in a Word report.
- Word figure caption: 宋体 / Times New Roman, 10.5 pt, centered below the figure.

## Geometry

- Standard Word width: 15.6 cm (`6.142 in`) maximum.
- Standard single chart: `6.142 × 3.8 in`.
- Dense horizontal ranking chart: `6.142 × 4.4 in`.
- Multi-panel chart: `6.142 × 5.0 in`.
- Use a white figure and axes background.
- Remove top and right spines.
- Use 0.75 pt left/bottom spines in warm gray.
- Disable gridlines by default. When comparison requires them, use only horizontal gridlines at 0.5 pt in `#D6D3CB`.
- Keep legends borderless and prefer a horizontal legend above or below the plot when space allows.

## Word placement

- Insert every chart as an inline object, never as a floating anchor.
- Put the chart in a dedicated paragraph using the `Figure Image` style.
- Center the paragraph and the chart.
- Limit displayed width to 15.6 cm.
- Put `图X-X  标题` below the chart using the centered `Figure Caption` style.
- Put source, update date, value class, geography, sample size, and caveat below the caption using `Source Note`.
- Mention every chart in the surrounding body text.

## Production contract

1. Define the human-confirmed claim, chart type, panel map, exact source data, output location, and report placement.
2. Assign one embedded owner: `embedded-market-figure-v1` for `market-insight`, or `embedded-modeling-figure-v1` for `modeling`. Do not use both on the same figure.
3. Import and call `apply_kami_broker_theme()` before creating axes.
4. Export editable SVG and PNG at 300 dpi or higher.
5. Write a theme manifest carrying `theme_id: kami-broker-v1`, `figure_owner`, `figure_class`, `backend=python`, source-data path, output hashes, figure dimensions, and claim status.
6. Pass the figure render check before Word insertion.
7. Use `docx`/`documents` to insert and verify the centered inline figure.

Do not use decorative stock graphics, gradients, 3D effects, heavy shadows, rounded dashboard cards, rainbow palettes, or untraceable chart data.

## v2 视觉层（2026-08-10 教训固化）

Word 报告图表必须达到以下**硬性层级**（此前 13px 标题 + 7px 标签 + 全 SimSun 被判丑并全量返工）：

1. **图内顶部零文字（v2.2 硬性）**：图内**不绘制标题、饰线、灰色图注**——Word 图题行
   （"图X-X 标题"）承载标题，任何图内顶部文字都会与绘图区重叠（用户两轮反馈）。
   `title_block` 为 no-op，图表顶部必须干净。
2. **字号下限（机械门禁）**：任何标签/刻度/注释 ≥ 8 pt（`bump_min_font(fig, 8.0)` 兜底；
   `place_bar_labels` min_font 默认 8，标签放不下就丢弃而不是缩小到 7pt）。
3. **中英双轨字体（机械门禁）**：纯拉丁/数字文本 = Times New Roman；含中文的混合串 =
   `font-family: 'SimSun', 'Times New Roman'` 回退列表（matplotlib ≥3.6 逐字形回退）。
   保存前必须调用 `apply_mixed_text_fonts(fig)`；SVG 校验必须能同时检出两种字体。
4. **色板白名单**：仅允许 kami-broker 色板 + 面板 `#F7F9FC`/网格 `#D9E2EC` +
   分区着色（`#EAF3E8`/`#F3E8E8`/`#FDE8E8`/`#FEF3C7`）+ 热力蓝阶
   （`#EEF2F7`→`#B8C7DC`→`#7A94BD`→`#4A6A9C`→`#1B365D`）+ 强调浅蓝 `#0EA5E9`；
   禁止 matplotlib 默认色板泄漏。
5. **图例置顶无框**：图例放绘图区上方（`bbox_to_anchor=(0.5, 1.12)`，无边框）。
6. **每图至少一个视觉层次增强**：预测虚线/置信带、累计线+80/20 参考（Pareto）、
   象限分隔线（风险矩阵）、区间带（情景）、堆叠+分区线（毛利）等，禁止裸柱/裸点堆叠。
