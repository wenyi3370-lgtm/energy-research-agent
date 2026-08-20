# Review Gate（Phase 5）

## 规则引擎

`automation/review.py` 定义 10 条声明式触发规则（RV-01 ~ RV-10），配置在
`config/review_policy.yaml`，每条可独立 `enabled`：

| 规则 | 触发条件 | 默认 |
|---|---|---|
| RV-01 | validation 通过但带警告（PASS_WITH_WARNINGS） | **enabled** |
| RV-02 | 模型置信度 < min_confidence (0.70) | disabled |
| RV-03 | risk_level ≥ HIGH | disabled |
| RV-04 | 存在冲突 claim | disabled |
| RV-05 | 存在数据缺口 | disabled |
| RV-06 | evidence 记录数 < min_evidence (10) | disabled |
| RV-07 | executor 自带 review_reasons（如产品看板跳过） | disabled |
| RV-08 | 市场级任务（无公司主体） | disabled |
| RV-09 | 敏感类型（policy_regulation / channel_research） | disabled |
| RV-10 | 高/紧急优先级需高级别确认 | disabled |

默认只启用 RV-01 —— 与 V1 基线完全一致，启用更多规则只会收紧、不会放松门。

## 门控流程（service 内强制）

```
VALIDATING
  ├─ BLOCKED 报告 → BLOCKED（终态语义，finished）
  ├─ outcome.review_required 或 policy 触发 → REVIEW_REQUIRED（冻结前必须人工）
  └─ 自动通过 → APPROVED → FROZEN → PUBLISHING → PUBLISHED
```

- 评审决策：APPROVE / EDIT_AND_APPROVE → APPROVED → 冻结发布；
  REJECT → REJECTED（终态）；RESEARCH_AGAIN → RETRYING → QUEUED（重新执行）。
- 评审记录落 `human_reviews` 表（reviewer/decision/reason/original_value/modified_value），
  每次人工编辑可审计。
- **冻结发生在 APPROVED 之后**：`Phase3Runner.process_batches_until_ingest`
  只做 ingest+验证，freeze 由 `finalize_evidence` 在门后执行（ADR-0003）。

## 与 executor 的关系

executor 的 `review_required`/`review_reasons` 是"软"输入；最终门由
`service._gate()` 合并 executor 标志 + policy 规则决定，原因列表去重后写入
`ResearchResult.review_reasons`，供 n8n/飞书直接消费。
