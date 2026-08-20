# ADR-0006: Review / Retry 策略全部声明式配置

- 状态：Accepted
- 日期：2026-08-19

## 背景
评审门与重试边界是业务策略，不是代码逻辑；审计要求"Rule 能解决的不用 Agent"。

## 决策
- Review：`config/review_policy.yaml` 10 条 RV 规则（enabled/阈值全可配），
  `ReviewPolicy.load()` 加载；**默认只启用 RV-01**，与 V1 基线一致——启用更多
  规则只会收紧门，不会放松。
- Retry：`config/retry_policy.yaml`（max_retries/base/max/jitter）；transient/permanent
  分类在 `automation/retry.py`；重试计数取自 `workflow_events` 持久轨迹。
- 改策略 = 改 YAML，不发布代码；缺失文件回退到代码内默认值。

## 后果
- 业务节奏变化（敏感类型、置信度阈值、重试次数）无需发版。
- 默认配置保持"不过度收紧"，避免拖慢 V1 自动化节奏。
