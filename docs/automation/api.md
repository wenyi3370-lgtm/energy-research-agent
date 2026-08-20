# Automation API 参考（Phase 2 + 扩展）

Base URL：`http://research-api:8000`（dev: `http://localhost:8000`）。OpenAPI：`/docs`。

统一错误体：`{"error": {"type", "message", "run_id"}}`；所有响应带 `X-Request-ID`。

## 端点

| Method & Path | 说明 | 成功 | 错误 |
|---|---|---|---|
| `POST /api/v1/research` | 提交任务（后台执行） | 201 `{run_id, task_id, status:QUEUED}` | 409 DUPLICATE_TASK |
| `GET /api/v1/research/{run_id}` | 状态摘要 | 200 ResearchResult | 404 RUN_NOT_FOUND |
| `GET /api/v1/research/{run_id}/result` | 完整结果 | 200 | 404 |
| `GET /api/v1/research/{run_id}/artifacts` | 发布物清单 | 200 `{run_id, artifacts[]}` | 404 |
| `POST /api/v1/research/{run_id}/review` | 评审决策 | 200 最终状态 | 409 INVALID_TRANSITION |
| `POST /api/v1/research/{run_id}/retry` | 失败重试（自动重执行） | 200 QUEUED | 409 INVALID_TRANSITION / RETRY_EXHAUSTED |
| `POST /api/v1/research/{run_id}/feedback` | ROI 反馈（Phase 11） | 201 | 404 |
| `POST /api/v1/triggers/feishu` | Feishu 表单触发（Phase 7） | 201 `{run_id, task_id, status}` | 409 |
| `GET /api/v1/roi/summary` | ROI 汇总（Phase 11） | 200 | - |
| `GET /api/v1/research/{run_id}/conflicts` | 该 run 的证据冲突列表（冲突裁决） | 200 `{run_id, conflicts[]}` | 404 |
| `POST /api/v1/research/{run_id}/conflicts/{conflict_id}/resolve` | 裁决 BLOCKING 冲突 → run 进入 QUEUED | 200 当前状态 | 404 CONFLICT_NOT_FOUND / 409 CONFLICT_RESOLUTION_INVALID / 409 INVALID_TRANSITION |
| `POST /api/v1/research/{run_id}/resume` | 裁决后恢复执行（验证保留证据 → freeze → publish） | 200 最终状态 | 409 CONFLICT_RESOLUTION_INVALID（无裁决） |
| `GET /health` | 存活 + DB 连通 | 200 | 503 |

## 冲突裁决（BLOCKED 的唯一人工出口）

真实研究最常见的 BLOCKED 原因是证据冲突（`UNRESOLVED_CORE_CONFLICT`）。
裁决请求体（`ConflictResolutionPayload`）：

```json
{
  "reviewer": "你的名字",
  "decision": "select_authoritative",
  "selected_claim_id": "CLAIM-000839",
  "rationale": "以年报PDF口径为准"
}
```

- `decision`：`coexist`（口径差异可共存）/ `select_authoritative`（必须带
  `selected_claim_id`，且须属于该冲突组）/ `superseded`（已被后续证据取代）
- 裁决记录落 `conflict_resolutions` 表（审计可追溯）；冻结证据保持不可变
- 裁决后 `POST /resume`：**不重跑研究**，直接对保留证据重新验证并发布
- 未裁决的其余 BLOCKING 冲突会继续阻断（freeze 拒绝），逐个裁决即可

## 状态机

`CREATED → QUEUED → RESEARCHING → EVIDENCE_COLLECTED → VALIDATING →`
`REVIEW_REQUIRED → APPROVED → FROZEN → PUBLISHING → PUBLISHED`（终态）
`└ BLOCKED / FAILED ↔ RETRYING → QUEUED`；`REJECTED`（终态）。

关键约束：VALIDATING 只能到 REVIEW_REQUIRED / APPROVED / BLOCKED；
FAILED 只能经 RETRYING 恢复；PUBLISHED / REJECTED 为终态（`automation/state_machine.py`）。

## 评审决策（review body）

```json
{"reviewer": "analyst_01", "decision": "APPROVE|EDIT_AND_APPROVE|RESEARCH_AGAIN|REJECT",
 "reason": "…", "original_value": {}, "modified_value": {}}
```

EDIT_AND_APPROVE 必须携带 `modified_value`（契约强制）。

## 环境变量

`EER_AUTOMATION_DATABASE_URL`、`EER_AUTOMATION_WORKDIR`、
`EER_FEISHU_APP_ID` / `EER_FEISHU_APP_SECRET` / `EER_FEISHU_DEFAULT_RECEIVER`（Phase 7 通知）。
