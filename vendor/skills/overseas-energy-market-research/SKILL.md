---
name: overseas-energy-market-research
description: End-to-end domestic and global market research for energy products and systems, with a self-contained Five Views market-insight branch, especially for residential storage, portable storage, balcony PV-storage, V2G/V2H, bidirectional charging, HEMS/EMS, VPP, microgrids, and vehicle-grid pilot projects. Use for any country, region, province/state, or city when the user asks for a research plan or outline, market sizing, policy and tariff analysis, customer/industry/competitor insight, demand/load modeling, exact-model benchmarking, pricing/channel/service research, review mining, economic modeling, business-model design, product definition, market-entry strategy, or Chinese consulting-style Excel/Word/PPT deliverables.
---

# Domestic And Global Energy Market Research

## Mission

Act as a residential-storage and V2G system engineer, product manager, and senior market researcher. Produce decision-grade research for China or any global market without hard-coding a country, channel, standard, currency, or language.

Default to Chinese deliverables. Preserve original brand names, model numbers, standards, protocols, URLs, and short source quotations where accuracy requires them.

## Mandatory Execution Order

For a full research project, execute in this order:

1. Draft the research plan and detailed outline.
2. Pause for human review and obtain explicit approval.
3. Collect and inspect online evidence through the collection router: use `anysearch` for search and static-page extraction, and use `kimi-webbridge` only for dynamic, authenticated, or interactive browser tasks.
4. Build, style, recalculate, and audit the Excel evidence/model workbook with the embedded Excel pipeline.
5. Branch to mathematical modeling or the bundled Five Views market-insight workflow.
6. Produce and verify the Word report.
7. Produce and verify the presentation with the embedded presentation pipeline.

Do not start web collection before the outline approval gate passes. A user message that explicitly approves the proposed outline is sufficient; record it in `00_Research_Approval.csv`.

For a narrowly scoped follow-up task inside an already approved project, reuse the recorded approval and narrow the decision scope, but do not reduce the mandatory collection-goal family floor or the three-round requirement. If scope materially changes, update the outline and request approval again.

## Non-Negotiable Integrity Rules

- Never present an invented value as observed market data.
- Attach a source URL to every web-collected fact. Keep URLs beside sensitive rows during analysis and place the complete source ledger in the last Excel sheet, `99_来源与口径`.
- Distinguish `观测值`, `推导值`, `模型估算`, `情景假设`, and `待核实`. Never convert a missing observation into an unlabeled fact.
- Keep only missing **market evidence** in the internal audit file `11_Evidence_Issues.csv` with `data_domain=market`; do not expose a `数据缺口` sheet in the decision workbook. Under frozen quantity-policy v3+, a `market_gap` quantity exception is valid only after the same scoped goal completes R1/R2/R3, all three task count-audit JSON files are linked, every round records attempted queries/source IDs/failure reasons/project-local raw captures, zero high-priority discoveries remain, the reason/decision impact/resolution path/owner/status/source context are complete, and a named human records dated approval. A narrative assertion of “not found” never qualifies.
- Missing mathematical-model inputs may not remain as gaps. Fill them with the most realistic reproducible simulation that available evidence and physical/business constraints permit.
- Mark every such input `value_class=simulated` in `12_Model_Assumptions.csv`, and document it in `14_Simulated_Modeling_Data.csv`. Never label simulated data `observed`.
- A simulated input must retain calibration source IDs/URLs, method or distribution/process, parameters, physical bounds, correlation/time structure, fixed random seed, sample size, generator-code path, generated-data path, validation result, and sensitivity/uncertainty. Calibration and material simplifying assumptions remain subject to human approval.
- Put formulas in Excel cells for all calculations. Do not hard-code calculated outputs. Audit units, signs, currencies, time bases, and formula references.
- Use exact model identifiers for product facts. Verify ASIN, SKU, model code, certification ID, regional variant, bundle, and product URL before merging parameters, prices, or reviews.
- Collect and save the raw exact-model review corpus before coding themes or quoting users. A platform-limit claim must prove that every accessible unique review was collected; a prose note is not evidence.
- Prefer user-provided local files for product parameters. Use web parameters only when local files are absent, incomplete, or contradicted by stronger official evidence, and record the reason.
- Separate facts, calculations, interpretations, and recommendations. Bind every strategic judgment to evidence row IDs.

## Intake And Localization

Capture these inputs before drafting the outline:

- Decision to support and intended audience.
- Geography level: global, region, country, province/state, city, or pilot project.
- Product/system boundary and exact use cases.
- Historical period, base year, forecast horizon, and required update date.
- Customer segments and application scenarios.
- Required deliverables and depth.
- Available local parameter files, internal data, templates, and prior studies.
- Currency, tax basis, unit system, language, exchange-rate convention, and price date.
- Required standards, certification, grid codes, tariffs, subsidies, and market-access rules.

If details are missing, make reasonable draft assumptions in the outline and ask the reviewer to approve or edit them. Do not silently freeze material assumptions.

### Regional adapter

Build a market-specific source map instead of copying channels from another country:

- China: national/provincial/municipal government, NDRC, NEA, MIIT, SAMR, grid companies, power exchanges, industry associations, official tenders, company filings, Tmall/JD/1688/Suning, local installers and distributors.
- Other markets: national regulator, energy ministry, grid/market operator, utility/VPP programs, standards/certification bodies, official statistics, local marketplaces, electronics/home-improvement retailers, installers, distributors, automotive channels, and brand stores.
- For every geography, identify local terminology and search in Chinese, English, and the local language when useful.

## Research Architecture

Load `references/deliverables.md` and use its stage gates. Select modules by the decision question:

### Market and policy

Cover market definition, TAM/SAM/SOM, historical and forecast size, growth, segmentation, value chain, supply/capacity where relevant, policy, tariffs, taxes, incentives, grid access, standards, certifications, trade rules, and macro risks.

### Demand and scenario

Build representative customer or project archetypes, 24-hour/seasonal load and generation curves, outage or grid-quality conditions, EV travel/availability, energy spending, willingness and ability to pay, and current alternatives.

### Product and engineering

Cover architecture, battery, inverter, PV input, charging interface, bidirectional power, grid connection, backup transfer, protocols, VPP compatibility, HEMS/EMS, safety, IP rating, thermal design, installation, warranty, serviceability, and exact regional compliance.

### Competition, channel, and users

Cover player taxonomy, exact models, parameters, price/configuration, promotions, online/offline channels, installer/service networks, financing, rankings, raw reviews, user pain points, and purchase drivers.

### Economics and business model

Cover baseline vs solution economics, CAPEX/OPEX, energy savings, export/VPP/service revenue, battery degradation, replacement, financing, tax, NPV, IRR, payback, sensitivity, scenarios, revenue allocation, partners, and who pays/benefits.

