# Data Fields And Source Plan

## Contents

1. Evidence classes and tiers
2. Geography and localization
3. Mandatory source routes by data class
4. Market/policy/demand fields
5. Product and competitor fields
6. Pricing/channel/service fields
7. Reviews
8. Modeling
9. Conflict and estimation

## Evidence Classes And Tiers

Value classes:

- `observed`: directly reported or measured.
- `derived`: calculated from observed values.
- `modeled_estimate`: estimated because no direct observation is available.
- `scenario_assumption`: chosen input for what-if analysis.
- `simulated`: reproducibly generated modeling input calibrated to evidence and constraints; never an observation.
- `pending_verification`: collected but unresolved.

Reliability tiers:

- Tier 0: user-provided local files and internal approved data.
- Tier 1: government, regulator, grid/market operator, utility tariff/VPP program, official statistics, standards/certification database, brand official page/manual/spec PDF, audited filing.
- Tier 2: exact-identifier marketplace/retailer, testing lab, established analyst/report publisher, trade association, official distributor/installer.
- Tier 3: media, review sites, Reddit, YouTube, forums, and other social/community sources.

Use Tier 0 first for product parameters. Use Tier 1 for policy, tariffs, grid rules, standards, and official specifications. Use Tier 2 for live price and availability. Use Tier 3 for user voice and triangulation.

For R3 critical claims under frozen policy v2+, independence is conjunctive rather than a raw source count. The qualifying subset must use different publisher groups, registrable root domains, canonical/original chains, and enough distinct controlled source types under the frozen policy. A mirror, syndicated copy, reprint, or summary must point to its original source ID and cannot independently corroborate that original.

Every evidence row requires:

- Evidence/source ID.
- Value class.
- Raw value and unit.
- Geography and period/date.
- Source title, publisher, URL or local file path, access/extraction date.
- For policy v2+ web evidence: controlled `source_type`, accountable `publisher_group`, URL-derived `root_domain`, `source_relation_type`, and `canonical_source_id` for derivative copies.
- Reliability tier, verification status, and notes.
- Exact model/identifier where applicable.

## Geography And Localization

Capture:

- Global region, country, province/state, city/site.
- Local language and search synonyms.
- Currency, exchange-rate source/date, tax basis, shipping/install basis.
- Voltage/frequency, plug/connector, grid structure, dwelling type, climate/environment.
- Regulator, energy ministry, grid/market operator, standards/certification bodies.
- Local tariff names, subsidy schemes, wholesale/ancillary/VPP access.
- Main marketplace, retailer, installer, distributor, automotive, utility, and financing channels.

China source map:

- National/provincial/municipal government and statistics.
- NDRC, NEA, MIIT, SAMR, State Grid, China Southern Power Grid, power exchanges, official tenders and pilots.
- Company filings, official product materials, certification databases, Tmall, JD, 1688, Suning, installers, distributors, automotive and charging operators.

For other markets, build the same functional map with local institutions and channels.

## Mandatory Source Routes By Data Class

Follow the route for the data class before creating an estimate. Record attempted sources and access dates even when no usable observation is found.

### Social-media and user-voice data

- Include Reddit and YouTube in the social/community source map, together with relevant local forums, review communities, and social platforms.
- Preserve the thread/video URL, channel or subreddit, publication date, collection date, original text or transcript segment, language, engagement context, and exact-model linkage.
- Treat social-media evidence as Tier 3. Use it for user voice, pain points, adoption barriers, and triangulation; do not let it override official specifications, policy, or audited statistics.

### Modeling inputs

Use this priority:

1. User-provided/internal approved data.
2. Official national or regional statistics, regulators, grid/market operators, utilities, ministries, and open-data portals.
3. World Bank datasets, `https://energydata.info/dataset/`, and `https://www.globalpetrolprices.com/` where the indicator and geography match.
4. Other official organizations, established research institutions, and traceable media sources.
5. If the model still needs a missing input after the routes above are exhausted, generate the most realistic reproducible `simulated` input calibrated to analogous evidence and physical/business constraints.

For every modeling dataset, capture dataset title, indicator/variable, geography code, period/vintage, unit, methodology or definition, update date, download/API URL, license where shown, missing-value treatment, and transformation into the model input.

### Selling price and promotion data

