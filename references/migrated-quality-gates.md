# Migrated Quality Gates

These rules are adapted from `overseas-energy-market-research` for enterprise-level company, factory, product and energy-cooperation research. They are mandatory unless the user explicitly requests a concise/draft artifact. Country-specific, marketplace-specific and residential-storage-specific quotas were intentionally not copied.

## 1. Data saturation

Every scoped goal must complete `R1 coverage`, `R2 depth` and `R3 triangulation`. The authoritative policy is `config/collection_saturation_policy.yaml`. Numeric floors are minimum execution evidence, never a stopping target.

Research may be labeled `SATURATED` only when all conditions hold:

- every scoped goal has R1/R2/R3 evidence;
- the attempt journal and raw capture references are complete;
- critical claims meet source independence rules;
- no critical gap remains unresolved;
- no high-priority discovery is left unexpanded;
- the last two query batches produced no new high-priority records;
- marginal high-priority discovery yield is at or below 5%.

Budget exhaustion is not saturation. If the budget is exhausted with missing rounds or critical gaps, the run is `BLOCKED`; with only disclosed non-critical gaps it can be `PARTIAL`/`PASS_WITH_WARNINGS`, but never “complete”.

An evidence-gap exception must include all three attempted rounds, queries, sources, failure reasons, raw captures, zero remaining high-priority discoveries, decision impact, resolution path, owner, status, source context and named approval. Narrative “not found” statements do not satisfy this gate.

## 2. Word depth and pagination

The default formal report profile is:

- 15,000–30,000 Chinese characters;
- at least 30 rendered pages;
- the full chapter structure in `ARTIFACT_SPEC.md`;
- 4–6 substantive analytical paragraphs per core chapter, generally 200–350 Chinese characters each;
- at least 50 characters of analysis after every Heading 1/2 and before its first figure/table;
- at least one decision-useful figure/table per core chapter, using traceable data or an explicitly labeled framework/process diagram;
- real TOC and PAGE fields, unique figure/table numbers, captions kept with their objects and every visual cited in the text;
- table/figure source notes use `数据来源：` consistently.

The user may explicitly request `concise_report`; otherwise a short draft cannot pass the formal delivery gate. Render through the bounded LibreOffice path and inspect every page.

Run:

```powershell
python scripts/validate_delivery_quality.py --docx <report.docx> --pdf <rendered-report.pdf>
```

## 3. PPT visual quality

The formal route is the embedded PPT Master SVG pipeline; a quick Python-native deck is a draft fallback and is not quality-equivalent.

Before page production, create the storyline, evidence map, `design_spec.md` and `spec_lock.md`. Every substantive slide uses an answer-first conclusion title and contains at least one decision-useful visual. Reuse verified Word charts/product/factory images first; use slide-native editable SVG for frameworks. Never use AI imagery as a substitute for product, factory or data evidence.

Visual system:

- cover: deep navy-purple technology identity with left text/right verified hero image; approved light typographic fallback only when image acquisition is unavailable;
- body: white consulting canvas, black text, thin rules, restrained SEVC purple/cobalt/cool gray accents;
- at least four layout families; no layout family on three consecutive slides;
- no text-only slides, repetitive large-round-card grids, emoji, decorative colored icons or low-density filler;
- every substantive slide shows source, update date and bias/assumption context;
- KPI values and units remain on one line; page numbers, badges and short labels must never wrap;
- all text must remain above the footer safe zone and pass overflow/clipping/contrast checks.

Quality registration requires 15–20 slides, all-slide renders, a contact sheet, actual inspection of every slide, at least one visual fix followed by a full-deck rerender, and zero unresolved overflow, clipping, placeholder or source-binding defects.

Use `validation.delivery_quality.inspect_ppt_visual_delivery()` as the record-level mechanical gate and the embedded PPT Master checker/finalizer/exporter for file-level validation.

For release, save the record next to the deck as `<deck.pptx>.quality.json`. The release auditor loads this sidecar automatically. Word release similarly requires a same-stem rendered PDF next to the DOCX.

## 4. Product-image completion

Product-image saturation is measured at four distinct layers: discovered URL, provenance-verified evidence, locally archived binary and artifact-rendered image. Counts at an earlier layer cannot be reported as completion at a later layer.

A formal product dashboard passes only when every displayed product has a locally archived, decodable image whose SHA-256, MIME type and dimensions match the verified image ledger, and the standalone HTML renders those bytes without network access. Remote URLs remain provenance links only. Any remote-only image, placeholder, broken decode, checksum mismatch or less than 100% displayed-product coverage is a release blocker.