### Product definition and strategy

Translate evidence into target segments, prioritized geography, SKU/capacity/power, required protocols/certifications, price corridor, channel entry, service model, pilot plan, risks, milestones, and owner-based actions.

## Product-Specific Extensions

Load `references/data-fields-and-sources.md` before building schemas.

- V2G/V2H: tariff windows, export rules, aggregator/VPP/ancillary-service access, EV compatibility, connector/protocol, vehicle availability, minimum state of charge, degradation, dispatch frequency, interconnection, and stakeholder revenue share.
- Residential/balcony storage: PV/load curves, self-consumption, backup, anti-backflow, coupling, MPPT, inverter limits, installation, dwelling type, and tariff optimization.
- Portable/off-grid storage: outage hours, fuel-generator alternative, appliance basket, charging access, productive-use revenue, affordability, PAYG, dust/heat/humidity, and serviceability.
- Pilot-project benchmarking: project owner, site, scenario, status, technical route, facility/vehicle scale, platform, business model, tariff/subsidy, operational results, replicability, and bottlenecks.

## Mandatory Data-Source Routing

Load `references/data-fields-and-sources.md` and `references/kimi-webbridge-collection-playbooks.md`, then apply these routes:

- Social-media/user-voice data: include Reddit and YouTube plus relevant local communities; retain raw URLs, dates, context, and exact-model linkage. Treat these as Tier 3 evidence.
- Modeling inputs: use local/internal and official national/operator data first, then World Bank, `https://energydata.info/dataset/`, `https://www.globalpetrolprices.com/`, other official/research sources, and traceable media.
- Price/promotion: include Amazon.de, MediaMarkt, Galaxus, brand stores, and relevant local retailers. For Amazon.de, complete `asin_search`/exact-match ASIN verification before collecting price, promotion, reviews, ranking, availability, channel, service, or parameters.
- Product specifications: prefer exact regional official product pages, manuals, datasheets, support, and certification pages; use `https://device.report/` only as a secondary discovery/cross-check source with explicit conflict notes.
- If the applicable routes yield no usable market observation, log a market-evidence issue. If a mathematical model still needs the input, generate the most realistic traceable simulated input, record low/base/high quantiles, and never label it `observed`.

## Search And Collection Contract

Before collection, load `references/kimi-webbridge-collection-playbooks.md`; it is the complete routing and quantity-integrity contract.

- Collection tools are embedded in this skill. `anysearch` is the official 3.0.1 CLI copied verbatim into `scripts/anysearch/` (search / batch_search / extract / get_sub_domains / doc; `--api_key > .env > env var > anonymous`; Apache 2.0 notice in `scripts/anysearch/README_embedded.md`). `kimi-webbridge` is driven through the embedded client `scripts/_kimi_webbridge.py` (`command()` payload is field-for-field identical to the official curl examples; contract and operations docs are embedded in `references/kimi-webbridge-client-contract.md` and `references/kimi-webbridge-operations.md`). No external skill installation is required; the anysearch API and the kimi daemon + browser extension remain runtime prerequisites (kimi daemon auto-start and diagnostics are embedded).
- Use the unified entry `scripts/web_collection/cli.py` (`doctor` first; then `search` / `batch-search` / `extract` / `browse` / `auth-check` / `journal-summary`). It auto-writes the collection attempt journal `13_Collection_Attempt_Journal.csv` and raw captures under `raw_capture/<goal>/`. When the machine still has the official skills, `--official-cli` keeps the byte-identical external path; `doctor` compares hashes and warns when the embedded copy is out of sync.
- Use `anysearch` for general/vertical search, batch search, static pages, reports, news, and PDF-to-markdown extraction. Use `kimi-webbridge` only for dynamic, authenticated, or interactive browser work, or as the documented fallback after extraction failure. Never invoke both merely to satisfy form.
- Save raw captures, exact URLs, access dates, and the actual collection tool. Never bypass access controls or claim evidence was collected when the required browser connection was unavailable. Login walls, disconnected browser extensions, stopped daemons, and insufficient API balance are recorded explicitly (`auth_required` / `bridge_unavailable` / `tool_unavailable` / `insufficient_balance`) and block task completion.
- Initialize every project from `assets/config/collection_quantity_policy.yaml`, freeze the exact policy snapshot, and derive scope/task totals from it. Existing projects always use their verified frozen snapshot; upgrades require explicit human approval through `scripts/upgrade_collection_policy.py`.
- Create every applicable scoped goal and all three rounds: R1 coverage, R2 structured depth, and R3 triangulation. Numeric floors are minimums, not stopping targets; a family may not be marked N/A or merged merely to reduce work.
- Treat task counts as derived audit outputs. Source independence, market/platform exceptions, record ownership and content hashes, type/platform derivation, task-qualified primary sources, and critical-claim evidence bindings are enforced by the frozen policy and validators. Do not duplicate or reinterpret policy-version rules in prompts.
- Only missing market facts may use the audited `market_gap` path. Missing modeling inputs must use the reproducible Python simulation workflow. Review shortfalls may use `platform_limit` only through its structured, approved evidence contract.
- **审计缺口闭环（v1.2.6）**：当最终审计（`run_workflow.py --mode final --strict-final-files`）暴露低于轮次目标的缺口时，按此闭环处理——(1) 核实缺口为真实公开证据缺失（R1/R2/R3 轮次均已执行并登记 count_evidence 审计）；(2) 按 `assets/templates/csv/data_gaps_template.csv`（`11_Evidence_Issues.csv`）登记 `market_evidence_gap` 记录，并生成 `audits/market_gap/GAP-xxx.json`（模板 `assets/templates/json/market_gap_evidence_template.json`，每轮含 attempted_queries/attempted_source_ids/failure_reasons/raw_capture_refs）；(3) 经用户人工批准（`exception_approval_status=approved` + 具名审批人/日期/理由）；(4) 02 表对应任务挂 `quantity_exception_type=market_gap` 与 `quantity_exception_refs=GAP-xxx`；(5) 重跑 `generate_collection_audits.py`（空分段会打印 `[WARN]` 诊断）→ 重跑最终审计。R3 关键声明在有效 market_gap 例外 + gap 审计含真实 R3 失败记录 + 无遗留高优发现时，可用**缺口验证声明**替代双源三角验证（v1.2.6 受控豁免）。
- Run `scripts/validate_collection_tasks.py`, `scripts/validate_source_ledger.py`, and `scripts/validate_collection_attempts.py` after collection updates; the attempt journal mechanically checks anti-under-collection (every R1/R2/R3 task has attempts at or above its target/floor), anti-fake-completion (unresolved blocking errors forbid completed status), failure reasons, and raw-capture existence. Final counts must resolve to source-ledger IDs, registered record rows, and substantive evidence fields.
- **生成器项目配置（v1.2.6）**：`generate_collection_audits.py` 的 registry 写入（market/created_date）、URL→来源提示表、06 渠道品牌映射、04 表 technology_performance 分类关键字、08 编码主题继承映射均来自冻结策略快照的 `generator_overrides` 段（模板默认保持既有行为）。跨市场项目通过 `scripts/upgrade_collection_policy.py --confirm-policy-upgrade --approved-by <人> --overrides <yaml>` 注入项目定制值（如 `market: Australia`），生成器自动写入 registry，无需生成后手工修补。回归：`scripts/regression_test_collection_audits.py`。

