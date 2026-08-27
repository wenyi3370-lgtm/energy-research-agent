# Failure Case Library

本目录记录 Agent 真实运行中已验证的失败模式，包括 LLM 配额耗尽、搜索能力不可用、
发布依赖缺失、证据饱和不足及真实研究链路故障。每项都包含检测信号和恢复动作。

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
