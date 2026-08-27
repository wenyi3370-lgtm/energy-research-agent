# Agent Automation API 参考

Base URL：`http://research-api:8000`（dev: `http://localhost:8000`）。OpenAPI：`/docs`。

统一错误体：`{"error": {"type", "message", "run_id"}}`；所有响应带 `X-Request-ID`。

## 端点

| Method & Path | 说明 | 成功 | 错误 |
|---|---|---|---|
| `POST /api/v1/research` | 提交任务（后台执行） | 201 `{run_id, task_id, status:QUEUED}` | 409 DUPLICATE_TASK |
| `GET /api/v1/research/{run_id}` | 状态摘要 | 200 ResearchResult | 404 RUN_NOT_FOUND |
| `GET /api/v1/research/{run_id}/result` | 完整结果 | 200 | 404 |
| `GET /api/v1/research/{run_id}/artifacts` | 发布物清单 | 200 `{run_id, artifacts[]}` | 404 |
| `POST /api/v1/research/{run_id}/retry` | 失败重试（自动重执行） | 200 QUEUED | 409 INVALID_TRANSITION / RETRY_EXHAUSTED |
| `POST /api/v1/research/{run_id}/feedback` | ROI 反馈（Phase 11） | 201 | 404 |
| `POST /api/v1/triggers/feishu` | Feishu 表单触发（Phase 7） | 201 `{run_id, task_id, status}` | 409 |
| `GET /api/v1/roi/summary` | ROI 汇总（Phase 11） | 200 | - |
| `GET /api/v1/research/{run_id}/conflicts` | 该 run 的自动裁决记录、入选 claim 与备选 claim | 200 `{run_id, conflicts[]}` | 404 |
| `GET /health` | 存活 + DB 连通 | 200 | 503 |

## 自动裁决

公司身份歧义和同字段证据冲突不再创建人工任务。系统按来源等级、监管/官方
权威性、独立来源支持数、发布日期、表述精确度和稳定排序选择最可信项；
`GET /conflicts` 可查看 `selected_claim_ids`、排序分析及全部备选值。只有无可用
证据或运行故障才会 BLOCKED/FAILED。

## 状态机

`CREATED → QUEUED → RESEARCHING → EVIDENCE_COLLECTED → VALIDATING →`
`APPROVED → FROZEN → PUBLISHING → PUBLISHED`（终态）
`└ BLOCKED / FAILED ↔ RETRYING → QUEUED`；`REJECTED`（终态）。

关键约束：新任务从 VALIDATING 自动进入 APPROVED 或 BLOCKED；
FAILED 只能经 RETRYING 恢复；PUBLISHED / REJECTED 为终态（`automation/state_machine.py`）。

## 环境变量

`ERA_AUTOMATION_DATABASE_URL`、`ERA_AUTOMATION_WORKDIR`、
`ERA_FEISHU_APP_ID` / `ERA_FEISHU_APP_SECRET` / `ERA_FEISHU_DEFAULT_RECEIVER`（Phase 7 通知）。