## Skill Routing

### Excel

Load `references/deliverables.md` and `references/format-and-visual-style.md`, then use the embedded Excel pipeline; no separately installed `excel-master` or spreadsheet Skill is required.

- Build and validate the CSV evidence/model tables first. Write only through explicit project-root paths, preserve the template schemas, and run the relevant validators immediately after changes.
- Run `scripts/sync_csv_to_excel.py --theme default|jade`; it synchronizes the CSVs and applies the embedded light consulting style while preserving formulas, then **automatically recalculates formula caches via LibreOffice** when available (pass `--skip-recalc` to disable; if LibreOffice is missing it prints a reminder). Verify every sheet row count against its source CSV. Do not generate Excel-native charts; Word owns report charts and PPT reuses approved figures.
- Preserve formulas and formula notes; separate observations, assumptions, calculations, results, and sources. Keep `99_来源与口径` last with complete URLs.
- Recalculate the workbook and run `scripts/validate_excel_delivery.py --project-dir <project> --mode final`. Require every modeled result to contain a compiled Excel formula, reconcile recalculated values to frozen results, reject empty 09/10 strategy sheets, and enforce the embedded font/fill/border/filter/freeze/print style contract plus A4 one-page-wide print layout with no fixed scale.

### Mathematical modeling

建模分支（`analysis_branch = modeling`）使用完整数学建模体系。**24 个建模 skill 指令文档已内嵌**
（`references/modeling_chain/`，零 diff 搬运、MIT，见 `references/modeling_chain/README_embedded.md`），
不依赖外部建模 skill 安装。**`intermediate/modeling/CLAUDE.md` 是 schema of record（单一事实源）**——
先加载该文件再执行建模链；完整契约见 `references/modeling-chain-adaptation.md`；
机械门验证：`scripts/validate_modeling_chain_gates.py --project-dir <项目>`（G1/G2/G3/G6 +
复用 `create_modeling_artifacts.py` 的决策门 G2.5/G4.5 与冻结新鲜度 G4）。

适配后完整链（科学层，去掉竞赛论文层）：

```
【0】problem-parser(输入=research_outline.md问题树) → problem-classifier
    → related-paper-analyzer(可跳过) → symbol-table-builder → model-assumptions-builder
    → planning/question_dependency.md     [G1 机械门]
【1】method-selector → methods/Qx/qx_method_candidates.md   [G2 机械门]
    → decision-prompt-builder → methods/Qx/decisions/method-selector_modeler_decision.md
                                          [G2.5★ 人工门]
【2】data-auditor-cleaner(输入=01~11 CSV) → model-code-analyzer
    → python/matlab-model-code-generator → code-reviewer(路由) → 语言reviewer
    → results/Qx/experiments/roundN/      [G3 机械门]
【3】result-report-generator → qx_experiment_report_roundN.md
【4】decision-prompt-builder → result-report-generator / robustness-checker /
    final-method-explainer 三份决策工件    [G4.5★ 人工门]
【5】final-method-explainer → qx_final_method_explanation.md
【6】result-report-generator(final) → qx_final_result_analysis.md
【7】robustness-checker → robustness/Qx/qx_robustness_report.md
【8】figure-table-planner(仅规划) → embedded-modeling-figure-v1（每图先 human-confirmed core claim，
    SVG 主 + 300dpi PNG 辅）
【9】solution-package-builder → qx_solution_package_for_writer.md + frozen_numbers.json
                                          [G4 机械门]
【10】consistency-auditor → completeness-auditor → quality-assurance-auditor
                                          [G6 三审计全 PASSED]
```

**2 个人工闸门（G2.5、G4.5）**：决策工件放 `methods/Qx/decisions/<skill>_modeler_decision.md`，必须 `status: DECIDED` + `decided_by: human` + `## Modeler's rationale` 非空且非逐字复制 `ai_suggestion` + 引用 `evidence_refs`。**AI 永不自设门通过、永不填写人工 rationale 最终内容**；每个闸门前先经 `decision-prompt-builder` 发 2–3 个 trade-off 问题。

**round 机制**：round1 必跑；round2 仅当 G4.5 的 `qx_result_verdict.round_decision == iterate` 触发；`return` 回方法修订；`proceed` 锁定；任何 Qx 最多 3 轮。

**12/13/14 CSV**：由 `scripts/create_modeling_artifacts.py` 从建模 workspace 生成（12 ← `planning/model_assumptions.md`，13 ← 各 Qx `frozen_numbers.json` 展开，14 ← `workspace/data/simulated_modeling_data.csv`），**禁止手工编辑**。记录 equations, symbols, units, constraints, assumptions, calibration, validation, sensitivity, uncertainty, and limitations；模型图统一挂 `intermediate/modeling/robustness/Qx/figures/` 与 `intermediate/modeling/results/Qx/experiments/roundN/figures/`。

The embedded owner `embedded-modeling-figure-v1` is solely responsible for modeling-branch figures: forecasts, optimization outputs, economics, baseline comparisons, sensitivity, robustness, and modeling workflow diagrams. Before generating each figure, define the human-confirmed core claim (or retain a sentinel in draft mode), figure type, panel map, exact source data, output files, and report/slide placement. Never fabricate chart data. When modeling inputs are unavailable, use realistic Python simulation with method, seed, assumptions, and calibration sources recorded in the manifest. Export editable SVG as the primary artifact and PNG at 300 dpi or higher as the secondary artifact, preserve text in SVG, save the plotting source data, and pass mechanical plus visual checks before Word/PPT integration. No separately installed figure Skill is required.

### Embedded market insight

When `analysis_branch=market-insight`, do not depend on a separately installed market-insight Skill.

