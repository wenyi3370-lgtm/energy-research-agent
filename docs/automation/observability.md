# 观测与成本（Phase 10）

`automation/observability.py`

## CountingGateway

包装任意 `ModelGateway`（不改协议），累计 `input_tokens / output_tokens /
llm_calls / estimated_cost_usd / latency_ms`。编排 executor 用它在真实抽取时采集
usage；`ExecutionOutcome` 携带 usage 字段 → service `upsert_metrics` 落 `run_metrics` 表。

成本估算按 provider 单价表（`DEFAULT_PRICES_USD_PER_1M`）计算，**永远标注 estimated**；
无真实 gateway 时 token 保持 0，ROI 报告不编造数字。

## run_span

`with run_span("research", run_id=...)`：测量 research / publishing 阶段墙钟时长，
退出时发 `step.finished` 事件。时长随 `_settle` 写入 metrics（后续可扩展 total/research/
validation/publishing 分项）。

## log_event

单行 JSON 事件（request_id/run_id/step/duration_ms/...），**禁止记录密钥与请求体**。
API 层每请求一行结构化日志（含 X-Request-ID 与延迟）。
