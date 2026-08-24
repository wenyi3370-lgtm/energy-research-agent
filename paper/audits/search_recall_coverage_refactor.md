# Search Recall & Coverage Refactor Audit

Date: 2026-08-24
Scope: P0 Search Recall & Coverage Expansion — Enterprise Research + Daily Intelligence

## 1. 修改前 Search Architecture

日报以 12 条固定中文查询分别运行 24h PRIMARY、72h RECOVERY，并对最多
12 个历史事件运行 7d UPDATE。企业研究以 GOAL_FAMILIES 生成 R1，再由
真实 gap/conflict/coverage 驱动 R2/R3/R4。两端都缺少共享 query intent、
source lane、动态 frontier 和完整 URL disposition。

## 2. 实际 Recall 短板

技术执行成功无法证明覆盖充分；固定中文词组不能系统覆盖别名、英文、
官方/政府/招标/合作方/技术文档等来源；搜索结果不能驱动下一轮；跳过 URL
和未覆盖 lane 不可审计。

## 3. 新 Search Recall Architecture

新增共享 `research/recall/`：

`Seed → Query Expansion → Source Lane → Entity/Event Mining → Dynamic Frontier → Convergence → Verification`。

使用 `RecallProfile.DAILY_INTELLIGENCE` 和 `RecallProfile.DEEP_RESEARCH`
隔离两种证据标准。

## 4. Query Expansion

Alias、intent、lane、language、max_variants 和 priority 均由
`config/intelligence_search_topics.yaml` 配置。默认 12 个日报 Seed 在无
UPDATE 时形成 25 个 PRIMARY 查询（12 Seed + 13 intent variants）、12 个
RECOVERY 和 8 个 SOURCE_PATROL，共 45 个初始查询；存在 12 个 UPDATE
目标时为 57 个初始查询。英语查询默认至少覆盖 V2G/BESS 海外发现。

## 5. Dynamic Frontier

`EntityEventMiner` 只读取 hydrated page，发现 project、subsidiary、policy、
tender、product_model 等 `FrontierEntry`。Daily P0/P1 最多 one-hop；P2/P3
不扩展。Enterprise P0/P1 最大深度 2，并严格受 query/result-slot 预算控制。

## 6. Source Lane

稳定 schema 包含 corporate_official、government_regulatory、
tender_procurement、industry_association、media_discovery、customer_partner、
technical_document、financial_disclosure 八类。不同 topic 的 intent 绑定到
不同 lane，不能把 Internet 当作单一来源池。

## 7. Source Roster

`config/intelligence_source_roster.yaml` 配置政府、监管、电网、协会、招投标
和披露来源。默认巡检 8 个重点来源；每来源 listing 上限为 2 页（硬上限 3），
文章上限可配置。当前日报主路径采用有界 `site:` source patrol；直接栏目翻页
能力保留为后续 P1 连接器扩展点，审计中如实记录 listing_pages_opened。

## 8. Enterprise Integration

企业 R1 前执行 source-lane recall variants；R1 hydrated page 驱动 bounded
frontier follow-up；Critical Gap 才可触发 `AnomalyHunter`。既有 R1、R2 gap、
R3 conflict、R4 coverage 全部保留。

## 9. Daily Intelligence Integration

Collector 变为三阶段：PRIMARY → Frontier → SOURCE_PATROL/RECOVERY/UPDATE。
随后仍使用原 hydration、DeepSeek extraction、Freshness Gate、same-event
dedupe、recency-first ranking 和 Top 5。

## 10. Budget Policy

`RecallBudgetPolicy` 是唯一预算源。Daily 默认 total_result_slots=168，初始
阶段预留 12 个 frontier slots；UPDATE、RECOVERY、SOURCE_PATROL 和 Seed
最低深度先分配，扩展查询再按 P0→P3 补深度。默认完整 12 Seed + 12 UPDATE
计划仍为 156 个初始 slots + 12 个 frontier reserve，未恢复固定 100，也未
突破 168。

## 11. Freshness Rules 保留情况

已保留：近期转载/二次传播可 NEW；历史事件的近期页面可 NEW；未知发布时间
为 NEW+LOW 且排在已知时间之后；明确 >72h 为 OLD；confidence 仅内部存储；
score 无硬门槛；排序为时间→可信度→来源权威性→Score；最多 5 条。

## 12. Recall Audit

每条 Query 输出请求/返回数、unique/duplicate URL、listing/search skip、
hydration、extraction、frontier 和 filter reasons。每个被跳过 URL 使用
`UrlDispositionReason`；同时记录 source-patrol 和完整 Funnel。

## 13. Convergence

Daily 至少两轮，frontier round 无新 P0/P1 可 `RECALL_SATURATED`。Enterprise
至少三轮且连续两轮无新 P0/P1 才可 saturated。预算耗尽固定为
`RECALL_BUDGET_EXHAUSTED`，技术执行 OK 不会映射成 coverage complete。

## 14. 新增文件

- `research/recall/`（models、budget、query expansion、source lanes、miner、frontier、anomaly、coverage、audit、engine）
- `config/intelligence_search_topics.yaml`
- `config/intelligence_source_roster.yaml`
- `tests/test_search_recall_coverage.py`
- 本审计报告

## 15. 修改文件

修改 Collector、DailyBrief/Service、AdaptiveResearchRunner、四份主文档和两份
既有测试。Portal、飞书 Delivery、Word/HTML/PPT、Decision Intelligence 均未
纳入本轮修改。