- Use Amazon.de, MediaMarkt, Galaxus, brand stores, and other relevant local retailers or marketplaces.
- For Amazon.de, first run an ASIN search and exact-match verification. Collect price, promotion, reviews, ranking, availability, or parameters only after the ASIN is recorded and linked to the exact regional model and bundle.
- Capture list price, discounted price, coupon or member price, promotion conditions and dates, VAT, shipping, installation, stock, seller, bundle contents, currency, and capture timestamp. Do not merge base units, expansion batteries, kits, subscriptions, or different regional variants.

### Product specifications

- Prefer the exact regional product page, official manual, datasheet, support page, certification page, and official firmware/revision notes.
- Use `https://device.report/` as a secondary discovery and cross-check source when official material is absent or incomplete. Preserve its exact document URL and model identifier, and do not let it override a newer exact-match official source without a documented conflict note.
- Exclude or mark `pending_verification` when the product family is known but the exact model, generation, regional variant, or bundle cannot be proven.

## Market, Policy, And Demand Fields

- Market definition and inclusion/exclusion.
- Segment, application, product type, system architecture.
- Historical/base/forecast year.
- Revenue, shipments, installed capacity, active systems, price, and CAGR.
- TAM/SAM/SOM method and formula.
- Production capacity, output, utilization, imports/exports where relevant.
- Policy/regulation title, issuing body, date, effective date, coverage, eligibility, amount/rate, implementation status, expiry/review date.
- Tariff plan, peak/shoulder/off-peak windows, import/export price, fixed charge, demand charge, free-energy window, taxes and limits.
- Grid reliability, outage hours/frequency, voltage quality, electrification.
- Typical household/business archetype, appliance basket, daily/seasonal load, PV generation, EV travel/availability.
- Income, energy-spend share, alternative-energy cost, willingness/ability to pay.

## Product And Competitor Fields

- Brand, parent company, country, player type, market presence.
- Product family, exact model, regional variant, ASIN/SKU/model code/EAN/UPC/certification ID, exact URL.
- Product/system type and target customer/scenario.
- Battery capacity/usable capacity, chemistry, cycle life and condition, expansion.
- Charge/discharge/peak power and duration, voltage/current.
- PV power, MPPT count/current/voltage range.
- Coupling and system architecture.
- Backup/off-grid/transfer method and anti-backflow.
- Smart tariff optimization, app, HEMS/EMS, VPP/grid services.
- Protocols: OCPP, ISO 15118, EEBUS, OpenADR, SunSpec, Modbus, Matter, MQTT, proprietary/local protocols.
- Connector: CCS, CHAdeMO, Type 2, NACS, GB/T, or local interface.
- EV compatibility and bidirectional limitations.
- Grid code, certification, safety and installation requirements.
- Dimensions, weight, IP rating, noise, operating temperature, cooling, installation method.
- Warranty, after-sales, serviceability, local support.
- Source URL/local path, page/sheet/location, date, value class, verification status.
- For web specifications, record whether the source is an official product/manual/support page or a secondary `device.report` document.

## Pricing, Channel, And Service Fields

- Country/region, currency, exchange-rate convention.
- Capture date and stock status.
- Channel name/type and exact URL.
- Exact model/identifier and configuration/bundle contents.
- List price, discounted price, tax included, shipping included, installation included.
- Promotion and price-history note.
- For Amazon.de, verified ASIN and the preceding ASIN-search task/evidence ID.
- Online/offline/installer/distributor/utility/VPP/automotive coverage.
- Financing, lease, PAYG, subscription, revenue share, service bundle.
- Local hotline, language, app, installer referral, training, return, spare parts, warranty service.

## Reviews

Raw fields:

- Review ID, platform, product/review URL, exact model and identifier.
- Variant/configuration, review date, crawl date, rating, language.
- Original text and concise translation/summary.
- Collection tool, visible/total counts, sort/filter, platform limit, verification status.
- Under frozen quantity-policy v4+, a claimed platform limit must additionally use the structured project-local JSON template: every R2 platform and source-ledger URL, access date, visible/raw/deduplicated/accessible counts, at least two retrieval methods, blocker reason, distinct nonempty raw captures, exact record refs, R1/R2/R3 links, zero high-priority discoveries, and human approval. A prose note cannot reduce the review target.
- For Reddit: subreddit, thread title, post/comment context, score when visible, and permalink.
- For YouTube: channel, video title, transcript/comment location, timestamp when relevant, and video/comment URL.

Coding fields:

