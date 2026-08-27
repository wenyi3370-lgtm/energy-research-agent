# Deliverables And Stage Gates

## Contents

1. Stage 0: Plan and approval
2. Stage 1: Market, policy, and demand evidence
3. Stage 2: Competitor and comparison framework
4. Stage 3: Product, technology, and compliance
5. Stage 4: Pricing, channel, service, and reviews
6. Stage 5: Excel evidence workbook
7. Stage 6: Modeling or market-insight branch
8. Stage 7: Word report and strategy synthesis
9. Stage 8: PPT and final handoff

Use all stages for a full project. For a targeted request, select a subset but preserve Stage 0 approval before new collection and preserve evidence gates.

## Stage 0: Plan And Human Approval

Deliverables:

- `调研计划与大纲.docx` or structured Markdown draft
- `00_Research_Approval.csv`
- `project_manifest.json`
- `policy_snapshot/collection_quantity_policy.yaml`（只读；版本与 SHA256 由 manifest 锁定）
- `02_Web_Collection_Tasks.csv`
- `15_Collection_Record_Registry.csv` (internal count-ownership and deduplication audit)

> **Audit artifacts are generated, not hand-rolled.** The generator reads
> project-specific behavior from the frozen policy snapshot's
> `generator_overrides` section (registry `market` / `created_date`, URL host →
> source hints, channel brand mapping, technology_performance keywords, review
> theme inheritance — see `assets/config/collection_quantity_policy.yaml` and
> `scripts/upgrade_collection_policy.py --overrides`); when a round segment
> gets no records it prints a `[WARN]` diagnostic instead of silently writing
> an empty audit (CHANGELOG v1.2.6).  Run
> `scripts/generate_collection_audits.py --project-dir <project>` after the
> collection tasks table is saturated; it writes the per-task count-evidence
> JSONs under `audits/count_evidence/`, rebuilds
> `15_Collection_Record_Registry.csv`, and refreshes the actual-count columns
> of `02_Web_Collection_Tasks.csv`.  The validator keys are
> `critical_claims` / `query_batches` / `high_priority_remaining_ids` (not
> `claims` / `batches` / `remaining_high_priority_ids`); claim objects require
> `claim_id`, `claim_text`, `claim_sha256`, `source_ids` and at least two
> `evidence_bindings` whose `record_ref` rows carry substantive (non-metadata)
> `evidence_fields`.  Primary sources are derived with the same policy rules
> the validator applies (eligible source types per family + allowed tiers +
> relation + verification status), so declared and derived counts always
> match.  Platform-limit exceptions use
> `audits/platform_limit_reviews.json` with `evidence_id`, `related_task_ids`,
> `platform_limits[]`, combined counts, `remaining_high_priority_ids` and an
> `approval` object (see `scripts/platform_limit_exception.py`).

The outline must define:

- Decision question and intended audience.
- Geography, product/system boundary, customer and scenario scope.
- Historical/base/forecast years.
- Research modules, issue tree, detailed chapter outline, task order, and outputs.
- Required data fields, source hierarchy, local-language queries, target platforms, and exact-model rules.
- Market-sizing and modeling methods.
- Currency, tax, exchange rate, units, language, and update date.
- Timeline, roles, review cadence, risks, and acceptance criteria.

Gate:

- Record explicit human approval as `approval_status=approved`.
- Do not start collection while status is `draft`, `pending`, `rejected`, or blank.
- If scope changes materially, increment `outline_version` and obtain approval again.

## Stage 1: Market, Policy, And Demand Evidence

Deliverables:

- `01_Market_Scan.csv`
- `市场与政策快速扫描笔记.docx`
- updated source ledger

Collect:

