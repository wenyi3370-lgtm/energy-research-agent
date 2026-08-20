# Runbook（运维手册）

## 状态速查

| 状态 | 含义 | 处理 |
|---|---|---|
| REVIEW_REQUIRED | 人工评审门 | 评审人 POST review（APPROVE/EDIT_AND_APPROVE/REJECT/RESEARCH_AGAIN） |
| FAILED | 执行失败（error.retryable 区分） | retryable=true → POST retry（有限次）；false → 人工诊断 |
| BLOCKED | 验证阻断 / 适配器不可用 / **证据冲突** | 见下方「BLOCKED 与证据冲突」 |
| RETRY_EXHAUSTED | 重试次数耗尽 | 人工介入，确认后手工重置或升级资源 |

## BLOCKED 与证据冲突（重要）

真实研究最常见的 BLOCKED 原因不是故障，而是**系统发现了来源冲突并拒绝自行裁决**
（铁律：冲突是一等记录，禁止静默平均/覆盖）。review_reasons 会带
`UNRESOLVED_CORE_CONFLICT: <field>` 及 WARNING（产品覆盖不完整等）。

处理步骤：

1. **查看冲突详情**（操作面板或 API）：

```
GET /api/v1/research/{run_id}/conflicts        # 列出所有冲突组
GET /api/v1/research/{run_id}/result           # review_reasons 含 UNRESOLVED_CORE_CONFLICT
```

（也可在容器内查具体 claim 值与来源，见下方命令。）

2. **判断并裁决**：确认冲突各方数值与来源后，选择处置：

```bash
# 选定权威说法（revenue 案例：以年报 PDF 口径为准）
curl -X POST http://localhost:8000/api/v1/research/{run_id}/conflicts/{conflict_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"reviewer":"你的名字","decision":"select_authoritative","selected_claim_id":"CLAIM-xxx","rationale":"以官方年报为准"}'
# 或 coexist（口径差异可共存）/ superseded（已被取代）
```

3. **恢复执行**（不重跑研究，直接验证+发布）：

```bash
curl -X POST http://localhost:8000/api/v1/research/{run_id}/resume
```

4. 若还有**其他 BLOCKING 冲突**，会再次 BLOCKED（freeze 拒绝），重复 2-3 步逐个裁决。

> 裁决记录全量落 `conflict_resolutions` 表（reviewer/decision/selected_claim/rationale），
> 冻结证据保持不可变——完全可审计、可追溯。未裁决的 BLOCKING 冲突绝不放行。

## 僵尸任务检测（自动保险）

容器重建/进程被杀会让正在执行的 run 悬挂在 RESEARCHING。系统自动恢复：

- **触发**：`POST /api/v1/maintenance/recover-stale`（n8n 每小时监测时自动执行）
- **规则**：RESEARCHING 且 `started_at` 超过 **120 分钟**无进展 → 标记 FAILED（retryable=True，错误信息注明"executor process interrupted"）→ 触发飞书失败通知
- **处置**：FAILED 后 `POST /retry` 重新执行（正常研究 10-20 分钟，阈值不会误伤）
- **手动**：`curl -X POST http://localhost:8000/api/v1/maintenance/recover-stale`

## 关键查询

```sql
-- 运行状态分布
SELECT status, count(*) FROM research_runs GROUP BY status;
-- 失败原因
SELECT error_type, count(*) FROM research_runs WHERE status='FAILED' GROUP BY error_type;
-- 人工评审耗时
SELECT run_id, human_review_seconds FROM research_runs WHERE human_review_seconds IS NOT NULL;
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
