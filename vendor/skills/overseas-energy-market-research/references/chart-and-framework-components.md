# Chart And Framework Components

## Chart Data Contract

Every plotted value must include:

- value class: observed, derived, modeled estimate, or scenario assumption
- value, unit, currency/tax basis where relevant
- geography and date/period
- exact model/project/segment
- source URL or local file path
- evidence row IDs or assumption IDs
- verification/confidence status and caveat

## Market And Policy

- Historical/forecast trend with CAGR and forecast boundary.
- Geography x policy/tariff/standard heatmap.
- Market segmentation, value chain, channel structure, or country attractiveness bubble chart.
- TAM/SAM/SOM bridge with formula and scope definitions.

## Demand And Energy System

- 24-hour and seasonal load/PV/EV availability curves.
- Outage/reliability comparison.
- Energy-cost stack or baseline-vs-solution waterfall.
- Sankey or energy balance only when flows reconcile.

## Product And Competition

- Price-capacity/power scatter.
- Critical-parameter heatmap.
- Capability radar with normalized-axis definitions.
- Parallel coordinates for comparable numeric specifications.
- Channel/service coverage matrix.
- Competitive 2x2 with evidence-backed axes.

## Reviews

- Pain-point Pareto.
- Purchase-driver frequency.
- Rating distribution.
- Quote cards with short source-linked excerpts.
- Word cloud only as a supplement, never as the primary evidence.

## Modeling And Strategy

- Baseline/intervention waterfall.
- Payback, NPV, or IRR comparison.
- One-way/two-way sensitivity and tornado chart.
- Low/base/high or confidence interval.
- Scenario path, value curve, SWOT plus risk matrix, opportunity whitespace, and prioritized roadmap.

## Visual Rules

- Assign exactly one embedded owner before generation: `embedded-market-figure-v1` for `market-insight` evidence/strategy figures, and `embedded-modeling-figure-v1` for `modeling` figures. Do not pass a completed figure from one branch to the other for regeneration or restyling.
- Record `figure_pipeline_id=embedded-figure-production-v1`, `figure_owner`, `figure_class`, and `backend=python` in the figure theme manifest. Use `scripts/render_charts.py` for standard market evidence figures and `scripts/render_figure_from_spec.py` for declarative market/modeling figures.
- Load `kami-broker-chart-theme.md` and apply `scripts/kami_broker_chart_theme.py`; the fixed theme ID is `kami-broker-v1`.
- Before generation, define the core claim, figure type, panel map, exact source data, output contract, and report/slide placement. The core claim must be human-confirmed or explicitly marked as a sentinel.
- Never invent or silently infer plotting data. Save the plot-ready source table beside the figure.
- Export editable SVG as the primary artifact and PNG at 300 dpi or higher as the secondary artifact. Preserve live text in SVG (`svg.fonttype='none'`).
- Retain the generated `.theme.json` manifest beside every final SVG/PNG pair; it must identify the single responsible embedded owner and pass `validate_figure_delivery.py` plus explicit visual registration.
- Render-check every figure and verify labels, legends, clipping, units, source notes, and numerical consistency before integration.
- Insert Word charts inline in centered `Figure Image` paragraphs, center their captions, and reject floating anchors.
- Use the embedded presentation renderer for slide-native editable PowerPoint visuals.
- Put source, update date, value class, and caveat on every chart.
- Do not infer a conclusion from visual placement alone.
- Do not use radar, 2x2, or scoring frameworks without defining normalization and weights.
