# Runbook（运维手册）

## 状态速查

| 状态 | 含义 | 处理 |
|---|---|---|
| FAILED | 执行失败（error.retryable 区分） | retryable=true → POST retry（有限次）；false → 人工诊断 |
| BLOCKED | 无可用证据 / 结构错误 / 适配器不可用 | 修复数据源或环境后从网页重跑 |
| RETRY_EXHAUSTED | 重试次数耗尽 | 人工介入，确认后手工重置或升级资源 |

## 自动裁决与 BLOCKED（重要）

身份或证据冲突会自动按可信度排序并继续，不再造成 BLOCKED。冲突仍是一等记录，
不会静默平均或覆盖。可通过以下接口审计：

```
GET /api/v1/research/{run_id}/conflicts        # 列出所有冲突组
GET /api/v1/research/{run_id}/result           # 最终状态与警告
```

若仍为 BLOCKED，说明没有可供选择的有效证据或出现运行/结构故障，应修复环境或数据源，
再从本地网页重新发起；业务人员不参与内容裁决。

## 僵尸任务检测（自动保险）

执行链抛出明确异常时会立即把 run 标记为 FAILED、停止后续步骤并推送飞书。容器重建/进程被杀等情况可能不抛异常，会让 run 悬挂在 RESEARCHING；故障看门狗负责补偿：

- **触发**：n8n 工作流 `research-failure-watchdog-v1` 每小时调用 `POST /api/v1/maintenance/recover-stale`
- **规则**：RESEARCHING 且 `started_at` 超过 **120 分钟**无进展 → 标记 FAILED（retryable=True，错误信息注明"executor process interrupted"）→ 触发飞书失败通知
- **安全边界**：看门狗没有研究提交、watchlist、retry 或飞书触发节点；它只终止悬挂任务并通知，不创建研究、不自动重试
- **处置**：如需重试，必须由人工调用 `POST /retry`（正常研究 10-20 分钟，阈值不会误伤）
- **手动**：`curl -X POST http://localhost:8000/api/v1/maintenance/recover-stale`

## 关键查询

```sql
-- 运行状态分布
SELECT status, count(*) FROM research_runs GROUP BY status;
-- 失败原因
SELECT error_type, count(*) FROM research_runs WHERE status='FAILED' GROUP BY error_type;
-- 自动裁决冲突数
SELECT run_id, conflict_count FROM run_metrics WHERE conflict_count > 0;
-- ROI 输入
SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT 20;
```

## 已知故障

见 `docs/failure-cases/index.md`（FC-001 配额耗尽、FC-002 适配器不可用、
FC-003 发布失败、FC-004 饱和未达成、FC-005 网关超时、FC-006 重复提交）。
`FailureLibrary.match(异常文本)` 可检索处置建议。

## 指标

- `GET /api/v1/roi/summary`：ROI 汇总（仅统计有 feedback 的 run）
- `run_metrics` 表：evidence/conflict/gap/verified_claim、token/cost、search_calls
- 日志：API 层每请求一行（request_id/run_id/path/status/latency）；automation 事件 JSON-line