Before collection, freeze the approved `target_markets` and `market_model_pairs` in `project_manifest.json`, then create a saturated plan in `02_Web_Collection_Tasks.csv`. `assets/config/collection_quantity_policy.yaml` is the sole source for new policy versions; `init_research_project.py` freezes it into the project and records version, SHA256, path, and time. Thereafter load goal families, exact-model coverage, family-by-round floors, status rules, exceptions, and R3 thresholds only from the verified project snapshot. Compute required totals from that frozen policy. The agent may not self-declare a family N/A, merge families, or silently adopt a newer global policy.

Policy upgrades require explicit human approval through `upgrade_collection_policy.py --confirm-policy-upgrade --approved-by ...`; the prior YAML is first preserved as a read-only `policy_snapshot/archive/v<version>_<hash>.yaml`, and its path/hash/trust status remain in the `project_manifest.json` upgrade history. A missing, writable, version-mismatched, or hash-mismatched active snapshot blocks collection and final audit.

Each task row must declare `target_unique_sources`, `target_records`, and the policy-defined `coverage_requirement`. In final mode, actual source/record/type/platform/primary-source counts must meet the policy target and trace to row IDs. Under frozen policy v5+, each counted output row must also have one verified primary owner in `15_Collection_Record_Registry.csv`; scope, source IDs and recomputed content SHA256 must pass, and copied content cannot count again across rows, files, rounds, or goals. Under frozen policy v6+, source-type and platform counts are derived from the linked source-ledger rows, audit declarations must match exactly, and unused sources cannot pad a count. Under frozen policy v7+, primary-source IDs and counts are derived from task-fit source authority rather than a self-assigned tier. Under frozen policy v8+, each critical claim must hash its text and bind at least two task-owned evidence rows and their substantive fields. R3 applies the saturation thresholds loaded from the same YAML.

- Market definition, historical size, base-year size, five-year forecast, CAGR, segmentation, value chain, supply/capacity where relevant.
- Policy, tariffs, taxes, subsidies, grid access, import rules, standards, certifications, and implementation timelines.
- Power supply, grid reliability, electricity/fuel prices, load/generation patterns, customer archetypes, payment ability, and current alternatives.
- Three player types and representative companies.

Gate:

- Each number and policy claim has URL, publisher, date, geography, unit, and evidence type.
- Under frozen policy v2+, each web source also has controlled source type, publisher group, URL-derived root domain, relation type, and canonical original ID where derivative. R3 dual-source claims must pass all independence dimensions simultaneously; two pages from one publisher/domain, mirrors/reprints of one original, or same-type repetition do not count.
- Market estimates separate published observations from modeled values.
- At least one primary or official source supports every critical policy or tariff conclusion.
- **三轮流进采集（硬性）**：本 Stage 每个 `collection_goal` 在 `02_Web_Collection_Tasks.csv` 中必须有 `round=1/2/3` 三条任务（coverage 广度扫描 → depth 深度提取 → triangulation 补漏与双源交叉验证），**每次爬取至少三轮，禁止提前终止**；每轮记录 `saturation_evidence`。关键市场/政策结论必须至少 2 个独立来源一致（R3）。冻结 policy v3+ 下，市场缺口只有在三轮任务及各自 `count_evidence_refs` 均完成、逐轮查询/尝试来源/失败原因/原始留痕齐全、高优线索为零、影响与解决路径等字段齐全并获得具名人工批准后，才能作为数量不足例外。

## Stage 2: Competitor And Comparison Framework

Deliverables:

- `02_Competitor_List.csv`
- `03_Model_Identifier_Check.csv`
- `竞品名单与对比框架.xlsx`

Tasks:

- Select core competitors using market presence, product similarity, strategic direction, and local channel evidence.
- Include at least 3-5 core competitors and 1-2 representative exact models per brand where the market allows.
- Define at least 15 comparison fields across engineering, compliance, price, channel, service, intelligence, and user experience.
- Verify exact model, regional variant, ASIN/SKU/model code, bundle, and product URL.

Gate:

- Model-level research cannot proceed until identifier status is `exact_match` or a documented regional-equivalence rule is approved.
- Brand-family evidence cannot be used as exact-model evidence.

## Stage 3: Product, Technology, And Compliance

