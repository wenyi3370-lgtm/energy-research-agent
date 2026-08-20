# ADR-0004: 适配器与集成一律 fail-closed

- 状态：Accepted
- 日期：2026-08-19

## 背景
研究系统服务政策/法规/投资判断场景；搜索与通知集成缺凭证时必须显式失败，
不能静默降级、猜测数据或假装已通知。

## 决策
1. 搜索：`OrchestratingExecutor` 只使用 `health()==available` 的适配器；
   缺失偏好 → blocked envelope → 零证据 → BLOCKED；`from_environment()` 构造失败用
   `UnconfiguredSearchAdapter` 兜底。
2. 通知：`LarkFeishuAdapter` 无 `EER_FEISHU_*` 凭证 → `available()==False` →
   notifier no-op 但写 warning 日志 + 事件（`notify.error`），绝不静默。
3. LLM：无 gateway → 抽取只透传 recorded fixture 批次（显式标注），不假装抽取。

## 后果
- 配置缺失时系统"诚实地说不知道"，而不是"自信地说错"。
- 每个 fail-closed 分支都有对应 review_reasons / 日志条目可排查。
