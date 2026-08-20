# 编排接线（关键新增）

审计发现（`architecture-audit.md` §2.2）：`ResearchPlanner → SearchExecutor →
EvidenceExtractor → DataSaturationValidator` 已实现但无生产 runner。
`automation/orchestration.py` 的 `OrchestratingExecutor` 将其接成
**由状态机驱动的确定性流水线**：

```
research_and_validate（不冻结）:
  plan (ResearchPlanner, budget=config/research_budgets.yaml)
  → search (SearchExecutor, 页面预算, 缺失适配器→blocked envelope)
  → extract (EvidenceExtractor; gateway 缺失→仅 recorded fixture 批次)
  → saturation (DataSaturationValidator, findings→review_reasons)
  → Phase3Runner.process_batches_until_ingest（resolver→normalizer→validators→
     classifier→energy→solutions→ingest，NO freeze）
  → CoreValidator.validate（评审门输入）

freeze_and_publish（仅 APPROVED 后调用）:
  Phase2Runner.finalize_evidence（re-validate→freeze→plan→export）
  → ArtifactPublicationService.publish → ArtifactConsistencyAuditor.audit
```

## 关键点

- **Human Gate 与内核解耦**：`Phase3Runner` 拆出 `process_batches_until_ingest`
  （加法式重构，原方法行为不变——test_phase3_workflow 全绿验证）。
- **fail-closed**：`from_environment()` 构造 AnySearch/Kimi WebBridge，失败用
  `UnconfiguredSearchAdapter` 兜底；零证据 → BLOCKED，绝不猜测。
- **fixture 模式后门防泄漏**：`RecordedFixtureAdapter` 的批次带
  `extraction_method=recorded_fixture`，phase3 据此跳过图片归档；生产 run 若
  混入 fixture 批次会在审计/review_reasons 显式标注。
- **usage 采集**：真实 gateway 经 `CountingGateway` 包装，token/cost 随 outcome
  落入 `run_metrics`（Phase 10）。