Deliverables:

- `04_Product_Parameters.csv`
- `核心竞品产品参数对比矩阵.xlsx`

Tasks:

- Import user-provided local parameter files first.
- Collect architecture, battery, power, PV, bidirectional charging, protocols, VPP/EMS, safety, environmental, installation, warranty, and service fields.
- Map country-specific grid codes, certification, connector, electrical system, and installation requirements.

Gate:

- Each parameter retains original value/unit, exact model, regional variant, source path/URL, date, and verification status.
- Web-sourced parameters state why local evidence was unavailable or incomplete.
- Conflicts preserve both values and identify the stronger source.

## Stage 4: Pricing, Channel, Service, And Reviews

Deliverables:

- `05_Pricing_Channel.csv`
- `06_Channel_Service.csv`
- `07_Raw_Reviews.csv`
- `08_Review_Coding.csv`

Tasks:

- Collect exact-configuration prices, tax, shipping, installation, promotion, currency, stock, capture date, and at least two channels per key model when available.
- Map online, offline, installer, distributor, utility/VPP, automotive, and service channels.
- Crawl and save the full available exact-model review corpus. Under frozen policy v4+, a platform-limit exception is not a narrative note: `platform_limit_evidence` must point to a structured JSON audit proving the complete accessible, deduplicated corpus across every R2 platform.
- Code pain points, purchase drivers, severity, and frequency only from saved raw rows.

Gate:

- Every price and channel fact has URL and identifier.
- Raw review rows exist before coding.
- Each quote/theme links to raw review IDs and URLs.
- **三轮流进采集（硬性）**：定价/渠道/评论每个 `collection_goal` 必须有 round 1/2/3（覆盖全渠道 → 每型号 ≥2 渠道 + 评论全量语料 → 价格锚点与评论主题双源/双平台交叉验证）；每次爬取至少三轮，禁止提前终止。冻结 policy v4+ 下，R2 评论不足目标只能用结构化 `platform_limit` 例外：关联完整 R1/R2/R3，逐平台记录 URL/访问日期/显示总数/可访问唯一数/原始采集数/去重数、至少两种尝试方式、独立非空留痕和评论行引用；实际有效数必须等于全部可访问上限并与计数审计一致，且高优线索清零、具名人工批准。

## Stage 5: Excel Evidence Workbook

Deliverable:

- `市场调研数据与模型.xlsx`

Required sheet groups:

- Scope and approval.
- Market/policy/demand evidence.
- Competitors and identifiers.
- Parameters.
- Pricing/channel/service.
- Raw reviews and coding.
- Model assumptions and results.
- Integrated matrix and strategic outputs.
- `99_来源与口径` as the final sheet.

Rules:

- Use the embedded Excel pipeline; no separately installed Excel Skill is required.
- **验证链路（验证版，2026-08-09 更新）**：`sync_csv_to_excel.py --theme default|jade`（15 张 sheet，含 `14_Simulated_Modeling_Data`；同步后由 `style_excel_consulting.py` 内置应用 Arial 11、浅色表头、公式黑字/硬编码数值主题色、三线式边框、列宽、筛选、冻结窗格、白底数据行；`delete_rows` 压缩维度；写入 A4 打印区域、横竖版、1 页宽/不限页高并清除固定缩放）→ 内置 `recalculate_excel.py` 调用 LibreOffice 重算 → `validate_excel_delivery.py --mode final`。验证器逐行要求 13 表模型结果为真实公式、重算值与冻结值一致，强制 09/10 非空，并检查视觉样式、打印设置与无原生图表。
- Do not include a visible `数据缺口` sheet. Keep only unresolved market-evidence issues in `11_Evidence_Issues.csv` outside the final workbook, with `data_domain=market`. For frozen policy v3+, preserve the linked three-round task IDs/count audits, a project-relative gap-evidence JSON with per-round attempts and raw captures, zero remaining high-priority discoveries, complete audit fields, and named/date-stamped human approval.
- Missing mathematical-model inputs must be filled with realistic, reproducible simulated data, never left as evidence gaps and never labeled `observed`.
- Put the simulated assumption in `12_Model_Assumptions.csv` with `value_class=simulated`, and its full traceability manifest in `14_Simulated_Modeling_Data.csv`.
- Use formulas for derived fields and include formula notes. Every row in `13_Model_Results.csv` must provide `excel_formula`; use `{{assumption:A-Qx-nnn:low|base|high}}` tokens so the sync script can compile stable cross-sheet cell references.
- Label values as observed, derived, modeled estimate, scenario assumption, or simulated. Final modeling inputs may not remain pending because of missing data.

