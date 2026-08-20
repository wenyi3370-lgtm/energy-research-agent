# ADR-0003: Human Gate 必须发生在 Freeze 之前

- 状态：Accepted
- 日期：2026-08-19

## 背景
用户原则 3（Human-in-the-loop）与既有"Validation Gate 先于 Freeze"铁律要求：
评审未通过不得创建不可变冻结包。

## 决策
1. `Phase3Runner.process_batches` 拆出 `process_batches_until_ingest`（ingest+验证，
   不冻结）；`service.execute_run` 在 VALIDATING 之后判定
   `outcome.review_required OR ReviewPolicy 规则`：
   - 通过 → APPROVED → 才调用 `executor.freeze_and_publish`（`finalize_evidence`）。
   - 否则 → REVIEW_REQUIRED，冻结永远不执行。
2. `ExecutionOutcome` 两阶段协议（research_and_validate / freeze_and_publish）在
   协议层保证该顺序；service 只从 APPROVED 调用后者。

## 后果
- 冻结包保证经过人工确认或明确的自动通过策略；REVIEW_REQUIRED 的 run 不可能有 freeze。
- 评审记录（decision/reason/前后值）全量落 `human_reviews` 表，可审计。
