---
name: enterprise-energy-research
description: Evidence-first enterprise industry, energy cooperation and decision-intelligence research. Use when Codex must investigate a company or group to evidence saturation, enumerate subsidiaries/factories/products, assess energy and EPC/zero-carbon/storage/V2G/overseas opportunities, or publish traceable Word, Excel, one unified offline HTML dashboard/product database and PPT from one frozen fact set.
---

# Enterprise Energy Research

Build every run around one rule: research produces evidence, validation freezes data, and publishers consume only the frozen snapshot. Never let an artifact publisher browse, infer new facts, or silently repair missing data.

## Start a run

1. Accept a company name plus optional scope constraints. Do not require step-by-step user operation during the normal path.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md), [WORKFLOW.md](WORKFLOW.md), [DATA_SCHEMA.md](DATA_SCHEMA.md), [SOURCE_POLICY.md](SOURCE_POLICY.md), [ARTIFACT_SPEC.md](ARTIFACT_SPEC.md), and [VALIDATION_SPEC.md](VALIDATION_SPEC.md) before implementation or execution.
3. Read [references/reference-findings.md](references/reference-findings.md) before producing Word or HTML. Preserve the reference report's structural logic and the SEVC/company-style header system.
4. Read [references/embedded-skills.md](references/embedded-skills.md) before invoking research or artifact adapters. Treat the bundled upstream instructions and quality gates as authoritative for their capability domain.
5. Use [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) to determine the current delivery phase. Do not cross a phase gate without the required validation evidence.
6. Read [references/migrated-quality-gates.md](references/migrated-quality-gates.md) before live collection or formal Word/PPT publication. Its three-round saturation, report-depth and visual-registration rules are release gates.
7. Read [references/office-visual-production.md](references/office-visual-production.md) before any formal Word/PPT build. Its SEVC-adapted `kami-broker-v2` typography, three-line tables, chart variety, per-slide contract, geometry checks and render artifacts are blocking requirements.
8. Read [references/v0.9-quality-contract.md](references/v0.9-quality-contract.md) before live research or formal release. Read [references/reference_visual_benchmark.md](references/reference_visual_benchmark.md) before Word or unified HTML layout work.

## Enforce the workflow contract

- Resolve the canonical legal entity before broad research. Stop for ambiguity that cannot be resolved safely.
- Route company complexity as `GROUP_LARGE`, `ENTERPRISE_NORMAL`, `SMALL_SIMPLE`, or `UNKNOWN` using configuration, never legal SME classifications.
- Route all web research exclusively through `KimiWebBridgeAdapter` or `AnySearchAdapter`. Do not invoke Web-Rooter, web-access, a built-in web search provider, or any parallel search path.
- Treat product research as catalog enumeration, not keyword sampling. Discover official product centers for the parent and operating subsidiaries, enumerate every visible category/series/detail page, then expand families into models, parameters, applications and images.
- Decompose the request into the configured Goal Families. Complete R1 official-source coverage, R2 Evidence-Gap-driven depth and R3 conflict/critical-claim triangulation for every scoped goal. Evaluate the final two batches per goal, not globally. Meeting a search-count floor is never saturation.
- Retain an attempt journal and raw capture reference for every collection action. Budget exhaustion cannot be called complete, and a public-evidence-gap exception requires all three attempted rounds plus named approval and decision-impact fields.
- For AnySearch business research, call `get_sub_domains --domain business` before vertical queries. Use Kimi WebBridge to inspect dynamic navigation, pagination, tabs and detail pages that search results cannot enumerate reliably.
- AnySearch availability is decided only after every bundled runtime has been attempted in deterministic order: Python, Node.js, PowerShell and Bash when present. If one runtime fails at the transport layer, record redacted system-proxy diagnostics and continue to the next bundled runtime. Anonymous access is supported, so a missing API key alone is not an outage. Never recover by switching to an unapproved search provider.
- The preferred AnySearch Python CLI must honor a working proxy, but on `requests.ProxyError` retry the same AnySearch endpoint once with process-local environment-proxy discovery disabled. Never change the user's global proxy settings; retain the bundled runtime fallback if the direct retry also fails.
- Record a verified `product_catalog_scope` claim with official product-center URLs, enumeration time/method and declared catalog items. Until every declared item maps to a product record, label coverage `PARTIAL`; never call a sampled list complete.
- Keep product family, series and model as distinct levels. One family such as “人造石墨” cannot substitute for multiple disclosed grades. Capture per-model parameter name, value, unit and source when published.
- Use a provider-neutral `ModelGateway`; configure DeepSeek as primary and OpenAI as fallback without storing secrets.
- Assign stable IDs to runs, entities, subsidiaries, factories, products, claims, sources, images, and charts.
- Record source context and image provenance before analysis.
- Treat image discovery, verification, binary acquisition and artifact readiness as four separate states. A URL, hash or dimension record without a successfully decoded local binary and `local_asset_ref` is not a completed image acquisition.
- Separate `EVIDENCE_SUPPORTED`, `ANALYTICAL_INFERENCE`, and `TO_BE_CONFIRMED` content.
- Preserve conflicts as first-class records. Never average, select, or overwrite conflicting values silently.
- Freeze validated facts and create `artifact_manifest.json` before any publisher runs.
- Invoke the embedded Excel Master, PPT Master, frontend-design, diagram-design, Kimi WebBridge, and AnySearch resources only through their adapters. Prefer `vendor/skills/` and never silently switch to an unrelated implementation.
- Generate the product dashboard only when verified physical-product evidence exists.
- Before publishing a formal product dashboard, download each displayed product image from its exact verified `source_url`, enforce size/content-type limits, verify SHA-256, MIME type and decoded dimensions, archive it under the run evidence directory, and embed the local binary into the standalone HTML. Formal product-image coverage must be 100%; remote-only images and placeholders block delivery.
- Fail closed for unresolved company identity, missing core evidence, unverified required images, broken key URLs, or cross-artifact inconsistency.