Gate:

- Formula, unit, currency, date, source, reconciliation, and visual checks pass.
- Every modeled estimate traces to `12_Model_Assumptions.csv`; every simulated input additionally traces to generator code, generated data, calibration evidence, fixed seed, validation, and sensitivity in `14_Simulated_Modeling_Data.csv`.
- Source sheet is last and contains complete URLs.

## Stage 6: Modeling Or Market-Insight Branch

Deliverables:

- `12_Model_Assumptions.csv`
- `13_Model_Results.csv`
- `14_Simulated_Modeling_Data.csv`
- model code/workbook as applicable
- branch analysis memo

### Modeling branch

Use for V2G/V2H economics, storage sizing, load/generation simulation, TAM/SAM/SOM models, forecast/scenario work, channel economics, and pricing sensitivity.

建模分支使用完整数学建模体系（26 skill + decision-prompt-builder），workspace 挂 `intermediate/modeling/`（`intermediate/modeling/CLAUDE.md` 为 schema of record）。**完整链、gate 表、决策工件 schema、round 机制、workspace 目录树与 12/13/14 CSV 映射规则，见 `references/modeling-chain-adaptation.md`（单一事实源）。**

关键机制：

- 2 个人工闸门：G2.5（方法选择，`methods/Qx/decisions/method-selector_modeler_decision.md`）与 G4.5（结果判定，result-report-generator / robustness-checker / final-method-explainer 三份决策工件），全部 `status: DECIDED` + `decided_by: human`。
- round 机制：round1 必跑；round2 仅当 G4.5 判 `iterate`；上限 3 轮。
- 12/13/14 CSV 由 `scripts/create_modeling_artifacts.py` 生成（12 ← `planning/model_assumptions.md`，13 ← 各 Qx `frozen_numbers.json` 展开，14 ← `workspace/data/simulated_modeling_data.csv`），禁止手工编辑。
- 竞赛论文层（paper-sections/LaTeX）不接入；结果经 12/13/14 CSV 进 Stage 7 Word 报告。

Minimum outputs:

- Baseline and intervention scenarios.
- Equations, symbols, units, constraints, assumptions, and calibration sources.
- CAPEX/OPEX, savings/revenue, degradation, NPV, IRR, payback, and sensitivity when relevant.
- Low/base/high or Monte Carlo uncertainty where the decision warrants it.
- Validation, reconciliation, and robustness results.

### Market-insight branch

Use when the task is primarily qualitative or evidence-synthesis oriented. Load the bundled `market-insight-five-views.md` and `market-insight-report-contract.md`; an independently installed `market-insight` Skill is optional. Convert data phenomena into product and market decisions while preserving fact/calculation/interpretation/recommendation/counter-evidence separation.

Required artifact:

- `intermediate/market-insight/market_insight_report.md`

Required method:

- `method_id: embedded-market-insight-five-views-v1`
- Five Views: macro, industry, customer, competition, and self/strategic fit.
- Material claims use `【证据：ID】` anchors resolving to project CSV rows.
- Every View ends with implications; the report ends with So What, prioritized actions, and risks/uncertainties.

Gate:

