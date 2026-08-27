# Web Collection Playbooks: AnySearch And Kimi WebBridge

## Contents

1. Tool routing and mandatory preflight
2. Collection plan
3. Source-specific playbooks
4. Failure handling
5. Completion rules
6. AnySearch 采集路径（双工具之一，2026-08-07 纳入）

Route every online task by page and interaction requirements. Use `anysearch` for general/vertical search, batch search, and static-page or PDF extraction. Use `kimi-webbridge` only when the task requires a real browser, dynamic rendering, authentication, or page interaction, or when a documented AnySearch extraction attempt fails and browser access is appropriate. A project may use one or both tools; do not invoke both merely to satisfy a formal requirement. Save raw captures before synthesis and write each usable fact to `00_Source_Ledger.csv` with the actual collection tool.

## Tool Routing And Mandatory Preflight

1. Confirm `00_Research_Approval.csv` contains the current `outline_version` with `approval_status=approved`.
2. Classify each task before execution:
   - Route search, vertical-domain discovery, batch search, and static URL/PDF extraction to `anysearch`.
   - Route dynamic rendering, authenticated pages, clicking/filling, browser-only downloads, and interactive marketplaces to `kimi-webbridge`.
   - If AnySearch extraction fails, record the failure first; then route to Kimi WebBridge only when browser access is suitable and permitted.
3. For an AnySearch-routed task, load the installed `anysearch` Skill, use its configured runtime, and follow its vertical-domain and fallback rules. Do not run Kimi WebBridge health checks.
4. For a Kimi-routed task, run `~/.kimi-webbridge/bin/kimi-webbridge status` and continue only when `running=true` and `extension_connected=true`.
   - If the daemon is stopped, follow `kimi-webbridge/references/operations.md` to start it.
   - If the extension is disconnected, ask the user to open the browser or install/enable the extension.
   - If daemon and extension versions are incompatible, ask the user to update the extension and do not retry the failed command.
5. For Kimi-routed commands, pick one stable task-level `session`. On the first `navigate`, set a user-language `group_title`; use `navigate` or `find_tab`, then `snapshot`, and prefer semantic `@e` references.
6. Save the exact page URL, access time, and tool-appropriate raw capture: Markdown/extraction output for AnySearch, or snapshot/screenshot/PDF for Kimi WebBridge when material.

## Collection Plan

Create `02_Web_Collection_Tasks.csv` before crawling:

- `task_id`, stage, market, language, collection goal.
- Starting URL or precise query.
- Set `required_tool` to the tool actually required by that row: `anysearch` or `kimi-webbridge`. Do not list both in one row.
- Target geography, brand, exact model, identifier type/value.
- Planned fields, raw capture path, output file, and completion contract.
- Source tier and expected cross-check.

Use controlled goals:

- `market_size`
- `policy`
- `tariff`
- `grid_reliability`
- `demand_load`
- `identifier_verify`
- `parameters`
- `price`
- `channel`
- `service`
- `reviews`
- `social_media`
- `modeling_input`
- `promotion`
- `pilot_project`
- `technical_standard`

## Layered Reading

- Metadata: locate sources.
- Abstract/summary: screen relevance.
- Structure: map headings/tables.
- Keyword/local extraction: answer a precise field.
- Full text: only for comprehensive analysis, model replication, or detailed policy interpretation.

For multiple candidate sources, screen at metadata/summary level first. Deep-read only the short list.

## Official Policy, Tariff, And Standards

1. Search local-language and English/Chinese synonyms.
2. Prefer the issuing authority, regulator, grid/market operator, standards body, or official gazette.
3. Capture title, document number, issuing body, publication/effective dates, geographic scope, eligibility, rate/amount, limits, expiry, and implementation status.
4. Save the original URL and relevant excerpt/table location.
5. Triangulate critical interpretations with a second authoritative source.

## Market Size And Forecast

1. Define segment and geography before collecting numbers.
2. Preserve publisher, publication date, base year, forecast period, unit, currency, nominal/real basis, and scope.
3. Do not combine reports with incompatible definitions without normalization.
4. Treat paywalled snippets as partial evidence and document the limitation.
5. Build modeled estimates only in the assumptions/model tables.

## Modeling Data Platforms

