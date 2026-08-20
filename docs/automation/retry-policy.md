# Retry Policy（Phase 8）

`automation/retry.py`，配置 `config/retry_policy.yaml`。

## 分类

| 类别 | 判定 | 示例 |
|---|---|---|
| **permanent**（不重试） | `is_transient() == False` | ValueError / ValidationError / InvalidTransitionError / DuplicateTaskError / RunNotFoundError / TypeError / NotImplementedError |
| **transient**（有限重试） | 默认瞬时 | AdapterError / GatewayError / TimeoutError / ConnectionError / OSError 及其余未知异常 |

## 退避

`backoff_seconds(attempt) = min(base * 2^(attempt-1), max) ± jitter`

默认：base 5s、上限 300s、jitter 20%、max_retries 3。

## 与状态机/审计结合

- 重试次数**不存内存**：从 `workflow_events` 中该 run 的 `STATUS_TRANSITION → RETRYING`
  事件计数，重启不丢、不会超限（`service.retry()` 达上限抛 `RetryExhaustedError` → API 409 RETRY_EXHAUSTED）。
- 失败 run 落 `ResearchError{error_type, message, retryable}`；`retryable=false` 的任务
  只转人工，不做无用重试（防 FC-001 类配额错误空转，见 failure-cases）。
