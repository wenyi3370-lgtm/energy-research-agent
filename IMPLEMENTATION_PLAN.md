# Implementation plan

## v0.8.1 verified image placement

Completed:

- Added a shared image publication pipeline for Word and PPT that revalidates archived SHA-256, MIME and decoded dimensions before producing offline publication PNGs.
- Added stable semantic routing for logos, entity/office, product, factory/production-line/location and certificate images.
- Word now inserts verified cover and chapter images with `图 N-Px` captions and exact original-page source notes while retaining every existing data chart/framework.
- PPT Master now receives local `image_placements` with role, fit, caption, source, and no-semantic-crop contracts; product/factory images supplement rather than replace each slide's required chart.
- Added release gates for selected-image coverage and caption/source coverage.

## v0.8.0 office visual production migration

Completed:

- Migrated and SEVC-adapted the Overseas Energy Market Research Word/PPT visual production rules.
- Added `config/office_visual_policy.yaml` and `references/office-visual-production.md` as blocking production contracts.
- Added a shared frozen-evidence `visual_manifest.json` generator with 300 DPI PNG and editable SVG output, 19 chapter/appendix visuals, real numeric KPI cards when verified numeric claims exist, and relationship-based fallback frameworks when they do not.
- Upgraded Word to A4 broker-research typography, exact 22 pt body leading, formal three-line tables, per-core-chapter visuals, captions and adjacent source notes.
- Upgraded the PPT brief to 17 complete slide contracts with action titles, questions, evidence themes, visual IDs, SO WHAT, layout families, claim/image bindings and source/date/bias footers.
- Added storyline/evidence-map files, token-aware SVG text checks, LibreOffice/PyMuPDF geometry verification, chart-font/overlap/wrap gates and full-rerender evidence requirements.
- Added regression tests for chart family quotas, dual PNG/SVG render, Word visual insertion, PPT contracts and protected token wrapping. Version 0.8.0 passes the complete recorded-fixture suite.

## v0.7.0 quality-gate migration

- Migrated three-round collection saturation from the overseas energy research pack into a company-research policy snapshot.
- Added mechanical saturation assessment, marginal-discovery stop logic, raw-capture obligations and budget-exhaustion fail-closed behavior.
- Added formal Word depth profiles and a DOCX/PDF delivery-depth validator.
- Strengthened the embedded PPT Master brief with answer-first, all-slide visual, layout-diversity, contact-sheet and fix/full-rerender requirements.
- Preserved the existing autonomous research path; human approval is limited to scope/policy upgrades and evidence-gap exceptions, while PPT Master's own visual confirmation gate remains intact.

## 1. Delivery policy

Develop in five gated phases. Keep the application executable at every implemented phase, but do not publish unvalidated business conclusions. Each gate requires passing tests and an explicit user approval before the next major phase.

## 2. Phase plan

### Phase 1 — architecture baseline (current)

Deliver:

- Skill entry and UI metadata;
- architecture, workflow, schema, source, artifact and validation specifications;
- complete planned repository tree;
- dependency rationale, risks, milestones and acceptance scenarios;
- reference Word/HTML findings, including the company-style HTML header.

Exit criteria:

- All requested planning documents exist and cross-reference consistently.
- Evidence First and Single Source of Truth are enforceable architecture constraints.
- No publisher has a direct search or model-research dependency.
- The Skill passes structural validation.
- User approves the architecture.

### Phase 2 — foundation and workflow skeleton (completed baseline)

Implement:

- Pydantic domain schemas and stable ID service;
- SQLite evidence store, Alembic migrations and JSON/JSONL exporters;
- immutable freeze service and artifact manifest schema;
- provider-neutral `ModelGateway` with DeepSeek primary/OpenAI fallback;
- adapter protocols and test doubles;
- LangGraph state, node interfaces, checkpointing and conditional route skeleton;
- configuration loading, structured logging and CLI.

Exit criteria:

- Unit tests cover IDs, schemas, migrations, freeze hashes and route decisions.
- A synthetic run traverses the graph without external research.
- Publishers can read a frozen fixture but cannot mutate evidence.

Implemented and verified in version `0.2.0`: strict domain models and generated JSON Schemas, SQLite append-only records, referential checks, immutable freeze/root hashes, deterministic exports, model/adapter ports, conditional LangGraph builder and synthetic runner. LangGraph and LiteLLM remain optional dependencies.

### Phase 3 — research, extraction and validation

Implement:

- company resolver and ambiguity gate;
- enterprise complexity classifier driven by YAML rules;
- bounded research planner and recursive group discovery;
- Kimi WebBridge and AnySearch adapters;
- page/source capture, claim extraction, entity mapping and product detection;
- image acquisition ledger, hashing, dedupe and authenticity gates;
- source grading, conflict groups, data-gap tracking and core-data thresholds;
- industrial/energy/four-solution analysis engines with evidence links.

Exit criteria:

- Integration tests use recorded fixtures, not live web calls.
- Every analysis statement carries evidence links or an inference label.
- Core unsupported claims and unverified required images block the freeze.
- Search budget, duplication and recursion limits are enforced.

Completed in version `0.3.0`: company resolver, ambiguity gate, complexity classifier, research planner/executor, approved adapter implementations, typed extraction/normalization, source and claim validation, core-conflict blocking, image validation, product routing, energy profiles, gap tracking and four evidence-linked solution engines. Recorded fixtures cover a large group, normal manufacturer, simple small enterprise, ambiguity, conflicts and adapter outages.

### Phase 4 — artifact publishers

Implement:

- Excel Master, PPT Master and frontend-design adapters;
- Word template publisher with Heading 1-3, TOC field, captions, sources and page numbers;
- enterprise dashboard with responsive company-style header and brand fallback;
- conditional product dashboard with search, filter, sort, detail, zoom and comparison;
- 15-20 page PPT planner and publisher;
- HTML asset embedding and offline-open verification.

Exit criteria:

- All artifacts consume the same freeze and manifest.
- No product HTML is created when `has_physical_products` is false.
- Word TOC is a real field and refreshes through LibreOffice/Word.
- PPT contains 15-20 slides; default is 17.
- HTML works as a standalone local file at 360, 768 and 1440 px widths.

Publisher boundary completed in version `0.4.0`: Excel Master workbook adapter, formal Word report with real TOC/PAGE fields, standalone enterprise dashboard, conditional interactive product dashboard, artifact dispatcher and deterministic 17-slide PPT Master brief. The Word fixture passed five-page PNG render inspection. Full PPT SVG generation/export and multi-viewport browser rendering remain Phase 4 execution gates before production release.

### Phase 5 — consistency, golden tests and release

Implement:

- artifact parsers for verification;
- cross-artifact claim/image/source comparison;
- visual/render validation for Word, HTML and PPT;
- deterministic package publisher and checksum manifest;
- golden fixtures for large group, normal manufacturer and simple small enterprise;
- failure injection, performance and resume tests.

Exit criteria:

- Required end-to-end scenarios pass.
- No critical cross-artifact mismatch remains.
- Package output is reproducible from the same freeze and configuration.
- Validation status is `PASS` or an explicitly approved `PASS_WITH_WARNINGS`.

Core release gate completed in version `0.5.0`: artifact parsers verify freeze provenance, publisher checksums and binding subsets for Excel, Word and HTML; release packaging uses deterministic ZIP metadata and is blocked after artifact tampering. Full PPT render consistency, document golden-image diffs and production performance/resume stress tests remain open before declaring a production release candidate.

Version `0.6.1` embeds complete portable snapshots from `C:\Users\Wenyi Zhang\.claude\skills`: Excel Master, PPT Master, frontend-design, Kimi WebBridge instructions, and AnySearch v3.0.1. Runtime adapters prefer these copies; the SHA-256 manifest, secret/runtime-state exclusions, direct AnySearch CLI health check, PPT tool-entry smoke checks, and vendor regression tests preserve capability quality. Search is restricted to AnySearch and Kimi WebBridge with no unapproved fallback. Kimi's daemon/extension, browser binaries, Office renderers, credentials, cookies and API keys remain explicit external runtime boundaries rather than unsafe bundled state.

Version `0.6.2` adds product-catalog completeness controls after live acceptance exposed family-level sampling. The planner separates product-center discovery, catalog enumeration, model extraction, parameter extraction, applications and launches. Product detection records verified scope, matched/unmatched items, model/parameter counts and coverage status; incomplete coverage creates explicit data gaps and a validation warning.

Version `0.7.1` closes two live acceptance gaps. `ImageAssetArchiver` now downloads exact verified product-image URLs, enforces size/type/decode checks, verifies SHA-256 and dimensions, writes deterministic local assets and requires 100% archived coverage before formal product HTML. The standalone dashboard embeds those bytes in cards, detail and comparison views. `AnySearchAdapter` now tries every available bundled runtime in deterministic order and recovers from a Python/system-proxy transport failure through Node.js, PowerShell or Bash while retaining redacted diagnostics and never switching to an unapproved search provider.