Use the following sequence for model inputs:

1. User-provided or internally approved data.
2. National/regional official statistics, regulator, ministry, grid/market operator, utility, and official open-data portals.
3. World Bank, `https://energydata.info/dataset/`, and `https://www.globalpetrolprices.com/`.
4. Other official organizations, established research institutions, and traceable media sites.
5. If a mathematical model still lacks a required input after the source routes are exhausted, a calibrated and reproducible simulated input with low/base/high quantiles.

For World Bank, preserve indicator code, country/geography code, period, unit, API or download URL, update date, and transformation. For EnergyData.info, preserve the dataset landing page, resource/download URL, publisher, coverage, vintage, license, variables, and missing-value treatment. For GlobalPetrolPrices, preserve country, energy/fuel type, price basis, currency/unit, period, page URL, and access date. Never treat a media summary as equivalent to the underlying official dataset.

## Amazon.de And Marketplaces

1. For Amazon.de, create and execute an `asin_search` task before any price, promotion, review, ranking, availability, channel, or parameter task.
2. Search brand plus exact model and identify ASIN candidates.
3. Open candidates one by one and verify ASIN, regional model, capacity/version, variant, bundle, title, seller/listing context, and URL.
4. Write the verified ASIN and exact-match evidence to `03_Model_Identifier_Check.csv` and the source ledger.
5. Only then collect product facts from the verified ASIN URL.
6. Record list/discounted/coupon/member price, VAT, shipping, installation, stock, promotion conditions and dates, configuration, capture timestamp, rating/review count, and seller.

Use `scripts/collect_amazon_asin.py` for Amazon task/prompt generation.

## Official Product Sites, Device.report, And Local Files

1. Inspect user local files before web parameter collection.
2. Prefer official product pages, manuals, datasheets, certification pages, and support pages.
3. Match exact model, regional SKU, generation, capacity, and firmware/revision.
4. Preserve original units and page/section location.
5. Use `https://device.report/` only as a secondary discovery/cross-check source when official material is absent or incomplete. Preserve the exact document URL and model identifier, and record conflicts instead of silently overriding official evidence.

## Retailers, Installers, Utilities, And Channels

For Germany and relevant European markets, include MediaMarkt and Galaxus alongside Amazon.de, brand stores, installers, and other local retailers. Use the exact URL and identifier. Record configuration, list/discounted price, promotion, tax, shipping, installation, financing, availability, geography, seller, and capture date. Do not merge base units, expansion batteries, PV kits, installation packages, subscriptions, or regional variants.

## Reviews And Community Sources

Use `scripts/collect_reviews_kimi_webbridge.py`.

1. Verify the product page and identifier.
2. Crawl the full available review corpus or document visible/total counts and platform limits.
3. Save raw rows before analysis.
4. Keep variant, date, rating, language, URL, and original text.
5. Use model-family threads only for category context unless exact linkage is proven.
6. Include Reddit and YouTube in the social-media plan when user voice is in scope. For Reddit, save subreddit, thread/comment context, permalink, date, and score when visible. For YouTube, save channel, video title, video/comment URL, transcript or comment segment, timestamp where relevant, date, and engagement context.
7. Treat Reddit, YouTube, forums, and media as Tier 3; use them for user voice and triangulation, not as substitutes for official specifications, policy, or statistics.

## Pilot Projects

For each project, capture:

- Official project name, site, owner/contractor, scenario, status and dates.
- Technical route, charger/facility/vehicle scale, platform/VPP connection.
- Business model, tariff/subsidy, stakeholder roles and revenue allocation.
- Operational results, dispatch volume/frequency, user participation and revenue.
- Replicability, bottlenecks, and evidence authority.

Prioritize government and operator sources. Use media and company announcements only as supplements.

## AnySearch 采集路径（2026-08-07 纳入，双工具之一；2026-08-10 内嵌官方 CLI）

### 工具定位
- 通用/垂直域**搜索**与**静态页正文提取**的首选工具；与 kimi-webbridge（浏览器路径）组成双工具采集。
- **本 Skill 已内嵌官方 anysearch 3.0.1 CLI（零 diff 拷贝）**：`scripts/anysearch/anysearch_cli.py`（含 `shared/`），
  不依赖外部 anysearch skill。功能与官方一致：search / batch_search / extract / get_sub_domains / doc。
  许可证声明见 `scripts/anysearch/README_embedded.md`（Apache 2.0）。
