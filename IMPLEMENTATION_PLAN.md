# Enterprise Energy Research v0.9.0 implementation status

`pyproject.toml` is the single version source. Work is organized by quality gates rather than historical phase numbers.

## P0 — evidence correctness and saturation

- AnySearch JSON and Markdown parsing paths are reachable and covered by regression tests.
- Research requests decompose into enterprise Goal Families.
- R1 performs official-source coverage; R2 accepts Evidence Gap records; R3 accepts ConflictGroup/critical-claim targets.
- Saturation is evaluated per goal using completed rounds, two final low-yield batches, critical gaps, unexpanded discoveries and triangulation.
- `research_quality.json` exposes coverage, source, verification, catalog, parameter, image, gap, conflict and saturation metrics.

## P1 — formal publication

- Word retains the evidence-first report pipeline and raises the gate to 15 formal figures, five visual families for ten or more visuals, 45% maximum bar-family share and 100% core-chapter visual coverage.
- `visual_manifest.json` carries claim IDs, source IDs, analytical class and Word/HTML/PPT targets.
- `enterprise_research_dashboard.html` combines management overview, report visualization, company/factory gallery and product intelligence database in one offline file.
- Image discovery, evidence and publication manifests remain distinct; publication revalidates local binary hash, MIME and dimensions and deduplicates exact/perceptual matches.

## P2 — QA, eval and deployment

- Recorded research eval and a fixed five-company live-acceptance panel are versioned under `evals/`.
- CI runs unit/integration/fixture tests, automation eval, vendor verification, schema parsing and Docker build.
- HTML QA requires screenshots at 360/768/1440/1920 px; static inspection alone cannot pass.
- Word QA inspects rendered PDF for blank pages, oversized whitespace and clipped blocks.
- PostgreSQL production credentials must come from `.env`/secret injection; n8n uses a pinned image.

## Remaining acceptance condition

A formal release is complete only after a live company run produces all seven output directories and the research, visual, image, validation and cross-artifact reports pass. Adapter unavailability, missing credentials, missing benchmark binaries or unrendered Word/HTML artifacts must be reported as blockers, not converted to success.