- No result without traceable inputs.
- Model checks and sensitivity pass.
- Insights reference evidence row IDs.
- `scripts/validate_market_insight.py --mode final` passes for the market-insight branch.
- 建模分支另加：G2.5 / G4.5 决策工件 DECIDED；12/13/14 与模拟代码、生成数据及 `frozen_numbers.json` 对账一致。

## Stage 7: Word Report And Strategy Synthesis

Deliverable:

- `市场深度调研与商业机会报告.docx`

Required narrative:

- Executive conclusion.
- Scope, definitions, and methodology.
- Market, policy, demand, and scenario findings.
- Competition, product, price, channel, service, and user findings.
- Economics or market-insight results.
- Business model, product definition, market-entry strategy, risks, roadmap, and action owners.
- Source/method appendix and labeled estimate notes.

### Word Report Generation Workflow (Critical)

**Step 1: Strip template placeholder chapters**

The template has 14 placeholder chapters with empty tables and placeholder text. These MUST be removed before adding content:

```python
from word_report_helpers import strip_all_template_chapters
doc = Document(str(TEMPLATE))
strip_all_template_chapters(doc)
```

This function removes all H1 sections while preserving `w:sectPr` (page layout properties).

**Step 2: Replace cover placeholders**

```python
from word_report_helpers import set_run_font
# Replace [[目标区域]], [[产品类别]], [[更新日期]], [[数据截止日期]], [[版本号]]
```

**Step 3: Add narrative content with proper table formatting**

Use `add_three_line_table()` from `word_report_helpers.py` for all tables:

```python
from word_report_helpers import add_three_line_table, add_source_note

add_three_line_table(doc, '表3-1 标题',
    ['列1', '列2', '列3'],
    [['值1', '值2', '值3']],
    source='数据来源说明'
)
```