## 16. 测试结果

修改前实测基线：452 passed, 1 skipped。
专项新增：34 项 Search Recall/Coverage 回归（包含真实验收后新增的全局
Frontier 上限与导航缩写噪声回归）。
最终 full regression：486 passed, 1 skipped（10 个既有 dependency/
deprecation warnings，无新增 failure）。

Docker `research-api` 镜像重建成功；替换容器后状态为 `healthy`，`/health`
返回 `status=ok, version=0.9.0`，`/api/v1/intelligence/status` 返回
`paused=false`。容器内 Daily Recall 计划实测 18 queries / 60 initial slots +
12 frontier reserve = 72，严格小于 168 上限。Portal smoke test 通过，人工研究、
停止全部调查、每日推送暂停/恢复控件均存在，浏览器 console errors=0；测试未
创建研究任务、未触发飞书发布。

## 17. Live Acceptance

AnySearch vendor manifest：PASS（12,328 files）。
AnySearch energy sub-domain discovery：PASS；系统代理失败后按既有适配器规则
process-local direct retry 成功。
Daily mini acceptance（2026-08-24 12:44 +08:00，同窗、不发布飞书）：旧固定
12 Query 为 12 hits / 12 unique URLs / 8 domains；Recall 使用 72 slots，执行
37 queries，72 hits，48/48 hydration 成功，得到 28 candidates，Freshness
接受 10、拒绝 18、unknown-time 8、secondary 4、original 6、最终 Top 5；
相对固定查询新增 47 URLs、31 domains，budget exhaustion=0。

Enterprise discovery-only acceptance：宁德时代使用 8 variants / 23 slots，
23 hits、16 URLs、9 domains、8/8 hydration、62 bounded frontier leads、1 个
follow-up，budget exhaustion=0；线索包括临港生产基地、美国德州 220MWh
液冷储能项目。特来电使用 7 variants / 18 slots，18 hits、11 URLs、9 domains、
8/8 hydration、budget exhaustion=0。两次验收 verified claims=0，明确证明
Frontier 未越过 evidence boundary。第二个样本暴露的导航缩写噪声已转成
型号必须含数字的回归修复。

## 18. Before / After Metrics

| Metric | Before | After (deterministic plan) |
|---|---:|---:|
| Daily seed queries | 12 | 12 |
| Daily PRIMARY query variants | 12 | 25 |
| Daily source-patrol queries | 0 | 8 |
| Daily initial queries, no UPDATE | 24 | 45 |
| Daily initial queries, 12 UPDATE | 36 | 57 |
| Logical source lanes | untracked | 8-schema / run-attempt audited |
| Default total result slots | dynamic up to 168 | 156 initial + 12 frontier reserve = 168 |
| Frontier discoveries | 0 | Daily acceptance 242 raw leads；修正后全局硬上限 64 |
| URL skip reasons | silent/partial | typed disposition required |
| Budget exhaustion in deterministic plan | 0 after f270fd2 | 0 |

| Metric | Before | After (live acceptance) |
|---|---:|---:|
| Daily unique domains | 8 | 39（+31） |
| Daily hydrated pages | untracked | 48/48 |
| Daily candidate items | run-dependent | 28（10 passed freshness） |
| Enterprise CATL unique domains | untracked | 9 |
| Enterprise CATL frontier | 0 | 62 bounded leads |

以上来自真实同窗验收，不以代码行数代替效果。

## 19. Remaining Limitations

- Search engine/index availability and source robots/authentication remain external.
- Direct listing pagination is schema/budget-ready but the default roster currently uses bounded site search.
- Deterministic regex miner is conservative; future semantic miner may improve multilingual entity recall while retaining the same state machine.
- Bounded recall can never prove complete Internet coverage.

## 20. Blockers

- Web-Rooter CLI is not installed/on PATH, so WR-based external acceptance is unavailable；已按产品边界使用批准的 AnySearch 完成真实验收。
- Product workflow does not depend on WR; approved AnySearch is healthy. Kimi/browser availability and live provider quotas are reported separately during final acceptance.

## 21. Post-acceptance P0 corrections

同一截止时间的完整 168-slot 日报对比显示：旧生产方案 102 次抽取、60 条候选、
13 条通过时效、最终 5 条；新 Recall 方案 97 次抽取、56 条候选、13 条通过时效、
最终 5 条。该结果证明来源面扩大，但不证明有效产出增加，因此验收口径已明确为
hydrated/extracted/verified/freshness-accepted/final-selected，而不是命中数。

企业深研曾将 Recall 查询放在原 R1 之前并共享 `max_pages`，满返回模拟会把产能和
生产线各从 10 页挤压到 2 页。现已改为双预算池：Recall 初始发现使用独立的
48-slot 预算（默认 60 中保留 12 给 Frontier），原 R1 继续完整使用原定 240 页。
产品、工厂、产能、生产线、财务等 Goal Family 不再因 Recall 增量而减少。

日报手动/定时入口增加跨线程/进程的日期级原子锁。并发复现实测两个同时调用只
产生一次发布，失败会释放自有锁；接口对运行中和当日已发布返回
`triggered=false`。Portal 初始页面永久显示每日一次规则，运行中或已发布时按钮
保持禁用。修正后专项 105 passed；全量 490 passed, 1 skipped。