- **推荐统一入口**：`scripts/web_collection/cli.py`（自动写采集台账 `13_Collection_Attempt_Journal.csv`
  与原始捕获 `raw_capture/<goal>/`）。也可直接调用内嵌 CLI（同等记录义务）。
- 双路径：本机仍装有官方 anysearch skill 时，可 `--official-cli <路径>` 显式走官方 CLI（行为逐字节一致）；
  `cli.py doctor` 会对比内嵌与官方哈希，提示是否需要同步。
- 垂直域规则：能源（energy）、财经（finance）、学术（academic）等查询**先 `get_sub_domains --domain <域>` 获取子域与参数**，再带 `--sub_domain`/`--sdp` 搜索；纯通用查询走 Path 1（general web）。
- 代理：Windows 本机按 `runtime.conf` 设置 `HTTP_PROXY=http://127.0.0.1:7897`（`export HTTP_PROXY=... HTTPS_PROXY=...`）后再调用；本地回环地址自动排除代理（NO_PROXY）。

### 命令速查（统一 CLI 优先）
```bash
CLI="python <skill_root>/scripts/web_collection/cli.py"
# 环境体检（采集前必做）：内嵌 CLI 哈希 vs 官方、kimi 插件状态、依赖、台账
$CLI doctor
# 单条搜索（自动写台账 + raw_capture）
$CLI search "Thailand BEV sales 2025" --max-results 5 --project-dir . --task-id T1 --round 1 --round-goal coverage
# 垂直域发现（必做：能源/财经等域）
$CLI search "..." --domain energy --sub-domain energy.electricity --sdp location=Thailand,metric=price ...
# 并行批量（≤5 查询）
$CLI batch-search --query q1 --query q2 --query q3 --max-results 4 --project-dir . --task-id T2
# URL 正文提取（markdown 直存 raw_capture）
$CLI extract "https://www.egat.co.th/home/en/20221021e/" --project-dir . --task-id T3 --goal pilot_project
# kimi-webbridge 浏览器动作 / 登录态检查 / 台账统计
$CLI browse <url> --session research --action snapshot --project-dir . --task-id T4
$CLI auth-check <url> --session research --project-dir . --task-id T5
$CLI journal-summary --project-dir .
```

### 在采集任务中的用法
- **R1 coverage**：`batch-search` 每批 ≤5 查询并行铺开（三语同义词分批），记录候选 URL 清单入台账；energy 域查询先 `get_sub_domains --domain energy`。
- **R2 depth**：对官方页/报告/新闻/PDF 用 `extract` 拿 markdown（保留 URL 与访问日期）；PDF 提取失败（403 等）记录后改用 kimi-webbridge 或换源。
- **R3 triangulation**：对缺口用替代关键词/语言再搜；关键结论双源验证时用 `batch-search` 并行交叉。
- **失败处理**：`extract_upstream_error` / HTTP 4xx → 记录平台限制，改用 kimi-webbridge（动态页/登录页）或换替代源；禁止绕过访问控制。

### 记录义务
- 来源台账 `collection_tool` 记 `anysearch`（验证器已允许该值）；URL、访问日期、原始 markdown（raw_capture/<goal>/）必须保留。
- **每次采集动作必须写 `13_Collection_Attempt_Journal.csv`**（`cli.py` 自动写；直接调 CLI 时用 `journal.py` 或统一 CLI 补记）。
  `scripts/validate_collection_attempts.py` 机械校验：防少搜（每 R1/R2/R3 任务有 attempt 且 attempted ≥ 目标/floor）、
  防假完成（未解决 auth_required/bridge_unavailable/tool_unavailable/insufficient_balance 的任务不得 completed）、
  失败必须带 error_class+failure_reason、成功必须有存在的 raw_capture。
- 与 kimi-webbridge 共用同一份 `02_Web_Collection_Tasks.csv` 任务表（round=1/2/3 不变）；每行 `required_tool` 只填写实际路由工具，补充执行细节写入 `notes`。

## Kimi WebBridge 采集路径（浏览器/动态页）

