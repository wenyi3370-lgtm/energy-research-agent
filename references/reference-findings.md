# Reference material findings

## Purpose

Use these findings when implementing publishers. They summarize the supplied Word report and three standalone HTML examples without copying their embedded data or imagery.

## Word report baseline

The supplied 普什 report establishes these reusable patterns:

- Place an important-use disclaimer before the executive summary.
- Use a real Word TOC field (`TOC \\o "1-3" \\h \\z \\u`) backed by Heading 1-3 styles.
- Move from company overview to industries/products, entity-by-entity analysis, energy opportunities, implementation priorities, risk boundaries, conclusion, and appendices.
- Give each researched subsidiary a repeatable section: profile, products/process/equipment, verified imagery, energy characteristics, and EPC/efficiency opportunities.
- Use structured tables for timelines, entity facts, energy potential, business modes, priorities, and risks.
- Number figures and cite their source. Keep source and image appendices.
- Retain explicit boundary language where data is estimated, public-source coverage is incomplete, or on-site due diligence is required.
- Use page numbers in the footer and refresh fields through LibreOffice/Word before release.

The final report specification expands this baseline to EPC, zero carbon, storage ODM, overseas cooperation, a 90-day plan, data gaps, and claim/image IDs.

## Enterprise dashboard baseline

The supplied 普什 cooperation dashboard uses:

- Deep navy industrial canvas (`#0b1120`, `#0f172a`, `#14233f`).
- Cyan data accent (`#38bdf8`) for active navigation, block titles, and KPI values.
- Persistent left navigation for multiple analysis dimensions.
- Compact KPI cards, opportunity cards, priority badges, matrices, and a 90-day route.

Retain the dense, executive-data character but improve accessibility, responsive behavior, semantic markup, source tracing, and empty-state handling.

## Product dashboard baseline

The supplied product dashboard uses:

- Dark navy-to-teal hero, light content canvas, strong cyan/green accents.
- Sticky search/filter/sort controls.
- Product cards with real embedded images, category and evidence badges, key metrics, detail modal, zoom, and 2-4 product comparison.
- Missing parameters displayed as `—`, never invented.
- Single-file offline delivery with print rules.

Retain these interaction patterns for verified physical products only.

## SEVC/company header system

Use the supplied “动力电池大会-SEVC高价值伴手礼多维交互看板” as the primary header reference:

- Sticky 72 px top bar with a dark translucent brand surface and subtle bottom border.
- Left-aligned verified company/SEVC logo rendered in white when contrast permits.
- Two-line identity lockup: report/dashboard name plus organization name.
- Right-aligned section navigation on desktop; accessible menu on small screens.
- Large verified company/factory hero image with a controlled dark brand-gradient overlay.
- Eyebrow label, strong Chinese headline, short decision-oriented subtitle, and 1-2 primary actions.
- KPI cards overlap the lower hero edge to bridge brand storytelling and data analysis.

### Brand token policy

1. Extract logo and dominant colors from the verified official website.
2. Preserve contrast and cap brand color use at header/accent level; keep analytic surfaces neutral and industrial.
3. If extraction is unreliable, fall back to:
   - `--brand-primary: #6f2b86`
   - `--brand-secondary: #8b3fa3`
   - `--industrial-deep: #0b1120`
   - `--industrial-panel: #0f172a`
   - `--data-accent: #38bdf8`
   - `--energy-accent: #24a577`
   - `--warning: #f29b52`
4. Never use an unverified logo, fabricated factory hero, or decorative stock image implying company ownership.
5. If no verified hero image exists, use an abstract CSS energy-grid background and label imagery as unavailable; do not synthesize a company facility.

### Header acceptance checks

- Logo source resolves to a verified `image_id` and `source_id`.
- Organization and canonical company names match the frozen snapshot.
- WCAG contrast is at least 4.5:1 for normal text and 3:1 for large text.
- Navigation is keyboard accessible and has a visible focus state.
- At 360 px width, the identity remains readable and navigation does not overflow.
- Print output removes sticky behavior and preserves the company identity and report date.