1. Load `references/market-insight-five-views.md` and `references/market-insight-report-contract.md`.
2. Fill `intermediate/market-insight/market_insight_report.md` from `assets/templates/markdown/market_insight_report_template.md`.
3. Analyze macro environment, industry/market, customer/use cases, competition, and self/strategic fit. Mark any approved out-of-scope View explicitly.
4. Bind material claims with `【证据：ID】` anchors resolving to project CSV rows. Separate fact, calculation, interpretation, recommendation, and counter-evidence.
5. End every View with implications; end the report with So What, prioritized actions, and risks/uncertainties.
6. Run `scripts/validate_market_insight.py --project-dir <project> --mode final` before Word or PPT writing.

The embedded method identifier is `embedded-market-insight-five-views-v1`. An external `market-insight` Skill may be used only as an optional cross-check and cannot override the approved outline, evidence rules, source routing, or embedded report contract.

### Word

For market research narrative, use the embedded Five Views branch above. For modeling narrative, use the modeling chain above. Use the embedded Word pipeline for template-based typesetting, structural QA, bounded rendering, and page inspection; no separately installed `kami`, `docx`, or `documents` Skill is required.

**图表唯一责任路由（硬性）**：每张正式图表只能有一个内嵌 `figure_owner`，禁止市场图与建模图两个分支对同一图表串行重复生成或二次美化。

- `figure_class=market-insight` → `figure_owner=embedded-market-figure-v1`：负责市场规模、政策时间线、竞品/价格/渠道/评论分析、价值链和战略框架等非模型证据图。后端固定为 **Python**；市场数据不足时只能记录证据缺口，禁止用模拟值补图。
- `figure_class=modeling` → `figure_owner=embedded-modeling-figure-v1`：负责预测、优化、经济性、基线比较、敏感性、稳健性和建模流程图；建模输入缺失时使用最真实的 Python 模拟数据，并完整记录模拟方法、随机种子、假设与校准来源。
- 内嵌演示管线优先复用已验收的上述图表；仅对幻灯片专属框架制作可编辑 PowerPoint 原生矢量视觉，不得用同一数据重新生成另一份图表。
- 两类图表共同使用 `scripts/figure_production.py`、`scripts/render_charts.py` / `scripts/render_figure_from_spec.py`：定义核心主张、图表类型、面板布局和精确数据源；应用 `kami-broker-v2` 白底券商配色（`apply_kami_broker_theme_v2()`）；每张图保存前必须执行 `bump_min_font(fig, 8)`（8 pt 标签下限）与 `apply_mixed_text_fonts(fig)`（中英双轨：纯拉丁/数字 Times New Roman，混合串 'SimSun','Times New Roman' 回退），图内顶部零文字（无标题/饰线/图注，Word 图题行承载，防重叠；`title_block` 为 no-op）；生成可编辑文本 SVG + ≥300 dpi PNG；记录来源、脚本与输出哈希；通过 `validate_figure_delivery.py` 和 `register_figure_delivery.py`。禁止装饰性素材图、渐变、3D 效果、matplotlib 默认色板泄漏和不可追溯数据。

- **图表美化与多样性（硬性）**：图表生产优先复用 `scripts/chart_polish.py` 的券商研报级组件——浅色面板（#F7F9FC）、细网格、label-safe 数据标签避让（`place_bar_labels`，禁止标签堆叠）、`save_manifest`（自动写入 generator/源 hash/qa 块，避免注册时 PermissionError）。图型选择遵循 `references/chart-polish-and-variety.md` 的选择矩阵：占比用环形图、量级跨度大用对数气泡图、风险用 2×2 矩阵、层级收窄用漏斗图、价值桥接用瀑布图；同一章节块不得全是柱状图。theme manifest 的 `figure_contract.figure_type` 必须准确标注实际图型。**图表机械回归门禁（硬性）**：注册/插入 Word 前必须运行 `scripts/verify_chart_svg_quality.py --charts-dir deliverables/charts`（字号 ≥8pt、色板白名单、字体双轨按内容判定、图内顶部零文字、文本重叠解析兼容两种属性顺序），退出码 1 即阻断。写作层预控：底部刻度按柱间距 `fit_label` 截断、类别轴禁数据坐标装饰带、Pareto 数值入柱、标注带白底+象限偏移。完整规则见 `references/chart-polish-and-variety.md` §5 与 `references/kami-broker-chart-theme.md`。
- **纯文本模型图表契约（硬性）**：没有多模态能力的模型不得凭视觉模仿图表。每个 spec 必须先写 `core_claim`、`visual_intent`、`encoding.relationship` 与精确字段，优先使用 `figure_type: auto`；`render_figure_from_spec.py` 会把关系确定性路由为 line/timeline、lollipop、donut、waterfall、diverging-bar、scatter、risk-matrix、heatmap、funnel 或 grouped-bar，并在 manifest 中写入实际图型。最终图表数 ≥6 时，柱状图家族占比必须 ≤60%，实际图型至少 3 类，否则 `validate_figure_delivery.py` 阻断。执行细则见 `references/text-only-chart-and-slide-design.md`。
- **单一图型次数上限（硬性、机械门禁）**：整份最终报告中任一标准化图型最多出现 2 次；`trend-line`/`bar_line` 归入 `line`，`scatter-positioning` 归入 `scatter`，`coverage-heatmap` 归入 `heatmap`，`evaluation-ranking` 归入 `pareto`，`evaluation-comparison` 归入 `radar`，禁止改别名绕过。`save_figure_bundle()` 在生成第三张同型图之前立即阻断，`validate_figure_delivery.py` 在组合交付时再次统计阻断。达到 2 次后必须重写证据关系并选择另一种真实适配的图型，不得只改名称。
- **无视觉模型图表协议（DeepSeek 等，硬性、机械门禁）**：文本模型只提交 `core_claim`、数据字段、`visual_intent`/证据关系、来源和章节落点，不得自行批准画面，也不得伪造人工视觉确认。`render_figure_from_spec.py` 的确定性解析器接管选型、字体、配色、标签、留白与长文本布局；`automated_visual_qa` 检查字号、文字越界、实质文字碰撞、异常画布比例与文字密度。最终图允许人工视觉确认或自动视觉 QA 通过二选一；DeepSeek 必须走后者。除图型上限外增加视觉家族上限：bar、ranking-bar、grouped-bar、lollipop、dot-plot 均归入 `single-axis-comparison`，全篇合计最多 4 次，禁止用棒棒糖替换柱状图制造虚假多样性。优先使用 KPI/决策卡片、折线、环形、情景区间、评分卡、风险卡片、Pareto、漏斗、热力图、散点等真正不同的语法。

**每章必有图表规则（硬性）**：报告每一章（即每个一级标题下的章节）至少包含一张正式图表（figN_*.png）。不允许任何章节仅有文字而无图表。若某章节数据不足以支撑图表，必须使用示意图、流程图或框架图补充，仍需遵循图表命名和格式规范。