## Respect the frozen-data boundary

Version comes only from `pyproject.toml`. The v0.9 baseline includes typed evidence schemas, append-only storage, immutable freezes, ambiguity/conflict/gap gates, Goal-Family research, catalog enumeration, approved Kimi WebBridge/AnySearch adapters, three image manifests, one cross-artifact visual manifest, deterministic diagram-design visualization (VisualSpec → Visual Router → DiagramDesignAdapter), frozen-bundle publishers, visual QA and deterministic release packaging. PPT Master still receives a deterministic 17-slide frozen brief and remains blocked until its confirmation, SVG, preview and export gates complete. Use `PYTHONPATH=src python -m unittest discover -s tests -v` for recorded-fixture regression and `python scripts/run_recorded_research_eval.py` for L2 eval. Fixtures never justify real-company claims.

## Content pipeline contract (v0.9.1 remediation)

- Research content, not research metadata, is the body of every formal report: CompanyProfile/GroupProfile built from verified claims replace `entity_type`/`verification_status` dumps (research/profile.py).
- Every goal family has a `GoalExtractionContract` (expected fields + business question); the full ResearchGoal (topic/purpose/round/trigger/gap/conflict targets) travels into the EvidenceExtractor prompt (research/contracts.py).
- Raw field names canonicalize through `CanonicalFieldRegistry` and are preserved as `raw_field_name` (research/field_registry.py).
- Official-page identity evidence becomes provenance-bound identity Claims before validation, so a resolved company is never left UNVERIFIED (research/identity_evidence.py).
- Kimi WebBridge opens REAL target pages (AnySearch discovers, Kimi navigates + DOM-inspects); image discovery reads `<img>/<picture>/srcset/lazy/background` and binds product/factory images (research/image_discovery.py). Adapter routing is not usage: `kimi_telemetry.json` records availability, pages, DOM inspections and image-pipeline counters.
- The adaptive production runner executes R1 -> Gap -> R2 -> Conflict -> R3 with real EvidenceDelta saturation, precise gap reasons, chapter/placeholder/readiness gates, claim-bound synthesis, high-value claim utilization and the goal pipeline trace (research/production_runner.py). Live acceptance: `PYTHONPATH=src python scripts/run_live_acceptance.py --company 宁德时代` and read `acceptance_summary.json` (sections A-L).

## Publish a run

Use `outputs/{canonical_company}/{run_id}/` and preserve the directory contract in [ARTIFACT_SPEC.md](ARTIFACT_SPEC.md). A successful run must end as `PASS` or `PASS_WITH_WARNINGS`; a blocked run must retain evidence, diagnostics, and missing-data reasons instead of publishing misleading final artifacts.