- 完整工具契约与操作手册已内嵌：`references/kimi-webbridge-client-contract.md`（13 个 action、session/tabs 规则、截图/PDF 语义）
  与 `references/kimi-webbridge-operations.md`（安装/启动/诊断路由表）。
- 客户端：`scripts/_kimi_webbridge.py`（`command()` 直连 `127.0.0.1:10086/command`，payload 与官方 curl 示例逐字段一致；
  `ensure_ready` 硬门禁：daemon running + extension_connected）。
- 统一入口：`scripts/web_collection/cli.py browse|auth-check`。

## Kimi WebBridge Failure Handling

When a Kimi-routed task fails:

1. Re-run `~/.kimi-webbridge/bin/kimi-webbridge status`.
2. If unhealthy, follow `kimi-webbridge/references/operations.md`.
3. If the extension is disconnected, stop and ask the user to open the browser or install/enable it.
4. Inspect `~/.kimi-webbridge/bin/kimi-webbridge logs -n 100`.
5. Classify version mismatch, disconnected extension, timeout, access/authentication, challenge, empty snapshot, wrong current tab, or synthetic-event limitation.
6. Fix the cause and retry only the affected task. Do not bypass authentication, captchas, or site access controls.

Do not silently switch to ad hoc scraping.

## Completion Rules

- Inspect the completion contract and missing outputs.
- Every web row has URL and access date.
- Every product row has exact identifier or is excluded/pending verification.
- Every review insight traces to saved raw rows.
- Raw captures are retained.
- Every Amazon.de price/promotion row traces to an earlier ASIN-search/verification task and an exact-match ASIN.
- Product specifications show whether they came from an official product/manual/support source or secondary device.report evidence.
- Modeling inputs record dataset metadata and transformations; if no usable source exists after the prescribed search route, the fallback is a realistic Python-generated simulation with traceable calibration, fixed seed, code/data paths, validation, and uncertainty.
- Any unresolved item is logged internally; any value used for progress is transparently modeled, not fabricated.

## 三轮递进采集（硬性，2026-08-06 定稿）

### 饱和目标数量门禁（先于三轮）

- `assets/config/collection_quantity_policy.yaml` 是创建新政策版本的唯一事实源。初始化项目时必须冻结到 `policy_snapshot/collection_quantity_policy.yaml`，并在 `project_manifest.json` 记录版本、SHA256、相对路径和冻结时间。禁止在提示词、脚本或本文档复制数值。
- 项目执行期间，验证器和采集助手只读取经版本与哈希验证的项目快照，并据此计算最低目标数和最低任务行数；缺少快照、快照可写、越出项目目录、版本不符或哈希不符均立即 FAIL。禁止 Agent 自行判定 N/A、合并目标或用一个市场/型号的轮次抵扣另一个。
- 全局 YAML 更新不会自动改变历史项目。只有获得人工明确批准后，才可运行 `upgrade_collection_policy.py --confirm-policy-upgrade --approved-by <审批人或责任角色>`；覆盖前先把旧 YAML 只读归档到 `policy_snapshot/archive/v<version>_<hash>.yaml`，并将归档路径、哈希、可信状态、升级前后身份与审批说明留在 manifest 历史中。
- 市场数与市场型号对数以 `project_manifest.json` 中经审批的 `target_markets` / `market_model_pairs` 为准；任务表出现未登记的新市场或型号对时必须先更新范围，验证器拒绝“表内自报数量”。
- 新发现且仍在范围内的市场、品类或精确型号，必须新增对应目标及 R1/R2/R3。只有全家族三轮完成、关键结论双源验证、R3 无未展开高优先级发现，才可声明饱和。

### 分家族、分轮数量门槛

执行前必须从已验证的项目快照加载 `goal_family.rounds.<round>`：`min_unique_sources`、`min_records`、`min_source_types`、`min_platforms`、`min_primary_sources` 和 `coverage_requirement`。数值是下限，不是提前停止条件；新政策版本只修改 skill 级 YAML，历史项目必须显式升级后才采用。

数量审计字段：`target_unique_sources`、`actual_unique_sources`、`target_records`、`actual_records`、`source_type_count`、`platform_count`、`primary_source_count`、`coverage_requirement`、`critical_claim_count`、`dual_sourced_claim_count`、`remaining_high_priority_count`、`no_new_high_priority_batches`、`count_evidence_refs`。

