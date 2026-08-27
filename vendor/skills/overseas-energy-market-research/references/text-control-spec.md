# Text Control Spec (Pre-flight, Not Post-hoc)

Hard rule learned from production: **text overflow and label overlap must be
prevented at write time, not detected and patched after rendering.**  Every
`<text>` in a slide SVG and every label in a chart is written knowing the
available width.  This file is the contract.

## 1. PPT slide SVG — write-time width budget

Before emitting any `<text>`, compute its containing card:

- Cards are `<rect>` elements with `height > 30` and `width > 20`, **plus**
  the rounded-rectangle `<path d="M x0,y0 H x1 A r,r ... V y1 ...">` form
  produced by `finalize_svg.py` — parse the FULL `d` attribute (`x0/y0`
  from `M`, `x1` from the first `H`, `y1` from the first `V`) so real card
  bounds are used. Decorative hairline dividers (real height ≤ 30) and
  vertical accent bars (width ≤ 20) must be EXCLUDED — a wrong height
  fallback resurrects them as phantom cards whose narrow right edge shreds
  body text into 4-6 char fragments.
- A text belongs to the card whose
  `x0-5 <= text.x <= x1+5` and `card.y0-5 <= text.y <= bottom+10`.
- Available width = `card.x1 - text.x - 4` (4px right padding).
- Estimate text width with the CJK-aware formula
  (`chart_polish.text_width`): CJK ≈ 1.0em, latin/digit ≈ 0.55em
  (serif/Georgia ≈ 0.62em — Georgia digits/M/W render notably wider),
  space ≈ 0.32em.
- **Free-standing text** (titles, footers, cover lines — no card hit): the
  boundary is the 1280 canvas right edge; `x + width > 1284` fails.

Write-time rules:

1. **Body text (font-size ≥ 10)**: if the estimated width exceeds the card
   width, split into multiple **independent `<text>` elements** (one per
   line — `svg_to_pptx` does not support `<tspan>`) **before writing** —
   first line at the original `x`/`y`, subsequent lines `y += font-size *
   1.45`. Break at **atomic token boundaries**: numeric runs with trailing
   units ("351.6 MWh", "2026–2030", "891 MWh") and latin words are NEVER
   split; CJK chars pack one per token; closing punctuation (，。；：、）】）
   must not start a line. If a multi-line block grows downward, shift any
   element below it down so the last line keeps ≥ 1.2em clearance.
2. **Titles / KPI numbers** (Georgia or font-size ≥ 25): keep single-line;
   shorten the wording so it fits (prefer dropping adjectives over breaking
   the number). Never let the auto-wrap split a KPI figure.
3. **Page numbers (`text-anchor="end"`)**: keep right-aligned, never wrap.
4. **Continuation lines** keep the same `x` (flush-left); do not indent.

Verification gate (mandatory before export):

```
python scripts/wrap_slide_text.py --project-dir <project> --check
```

Exit 0 = no overflow (pass); exit 1 = overflow exists (block export, fix at
source, do not rely on the auto-wrap to paper over it). The gate validates
card-bound text AND free-standing canvas overflow, with the serif-aware
width estimate.

The same script without `--check` performs the mechanical wrap as a
*fallback* for legacy decks, but a new deck must pass `--check` before
`finalize_svg.py`.

## 1b. Renderer reflow protection (svg_to_pptx)

LibreOffice ignores `spAutoFit` and wraps text at the frame width, while
the 0.55em estimate under-measures serif fonts — a tight frame splits
single-line KPI numbers ("540 MWh" → "540"/"MWh") at render time.

- Single-line text frames get **1.5× width headroom** (multi-line
  paragraphs 1.3×) — PowerPoint (`wrap="none"` + `spAutoFit`) is
  unaffected; LibreOffice gets room to render the line un-wrapped.
- Text frames are **clamped inside the canvas** (off_x ≥ 0, off_x + cx ≤
  1280) so end-anchored footers with inflated frames never land past the
  slide edge.

## 1c. Render-geometry gate (mandatory before registration)

The SVG gate validates the *model*; the renderer can still rewrap or
misplace text. After export and before
`register_high_fidelity_ppt_delivery.py`, run:

```
python scripts/verify_ppt_render_geometry.py --project-dir <project>
```

It renders the final PPTX to PDF (LibreOffice headless; pass `--pdf` to
skip re-rendering) and extracts span-level text geometry with PyMuPDF:

- **Text-text overlap** > 3pt × 3pt on any page → fail
  (catches wrapped blocks growing into the element below, e.g. a 4th body
  line colliding with "详见第 X 页" links).
- **Canvas boundary**: span right edge > 962pt (1280px + 2pt slop) or left
  edge < -2pt → fail (catches right-edge frames clipped past the slide).

Exit 0 = clean; 1 = blocking issues (fix at the SVG write source — shorten
wording, shift elements down, widen frames — never patch the render).

## 2. Chart labels — truncate before placing

matplotlib places labels with fixed offsets and never measures them, so
overlap is guaranteed on crowded panels unless the label text is sized to
its space.

Rules:

1. **Data labels** (bar/line/scatter): use `chart_polish.place_bar_labels`
   (collision boxes + alternating offsets).  Additionally, prefer short
   labels: for scatter positioning use brand short names ("Huawei LUNA",
   "Tesla PW3", "BYD HVS") instead of full model codes.
2. **Narrow panels**: truncate any label whose estimated width exceeds its
   available space with `chart_polish.fit_label(text, max_px, font_size)`
   before calling `annotate`/`text`.  This is the pre-flight control — never
   render a label you know will collide.
3. **Legend / axis titles**: keep ≤ 12 chars; on narrow charts drop the
   y-axis title when the figure title already carries the semantics.
4. **Heatmap cell labels**: use 1-2 digit values; row labels shortened to
   the brand name; `tick_params(axis="y", pad=16)` so labels never touch the
   first data cell.

## 3. Where the width numbers come from

| Element | Width source |
| ------- | ------------ |
| Slide card text | card right edge minus text x (SVG coordinate space) |
| Chart data labels | axis data area (after `ax.set_xlim` margins) |
| Chart axis titles | `FIGURE_SIZES["standard"]` width ≈ 9.5 in @ 300 dpi |
| Heatmap cell | cell width minus padding (imshow grid) |

## 4. Regression checklist

- [ ] `wrap_slide_text.py --check` passes before every PPT export
- [ ] Every chart label was truncated with `fit_label` where the estimate
      exceeded space (or used short-name mapping)
- [ ] No `<text>` written longer than its card in a fresh SVG
- [ ] `place_bar_labels` used for all bar/line data labels
