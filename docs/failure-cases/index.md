# Failure Case Library（Phase 13）

本目录是自动化改造的失败案例库，共 8 个案例，均来自真实事件（含 2026-08-19
LLM 配额耗尽导致 Phase 2 中断的 FC-001，以及真实研究链路首次跑通的 FC-007/FC-008）。

| Case | 标题 | 阶段 | 标签 |
|---|---|---|---|
| FC-001 | LLM 计费周期配额耗尽（403 usage limit） | research | quota / llm / 403 / cost |
| FC-002 | 搜索适配器不可用（fail-closed） | research | adapter / fail-closed / search |
| FC-003 | 发布器失败（publisher failed） | publish | publisher / artifact / dependencies |
| FC-004 | 数据饱和未达成（saturation PARTIAL/BLOCKED） | research | saturation / quality / budget |
| FC-005 | LLM 网关超时/上游故障（transient） | research | gateway / transient / timeout |
| FC-006 | 任务重复提交（409 DUPLICATE_TASK） | trigger | idempotency / trigger / 409 |
| FC-007 | 真实研究链路首次跑通问题集（markdown/JSON/凭证） | research | real-research / anysearch / extraction / llm |
| FC-008 | 真实研究证据冲突导致 BLOCKED | validation | conflict / blocked / human-in-the-loop |

- 结构化目录：`catalog.yaml`（可被 `automation.failure_library.FailureLibrary` 加载检索）
- 使用方法：异常文本 → `FailureLibrary.match(text)` → 命中 case 的 recovery/prevent
- 新增案例：复制模板追加到 `catalog.yaml`，并在此表登记