Version `0.7.2` makes the preferred AnySearch Python runtime self-recovering. It honors configured/system proxies first, but on an explicit `requests.ProxyError` retries the same `https://api.anysearch.com/mcp` endpoint once with process-local environment-proxy discovery disabled. This leaves the user's global proxy untouched, retains the Node/PowerShell/Bash fallback chain and introduces no additional search provider.

## 3. Work packages

| Work package | Depends on | Key output | Primary tests |
|---|---|---|---|
| Domain contracts | Phase 1 | Pydantic/JSON schemas | schema/enum/property tests |
| Evidence persistence | Contracts | transactional store + exports | migration/idempotency tests |
| Freeze/manifest | Evidence store | immutable version + bindings | mutation/hash tests |
| Gateway/adapters | Contracts | provider-neutral ports | contract/fallback tests |
| LangGraph skeleton | Store, ports | resumable state graph | route/checkpoint tests |
| Research pipeline | Search adapters | normalized evidence | fixture integration tests |
| Validators | Evidence models | findings and gates | adversarial fixture tests |
| Analysis engines | Validated evidence | evidence-linked conclusions | traceability tests |
| Publishers | Freeze/manifest | five artifact types | golden/render tests |
| Package/release | All publishers | final bundle | e2e/reproducibility tests |

## 4. Configuration strategy

Keep mutable policy outside code:

- `enterprise_rules.yaml`: routing signals, thresholds and confidence rules;
- `source_policy.yaml`: domain/source grades and core-field requirements;
- `research_budgets.yaml`: query/page/depth/recursion/time ceilings;
- `artifact_profiles.yaml`: chapter, sheet, slide and dashboard profiles;
- environment variables: model providers, API bases, keys and optional database URL.

Version and hash all effective configuration into `00_run_manifest.json`.

## 5. Key technical risks and mitigations

| Risk | Impact | Mitigation | Gate |
|---|---|---|---|
| Ambiguous company names | Wrong company researched | candidate scoring, official-domain checks, blocking review | Identity gate |
| Incomplete group roster | False “complete” claim | coverage language, recursive budget, authority source check | Evidence gate |
| Adapter unavailable | Research cannot start | health check, all bundled AnySearch runtimes, redacted proxy diagnostics, approved adapter fallback only | Preflight |
| Dynamic/anti-bot pages | Missing content | browser adapter route, auth hints, cached evidence, no bypass | Retrieval gate |
| Search snippets treated as facts | Unsupported claims | snippets are D-level discovery only | Evidence gate |
| Conflicting figures | Misleading metrics | typed conflict groups and scope/date comparison | Freeze gate |
| Model extraction drift | Schema failures | structured output, validation, repair budget, fixture regression | Node gate |
| Fabricated analysis detail | Hallucination | evidence/inference/status labels and provenance enforcement | Analysis gate |
| Image misattribution or remote-only delivery | Reputational risk / broken offline artifact | page context, logo/name match, binary archive, hash/MIME/dimension verification, 100% displayed-product coverage | Image gate |
| Brand extraction error | Off-brand interface | verified official source or controlled SEVC fallback | Artifact gate |
| Word TOC/page drift | Unusable formal report | field refresh, PDF render and page sampling | Render gate |
| HTML local-file restrictions | Broken dashboard | inline data/assets, no runtime CDN requirement | Render gate |
| PPT overflow | Executive deck unusable | matrix compression and strict slide count | Artifact gate |
| External Skill API changes | Publisher failure | stable adapters and contract tests | Integration gate |
| Cross-file numeric drift | Loss of trust | manifest binding and parsed-output comparison | Release gate |
| Long group research cost | Budget exhaustion | breadth/depth router, dedupe and checkpoint/resume | Planner gate |
| Sensitive data leakage | Compliance issue | public-source scope, redaction and log filtering | Security gate |
| Schema evolution | Old runs unreadable | versioned schemas and migrations | Migration gate |
| Non-deterministic packaging | Audit difficulty | freeze hashes, sorted exports and checksums | Release gate |
| Partial run presented as final | Decision risk | fail-closed status and watermark/blocked package rules | Package gate |

## 6. Phase milestones

1. **M1 Architecture approved** — Phase 1 documents accepted.
2. **M2 Synthetic pipeline** — Phase 2 completes a no-network frozen fixture run.
3. **M3 Evidence-ready research** — Phase 3 produces validated evidence for three fixture enterprises.
4. **M4 Artifact parity** — Phase 4 publishes all applicable artifacts from one freeze.
5. **M5 Release candidate** — Phase 5 passes golden, render, consistency and failure tests.

## 7. Definition of done

A production run is done only when identity, source, image, schema, consistency, artifact and rendering checks have completed; the package contains its manifests and validation reports; and no `BLOCKED` finding remains. File existence alone is never completion.