Product coverage may be `COMPLETE` only when the official catalog scope is verified, all declared categories/series/detail pages have been visited, every catalog item has a matching verified record, and disclosed model/parameter detail has been captured. Otherwise emit product-coverage gaps and use “本次公开资料识别” language.

For HTML, publish only `enterprise_research_dashboard.html`: a navy-navigation/light-analysis management dashboard that also contains the searchable, filterable, zoomable, four-item product comparison database. Keep all runtime code, data and publication images inline; remote dependencies are forbidden. A verified remote image that has not been archived is a gap, not a placeholder. For Excel, route through `ExcelMasterFrozenPublisher`; for Word, retain real TOC/PAGE fields and render-inspect every delivered document.

Unless the user explicitly requests a concise report, Word is a 15,000–30,000 Chinese-character, 30+ rendered-page decision report. A fixture-style document is a draft. Use A4, 12 pt 宋体/Times New Roman正文、22 pt固定行距、22/14/12 pt标题层级、三线表，以及“分析→正文引用→图表→题注→数据来源”的顺序。Generate `visual_manifest.json` before layout. Report structure is driven by research conclusions and decision questions — chapters appear only when evidence passes their gate; never replace missing data with a process, relationship, hierarchy, decision-tree or decorative framework. Every figure is a VisualSpec (business thesis + semantic pattern + evidence data) routed by the Visual Router to a diagram-design visual type, with anti-chart-abuse rules (no fake time series → line, no fake scores → radar, no fake x/y → quadrant/scatter, no fake flows → Sankey); insufficient data degrades to table/KPI/prose, never to an implied chart. Each accepted figure produces one offline standalone HTML, one editable SVG and one high-resolution PNG rasterized from the SAME HTML. HTML inlines the same SVG; Word embeds the same-source PNG. Text-only models select only the semantic pattern/visual type; Python owns all geometry, typography, palette and export behavior. Generate discovery, evidence and publication image manifests independently; only pixel-verified, entity-bound local binaries with matching SHA-256, MIME, dimensions and original page may publish (editorial images excepted). Word and unified HTML consume the same ResearchNarrative and visual meaning. Missing manifests, sources, rendered QA or cross-artifact consistency evidence blocks formal release.

## Research-first content pipeline (P0 third round)

- The chain is `Evidence -> PublicationRelevanceFilter -> ResearchAnalysis -> DecisionSynthesis -> PublicationNarrative -> Word/HTML`. Decision analysis is one layer in the report's second half, never its skeleton.
- `research/research_analysis.py` (ResearchAnalysisEngine) answers the objective questions first: business scale and trend (YoY/CAGR/margin from real multi-year series), product families and key parameters, manufacturing geography, and the strict split between a company's OWN energy data and its energy PRODUCT capability. Missing data produces nothing — no padded prose.
- `research/publication_relevance.py` (PublicationRelevanceFilter) scores every verified claim (semantic relevance, metric completeness, source quality, period/scope completeness, visualization and decision value) and its Junk/Fragment Guard keeps phone numbers, marketing counters, isolated `+`/percent values and page-UI numbers OUT of the body — they stay in the internal evidence store with reasons.
- `research/data_coverage.py` (ResearchDataCoverageValidator) states the per-company-type data contract (listed companies: ≥3 comparable years of revenue/profit, margins, R&D, segments, market position, product parameters, factory list, product images) and drives the R4 targeted-retry round (annual reports, exchange filings, official product pages) instead of prose fill-in.
- `artifacts/visual_opportunity.py` (VisualOpportunityPlanner) proposes figures from the structured research dataset BEFORE narrative assembly; the Visual Router still owns the final visual type. No data -> no proposal -> QA records `missing_high_value_research_data`.
- `research/product_images.py` (ProductImageResolver) binds verified product photos to products (product.image_id -> verified image by product_id -> verified official image by name match -> no photo). Word shows 4–8 key products with photo+name+parameters; the full matrix is an appendix.
- The executive summary is data-first (what the company is, key financial facts, industry/technology capability, cooperation basis, opportunities/limits, final recommendation; 800–1500 CJK chars). Word TOC entries are one LEFT-aligned paragraph each with a real right dot-leader tab (TOC 1/2/3 styles, never Normal/JUSTIFY); "So What：" labels never render.
- QA additions (`validation/publication_quality.py`): PublicationBoilerplateValidator (the self-referential phrase list must be zero), ParagraphSimilarityValidator (skeleton similarity > 0.80 -> boilerplate_duplicate), ResearchValueValidator (boilerplate_sentence_ratio < 15%, enterprise-specific ratio > 60%, meaningful_visual_count target, visual-density warning), ProductImageCoverageValidator. Regression contract: tests/test_p0_third_round.py (TEST 1–25).