**图表接文规则（硬性）**：图表不得单独出现或悬空插入，必须紧跟在成段文字之后。插入顺序为：先写完该图表对应的分析段落，段落末尾引用图表（如"见图N-x"），然后在同一位置插入图表、图题和来源注。禁止在章节开头、空白段落后或两个图表之间无文字过渡的情况下直接插入图表。

**Word 生成规则（验证版，官方生成器 `scripts/build_template_report.py`）**：

1. **以券商模板骨架填充**，不从零排版：从 `assets/templates/word/energy_market_research_report_template.docx` 复制，保留页眉页脚（页眉左机构名"四川动力电池产业创新中心"+右"能源与电力设备专题研究"+免责条款）、章节结构、嵌入图片、三线表。
2. **封面占位符替换**：`[[目标区域]]` `[[产品类别]]` `[[更新日期]]` `[[数据截止日期]]` `[[版本号]]`。
3. **每章表 X-1 填入证据 CSV 真实数据**（不新增表格）；清理模板示例行残留的 `[[xxx]]` 占位符。
   **一级标题规则（硬性）**：所有一级标题必须以 Heading 1 或等效直接格式实现，22 pt 黑体加粗、整体居中，并显式设置左缩进、右缩进、首行缩进均为 0（同时清除字符单位缩进 `rightChars` 等，其在 Word 中优先于磅值缩进）；一级标题不带底部横线（删除样式与段落级 `pBdr` 底边线，横线横跨整栏会让居中标题看起来居左）；仅设置 `center` 而保留模板缩进或横线视为失败。
   **前置内容规则（硬性）**：生成报告只保留正文；封面之后如存在"文档控制与使用说明"章节（`strip_template_front_matter()`）必须删除。
   **模板残留章节检测（硬性）**：生成报告后必须检查是否存在重复章节标题（如同一编号出现两次，如两个"二、"章节）。若发现重复，删除模板残留版本（通常内容较短或为占位文本），保留实际内容版本。检测方法：遍历所有 Heading 1 标题，检查是否有相同编号前缀重复出现。
   **章节文字完整性（硬性）**：每个章节（Heading 1）和子章节（Heading 2）的标题之后、图表之前，必须有至少一段实质性分析文字（≥50字符）。禁止标题后直接跟图表。若内容不足，必须补充该章节的分析概述段落。
4. **表格规则**：整体居中、宋体小五 9pt + Times New Roman、表头加粗、全部文字水平垂直居中、无首行缩进、段前段后 0、单倍行距；严格三线表采用黑色 `#000000` 的 1.5 pt 顶线和底线，表头下线采用深蓝 `#1B365D`、1 pt，禁止左右边线、竖线和表体内部横线；表头统一浅蓝灰底 `#D9E2EC` + 深蓝字，表体保持白底。
   **表题分页规则（硬性）**：所有表题居中并设置 `keep_with_next=true`、`keep_together=true`（OOXML `keepNext`/`keepLines`），保证表题与后续表格首行同页；页尾孤立表题属于阻断错误。
   **一表一题规则（硬性、机械门禁）**：每张正文表格正前方必须且只能有一个表题，表题后必须立即是对应表格；同一 `表N-x` 编号全篇只能出现一次。禁止“正式表题→表格→通用表题→通用表题→下一表”的堆叠结构。`polish_word_ib_style.py` 按文档顺序保留离表最近的有效表题、删除多余通用表题并按章重编号；`verify_word_ib_style.py` 和 `validate_word_delivery.py` 双重阻断孤立、重复或不紧邻的表题。
5. **图片段落**：`Figure Image` 样式与每个含 `<w:drawing>` 的图片段落都必须使用单倍/auto 行距（1.0），禁止 `exact`/固定磅值行距；段前 6pt、段后 0、居中、`keep_with_next=true`、`keep_together=true`。固定 12pt 行高会把已嵌入的多英寸图表裁成细条，属于阻断错误。图题在图下方（宋体五号按章编号 图N-x）+ `数据来源：` 开头的 9pt 灰色来源注。每张 `.theme.json` 必须声明 `section_heading`、`caption` 和 `source_note`。
6. **图表中文字体（硬性）**：SVG 必须保留可编辑 `<text>` 节点，并为文本写入已安装的 CJK 字体样式；禁止把文字转成路径或只交付 PNG。
7. **图表配色**：使用 `kami-broker-v1` 白底、深蓝和冷灰的克制券商配色，正负向信号色只用于方向含义。
8. **图表命名规范（硬性）**：正式图表命名 `figN_*.svg/png/theme.json`；测试/临时图不得混入正式 charts 目录。正文完成后运行 `scripts/insert_approved_figures.py <docx> --charts-dir <charts> --mode final`；该步骤只会把通过清单的图插到目标章节的实质分析段之后，自动补“见图N-x”，若图未全部挂载则失败。
9. 插图后：**必须运行 `scripts/polish_word_ib_style.py <docx>`（幂等后处理，硬性）**——该脚本自动完成：删除模板骨架/占位段、来源注去重与规范化、表头/表题中性化、图序和引用复核、正文格式规范化。随后运行 `scripts/verify_word_ib_style.py <docx>`；任一 FAIL 视为交付失败。最终注册后运行 `scripts/validate_word_delivery.py --project-dir <project> --mode final`，它还会确认每个已登记图的 SVG/PNG 哈希真实存在于 DOCX media 包中；禁止用与正文无关的图表清单凑门槛。
10. 使用 `scripts/libreoffice_render.py` 完成 PDF/逐页 PNG 渲染并检查全部页面；随后运行 `scripts/register_word_delivery.py --project-dir <project> --file <docx> --render-dir <qa> --confirm-all-pages-inspected --figure-manifest <theme.json>...`。该命令重新执行结构、字数、占位符、逐图 final QA 和 DOCX 嵌图哈希门禁，按最终文件哈希生成 `word_production_manifest.json`。

**文风标准（2026-08-06 定稿，投行行业研究风格，硬性）**：Word 报告必须读起来像人写的投行研报，不是模板填充的产物。禁止出现任何"工作底稿痕迹"。具体规范：

