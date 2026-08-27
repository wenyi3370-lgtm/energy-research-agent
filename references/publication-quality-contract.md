# Publication quality contract

This is the current contract for formal Word and unified HTML delivery.

## Research coverage gate

- Listed and large enterprises require 3–5 comparable years of revenue,
  profit, gross margin, R&D and operating cash flow. Fewer than three periods
  must be described as operating change, never as a trend.
- Product research must bind official images, names, family/series, disclosed
  parameters, applications and source pages. When at least five verified
  products exist, formal publication requires at least five distinct products
  with pixel-verified official images.
- Manufacturing research must cover locations, regions, product/process
  mapping and at least one capacity disclosure. The body analyses the global
  layout and core bases; the full ledger belongs in the appendix.
- Enterprise own-energy consumption and enterprise energy-product/project
  capability are separate datasets and must never substitute for one another.
- Energy metrics require a numeric value and a field-compatible unit. Years in
  document titles or target statements are metadata, not consumption values.
- An unresolved high-severity coverage gap triggers targeted retry and blocks
  formal publication. Missing data is never replaced with generic prose.

## Enterprise Research Dashboard

- The hero contains at most six KPIs.
- Every chapter contains one core judgement, 3–6 evidence-backed KPIs, 1–3
  meaningful visuals and exactly three concise insights. Full prose, tables and
  ledgers are collapsed by default.
- Large-enterprise dashboards require at least eight meaningful visuals; a
  multi-base enterprise requires at least one geographic distribution map.
- The product showcase contains 4–8 key products with image, parameters and
  application context. Products without a formal image stay in the collapsed
  ledger and never render as placeholder cards.
- Visible text is at least 50% shorter than the corresponding full narrative;
  no default-view analysis block exceeds 500 uninterrupted characters.
- The following exact phrases have zero tolerance in HTML: `基于当前冻结公开事实`,
  `证据边界`, `本节判断由`, `该信息用于判断`, `不能替代`, `不足以证明`,
  `后续需要验证`.
- The complete Word/HTML publication payload must use ordinary business
  language. Internal reasoning-framework recitals, symmetric “A answers X / B
  answers Y” prose, self-defensive negatives and abstract gate chains are not
  acceptable published analysis. State the company fact, the proposed contact,
  the specific task and the proceed/stop condition directly.

## Word report

- The executive summary leads with positioning, core operating data, product
  capability, manufacturing layout, cooperation directions and constraints.
- The table of contents includes heading levels 1–2 and page numbers only;
  entries are independent left-aligned paragraphs without manual line breaks.
- A field code without materialized visible entries is treated as a missing
  table of contents. Final render QA requires the visible entries and their
  page numbers, not merely `updateFields=true` in OOXML.
- The target body mix is 50% facts/data, 35% analysis/insight and 15%
  constraints/limitations. Formal publication requires at least 3,500 Chinese
  characters for the thin-evidence tier and the higher evidence-adjusted gate
  for a full-evidence report. The count must be reached through enterprise-
  specific facts, comparable periods/scopes, source and disclosure analysis,
  market implications, counter-evidence and executable recommendations; a
  generic chapter recap, research-process narration or repeated framework
  sentence is a release blocker even when the count is reached.
- The key-product section pairs 4–8 official images with series/model,
  applications, disclosed parameters and sources.
- Every paragraph that contains an inline image must override the body style's
  fixed leading with automatic single-line spacing (`lineRule=auto`, one line).
  A rendered image clipped to a narrow strip is a release blocker even when
  the embedded binary has valid dimensions.
- Portrait report tables must have at most four visible columns. Prose-heavy
  six-column schemas are compacted in the Word projection; the complete
  source/product/due-diligence ledgers remain available in appendices.

## Portable source gate

- Incident fixes must live under `src/`, reusable `scripts/`, documentation
  and tests. Editing only a generated artifact or a run-specific database is
  never accepted as a fix.
- The production and deep-retry image paths must reuse one bounded handoff:
  URL de-duplication, page/candidate caps, concurrent bounded downloads and
  vision calls, canonical-entity ownership, normalized hostnames and exact
  product-ID binding.
- Shared catalog pages may not assign all images to the first/random product.
  A page-level product key is allowed only when the page belongs to exactly
  one verified product; otherwise the product name must be present in that
  image card's DOM context.
- Direct networking is the default. A proxy is process-local and opt-in via
  `ERA_OUTBOUND_PROXY`; loopback browser control must bypass it. No source file
  may contain a developer-machine absolute path or bundled secret.
- A portable release requires the full regression suite, vendor-manifest
  verification, package/archive creation and Word render inspection.

## Visual opportunity planner

The planner may route real data to line, area, dual-axis, Sankey, stacked,
treemap, parameter matrix, real-score radar, bubble, map, heatmap, timeline,
Gantt, network and business matrices. It must not invent scores, flows,
coordinates or time periods. Administrative centroids may be used for regional
distribution only when explicitly labelled as approximate.

## Fail-closed acceptance

Any error-level research coverage, publication QA, product-image, map, visual
count, boilerplate or rendered-layout finding makes the artifact result
`failed`; the production run cannot report `COMPLETED`.

Continuation research is subject to the same gate. It must load the newest
cumulative fixed evidence store, re-run entity mapping and verification,
recompute coverage after collection, and then enter the normal freeze and
publisher QA path. A private freeze/publish helper is never a bypass. Claims
from customers, suppliers, competitors or other new-energy companies may stay
in the evidence ledger but cannot populate the canonical enterprise's KPI,
financial series, product/factory count or coverage result.
