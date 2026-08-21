# ADR-0003: 自动裁决必须发生在 Freeze 之前

- 状态：Superseded（2026-08-20 改为全自动裁决）
- 日期：2026-08-19

## 背景
业务使用者不具备证据裁决能力，流程必须一次性执行，同时保持 Evidence-first 与
Freeze 前验证不变。

## 决策
1. `Phase3Runner.process_batches` 拆出 `process_batches_until_ingest`（ingest+验证，
   不冻结）；`service.execute_run` 在 VALIDATING 之后判定
   自动选择最可信的公司候选和冲突 claim：
   - 有可用证据 → APPROVED → 调用 `executor.freeze_and_publish`。
   - 无可用证据或结构错误 → BLOCKED，冻结不执行。
2. `ExecutionOutcome` 两阶段协议（research_and_validate / freeze_and_publish）在
   协议层保证该顺序；service 只从 APPROVED 调用后者。

## 后果
- 新任务不产生 REVIEW_REQUIRED。
- 机器选择理由、排序因素、入选与备选 claim 全量保存在证据冲突记录中。