- **禁止骨架标题残留**：每章的"本章关键问题：…？；…？"、"证据、分析与反证："等模板四级标题一律删除（或改写为自然过渡句），不得保留在正文中。
- **禁止标签前缀段**：正文段不得以"小结：""数据引用：""证据支撑：""反证与限制：""看宏观：""看行业：""看客户：""看自己："等标签开头。改写为自然叙述：如"综上，…""从宏观层面看，…""需要指出的是，…"。
- **禁止数据行 dump 进正文**：CSV 表格行（指标+数值+来源+日期字段粘连，如"BESS市场规模（2025）18亿美元Mark & Spark Solutions"）不得作为正文段落出现。数据信息要么融入通顺的分析句子，要么放表格。
- **禁止内部痕迹入正文**：证据编号（S001/C001/R001 等）、CSV 文件名（01_Market_Scan.csv 等）、内部缺口编号（D003 等）不得出现在正文；需引用时改为自然表述（"根据 Mark & Spark Solutions 数据…"）。
- **禁止转义符残留**：正文不得包含 `\-` `\.` `\+` 等 markdown 转义符。
- **来源注规范**：来源注只出现在图表下方（9pt 灰色，`数据来源：` 开头），内容为自然来源描述（如"数据来源：各品牌官网及经销商报价（2026 年 8 月）"），不得含 CSV 文件名或证据编号；正文段尾不得悬挂"（数据来源：…）"独立段或标注。
- **术语中性化**：报告读者面向管理层，避免"证据"这类研究内部用语。表格列名用"关键事项/来源编号"，表题用"本章关键数据与来源"，章节名用"数据体系/数据缺口"而非"证据体系/证据问题"。
- **重复内容清理**：章节间不得出现完全相同的段落（如执行摘要章与核心结论章重复），同一来源注不得连续堆叠多条。
- **每个图表必须在正文中被引用**（"见图N-x"/"见表N-x"），引用挂在图表前的分析段末尾，格式正确（不得出现"（见图图N-x）"重复字）。

Apply the exact Word rules in `references/format-and-visual-style.md`. Unless the user requests a short version, target 15,000-30,000 Chinese characters and at least 30 pages. Use an objective consulting tone, detailed evidence-backed paragraphs, and restrained wording.

The historical Word failure modes and their exact corrections live in `references/format-and-visual-style.md` and are enforced by `scripts/polish_word_ib_style.py`, `scripts/verify_word_ib_style.py`, and `scripts/validate_word_delivery.py`. Do not restate or weaken those contracts in project prompts.

**字数校验门（2026-08-07 教训固化，硬性，机械门禁）**：由 `scripts/check_word_char_count.py <final.docx>` 自动执行（总字符 <15,000 退出码 1 = FAIL），并在 Stage 7 门禁调用；正文 fill 完成后、polish 之前运行，**必须统计报告字符数**（`fitz` 提取 PDF 文本或 `docx` 遍历段落累计），总字符数（含表格、图题、来源注）不足 **15,000** 时必须扩充正文（增加分析段落/国际参照/情景推演/反证），不得以"已有足够段落"为由跳过。曾因每章只写 2-3 段导致全文仅约 1.3 万字符、未达 SKILL 15,000-30,000 字要求；正确做法是按"每章 4-6 段、每段 200-350 字"规划正文，fill 后立即校验。生成后 `libreoffice_render.py` 渲染并复核页数（≥30 页目标）。

**模板每章空表处理纪律（2026-08-07 教训固化，硬性，机械门禁）**：由 `verify_word_ib_style.py` 第 [11] 项「空表检查」自动执行（数据行全空的表 = FAIL）；券商模板每章预置一张"表X-1 本章关键数据与来源"，`fill_tables_from_csv` 只填充 01~10 CSV 有数据的行——当 09_Integrated_Matrix / 10_SWOT_Opportunity 等 CSV 为空时，对应章表即整表空白（曾出现 8 张全空表）。**fill 后必须逐表检查数据行数，空表一律删除（含表题段），不得保留空表**；推荐结构为：每章保留 1 张有实质数据的小表（3-4 行本章核心数字）+ 文档末尾（第十四章）1 张"报告关键数据与来源总表"（15-20 行覆盖全部核心数字）。总表用三线表格式、表题带 keepNext/keepLines。删除每章表后同步清理正文中的悬空"（见表X-x）"引用。

### PPT

Use the embedded high-fidelity pipeline `embedded-pptmaster-svg-v1` for every final presentation. It contains the former `ppt-master` scripts, strategist/executor contracts, live SVG editor, chart/layout/icon libraries, native DrawingML exporter, transitions, entrance animations, notes, and narration support; no separately installed `ppt-master`, `pptx`, or `ewo-image-generate` Skill is required. The older `embedded-presentation-production-v1` Python-native renderer is a stability fallback only and must never be described as quality-equivalent to the formal SVG route. Read `references/embedded-pptmaster-parity.md`, `references/strategist.md`, `references/executor-consultant-top.md`, `references/shared-standards.md`, and `references/ppt-style-prompts.md` before production.

**PPT 证据地图与构图契约（硬性）**：写 SVG 前必须先依据已验收报告、工作簿与图表 manifest 编制 storyline JSON，并运行 `scripts/build_presentation_evidence_map.py --charts-dir <charts> --page-plan <storyline.json> --output <presentation_project>/evidence_map.json`。每页必须具备一个 answer-first 结论、一个待回答问题、2–4 个证据主题、明确 `SO WHAT` 与一个语义匹配的 `layout_family`。高信息密度只能来自更有效的证据，禁止靠缩小字号或重复卡片网格实现；全稿至少 4 种版式家族，任一版式不得连续出现 3 页。核心标题、正文、简单图表、表格与几何必须保持可编辑 DrawingML。`validate_high_fidelity_ppt_delivery.py` 对 evidence map、版式多样性和页数一致性做机械阻断。纯文本模型执行规范见 `references/text-only-chart-and-slide-design.md`。

**PPT 正文页密度（v1.2.9，硬性）**：数据密集型正文页必须采用 `references/ppt-style-prompts.md` §1.4 三栏高密度版式（左证据栏 + 中图栏 + 右要点栏，图下数据注，SO WHAT 横幅 + 双栏页脚）；每页 2-4 个证据主题、要点绑定证据行号，内容区覆盖 ≥2/3 画布，禁止低密度"左图右文"默认布局；数学符号用文字表述。

**八项确认（唯一阻塞确认点，硬性）**：在写 `design_spec.md` / `spec_lock.md` 前，把 1) 画布，2) 页数范围，3) 目标受众，4) 风格目标，5) 配色，6) 图标方案，7) 字体与公式渲染策略，8) 图片使用方案作为一组建议提交用户确认，并附连续模式/拆分模式的一行说明。用户确认后，后续设计规范、逐页 SVG、讲稿、定稿、导出和 QA 自动连续推进，不再重复索取确认。

