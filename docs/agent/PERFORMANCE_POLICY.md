# Performance Policy — 减少时间不得降低质量

> **规则（P0 不变量）：任何缩短研究/交付耗时的手段，都不得降低证据量或质量门槛。
> "证据够不够"由饱和策略与质量门槛决定，不由时间预算决定。**

日期：2026-08-25（用户明确要求固化的约束，写于 HYBRID 融合验证期间）

## 1. 允许的时间优化（质量中立）

| 手段 | 机制 | 说明 |
|---|---|---|
| 并发抓取 | `ERA_FULLTEXT_WORKERS`（默认 6，可调大） | 同样的页面集，更少墙钟时间 |
| URL 去重 | `hydrate_target_pages` 按 URL 去重，一次抓取多目标复用 | 覆盖不变 |
| 饱和早停 | `EvidenceDeltaSaturation`（最小静默轮 2） | "证据够"由边际产出阈值判定，天然质量感知 |
| 避免重复工作 | §24 恢复轮禁止重复 query；已满足 Goal 不重跑（§12 continuation） | 覆盖不变 |
| 恢复轮定向补采 | 下一轮只跑缺口定向查询（目标：recovery 不再全量重跑企业计划） | 见下方"现状" |

## 2. 禁止的时间优化（质量破坏）

| 禁止项 | 原因 |
|---|---|
| 缩小 `config/research_budgets.yaml`（max_queries/max_pages/max_images/max_model_calls） | 证据量本身就是质量；缩减预算 = 削减证据 |
| 跳过 / 降级任何质量门槛（正文深度、渲染质检、制品一致性、饱和门槛、海外 Stage Gate） | 门槛是交付契约 |
| 用 mock / 录制数据冒充真实链路完成验收 | 测试可离线，验收必须真实（§78-25） |
| 降低阈值 / 删除断言让失败测试通过 | 明确禁止（§55/§78-24） |
| 用"时间不够"作为提前产出薄交付物的理由 | 证据不足 → 如实 BLOCK + Auditable Limitation，或进入 Recovery |

## 2.5 测试迭代成本纪律

- 迭代期（改代码→验证循环）：`pytest --lf --ff` —— 只重跑上次失败/中断处，
  **禁止** `-p no:cacheprovider`（它会清除失败缓存，导致全量重跑）。
- 中断恢复：`.pytest_cache/v/cache/lastfailed` 记录失败集，下次 `--lf` 自动从断点继续。
- 最终发布门（里程碑/交付前）：才做一次无 `--lf` 的**全量**回归。
- 新增/改动模块的定向测试始终先跑；`--lf` 是其补充，不替代定向测试。

## 3. 判定原则

1. "证据足够"的唯一判据：`collection_saturation_policy.yaml` 的轮次/来源/三角验证门槛 + 各质量验证器（CoreValidator、正文深度、渲染 QA、制品审计）。
2. 时间预算（`max_elapsed_minutes`）只负责"最多等多久"，不负责"够不够"；超时按失败分类如实处理（BUDGET_EXHAUSTED / RECOVERY_EXHAUSTED），绝不降级产出。
3. 任何性能优化提案必须附带"质量等价性论证"：证明覆盖集合与门槛判定结果在优化前后一致。

## 4. 现状与 TODO

- ✅ 已生效：并发抓取、URL 去重、饱和早停、恢复轮去重（§24）、continuation 不重跑已满足 Goal。
- ✅ 已实现（2026-08-25）：**恢复轮仅缺口定向查询**——`research_and_validate(..., recovery_only=True)`
  跳过全量计划，只执行本轮定向补采查询（deep_retry 风格），证据在同一次追加式 run 内跨轮累积。
  验证：`test_recovery_only_never_reruns_full_plan`（全量 50+ 查询 vs 恢复轮 <15 条且携带本轮策略）。
  生产默认预算与全部质量门槛不变。
- ⚠️ 验证探针例外：`scripts/agent_hybrid_live.py` 使用生产预算；探针仅收紧 Agent 循环上限（迭代/恢复轮数）以控制验证时长，**不缩减每轮证据量**。
