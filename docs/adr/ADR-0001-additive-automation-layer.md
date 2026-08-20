# ADR-0001: 自动化层为增量子包，不重构内核

- 状态：Accepted
- 日期：2026-08-19

## 背景
企业内核（evidence/freeze/validation/artifacts）已稳定并受 51+ 回归测试保护；
自动化改造不能动摇领域边界（publisher 禁联网、Validation 先于 Freeze、Freeze 不可变）。

## 决策
新增 `src/enterprise_energy_research/automation/` 子包承载契约/状态机/服务/API/
策略/集成；内核文件仅允许加法式修改（如 `Phase3Runner.process_batches_until_ingest`
拆分），禁止改动既有行为。跨内核文件的任何必要修改必须在交付报告中说明。

## 后果
- 内核回归线（原 88 测试）始终可独立验证；自动化层测试叠加其上（现 122+）。
- 编排逻辑集中在 automation 层，内核保持"可运行证据内核"的单一职责。