**封面与正文插图双路径决策（硬性，机械门禁）**：先按 `assets/templates/json/presentation_image_requests_template.json` 创建请求清单并运行 `scripts/resolve_presentation_images.py`。路径 A 始终是默认首选：直接调用 EWO 生成深蓝科技风封面和必要的非数据型正文插图，文件必须为矢量插画风格的 PNG/JPEG/WebP 位图；提示词、格式、文件路径与 SHA256 写入 `presentation_project/image_acquisition_manifest.json`。当 EWO 返回余额不足（402/429 `HABITAT_INSUFFICIENT_BALANCE`）、连接、凭证、权限、超时、上游失败或项目全局禁用生图时，封面自动走路径 B（白底、衬线主标题、皇家蓝饰带、三列元信息），正文插图改为主代理手写 SVG 矢量示意，并由导出器转成可编辑 PowerPoint 原生对象。4xx 不盲目重试，503 最多重试一次。禁止用降级示意冒充路径 A，禁止用 AI 生成数据图表。**路径 B 封面必须零插图残留**：白底上除饰带/分隔线/结论横幅外不得有任何插画组（太阳/云/光伏板/户储柜/电网塔等，含 translate(x≥500) 右区插画组与已知插画标记 FBBF24/sunGlow/能量流线条），否则视为违规。**路径 B 封面必须通过真实合规审计**：注册前运行 `scripts/audit_cover_compliance.py --project-dir <project>`（8 项检查：白底、无深蓝渐变、皇家蓝饰带、衬线标题、结论横幅、三列元信息、页脚、无插图），审计结果写入 `presentation_project/image_acquisition_manifest.json` 的 `cover_compliance_audit`；`register_high_fidelity_ppt_delivery.py` 的 `cover_prompt_compliance` 必须读取该审计结果，禁止硬编码 True。规范见 `references/cover-path-b-audit.md`。

**渲染后几何门禁（硬性，机械门禁）**：导出 PPTX 后、注册前必须运行 `scripts/verify_ppt_render_geometry.py --project-dir <project>`（自动调 LibreOffice 渲染最终 PPTX 为 PDF，PyMuPDF 提取 span 级文本几何）：任何两段文本重叠 >3pt×3pt、或文本越出 1280px 画布（右界 >962pt / 左界 <0pt）即退出码 1 阻断注册。该门禁捕获渲染器独有的问题——LibreOffice 忽略 spAutoFit 按框宽重排（KPI 被拆行）、换行块向下压入下方元素、右缘文本框越画布被裁。修复仍须回到 SVG 写入源头（缩短措辞 / 调整 y / 加框宽余量），不得在渲染层打补丁。

**PPT 文字事前控制（硬性，机械门禁）**：每个 `<text>` 在写入前必须按所在卡片宽度预换行——正文超宽按**原子 token 断行**（数字串+单位如"351.6 MWh"、拉丁单词永不拆行；闭合标点不悬行；行距 font-size×1.45，续行同 x），标题/KPI 数字（Georgia 或 font-size≥25）保持单行并缩短措辞，页码（text-anchor=end）不换行；宽度估算衬线感知（Georgia/serif 拉丁 0.62em，无衬线 0.55em，CJK≈1.0em）。卡片判定按 `<rect>` 与 finalize 后 `<path d="M x0,y0 H x1 …V y1…">` 双形态解析真实边界（高 ≤30px 的装饰条/分隔线必须排除）。**自由文本（标题/页脚等不在卡片内的 `<text>`）同样按 1280 画布右界校验**，Georgia 标题渲染宽度可达估算 1.1 倍。导出前必须运行 `scripts/wrap_slide_text.py --project-dir <project> --check`，退出码 1（存在溢出）即阻断导出，修复在写入源头而非事后。**渲染重排防护**：`svg_to_pptx` 文本框宽带余量（单行 1.5x、多行 1.3x，LibreOffice 忽略 spAutoFit 会按框宽重排），且文本框钳制在画布内；换行后若多出行数压入下方元素（如"详见第 X 页"链接），必须把下方元素下移。图表标签同理：数据标签用 `place_bar_labels` 避让，窄面板标签先 `chart_polish.fit_label` 截断再写入，散点用品牌短名。完整契约见 `references/text-control-spec.md`。

**正式串行生产顺序（硬性）**：从最终 Word/Excel、证据台账和图表 manifest 形成 10–18 页 answer-first 管理层叙事。`high_fidelity_presentation.py doctor` 只做依赖/环境自检（不产出文件）；`design_spec.md` 与 `spec_lock.md` 由主代理手写，放在展示项目目录内（`presentation_project/` 或 `high_fidelity_presentation.py init` 生成的 `<name>_ppt169_<YYYYMMDD>/` 均可——校验/注册/封面审计/几何校验脚本会**自动探测**展示项目目录，也可用 `--presentation-project <dir>` 显式指定，见 CHANGELOG v1.2.6）。启动 `high_fidelity_presentation.py preview ... --no-browser` 后，由当前主代理逐页手写 `svg_output/*.svg`；禁止委派给子代理，禁止用 Python/Node/模板循环批量生成页面。写每一页之前必须重新读取 `spec_lock.md`，并读取该页的 `page_rhythm`、`page_layouts`、`page_charts`。页面按序完成后执行 `validate → finalize → export`；默认导出可编辑 DrawingML、`fade` 转场、`auto` 入场动画和 conversion trace。再执行 `qa`，逐页检查、至少修复一次并全量重渲染，最后运行 `validate_high_fidelity_ppt_delivery.py --pptx <file> --qa-render-dir <dir> --mode final`（`--pptx` 与 `--qa-render-dir` 为必填）和 `register_high_fidelity_ppt_delivery.py`（另需 `--pages-inspected`、`--confirm-all-pages-inspected`、`--visual-fix-cycle-count`、`--visual-inspection-notes`）。

**备用路径边界（硬性）**：仅当高保真工具链经过 `doctor`/诊断仍无法初始化或用户明确要求快速稳定稿时，才允许运行 `build_executive_presentation.py`。必须在交付 manifest 中记录 `fallback_route=true` 和具体原因；不得把该产物称为与 `ppt-master` 完全一致。

Build an executive narrative from the approved report and workbook, not from memory. Verify slide rendering before delivery.

The automated package-builder PPT is a draft only. A final PPT must be built through the embedded handwritten-SVG workflow, inspected slide by slide, fixed and fully rerendered at least once, then registered. Strict final validation rejects missing/stale manifests, incomplete slide inspection, a zero fix-cycle count, SVG/spec drift, missing speaker notes, missing native conversion trace, missing transitions/animations, invalid EWO fallback reasons, or stale output hashes.

**PPT 渲染 QA 链路（验证版）**：`scripts/libreoffice_render.py <pptx> --output-dir <qa> --render-pages --timeout-seconds 120` 使用 PyMuPDF 将 PDF 逐页渲染为 PNG → 生成缩略图网格并逐页视觉检查（无重叠/溢出）→ `scripts/scan_office_placeholders.py <pptx>` 直接扫描 OOXML，确认无 `[[xxx]]` 等占位符残留。LibreOffice 未装时先安装并设置 `SOFFICE_PATH` 或加入 PATH；Python 侧只需已经列入本 Skill 的 `PyMuPDF`，不需要 MarkItDown。