- R1 的重点是独立来源、来源类型和平台覆盖；R2 的重点是去重后写入正式 CSV 的有效记录；R3 的重点是交叉验证，不允许用重复转载凑数。冻结政策 v2+ 下，关键结论的合格来源子集必须同时满足：`publisher_group` 不同、URL 推导的 `root_domain` 不同、`canonical_source_id` 解析后的原始链不同，并达到政策要求的 `source_type` 多样性；只有两个 `source_id` 不算双源。
- R3 必须满足 YAML `r3_saturation` 的全部条件，并保持 `dual_sourced_claim_count >= critical_claim_count`。
- 最终 Stage 4/8 验证使用 `--require-actual`：所有行状态必须完成，实际数量必须达到计划数量，且 `count_evidence_refs` 能回溯来源台账或输出行。
- `count_evidence_refs` 填项目内 JSON 相对路径。JSON 至少包含：`task_id`、`unique_source_ids`（必须命中 `00_Source_Ledger.csv`）、`record_refs`（格式 `relative.csv#row_number`）、`source_types`、`platforms`、`primary_source_ids`、`critical_claims[]`、`high_priority_remaining_ids`、`query_batches[{batch_id,new_high_priority_ids}]`。v6+ 下 `source_types` 与 `platforms` 只是待核对声明：验证器从台账中对应来源的 `source_type` 与 `platform_id` 重新推导集合和数量，要求声明精确一致，并要求每个计数来源至少被本任务一条注册记录使用；伪造名称、闲置来源凑数或记录/来源平台不一致均 FAIL。
- 冻结 policy v5+ 下，`record_refs` 还必须逐条命中内部 `15_Collection_Record_Registry.csv`。注册行需绑定唯一主计数任务、范围、来源、canonical key 和实质内容 SHA256；验证器从被引用 CSV 行重新计算哈希。同一记录可以列出 `supporting_task_ids` 支撑其他目标，但只能由 `owner_task_id` 计数一次。换行、换文件、换任务的相同内容仍为重复；R2/R3 沿用 canonical key 时必须声明较早轮次父记录、`novelty_type=material_enrichment` 和确实变化的 `material_new_fields`。
- 冻结 policy v6+ 下，`00_Source_Ledger.csv` 每条来源必须填写稳定的小写 `platform_id`；Web 来源必须等于 URL 校验得到的 registrable `root_domain`，本地来源固定为 `local-internal`。同一根域名不得拆成多个平台，镜像/转载/聚合副本必须继承 canonical source 的平台 ID；评论原始行的 `platform` 必须与其注册来源的平台 ID 一致。
- 冻结 policy v7+ 下，`primary_source_ids` 只是待核对声明，`primary_source_count` 由验证器按任务类型重新计算。来源必须同时满足该 `goal_family` 的一手来源类型白名单、来源类型—可靠性等级矩阵、`source_relation_type=original` 和允许的验证状态；转载、镜像、错误标级或跨任务类型冒充一手来源均不计数。Tier 0 仅限真实存在的 `local_internal` 文件。
- 冻结 policy v8+ 下，每条 `critical_claims[]` 必须填写 `claim_id`、`claim_text`、`claim_sha256`、`source_ids` 和至少两条 `evidence_bindings[{record_ref,evidence_fields}]`。`record_ref` 必须已由同一任务计数并在记录注册表中归该任务所有；`evidence_fields` 必须是被引用 CSV 行中真实存在、非空且非元数据的字段。绑定记录的来源并集必须与结论来源集合完全一致；重复结论、跨任务引用或只引用 ID/日期/备注等元数据均 FAIL。
- 评论记录不足 YAML 目标时，只能按 YAML 允许的 `platform_limit` 例外。冻结 policy v4+ 下，`platform_limit_evidence` 必须填写项目内 JSON 路径，`quantity_exception_refs` 必须等于其 `evidence_id`；JSON 需关联同一 scoped goal 的 R1/R2/R3，覆盖 R2 计数审计中的全部平台，逐平台记录来源台账 ID、URL、访问日期、显示总数、可访问唯一数、原始采集数、去重数、至少两种尝试方式、阻断原因、不可复用的非空 raw capture 和评论记录引用。评论引用必须与 R2 `count_evidence_refs` 完全一致，实际有效数必须等于全部可访问上限，高优线索为零，并具名、带日期人工批准。其他市场数据数量不足只允许引用 `11_Evidence_Issues.csv` 中 `data_domain=market` 的有效 `quantity_exception_refs`；冻结 policy v3+ 还必须满足市场缺口三轮审计合同。数学建模输入不得用市场缺口豁免。

