# Cover Compliance Audit (Path B Light-Consulting Fallback)

## Context

When the EWO image provider is unavailable, the presentation pipeline
records `cover_path_decision.path_taken = "B_light_consulting"` with a
normalized fallback reason.  The final validator
(`validate_deliverables.py`) only checks the boolean
`cover_prompt_compliance` in the production manifest — it does **not**
inspect the actual cover SVG.  Without a real audit this boolean can drift
from the actual cover design (e.g. a deep-navy Path-A-style cover recorded
as compliant Path B).

## Mandatory step

Run **`scripts/audit_cover_compliance.py --project-dir <project>`** after
the cover SVG is written and **before**
`scripts/register_high_fidelity_ppt_delivery.py`.  It:

1. Parses the cover SVG (`presentation_project/svg_output/slide_01_cover.svg`
   by default).
2. Checks the Path B light-consulting spec (see below).
3. Writes `cover_compliance_audit` into
   `presentation_project/image_acquisition_manifest.json`.
4. Exits 0 on pass, 1 on any failed check (blocking).

`register_high_fidelity_ppt_delivery.py` reads
`cover_compliance_audit.status == "passed"` into
`cover_prompt_compliance` — it must never hard-code `True`.

## Path B spec (light consulting, per AGENTS.md global preference)

| Check | Rule |
| ----- | ---- |
| `white_background` | root `<rect>` is `#FFFFFF` (pure white) |
| `no_navy_gradient_background` | no deep-navy cover gradient (that belongs to Path A) |
| `royal_blue_ribbon` | left-side royal-blue ribbon (`#123A7A` or `#1B365D`) |
| `serif_title` | main title uses Georgia/SimSun at 45–59pt |
| `conclusion_bar` | a filled conclusion/action bar under the title |
| `meta_columns` | ≥3 meta column labels (研究对象/日期/版本 etc.) |
| `footer` | footer contains "数据来源" + date |
| `no_illustration` | **zero illustration residue** — no energy-flow scene, sun/clouds (`FBBF24`/`sunGlow`), panels, storage cabinets, grid towers, labels like 光伏/自用/储能/电网, and no `<g transform="translate(x≥500, …)>` right-side illustration group. A leftover scene renders half-clipped ("自用" becomes a lone "自" at the slide edge) — the audit must catch it |

This matches the McKinsey-style consulting cover: white background, black
body text, deep royal-blue emphasis, serif title + sans-serif body,
conclusion-first action titles. **Path B means NO images at all** — when
EWO is unreachable the cover is pure white consulting style with no
illustration whatsoever (per AGENTS.md and the user's explicit rule).

## When Path A is used instead

If `path_taken = "A_ai_image"`, the validator independently checks that the
registered AI cover image exists, is a PNG/JPEG/WebP raster, and its sha256
matches.  `cover_compliance_audit` is only meaningful for the Path B
fallback.

## Regression checklist

- [ ] `audit_cover_compliance.py` exits 0 before registration
- [ ] `image_acquisition_manifest.json` contains `cover_compliance_audit`
      with `status: passed`
- [ ] production manifest `cover_prompt_compliance` is `true` **and** traces
      to the audit (not a hard-coded literal)
- [ ] the cover is visually confirmed (white consulting cover, not navy)
