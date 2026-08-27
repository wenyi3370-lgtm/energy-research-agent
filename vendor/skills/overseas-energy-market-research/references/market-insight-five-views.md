# Embedded Market Insight Five Views

## Contents

1. Purpose and precedence
2. Required inputs
3. Five Views
4. Analytical tools
5. Evidence and writing contract
6. Execution sequence
7. Energy-product adaptations

## Purpose And Precedence

Use this reference when `analysis_branch=market-insight`. It is the self-contained qualitative-analysis method bundled with this Skill; an independently installed `market-insight` Skill is optional and must not be required for execution.

Apply rules in this order:

1. User-approved decision question and outline.
2. Evidence integrity, identifier, source, and value-class rules in the parent Skill.
3. This embedded Five Views method.
4. Optional external market-insight suggestions, only when they do not conflict with items 1-3.

The Five Views are an analysis lens, not a fixed report outline. Include only decision-relevant material, but explicitly mark an omitted view as out of scope and state why.

## Required Inputs

Load before synthesis:

- `research_outline.md` and the approved row in `00_Research_Approval.csv`.
- `project_manifest.json`, including decision question, region, category, currency, tax basis, and current outline version.
- Audited evidence tables `00` through `10`, plus `12_Model_Assumptions.csv`, `13_Model_Results.csv`, and `14_Simulated_Modeling_Data.csv` when applicable.
- Raw review rows before any customer-theme synthesis.
- Exact-model identifier status before product or competitor claims.
- `11_Evidence_Issues.csv` for counter-evidence, market-only gaps (`data_domain=market`), and unresolved conflicts.

## Five Views

### 1. 看宏观 Macro Environment

Answer which external forces change the decision. Cover only relevant policy, electricity market, tariff, grid, economy, society, technology, trade, standards, certification, and infrastructure factors.

Required outputs:

- Confirmed trends versus high-impact uncertainties.
- Regional policy and implementation distinction.
- Scenario triggers and early-warning indicators.
- Implications for product, channel, timing, and compliance.

Preferred tools: PESTEL, certainty-uncertainty matrix, scenario triggers, policy implementation timeline.

### 2. 看行业 Industry And Market

Answer where value and growth exist. Cover market definition, lifecycle by segment, TAM/SAM/SOM where supported, growth, concentration, value chain, profit pools, substitutes, and structural bottlenecks.

Required outputs:

- Market boundary and non-overlapping segments.
- Observed size separated from modeled estimates.
- Value-chain power nodes and value migration.
- Attractive segments with reasons and limitations.

Preferred tools: lifecycle analysis, value-chain analysis, concentration, segment attractiveness, supply-demand structure.

### 3. 看客户 Customer And Use Cases

Answer who has the problem, when it occurs, and what drives adoption. Cover customer archetypes, load/generation/travel/outage scenarios, jobs-to-be-done, current alternatives, willingness and ability to pay, KANO attributes, pain points, purchase drivers, and service expectations.

Required outputs:

- MECE customer segmentation and validation.
- Evidence-based use cases and unmet needs.
- Raw-review-to-theme traceability.
- Must-be, performance, attractive, indifferent, and reverse attributes where support exists.

Preferred tools: MECE, persona/archetype, customer journey, KANO, need-severity-frequency matrix.

### 4. 看竞争 Competition

Answer how customers currently solve the problem and where differentiation is defensible. Cover player taxonomy, exact regional models, engineering and compliance, price/configuration, promotion, channel, installation, warranty, service, ecosystem, VPP/EMS compatibility, and positioning.

Required outputs:

- Macro player map and micro exact-model benchmark.
- 4P comparison and price-capability position.
- Competitor strengths, weaknesses, strategic direction, and likely response.
- White-space opportunities that are evidence-supported rather than feature wish lists.

Preferred tools: player taxonomy, 4P, exact-model scorecard, positioning map, capability heatmap.

### 5. 看自己 Self And Strategic Fit

Answer whether the proposed business can win. If internal company data is unavailable, assess required capabilities and explicitly label actual self-performance as pending rather than inventing it.