**每次爬取至少三轮，禁止提前终止。** 每个 `collection_goal` 必须在 `02_Web_Collection_Tasks.csv` 中有三条任务（`round=1/2/3`），验证器 `validate_collection_tasks.py` 强制检查缺轮即 FAIL。

### Round 1 — 广度扫描（round_goal=coverage）

目的：**尽可能多地找到候选来源**，铺开覆盖面，不做深度提取。

- 按数据类路由全渠道铺开：官方/监管/电网运营商 + 研究机构 + 零售/电商 + 社区/社交 + 试点项目。
- 每个数据类至少覆盖 4 类渠道；每个渠道至少 2 个独立来源（官方源 + 三角源）。
- 用本地语言 + 英语 + 中文同义词各搜一轮；记录搜索词、结果数、候选 URL 清单。
- 输出：候选源清单（可全部进 `00_Source_Ledger.csv`，`tier` 标注）；本轮的 `saturation_evidence` 写"覆盖了哪些渠道、发现多少候选源"。

### Round 2 — 深度挖掘（round_goal=depth）

目的：**对 R1 每个可用候选源做精确化提取**，把字段填满。

- 逐个打开 R1 候选源：提取精确数值/单位/日期/版本/税/运费/促销条件/库存/评分等计划字段；ASIN/型号标识核验后写入 `03_Model_Identifier_Check.csv`。
- 每型号价格至少 2 个渠道；评论语料爬取可见全量（或记录平台上限）。
- 政策/规模结论记录原文位置与发布日期；建模输入记录数据集元数据与变换。
- 输出：字段完整的 CSV 行；`saturation_evidence` 写"哪些字段已填满、哪些源拒绝/付费墙/缺字段"。

### Round 3 — 补漏与三角验证（round_goal=triangulation）

目的：**补 R2 缺口 + 关键结论双源交叉验证**。

- 对 R2 标记为缺/弱/付费墙的项，用替代渠道/替代关键词/替代语言再采一轮。
- 每个关键结论（市场规模、政策/补贴、价格锚点、技术参数）至少 2 个独立来源一致；不一致时保留两个值并标注更强来源。
- 仍无法获得的市场事实进入 `11_Evidence_Issues.csv`，并设置 `data_domain=market`；若据此申请数量例外，冻结 policy v3+ 要求三轮穷尽证据、三个计数审计链接、逐轮查询/来源/失败/原始留痕、零剩余高优线索、完整影响与处置字段及人工批准全部通过机械校验。数学建模输入不得记为缺口，必须按真实来源与物理约束校准模拟数据，写入 `12_Model_Assumptions.csv` 和 `14_Simulated_Modeling_Data.csv`；禁止静默替代或伪装为观测值。
- 输出：缺口清单（清零或显式标注）；`saturation_evidence` 写"关键结论的交叉验证结果、遗留缺口编号"。

### 轮次记录与校验

- `02_Web_Collection_Tasks.csv` 每行必填：`round`（1/2/3）、`round_goal`（coverage/depth/triangulation）、`saturation_evidence`（本轮结束时的覆盖/新增/缺口摘要）。
- R3 行必须填写 `saturation_evidence`（或 cross-check 来源），验证器强制。
- 三轮之间**信息量递增**是默认要求：R2 发现应多于 R1，R3 应消解 R2 缺口或证明不可得；每轮 `notes` 记录"本轮新增了什么、比上轮多发现了什么"。
- 多轮重复同一 URL 是允许的（深度递增），但每轮必须产出新增内容；若某轮确实无新增，在 `saturation_evidence` 中写明"本轮无新增信息（已饱和），依据：xxx"——仍须完成三轮。
