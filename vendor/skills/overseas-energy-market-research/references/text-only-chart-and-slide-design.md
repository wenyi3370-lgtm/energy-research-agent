# Text-only Chart And Slide Design Contract

This contract lets a text-only model produce varied, editable business charts

The text-only model declares evidence relationship, fields, claim and source only.
Deterministic Python selects and styles the final grammar. `automated_visual_qa`
must check minimum font size, text overflow, material text collisions, aspect
ratio and text density. Never write a fake human-inspection confirmation.
Type diversity is not enough: bar, ranking-bar, grouped-bar, lollipop and
dot-plot are one single-axis comparison family, capped at four uses per report.
and presentation pages without inspecting a reference image. It converts visual
judgment into explicit data relationships, composition rules, and validators.

## 1. Figure spec: describe the relationship before the chart

Every figure spec must contain:

```json
{
  "figure_id": "fig7_policy_timeline",
  "title": "政策从试点验证转向规模化准入",
  "core_claim": "2025–2027 年的政策节点决定商业化窗口",
  "visual_intent": "timeline",
  "figure_type": "auto",
  "encoding": {
    "relationship": "time progression",
    "date": "date",
    "label": "milestone"
  }
}
```

`visual_intent` and `encoding.relationship` are semantic instructions, not
decorative style labels. `render_figure_from_spec.py` deterministically selects
the chart. A generic `bar` request may be upgraded when the evidence clearly
requires another grammar.

Relationship routing:

| Evidence relationship | Figure type | Required fields |
|---|---|---|
| rank / priority / compact comparison | lollipop | category, value |
| time progression | line or timeline | x+series, or date+label |
| composition / share | donut | category, value |
| baseline plus deltas | waterfall | category, value |
| positive and negative sensitivity | diverging bar | category, value |
| two numeric dimensions | scatter | x, y, label |
| likelihood × impact | risk matrix | likelihood, impact, label |
| two-dimensional coverage | heatmap | row_label, value_columns |
| staged narrowing | funnel | category, value |
| multi-series scenario | grouped bar | category, series |

Do not choose a chart because it is easy to draw. Do not generate one bar chart
per chapter. In a final set of six or more figures, bar-family charts must be at
most 60%, and the set must use at least three chart families. Every canonical
chart type may appear at most twice across the complete report; aliases are
normalized before counting.

## 2. Visual grammar

- White canvas, pale `#F7F9FC` plot panel, subtle `#D9E2EC` grid.
- Core palette: navy `#17365D`, blue `#4472C4`, teal `#167C80`, gold
  `#C9A227`, plus cool greys. Red/green only encode negative/positive meaning.
- Use one dominant series and one comparison series. Extra colors identify
  genuinely different series; they are not decoration.
- All chart text is at least 8 pt. Chinese strings include SimSun fallback;
  Latin and numbers include Times New Roman.
- The chart contains no title, subtitle, source, or decorative top strip. Word
  owns the caption; PPT owns the answer-first title.
- Labels are collision-aware. If a label cannot fit, shorten it or omit the
  redundant label and keep the value legible through the axis.
- SVG with editable text is the primary artifact; PNG at 300 dpi or higher is
  the Word rendering artifact. The manifest records the actual chart type and
  hashes both outputs and source data.

## 3. Word image-paragraph invariant

An inline chart must never inherit an exact or fixed line height. Both the
`Figure Image` style and every paragraph containing `<w:drawing>` must use:

- line spacing rule: single / auto;
- line spacing: 1.0;
- centered alignment;
- 6 pt space before and 0 pt after;
- `keep_with_next` and `keep_together`.

A 12 pt exact line height can clip a multi-inch inline chart into a thin strip
even though the image is present in OOXML. This is a final-delivery blocker,
not a cosmetic warning.

## 4. Evidence-map-to-slide workflow

Before authoring SVG pages, build `presentation_project/evidence_map.json`:

1. **Evidence map**: bind every page to an approved chart manifest, table,
   model result, or explicitly sourced narrative fact.
2. **Storyline**: write one answer-first conclusion per page and the question
   it answers.
3. **Supporting themes**: limit the page to 2–4 evidence themes.
4. **Composition**: choose a layout family from the evidence relationship;
   do not default to a repeated chart-left/commentary-right grid.
5. **SO WHAT**: write the decision implication before drawing the page.
6. **Editable build**: titles, text, simple charts, tables, and geometry remain
   native DrawingML after SVG conversion. Raster assets are limited to the
   approved EWO illustration route.
7. **QA loop**: validate source SVG, finalize, export, render with LibreOffice
   and PyMuPDF, inspect every page, repair at least once, and fully rerender.

Use `build_presentation_evidence_map.py --page-plan <storyline.json>` for formal
decks. The page plan includes cover, agenda, section transitions, evidence
pages, decisions, risks, and next actions—not only chart pages. Final decks use
at least four layout families and never repeat one family on three consecutive
pages.

Recommended layout families include executive summary, section opener, full-
width trend, comparison with commentary, ranked evidence, small multiples,
positioning map, evidence matrix, value bridge, risk matrix, action roadmap,
and decision tree. High density means more decision-relevant evidence, never
smaller text or more decorative cards.


## 6. Slide density contract (v1.2.9)

Data-heavy body slides use the three-column dense layout validated on the AU
V2G deck (2026-08-12): left evidence column (x=60 w=290) + approved chart
(x=380 w=520) + right implication column (x=930 w=290), with a 1-2 line
data note under the chart and the SO WHAT banner + dual footer below. Each
bullet must bind to an evidence row id or source. Page density comes from
more decision-relevant evidence (2-4 themes per page), never from smaller
text or repeated card grids. Math symbols render as words to avoid
LibreOffice font-substitution overlap. Full coordinates:
`ppt-style-prompts.md` §1.4.

- [ ] Every body slide has ≥2 evidence themes plus a chart/framework visual
      and a SO WHAT banner; content area spans at least 2/3 of the canvas.
- [ ] Bullets carry evidence row ids; under-chart notes do not duplicate the
      footer source line.
## 5. Text-only completion checklist

- [ ] Every figure spec states `core_claim`, `visual_intent`, relationship, and
      exact source fields.
- [ ] The rendered manifest records the actual inferred chart type.
- [ ] The figure portfolio passes type diversity, font, palette, overlap, SVG,
      PNG, and hash checks.
- [ ] Word figure styles and direct paragraphs both pass the single-spacing
      contract; rendered pages show full charts.
- [ ] Every slide has question, answer-first title, evidence, SO WHAT, and
      layout family in `evidence_map.json`.
- [ ] Four or more slide layout families are present, with no three-page repeat.
- [ ] Body slides meet the §6 density contract (three-column layout, evidence-bound bullets).
- [ ] Core content is editable and the rendered PPT has no overlap or overflow.