Required outputs:

- Target-state capabilities and key success factors.
- Known strengths/gaps from user-provided evidence only.
- Root causes, build/buy/partner choices, and organizational dependencies.
- Fit with product definition, channel, service, economics, and risk appetite.

Preferred tools: capability benchmark, SWOT/TOWS, six-dimension root-cause analysis, gap-to-action map.

## Analytical Tools

### Certainty-Uncertainty Matrix

Score material external factors on impact and uncertainty. Use high-impact/low-uncertainty factors as strategy anchors; use high-impact/high-uncertainty factors for scenarios and monitoring. Do not assign scores without a stated basis.

### Industry Lifecycle

Assess lifecycle at segment level using growth, competitor entry/consolidation, product standardization, margins, awareness, and technology change. Do not label an entire industry by one fast-growing niche.

### Value Chain

Map upstream inputs, equipment, software/platform, installation, aggregation/operation, financing, after-sales, and end users. For each node assess margin, concentration, entry barriers, bargaining power, and value migration.

### MECE Segmentation

Use non-overlapping and collectively exhaustive dimensions. Validate each segment for differentiation, size, measurability, stability, accessibility, and actionability. Redefine segments failing two or more criteria.

### KANO

Use survey evidence when available. Without a KANO survey, label review-derived categorization as a qualitative hypothesis: complaints suggest must-be gaps; repeated positive differentiation may indicate performance or attractive attributes.

### 4P

Compare Product, Price, Place, and Promotion using exact regional models and matched configurations. Keep installation, tax, shipping, bundle, and promotion conditions visible beside price.

### Six-Dimension Root Cause

Test strategy, organization/governance, systems/processes, performance/incentives, people/capabilities, and technology/IT. Recommend against root causes, not symptoms.

### Priority Matrix

Score recommendations on strategic value and execution difficulty. Classify quick wins, major initiatives, fill-ins, and avoid items. Add owner, timing, dependency, KPI, and evidence IDs.

### Risk Matrix

For each risk record likelihood, impact, evidence, trigger, early-warning indicator, mitigation, contingency, and owner. Separate known risks from uncertainty scenarios.

## Evidence And Writing Contract

- Separate fact, calculation, interpretation, recommendation, and counter-evidence.
- Bind material statements with inline anchors in the form `【证据：ID1, ID2】`.
- Use IDs that exist in project CSV files; never cite a URL-only memory claim.
- End every included View with `对本企业/产品的启示`.
- Mark estimates as `模型估算` or `情景假设` and link them to row IDs in `12_Model_Assumptions.csv`.
- Preserve negative evidence and conflicts; do not turn absence of evidence into market proof.
- Do not generate internal company KPIs, capabilities, or performance claims without user-provided evidence.
- End with a 3-5 item `So What` summary, prioritized actions, and a risk/uncertainty watch list.

## Execution Sequence

1. Freeze the approved decision question, scope, and outline version.
2. Build a question-to-evidence map for each selected View.
3. Extract observed facts and calculations before interpretation.
4. Apply only the analytical tools that change the decision.
5. Draft each View with evidence anchors, counter-evidence, and implications.
6. Reconcile insights against `09_Integrated_Matrix.csv`, `10_SWOT_Opportunity.csv`, and model results.
7. Prioritize actions by value, difficulty, timing, dependencies, and owner.
8. Fill `intermediate/market-insight/market_insight_report.md` from the bundled template.
9. Run `scripts/validate_market_insight.py` before Word or PPT writing.

## Energy-Product Adaptations

- Residential/balcony storage: connect tariff, PV/load shape, dwelling/installation constraints, self-consumption, backup, anti-backflow, and channel economics.
- V2G/V2H: connect export rules, vehicle availability, interoperability, degradation, aggregator access, dispatch, customer control, and stakeholder revenue share.
- Portable/off-grid storage: connect outage reliability, generator substitution, productive use, affordability/PAYG, environment, logistics, and repairability.
- Pilot projects: distinguish announced, installed, operating, and independently verified results; test repeatability, economics, stakeholder incentives, and bottlenecks.
