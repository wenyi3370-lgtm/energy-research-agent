# 自动裁决门（Phase 5）

## 规则引擎

`automation/review.py` 定义 10 条声明式触发规则（RV-01 ~ RV-10），配置在
`config/review_policy.yaml`，每条可独立 `enabled`：

| 规则 | 触发条件 | 默认 |
|---|---|---|
| RV-01 | validation 通过但带警告（PASS_WITH_WARNINGS） | disabled |
| RV-02 | 模型置信度 < min_confidence (0.70) | disabled |
| RV-03 | risk_level ≥ HIGH | disabled |
| RV-04 | 存在冲突 claim | disabled |
| RV-05 | 存在数据缺口 | disabled |
| RV-06 | evidence 记录数 < min_evidence (10) | disabled |
| RV-07 | executor 自带 review_reasons（如产品看板跳过） | disabled |
| RV-08 | 市场级任务（无公司主体） | disabled |
| RV-09 | 敏感类型（policy_regulation / channel_research） | disabled |
| RV-10 | 高/紧急优先级需高级别确认 | disabled |

生产配置全部禁用；这些规则只为旧部署兼容和审计原因解析保留，不会暂停新任务。

## 门控流程（service 内强制）

```
VALIDATING
  ├─ BLOCKED 报告 → BLOCKED（终态语义，finished）
  ├─ 无可用证据/结构错误 → BLOCKED
  └─ 身份与冲突自动裁决 → APPROVED → FROZEN → PUBLISHING → PUBLISHED
```

- 不产生人工审批、拒绝或恢复步骤。
- `ConflictGroup` 保存自动排序依据、`selected_claim_ids` 和全部备选 claim。
- **冻结发生在 APPROVED 之后**：`Phase3Runner.process_batches_until_ingest`
  只做 ingest+验证，freeze 由 `finalize_evidence` 在门后执行（ADR-0003）。

## 与 executor 的关系

executor 的历史 `review_required` 标志会被清零；`review_reasons` 仅作为警告和
审计信息随最终 `ResearchResult` 保存，不会创建人工任务。
