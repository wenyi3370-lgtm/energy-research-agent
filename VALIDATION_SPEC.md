# Validation specification

## 1. Validation model

Validators emit machine-readable findings:

```yaml
finding_id: FIND-...
validator: SchemaValidator|EvidenceValidator|SourceURLValidator|ImageValidator|ConsistencyValidator|ArtifactValidator|RenderingValidator
severity: INFO|WARNING|ERROR|BLOCKER
code: string
message: string
record_ids: [string]
artifact_ids: [string]
expected: any|null
actual: any|null
remediation: string
```

Aggregate status:

- `PASS`: no warning/error/blocker remains.
- `PASS_WITH_WARNINGS`: no error/blocker; warnings are explicit and non-misleading.
- `BLOCKED`: any blocker, or an error in a required artifact/core fact.

## 2. Validation stages

### `SchemaValidator`

- Validate all Pydantic/JSON Schema records and enum values.
- Validate stable ID format and referential integrity.
- Enforce `null` rather than missing placeholders in data.
- Validate units, dates, confidence range and schema version.
- Reject orphan claims/sources/images and duplicate IDs.

### `EvidenceValidator`

- Enforce source thresholds for core fields.
- Confirm raw/context text and source locator are present.
- Detect unsupported core claims and snippet-only evidence.
- Confirm analysis statements carry evidence IDs or explicit inference labels.
- Check large-group coverage wording and member evidence.
- Require a verified `product_catalog_scope` for any complete-product claim; compare its catalog items with product records and retain unmatched items as gaps.
- Warn when products exist but only family-level names were captured despite official model/parameter pages, or when no product carries parameters.
- Block company identity below configured confidence.
- Require the three-round saturation audit for every scoped goal. Quantity floors alone do not satisfy completeness.
- Block a `SATURATED`/complete label when critical gaps, unexpanded high-priority discoveries, missing raw captures or insufficient independent-source verification remain.

### `SourceURLValidator`

- Recheck canonical URL, redirect, status, content type and domain.
- Detect domain/title mismatch and link rot.
- Compare retrieved content hashes when revalidation is required.
- Block dead key URLs unless an allowed authoritative archive exists.

### `ImageValidator`

- Verify type, dimensions, decode, hash and perceptual duplicate status.
- Check entity/product association from page title, domain, alt and surrounding text.
- Reject thumbnails/placeholders and unrelated images.
- Confirm every formal-artifact image is `VERIFIED` and bound in the manifest.
- Resolve every formal product-image `local_asset_ref`; require the file to exist within the run/package boundary and recheck its SHA-256, MIME type, decoded dimensions and size ceiling.
- Require 100% archived-image coverage across displayed products. URL/hash metadata without a validated local binary is evidence-only and cannot pass the artifact gate.
- Emit `BLOCKED_MISSING_REQUIRED_IMAGE` for an unmet required image policy.

### `ConsistencyValidator`

- Compare canonical company/subsidiary/factory/product names across records.
- Compare values, units, dates, scope and display rounding across artifacts.
- Verify source/image/chart IDs map to the same frozen record.
- Confirm no artifact contains a claim absent from the manifest.
- Detect stale outputs generated from a prior freeze.

### `ArtifactValidator`

- Excel: required sheets, table headers, numeric cell types, URLs and ID columns.
- Word: narrative-driven chapters (only chapters whose evidence gate passed), Heading 1-2 TOC field, captions, page fields and source mapping. Research density and the 50% facts / 35% insights / 15% constraints target supersede fixed character/page minimums. Require diagram-design figures with adjacent source notes, three-line tables, `visual_manifest.json`, and HTML+SVG+PNG siblings for every emitted figure. Insufficient data degrades to table/KPI/prose. Each Word PNG must be a direct rasterization of the same diagram-design HTML whose SVG is inlined by HTML; separately redrawn Word charts and dual-logic charting are blocking defects. When verified real images are selected, require all three image manifests, exact binary revalidation, an embedded image for every selected ID, and a caption/source pair for every non-cover image.
- Enterprise HTML: Enterprise Research Dashboard contract (one judgement, 3–6 KPI, 1–3 visuals and three insights per chapter), embedded data, company header, collapsed source ledger and no network-critical dependencies.
- Product HTML: generation route, 2-4 comparison, `—` for nulls and verified images.
- Product HTML additionally requires verified locally archived images in cards, detail and comparison views, plus no network-critical image dependency.
- PPT: 15-20 slides, required storyline/evidence map, answer-first titles, visual on every slide, at least four layout families, no three consecutive identical layouts, source/date/bias footer, no overflow flags, no wrapped KPI units/page numbers, no chart text below 8 pt and no overlap/escape above 3 pt. When evidence images are contracted, require every selected image to be embedded in its mapped chapter with caption and original-page source while retaining the page's chart/framework.

### `RenderingValidator`