## Decision synthesis and consulting narrative contract (P0)

- Apply Pyramid Principle, Conclusion First and SCQA. Every substantive module follows `Facts → Interpretation → So What → Recommendation → Action`; the objective is to answer a management decision, not to display the database.
- Convert frozen evidence into typed `DecisionFinding` records before writing prose. Keep `FACT`, `CALCULATION`, `ANALYTICAL_INFERENCE`, `RECOMMENDATION` and `TO_BE_CONFIRMED` distinct and retain claim/source lineage, calculation inputs, limitations and counter-evidence.
- Convert candidate `Solution` records into canonical, deduplicated `OpportunityAssessment` records before publication. Every opportunity must state why it matters, where to enter, what value we provide, prerequisites, owner, 30/60/90-day actions and a Go / No-Go gate.
- Write assertion titles: an H2 states the conclusion, while `decision_question` remains an internal control field. Never publish `决策问题：`, `thesis`, `content[]`, raw enums, snake_case keys or source-level codes.
- Contextualize every number with period, unit, scope and decision meaning. Never publish an isolated number, raw database-sized currency value, field dump, source dump, internal status, generic AI template sentence or duplicate conclusion.
- Enforce semantic domains. Manufacturing output or battery production capacity never becomes electricity consumption; product capability never becomes energy-project value; missing data never becomes an inferred fact.
- Select information by asking “它回答哪个管理问题？” Move complete factory/product/source ledgers to appendices or interactive attachments when they do not change the decision.
- `ResearchNarrative.appendices.source_ledger` is the single source owner. Word shows it only in Appendix B; HTML shows it only once at the page end.
- Run `ConsultingNarrativeValidator`, `VisualSemanticValidator`, `PublicationVisibleTextValidator`, `SourceOwnershipValidator`, `TOCValidator`, `WordLengthValidator` and `BrowserExecutionValidator`. Insufficient evidence must produce `insufficient analytical evidence`, never padded prose.
- The Product Detail Frontier normalizes and deduplicates URLs, persists queue/checkpoint state, uses at most four browser workers and closes each page in that task's `finally` block. Crawlers discover, retrieve, parse and save evidence only; they never write decisions or recommendations.

## Embedded capability policy

- `vendor/skills/excel-master/`: preserve its DataFrame-to-XLSX engine, type inference, themes, chart layout guard, and delivery checklist.
- `vendor/skills/ppt-master/`: preserve its serial pipeline, Eight Confirmations hard stop, strategist/executor specifications, SVG quality checker, finalizer, PPTX exporter, templates, icons, and workflows. Never batch-generate SVG pages or bypass its blocking confirmation.
- `vendor/skills/frontend-design/`: preserve its complete aesthetic instructions and license, but subordinate generic visual preferences to verified enterprise branding and the supplied SEVC header reference.
- `vendor/skills/diagram-design/`: the consulting visualization engine (MIT, third-party notices under `third_party/diagram-design/`). All figures are rendered through `artifacts/diagram_design_adapter.py`, which follows the skill's style guide (semantic tokens, 4px grid, orthogonal connectors, role/aria contract) with the enterprise consulting profile (white paper, near-black ink, navy `#1B365D` accent, CJK fonts) and its export procedure (first-SVG extraction; PNG rasterized from the same HTML). Diagram types are chosen ONLY by the Visual Router's semantic-pattern rules.
- `vendor/skills/kimi-webbridge/`: preserve its session/tab discipline, health-first rule, operations guide, snapshot-first interaction, and real-browser daemon boundary. The browser extension and daemon remain runtime services and are not impersonated by bundled files.
- `vendor/skills/anysearch/`: preserve its four CLI runtimes, shared contract, domain-directory-first routing, extraction support, license, notices, and fail-closed behavior. Try every available bundled runtime before declaring an outage; transport/proxy failure in one runtime must trigger the next runtime and a redacted diagnostic. Do not bundle populated `.env` files or machine-specific `runtime.conf`; never replace it with an unapproved search backend.
- Verify `vendor/manifest.json` before release. A missing or hash-mismatched embedded file is a release blocker.