- Raw review IDs and source URLs.
- Theme, sentiment, severity, frequency, representative short quote, summary.
- Installation, stability, actual savings/output, compatibility, service, price/value, and purchase drivers.

Do not code before raw rows exist. Exclude model-family or mixed-variant comments from model-specific counts unless linkage is proven.

## Modeling

Assumption fields:

- Assumption ID, model/module, parameter/symbol, definition, value class.
- Low/base/high values, unit, geography, period.
- Rationale, formula/use, source IDs/URLs, owner, confidence, approval status.

Result fields:

- Result ID, model/module, scenario, metric, value, unit, geography, period.
- Formula/method, input assumption IDs, source/evidence IDs.
- Validation check, sensitivity/uncertainty, confidence, interpretation, verification status.

Typical energy-economics inputs:

- Load and PV curves, EV availability, battery capacity/SOC bounds.
- Charge/discharge efficiency and power.
- Tariff/export/VPP/ancillary revenue.
- CAPEX, installation, OPEX, degradation, replacement, financing, tax, discount rate.
- World Bank, EnergyData.info, GlobalPetrolPrices, and official national/operator indicators with dataset vintage and transformation notes where applicable.

Typical outputs:

- Grid import/export, self-consumption, backup coverage, annual savings/revenue.
- Degradation cost, total cost of ownership, NPV, IRR, payback.
- Low/base/high results and threshold/sensitivity.

## Conflict And Estimation

When sources conflict:

- Prefer exact, current, primary evidence.
- Preserve both values when regional variants or dates may explain the difference.
- Record conflict note and verification status.
- Do not average incompatible values.

When an observation is unavailable:

- Only a missing market fact may remain in internal `11_Evidence_Issues.csv`, with `data_domain=market`.
- Under frozen quantity-policy v3+, using that row as a `market_gap` quantity exception requires the same scoped goal's completed R1/R2/R3 task IDs and count-audit JSON references, per-round attempted queries/source-ledger IDs/failure reasons/project-relative raw captures, zero remaining high-priority discoveries, complete reason/decision-impact/resolution-path/owner/status/source-context fields, and named/date-stamped human approval.
- Record which official, World Bank, EnergyData.info, GlobalPetrolPrices, retailer, product-site, device.report, media, or social routes were attempted as applicable; a prose “not available” note is not sufficient evidence.
- If the missing value is a mathematical-model input, do not log it as a gap. Generate calibrated simulated data with Python and label the corresponding assumption `value_class=simulated`.
- Record low/base/high quantiles, calibration evidence, method/process, parameters, physical bounds, correlation/time structure, fixed seed, sample size, generator and generated-data paths, validation, and sensitivity in `14_Simulated_Modeling_Data.csv`.

For frozen quantity-policy v5+ record counting, register every counted output row in internal `15_Collection_Record_Registry.csv`. Preserve one primary owner task, optional non-counting supporting tasks, exact market/model/goal/round scope, source IDs, a stable canonical record key, and the SHA256 generated by `scripts/compute_record_content_hash.py`. Copying content to a new row/file/task does not create a new record. Later-round enrichment must link its earlier-round parent and name fields whose substantive values actually changed.

For frozen quantity-policy v6+, give every source-ledger row a controlled `source_type` and stable lowercase `platform_id`: web IDs equal the URL-verified registrable root domain, while local evidence uses `local-internal`. Actual type/platform counts are derived only from source IDs linked by current-task counted records. Count-audit declarations must equal those derived sets exactly. Reused root domains and canonical derivative chains cannot be renamed into extra platforms, and each counted review row must match the platform ID of its linked source.

For frozen quantity-policy v7+, validate `reliability_tier` against the source-type matrix and derive task-qualified primary sources from the family-specific eligibility map. A primary source must be original, verified/accepted, and linked to a counted record owned by the task. A Tier 0 row must use `source_type=local_internal`, `collection_tool=local file`, and an existing file path. A retailer may be a direct primary source for a live price while remaining Tier 2; reliability tier and task-specific primary role are deliberately separate concepts.

For frozen quantity-policy v8+, bind every critical claim to at least two task-owned countable records and name the substantive fields that support it. Hash the normalized claim statement with `scripts/compute_claim_hash.py`. Claim source IDs are not free-form citations: they must exactly equal the source union on the bound registry rows, and the existing publisher/root/canonical/source-type independence checks still apply to that same set.
- Never attach a source URL in a way that implies the source directly reported the simulated value, and never label simulated data `observed`.