- Render Word to PDF through LibreOffice/Word and inspect key pages.
- Inspect every rendered Word page, including caption/table pagination; page count is descriptive rather than a quality proxy.
- Render HTML at desktop/tablet/mobile, exercise keyboard interactions and capture console errors.
- Render PPT slides and detect text/image overflow, clipping and low contrast.
- Require pre-finalization token-aware SVG wrapping and post-export LibreOffice/PyMuPDF geometry inspection.
- Require a PPT contact sheet, all-slide visual inspection and at least one fix followed by full-deck rerender.
- Check broken image/font/resource links and standalone local opening.
- Use targeted visual/golden snapshots with tolerance; do not equate pixel identity with correctness.

## 3. Severity policy

Immediate blockers include:

- unresolved company identity;
- unsupported core number used as fact;
- unresolved core product parameter conflict;
- unverified required company/factory/product image;
- formal product HTML containing a remote-only, missing, undecodable or checksum-mismatched product image, or less than 100% displayed-product archived-image coverage;
- broken key URL without acceptable preserved evidence;
- false “all subsidiaries” assertion;
- publisher-originated fact absent from the freeze;
- cross-artifact disagreement for the same claim;
- hand-written/static Word TOC masquerading as automatic;
- product dashboard generated without qualifying products;
- PPT outside 15-20 slides;
- unresolved high-severity fifth-round coverage gap, including missing 3-year financial series or required five-product image coverage;
- Dashboard chapter outside the 1 judgement / 3–6 KPI / 1–3 visual / 3 insight contract;
- large-enterprise Dashboard with fewer than eight meaningful visuals, or a multi-base enterprise without a map;
- any fifth-round zero-tolerance phrase in the complete offline HTML payload;
- any formal publisher QA report with `status: fail`;
- Word with a missing visual manifest, missing HTML/SVG/PNG siblings, missing figure source notes, grid tables, or a figure whose frozen data fails the Visual Router's data-sufficiency checks for the routed diagram-design type;
- Word/PPT with a selected verified image missing from the package, a binary/hash/MIME/dimension mismatch, a remote-only image, a missing image caption/source, or an image used to replace a required chart;
- PPT delivered without all-slide render inspection or the required fix/full-rerender cycle;
- PPT without storyline/evidence map, with three consecutive identical layouts, wrapped KPI/page tokens, chart text below 8 pt or geometry overlap/escape above 3 pt;
- missing same-stem Word PDF or `<deck.pptx>.quality.json` on a non-fixture formal release;
- inaccessible or non-opening required HTML.

Warnings may include disclosed non-critical gaps, optional image absence, low-priority stale context, or accepted render variations that do not impair use.

## 4. Test pyramid

### Unit tests

- ID generation and parsing;
- schema validators and enum transitions;
- routing thresholds from YAML;
- query deduplication and budgets;
- source grading and independence;
- conflict grouping/resolution;
- image hash/dimension/type checks;
- freeze mutation rejection and root hash;
- artifact binding and skip logic.

### Integration tests

- LangGraph routes and checkpoint resume;
- gateway primary/fallback behavior;
- adapter contract tests using recorded fixtures;
- embedded Skill manifest verification and required-resource tests;
- SQLite/PostgreSQL parity for core queries;
- source/image validation pipelines;
- each publisher from a frozen fixture;
- LibreOffice/Playwright rendering.

### Golden tests

Maintain three curated frozen datasets:

- large state-owned/group enterprise;
- normal manufacturing enterprise;
- small/simple enterprise.

Golden comparisons cover structure, IDs, required sections/sheets/slides, selected text, charts and key visual snapshots. Update golden files only through reviewed changes.

## 5. End-to-end acceptance scenarios

At least these 24 scenarios must pass:

1. Exact large group name resolves and routes to `GROUP_LARGE`.
2. Short ambiguous brand name stops at human review with ranked candidates.
3. Normal manufacturer routes to `ENTERPRISE_NORMAL` and performs bounded subsidiary research.
4. Small enterprise routes to `SMALL_SIMPLE` and skips deep group work.
5. Initially unknown entity performs bounded research and reclassifies without legal-size claims.
6. Large group discovers multiple levels while enforcing recursion/entity budgets.
7. Incomplete public roster uses “本次公开资料共识别…” and never “全部”.
8. Two subsidiaries with similar names remain distinct entities.
9. A physical-product manufacturer generates the product dashboard.
10. A service-only enterprise emits `SKIP_PRODUCT_DASHBOARD` and no product HTML file.
11. A product with missing parameters displays `—` and no invented values.
12. Conflicting revenue figures with different scopes coexist with explanation.
13. Unresolved same-scope core revenue conflict blocks definitive use and release.
14. A search snippet cannot validate employee count or revenue.
15. One A-level official source validates a core fact.
16. Two independent B-level sources validate a core fact; two syndicated copies do not.
17. A dead key URL at pre-freeze validation blocks unless an allowed authoritative archive is retained.
18. A search thumbnail/foreign-company factory photo is rejected.
19. A verified official logo and factory image retain source/image IDs in all artifacts.
20. Missing required verified image yields `BLOCKED_MISSING_REQUIRED_IMAGE`, not generated imagery.
21. Missing company energy data produces `requires_on_site_due_diligence`, not industry averages as facts.
22. Storage ODM output separates evidence, inference and to-be-confirmed specifications.
23. Excel source rows and Word Appendix B resolve to identical source IDs/URLs.
24. Word contains a real TOC field, Heading 1-3, page numbers and renderable cross-page tables.
25. Enterprise HTML opens offline, uses the company-style header and passes 360/768/1440 layouts.
26. Product HTML supports search, category, sorting, detail, zoom and 2-4 verified-product comparison.
27. PPT contains 15-20 slides, defaults to 17 and compresses large groups into matrices.
28. A publisher attempts to introduce an unbound fact and is rejected.
29. A changed fact after freeze forces a new freeze and regeneration of dependent artifacts.
30. A node interruption resumes from checkpoint without duplicate evidence IDs.
31. Exhausted research budget ends with explicit gaps/warnings or blocking status, not an infinite loop.
32. DeepSeek provider failure uses configured OpenAI fallback; schema failure does not trigger silent factual fallback.
33. A missing/unauthenticated search adapter fails preflight with an actionable diagnostic.
34. Every trusted file under `vendor/skills/` matches `vendor/manifest.json`; missing or modified embedded resources block release.
35. The trusted vendor manifest and distributable archive contain no cookies, login profiles, browser state, cache databases, job histories, virtual environments, Git metadata, compiled caches, or unredacted configuration secrets.
34. Cross-artifact numeric, unit, date or name drift is detected before packaging.
35. Same freeze/config produces stable exports and package checksums except declared nondeterministic metadata.
36. Final package includes manifests, validation reports and checksums; a blocked package is clearly non-final.
37. A product manufacturer with only sampled product families emits `PARTIAL` coverage and open product gaps, never a “complete product catalog” claim.
38. An enumerated subsidiary product center expands families into disclosed models/SKUs and preserves per-parameter source evidence.
39. Verified image URLs and hashes without local binaries block formal product HTML; exact archived binaries with matching hash/MIME/dimensions render offline in cards, detail and comparison views.
40. An AnySearch Python transport failure caused by system proxy settings records redacted diagnostics and recovers through the bundled Node.js runtime; only failure of every available bundled runtime declares the adapter unavailable.

## 6. Validation reports

Generate:

- `validation_report.json`: summary, counts, status, findings, validator versions, tested artifacts and timestamps;
- `validation_report.md`: executive summary, blocking items, warnings, coverage, artifact table, traceability samples and remediation actions.

Both reports must state the `run_id`, `freeze_id`, schema/config hashes and artifact content hashes.

## 7. Release decision

Release only when:

- every required validator ran successfully;
- no blocker/error remains;
- artifacts match the current freeze and manifest;
- rendering is usable;
- warnings, if any, are disclosed and do not invalidate executive conclusions.

## 8. P0 consulting and browser validators

- `ConsultingNarrativeValidator`: runs the 20 decision-narrative checks, including evidence-adjusted executive/body length, conclusion-first depth, opportunity completeness, duplicate removal and cross-render consistency.
- `VisualSemanticValidator`: validates visual claim fields against the declared semantic domain; manufacturing capacity cannot enter an energy visual.
- `PublicationVisibleTextValidator`: scans rendered/visible Word and HTML text for raw enums, snake_case fields and database headers.
- `SourceOwnershipValidator`: rejects a body source chapter and requires `appendices.source_ledger`.
- `TOCValidator`: requires TOC field plus `updateFields`, and rejects visible placeholder text after the LibreOffice refresh/fallback cycle.
- `WordLengthValidator`: returns `insufficient analytical evidence` when the scoped body gate is unmet; it never permits padding.
- `BrowserExecutionValidator`: enforces a 1–4 worker ceiling, zero active pages at completion and opened/closed lifecycle equality.

The recorded regression suite maps TEST 1–24 in `tests/test_p0_second_round.py`. Formal release additionally requires a real-company regeneration, DOCX → LibreOffice → PDF → per-page PNG inspection, and HTML renders at 1366×768, 1920×1080 and 390×844.

## DecisionIntelligenceValidator

Formal Word/HTML publication is fail-closed on: process-language ratio >=5%; gap narrative >=10% (>=5% for large listed enterprises); a missing strategic trajectory despite three complete comparable years; competition output without comparable evidence; a priority hypothesis missing Need/Why Now/client capability/value logic/target department/disconfirming conditions; priority based on UNKNOWN client capability; generic pre-feasibility service wording; or an executive summary that does not answer the five management questions. Enterprise-specific chapter ratio >70% is tracked as a release target. Regression ownership is `tests/test_p0_decision_intelligence.py` plus existing Word/HTML shared-narrative tests.