This automatically applies:
- Three-line borders (top/bottom 1.5pt black, header 1pt deep blue)
- Header shading (#D9E2EC)
- Proper font (宋体小五 9pt + Times New Roman)
- Vertical/horizontal centering
- No first-line indent
- Single line spacing
- keep_with_next/keep_together on captions

**Step 4: Generate charts through the single-owner route and insert them**

- Market-insight evidence and strategy charts: `figure_class=market-insight`, `figure_owner=embedded-market-figure-v1`, fixed Python backend.
- Modeling output, economics, sensitivity, robustness, and modeling workflow charts: `figure_class=modeling`, `figure_owner=embedded-modeling-figure-v1`, fixed Python backend.
- Never call `word_report_helpers.generate_chart_png()` to create a final chart directly. The Word helper may insert already approved PNG/SVG assets, but it is not a final figure generator.
- Never send a completed figure from one embedded owner to the other for restyling. Insert the owner's passed SVG/PNG output and retain its `.theme.json` manifest after `validate_figure_delivery.py` and `register_figure_delivery.py` pass.

```powershell
# Standard market-evidence figures; final mode requires a confirmed claim registry.
python scripts/render_charts.py --project-dir <project> --claim-registry <claims.json> --mode final

# Declarative market or modeling figure (including traceable realistic simulation metadata).
python scripts/render_figure_from_spec.py --project-dir <project> --spec <figure-spec.json> --mode final

# Open every PNG/SVG, then register and validate each theme manifest.
python scripts/register_figure_delivery.py <figure.theme.json> --project-dir <project> --confirm-visual-inspected
python scripts/validate_figure_delivery.py <charts-dir> --project-dir <project> --mode final

# After the narrative is complete, place every approved figure after its declared analysis paragraph.
python scripts/insert_approved_figures.py <report.docx> --charts-dir <charts-dir> --mode final
```

**Chart naming convention**: `figN_*.png` (e.g., `fig1_price.png`, `fig2_mix.png`)
**Chart style**: White background + restrained deep-blue/cool-grey brokerage palette; Chinese text must remain editable in SVG and declare an installed CJK font family.

**Step 5: Save and render**

```python
doc.save(str(OUTPUT))
# Then render with libreoffice_render.py for QA
```

Gate:

- Use the embedded Five Views market-insight branch or the modeling chain for content, and use `embedded-word-production-v1` for template typesetting, structural QA, bounded render review, and final manifest registration.
- **Word 生成走官方生成器** `scripts/build_template_report.py`（券商模板骨架填充：封面占位符 + 每章表 X-1 真实数据 + 图表插入）。
- **验证版规则**（详见 `format-and-visual-style.md`）：表格居中宋体小五 9pt；三线表顶线/底线为黑色 `#000000`、1.5 pt，表头下线为深蓝 `#1B365D`、1 pt，表头浅蓝灰底 `#D9E2EC`、表体白底；图片单倍行距；图表 SVG 保留可编辑文本与显式 CJK 字体样式；图表使用内嵌白底券商配色。
- LibreOffice QA must use `scripts/libreoffice_render.py` with an isolated profile, valid Windows file URI, 120-second timeout, and PyMuPDF-rendered page PNG output.
- Apply `format-and-visual-style.md`.
- Unless shortened by the user, target 15,000-30,000 Chinese characters and at least 30 pages.
- Inspect every rendered page.
- After inspection, run `scripts/register_word_delivery.py` with `--confirm-all-pages-inspected`; final validation accepts only the matching final DOCX hash and the embedded component list.

## Stage 8: PPT And Final Handoff

The final PPT is accepted only after the formal embedded handwritten-SVG pipeline and full visual QA. Register it with `scripts/register_high_fidelity_ppt_delivery.py`; `deliverables/ppt_production_manifest.json` must record the matching file hash, full slide count, inspected page count, at least one render-inspect-fix-rerender cycle, and passed cover compliance. `register_ppt_delivery.py` is fallback-only and additionally requires `--fallback-reason`. Automated package-builder decks are drafts and cannot satisfy the final gate by file existence alone.

Deliverables:

- `市场调研内部宣讲PPT.pptx`
- final Word and Excel files
- `evidence_audit.md`

Tasks:

- Build a 10-18 slide answer-first narrative from the approved report, workbook, evidence ledger, and approved figure manifests. After the eight confirmations, the current main agent writes pages serially as SVG under `presentation_project/svg_output/`, re-reading `spec_lock.md` before every page; scripts must not batch-generate the page SVGs.
- Run `scripts/resolve_presentation_images.py` first. Use cover Path A by default: deep-blue technology cover plus an EWO-generated vector-illustration-style raster visual in PNG, JPEG, or WebP format. The image-acquisition manifest records its prompt, path, normalized format, and SHA-256.
- Use cover Path B (light consulting fallback) only after a normalized EWO connectivity, credential, permission, balance/quota, timeout, upstream, or global-disable failure. Body illustration failures become handwritten SVG vector diagrams and are exported as editable native-PowerPoint objects. User preference alone is not a valid failure reason.
- Build a 15-minute executive story from the approved workbook/report.
- Include answer-first titles, dense charts, key assumptions, counter-evidence, source/update/bias footers, decisions, and next actions.

**渲染 QA 链路（验证版）**：

- `scripts/libreoffice_render.py <pptx> --output-dir <qa> --render-pages --timeout-seconds 120` 生成非空 PDF 与逐页 PNG。
- 生成缩略图网格，逐页视觉检查无重叠或溢出。
- `python scripts/scan_office_placeholders.py <pptx>` 直接扫描 OOXML，检查无 `[[xxx]]` 等占位符残留；无需 MarkItDown。
- 至少完成一次“渲染—发现问题—修复—全量重渲染”，并将实际问题与修复记录传给 `register_high_fidelity_ppt_delivery.py --visual-fix-cycle-count 1 --visual-inspection-notes <notes>`。

Gate:

- Render and inspect every slide.
- The PPT production manifest records `default_path=A_ai_image`; Path A has a valid cover-image path/hash, while Path B has a non-empty AI-generation failure reason.
- Run all stage validators and the final evidence audit.
- Confirm `.docx`, `.xlsx`, and `.pptx` exist and open.