## Automation

For multi-stage work, use:

- `workflows/overseas_energy_research.workflow.yaml`
- `scripts/run_workflow.py`
- `scripts/init_research_project.py`
- `scripts/upgrade_collection_policy.py`（显式人工批准后升级项目冻结的采集数量政策，并保留版本/哈希历史）
- `scripts/validate_stage_gate.py`
- `scripts/build_evidence_audit.py`
- `scripts/create_modeling_artifacts.py`（建模分支：决策工件机械校验 + 12/13/14 CSV 生成）
- `scripts/validate_market_insight.py`（内置五看分支：结构、版本、证据 ID、启示、结论与占位符门禁）
- `scripts/figure_production.py` + `scripts/render_charts.py` / `scripts/render_figure_from_spec.py` + `scripts/validate_figure_delivery.py`（内嵌双 owner 图表生产与机械门禁）
- `scripts/register_figure_delivery.py` + `scripts/insert_approved_figures.py`（逐图视觉确认与按正文位置插图）
- `scripts/libreoffice_render.py`（跨平台独立 profile、正确 file URI、超时与进程树清理）
- `scripts/style_excel_consulting.py` + `scripts/recalculate_excel.py` + `scripts/validate_excel_delivery.py`（内置 Excel 浅色咨询样式、重算、公式/空表/视觉/打印布局门禁，不再依赖外部 Excel Skill）
- `scripts/scan_office_placeholders.py`（标准库 OOXML 占位符扫描，不依赖 MarkItDown）
- `scripts/register_word_delivery.py`（内置 Word 结构门禁、最终哈希、逐页检查与生产清单注册）
- `scripts/resolve_presentation_images.py`（直接调用 EWO，余额不足/不可用时输出结构化双路径降级）
- `scripts/high_fidelity_presentation.py` + `scripts/svg_editor/server.py`（内嵌 PPT Master 诊断、项目、实时预览、逐页 SVG、定稿和原生导出入口）
- `scripts/svg_quality_checker.py` + `scripts/finalize_svg.py` + `scripts/svg_to_pptx.py`（SVG/spec_lock 质量门、资源内嵌、可编辑 DrawingML、转场、动画、讲稿与旁白）
- `scripts/validate_high_fidelity_ppt_delivery.py` / `scripts/register_high_fidelity_ppt_delivery.py`（正式 PPT 路径的结构、转换追踪、动画、逐页渲染与修复循环门禁）
- `scripts/build_executive_presentation.py` + `scripts/validate_ppt_delivery.py` / `scripts/register_ppt_delivery.py`（仅稳定性 fallback）
- `scripts/bootstrap_runtime.py --install`（安装并检查当前 Skill 的 Python 运行依赖；整合状态见 `assets/config/integration_manifest.yaml`）

Treat automated Office builders as draft-package generators. Final Excel/Word/PPT outputs still require the skill routing and visual QA above.

Before moving stages, run:

```text
python scripts/validate_stage_gate.py --project-dir <project> --stage <n> --mode draft
```

建模分支（`analysis_branch = modeling`）在推进 Stage 6 前运行：

```text
python scripts/create_modeling_artifacts.py --project-dir <project> --dry-run   # workspace 缺失时只告警
python scripts/create_modeling_artifacts.py --project-dir <project>             # 生成 12/13/14 CSV
```

Before final handoff, run:

```text
python scripts/run_workflow.py --project-dir <project> --stages 0-8 --check --audit --mode final --strict-final-files
```

**交付硬门槛（2026-08-07 固化，硬性）**：上述 `run_workflow --mode final --strict-final-files` 是**交付的唯一放行凭证**——任何交付（Word/Excel/PPT 及证据审计）只有在本次审计输出 `Stage gate validation: OK (0 fail, 0 warn)` 且 `build_evidence_audit` 成功写出审计报告后，才允许宣布交付完成；出现任何 `FAIL` 即视为**交付未完成**，必须修复后重跑直至 `OK`。禁止以「上次跑过」「局部检查通过」「人工确认」替代最终审计；交付说明中必须附上最终审计的输出摘要（gate 状态 + evidence audit 路径）。四个历史错误（CSV 写错目录、空表泛滥、字数不足、封面路径缺失）均已由机械门禁纳入该审计，本硬门槛是其总兜底。

## Final Quality Gate

Confirm all of the following:

- The approved outline and approval record exist.
- Web collection began only after approval.
- Every web fact has a URL and access date.
- Exact identifiers are verified for model-level evidence.
- Raw reviews precede review synthesis.
- Local parameter files were checked first.
- Estimates are labeled and trace to assumptions, formulas, and supporting URLs.
- Excel formulas, units, currencies, and reconciliations pass audit; the workbook contains no native charts (2026-08-06 起废止).
- 建模分支：G2.5 / G4.5 决策工件全部 DECIDED（decided_by: human），且 12/13/14 CSV、模拟生成代码/数据与 `frozen_numbers.json` 对账一致。
- Every analytical/model figure has a confirmed claim, traceable source data, SVG and high-resolution PNG outputs, and a passed render check.
- Source routes cover Reddit/YouTube, official and named modeling-data platforms, required Amazon.de ASIN sequencing, relevant retailers, and official/device.report specification evidence as applicable.
- Every Word table title is centered, keeps with the following table, and passes rendered page inspection without orphan captions.
- Every chapter (H1 section) contains at least one formal figure; no chapter is text-only.
- Every figure immediately follows a paragraph of analytical text with an inline reference (e.g., "见图N-x"); no figure appears at the start of a chapter, after a blank paragraph, or between two figures without intervening text.
- Every formal figure has exactly one embedded owner: `embedded-market-figure-v1` for `market-insight` or `embedded-modeling-figure-v1` for `modeling`. Each `.theme.json` records `figure_pipeline_id=embedded-figure-production-v1`, the matching owner/class, `backend=python`, confirmed core claim, traceable source data, SVG + ≥300 dpi PNG outputs, and passed mechanical plus visual checks.
- LibreOffice QA uses the Skill-owned bounded converter; PDF/PNG outputs exist and no launched LibreOffice process remains after completion.
- Word uses `embedded-word-production-v1`; final PPT uses `embedded-pptmaster-svg-v1` unless a justified fallback is explicitly registered. Both pass complete visual rendering review.
- Conclusions answer the original decision question and include owners, priorities, timing, risks, and next actions.
- Market-insight projects use `embedded-market-insight-five-views-v1`; all inline evidence anchors resolve to project CSV IDs and the final embedded-branch validator passes.
