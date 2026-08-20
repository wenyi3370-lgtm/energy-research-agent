---
name: enterprise-energy-research
description: Evidence-first enterprise industry and energy cooperation research planning and delivery. Use when Codex must investigate a company or group, resolve subsidiaries, factories and products, assess energy use and EPC/zero-carbon/storage ODM/overseas opportunities, and publish consistent Excel, Word, standalone HTML dashboards and a 15-20 page PPT from one validated fact set. Also use when designing or reviewing the architecture, schemas, source policy, validators or artifact specifications for this workflow.
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

## Enforce the workflow contract

- Resolve the canonical legal entity before broad research. Stop for ambiguity that cannot be resolved safely.
- Route company complexity as `GROUP_LARGE`, `ENTERPRISE_NORMAL`, `SMALL_SIMPLE`, or `UNKNOWN` using configuration, never legal SME classifications.
- Route all web research exclusively through `KimiWebBridgeAdapter` or `AnySearchAdapter`. Do not invoke Web-Rooter, web-access, a built-in web search provider, or any parallel search path.
- Treat product research as catalog enumeration, not keyword sampling. Discover official product centers for the parent and operating subsidiaries, enumerate every visible category/series/detail page, then expand families into models, parameters, applications and images.
- Complete R1 coverage, R2 depth and R3 triangulation for every scoped research goal. Meeting a quantity floor is not saturation; require two consecutive no-new-high-priority batches, marginal high-priority yield at or below 5%, no unresolved critical gap and no unexpanded high-priority discovery.
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
- Invoke the embedded Excel Master, PPT Master, frontend-design, Kimi WebBridge, and AnySearch resources only through their adapters. Prefer `vendor/skills/` and never silently switch to an unrelated implementation.
- Generate the product dashboard only when verified physical-product evidence exists.
- Before publishing a formal product dashboard, download each displayed product image from its exact verified `source_url`, enforce size/content-type limits, verify SHA-256, MIME type and decoded dimensions, archive it under the run evidence directory, and embed the local binary into the standalone HTML. Formal product-image coverage must be 100%; remote-only images and placeholders block delivery.
- Fail closed for unresolved company identity, missing core evidence, unverified required images, broken key URLs, or cross-artifact inconsistency.

## Respect phase boundaries

The current repository baseline has completed Phase 3, the Phase 4 publisher boundary, the core Phase 5 consistency/package gate, and portable embedding of all five named external Skill capability packs. It includes typed evidence schemas, append-only SQLite storage, immutable freezes, identity ambiguity gates, YAML complexity routing, bounded research plans, approved Kimi WebBridge/AnySearch adapters, source/claim/image/product validation, conflict and gap records, energy/four-solution analysis, frozen-bundle Excel/Word/standalone HTML publishers, cross-artifact provenance checks and deterministic release packaging. PPT Master receives a deterministic 17-slide frozen brief and must remain blocked at its required confirmation until SVG, preview and export gates complete. Use `PYTHONPATH=src python -m unittest discover -s tests -v` for the recorded-fixture regression suite. Fixtures are synthetic and never justify real-company claims.

## Publish a run

Use `outputs/{canonical_company}/{run_id}/` and preserve the directory contract in [ARTIFACT_SPEC.md](ARTIFACT_SPEC.md). A successful run must end as `PASS` or `PASS_WITH_WARNINGS`; a blocked run must retain evidence, diagnostics, and missing-data reasons instead of publishing misleading final artifacts.

Product coverage may be `COMPLETE` only when the official catalog scope is verified, all declared categories/series/detail pages have been visited, every catalog item has a matching verified record, and disclosed model/parameter detail has been captured. Otherwise emit product-coverage gaps and use “本次公开资料识别” language.

For HTML, preserve the SEVC-style deep-purple identity header defined by the frozen HTML publisher. Keep all data and displayed product-image binaries inline and avoid CDN or remote-image dependencies. A verified remote image that has not been archived is a data gap, not a publishable placeholder. For Excel, route through `ExcelMasterFrozenPublisher`; for Word, retain real TOC/PAGE fields and render-inspect every delivered document. Never bypass a missing publisher with an unrelated generator.

Unless the user explicitly requests a concise report, Word is a 15,000–30,000 Chinese-character, 30+ rendered-page decision report. A short fixture-style document is a draft and cannot pass formal delivery. Word must use the SEVC-adapted券商研报 system: A4, 12 pt 宋体/Times New Roman正文、22 pt固定行距、22/14/12 pt标题层级、三线表、每个核心一级章节至少一幅正式视觉，以及“分析→正文引用→图表→题注→数据来源”的顺序。Generate `visual_manifest.json` before layout, preserve 300 DPI PNG plus editable SVG, use at least three visual families once six or more visuals exist, and keep the bar family at or below 60%. Independently generate `image_publication_manifest.json`: only verified, locally archived images whose SHA-256, MIME and decoded dimensions match may be normalized to offline PNG and inserted. Put logos on the cover, office/identity images in the entity chapter, product images in the product chapter, factory/production-line/location images in the factory/process chapters and certificates in the evidence/zero-carbon chapter. Every non-cover image needs a caption and exact original-page source note; missing selected binaries block formal publication. These evidence images supplement rather than replace the required data charts. PPT uses the embedded SVG route, consumes the same approved visual manifest and image publication manifest, and requires a storyline/evidence map, answer-first titles, a visual on every slide, at least four layout families, no three consecutive identical layouts, source/date/bias footers, token-aware text wrapping, PDF geometry checks, a contact sheet and at least one fix-plus-full-rerender cycle. Missing manifests, figure/image sources, same-stem Word PDF, PPT geometry evidence or inspection records block formal release.

## Embedded capability policy

- `vendor/skills/excel-master/`: preserve its DataFrame-to-XLSX engine, type inference, themes, chart layout guard, and delivery checklist.
- `vendor/skills/ppt-master/`: preserve its serial pipeline, Eight Confirmations hard stop, strategist/executor specifications, SVG quality checker, finalizer, PPTX exporter, templates, icons, and workflows. Never batch-generate SVG pages or bypass its blocking confirmation.
- `vendor/skills/frontend-design/`: preserve its complete aesthetic instructions and license, but subordinate generic visual preferences to verified enterprise branding and the supplied SEVC header reference.
- `vendor/skills/kimi-webbridge/`: preserve its session/tab discipline, health-first rule, operations guide, snapshot-first interaction, and real-browser daemon boundary. The browser extension and daemon remain runtime services and are not impersonated by bundled files.
- `vendor/skills/anysearch/`: preserve its four CLI runtimes, shared contract, domain-directory-first routing, extraction support, license, notices, and fail-closed behavior. Try every available bundled runtime before declaring an outage; transport/proxy failure in one runtime must trigger the next runtime and a redacted diagnostic. Do not bundle populated `.env` files or machine-specific `runtime.conf`; never replace it with an unapproved search backend.
- Verify `vendor/manifest.json` before release. A missing or hash-mismatched embedded file is a release blocker.
