# n8n 集成说明（Phase 6）

## 工作流文件

`enterprise-research-workflow.json` —— 端到端自动化工作流：

```
Feishu Form Webhook → Map Form to Task → Submit Research Task (POST /api/v1/triggers/feishu)
  → Wait 15s → Poll Run Status (GET /api/v1/research/{run_id})
    → Published? ──yes──→ Build Publish Notice → Collect Feedback (ROI)
    → Review Required? ──yes──→ Build Review Notice → Wait For Human Review → Approve In Review Gate
    → Failed? ──yes──→ Build Failure Notice → Auto Retry (POST /retry)
```

## 导入步骤

1. 启动 n8n（见仓库根 `docker-compose.yml`，服务名 `n8n`）。
2. n8n 界面 → Workflows → Import from File → 选择本 JSON。
3. 编辑节点中的占位配置：
   - `research-api` 主机：docker-compose 网络内为 `http://research-api:8000`；本机调试改为 `http://localhost:8000`。
   - Webhook 路径 `feishu-form-trigger`：在飞书表单/多维表格的「新增记录」自动化中配置 Webhook 回调到
     `https://<n8n-host>/webhook/feishu-form-trigger`（生产需 HTTPS 反代 + 签名校验）。
   - 「Collect Feedback (ROI)」节点的 JSON body 为示例值，需替换为真实反馈表单字段。
4. 保存并 Activate。

## 依赖端点（research-api）

| 端点 | 用途 |
|---|---|
| `POST /api/v1/triggers/feishu` | Feishu 表单触发（body 见 `automation.contracts.FeishuFormPayload`） |
| `GET /api/v1/research/{run_id}` | 轮询状态 |
| `POST /api/v1/research/{run_id}/review` | 评审决策（REVIEW_REQUIRED 门） |
| `POST /api/v1/research/{run_id}/retry` | 失败重试（自动重新执行） |
| `POST /api/v1/research/{run_id}/feedback` | ROI 反馈 |
| `GET /api/v1/roi/summary` | ROI 汇总 |

## 可靠性约定

- 提交与重试均幂等：重复触发同一 `idempotency_key` 返回原 run 状态。
- 轮询间隔建议 ≥15s；run 在 REVIEW_REQUIRED 时工作流进入人工等待，不会自动通过。
- 所有错误响应为 `{"error": {"type", "message", "run_id"}}`，n8n 可用 IF 节点按 `error.type` 分支。
