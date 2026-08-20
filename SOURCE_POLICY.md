# Source policy

## 1. Evidence standard

Treat a source as evidence only when the retrieved page/document contains the claim in context. Search-result snippets, generated summaries and model memory are discovery aids, not proof.

Core facts require either:

- one relevant `SOURCE_A` source; or
- two independent, mutually consistent `SOURCE_B` sources.

Use `SOURCE_C` and `SOURCE_D` only as supporting evidence, lead generation, or explicitly qualified context. Independence is based on origin, not URL count: syndicated copies count as one origin.

## 2. Source levels

| Level | Typical sources | Allowed use |
|---|---|---|
| `SOURCE_A` | government/registry, SASAC, official company site, audited annual report, company announcement, official product manual/certificate | core facts and primary evidence |
| `SOURCE_B` | industry association, recognized media with original reporting, university/research institution, standards/certification body | corroboration; two independent B sources may support a core fact |
| `SOURCE_C` | recruitment site, commercial database, major marketplace/channel, tender aggregator carrying traceable documents | workforce/process hints, product-channel evidence, discovery |
| `SOURCE_D` | ordinary media, forum/social post, search snippet, unverified repost | leads and sentiment only; never core facts |

Grade the specific page/document, not the domain forever. A company blog post is not equivalent to an audited report; an official press release may still be promotional.

## 3. Core fields

Apply the highest evidence threshold to:

- canonical legal name, ownership, parent and actual controller;
- group/subsidiary relationship and factory operator;
- revenue, profit, capacity, employee count and investment figures;
- product model and technical parameters;
- energy consumption, load, tariff, roof area and savings inputs;
- export/overseas factory/customer claims;
- certifications and government awards;
- company/factory/product image identity.

If a core field does not meet the threshold, mark it missing/conflicting/unverified. Do not fill it from inference.

## 4. Retrieval rules

- Route all search and page retrieval through `KimiWebBridgeAdapter` or `AnySearchAdapter`.
- Capture requested URL, final canonical URL, title, domain, publication date if available, retrieval time, content type, adapter and content hash.
- Prefer the original document over a quoting article.
- Follow robots, authentication, licensing and access restrictions. Do not bypass protected workflows.
- Record failure states such as gone, blocked, auth required and challenge encountered.
- Cache by canonical URL/content hash within the run to reduce duplicates.
- Preserve only the minimum raw content required for audit and comply with applicable copyright limits.

## 5. Company identity resolution

Before broad research:

1. Search canonical legal name candidates.
2. Validate official domain and registered location.
3. Compare aliases/former names, parent/controller and business description.
4. Store all candidates and disambiguation evidence.
5. Continue only when one candidate meets configured uniqueness/confidence thresholds.

Never merge entities because they share a short brand name.

## 6. Group coverage language

For a large group, search recursively within configured budgets. Use:

> 本次公开资料共识别 XX 家成员企业。

Do not use “全部子公司” or “完整覆盖” unless an authoritative, dated roster proves completeness and the evidence snapshot matches it.

## 6.1 Product catalog coverage

- Start from verified official parent-company and operating-subsidiary product centers; a parent overview page is only a discovery source when a subsidiary has a richer catalog.
- Enumerate categories, series, models/SKUs, pagination, tabs, downloadable brochures/manuals and product-news pages. Preserve the URL inventory and enumeration time.
- Use search results to discover official product domains, then retrieve original pages. Snippets cannot establish completeness or parameters.
- Reconcile the official catalog inventory against normalized product records. Unmatched items become explicit `product_catalog_coverage` gaps.
- Report “本次公开资料共识别…” when the site provides no authoritative closed catalog or enumeration is constrained. Use “完整产品目录” only after verified scope and zero-unmatched gates pass.

## 7. Conflict policy

Never average, arbitrarily select or silently overwrite conflicting values.

For each conflict, compare:

- metric definition (revenue vs sales revenue, installed vs effective capacity);
- reporting period and as-of date;
- standalone vs consolidated scope;
- legal entity and geography;
- currency, tax treatment and unit;
- source grade, publication chronology and supersession.

Resolve as:

- `coexist` for valid different scopes/definitions;
- `select_authoritative` with rationale and retained alternatives;
- `superseded` for a corrected/later official record;
- `unresolved`, which blocks use as a single definitive core fact.

## 8. Analytical inference

An analyst may infer opportunities from validated evidence, but must store:

- statement type;
- linked claim IDs;
- reasoning method and assumptions;
- uncertainty/confidence;
- required on-site data;
- risk and validation next step.

Industry benchmarks may be scenario assumptions, never company observations. Label every scenario input and keep it out of `facts.json` as an observed fact.

## 9. Image policy

Accept formal-artifact images only when all of the following are satisfied:

- source page and image URL are retained;
- page title/domain and surrounding text support the entity/product association;
- file is retrievable with valid type and dimensions;
- SHA-256 and perceptual hash are recorded;
- duplicate/thumbnail/placeholder checks pass;
- verification status is `VERIFIED`.

Verification of provenance does not complete acquisition. Before a verified product image is used in a formal artifact, download the exact `source_url`, enforce the configured byte ceiling, decode the file, recheck SHA-256/MIME/dimensions, archive it under the run evidence directory and set `local_asset_ref`. Downloading that already-discovered exact binary is acquisition rather than a new search route; it does not authorize any search provider beyond AnySearch and Kimi WebBridge.

Formal product-image coverage is 100% of displayed products. A remote URL, thumbnail cache, metadata-only hash, browser-memory object, inaccessible local path or placeholder does not satisfy this requirement. Remote URLs remain provenance links only and must not be required to render the standalone deliverable.

Prefer official sites, government pages, official manuals and company announcements. Search thumbnails cannot establish attribution.

Reject:

- AI-generated company/factory/product images;
- unrelated stock factory imagery implying ownership;
- low-resolution logos/screenshots when a primary asset exists;
- images whose context names another company/product;
- certificates without a legible and matching holder/product.

If a required image cannot be verified or its binary cannot be archived and validated, emit `BLOCKED_MISSING_REQUIRED_IMAGE` or request a human-provided verified asset. For optional non-product visuals, use a transparent missing-image state without fabrication; formal product dashboards do not use placeholders.

## 10. Freshness and URL validity

- Store publication and retrieval dates.
- Prefer current sources for leadership, ownership, operational status, products, policies and financials.
- Allow historical sources for timelines only when clearly dated.
- Revalidate all core URLs before freeze and again before final package if the run is long-lived.
- A broken key URL is blocking unless the source content is an archived authoritative document whose integrity is recorded and policy permits its use.

## 11. Citation contract

- Word appendices display `[S023]` mapped to `SOURCE-S023`.
- Excel source sheets use the full `SOURCE-S023` ID and URL.
- HTML shows source IDs in drawers/tooltips or a source panel.
- PPT places source IDs in footers or speaker notes.
- All artifacts must map to the same frozen source record.
