# Feishu 集成（Phase 7）

## 组件

- `automation/feishu/base.py` —— `FeishuAdapter` 协议（send / notify_run / available）
- `automation/feishu/lark.py` —— `LarkFeishuAdapter`：飞书开放平台 API（tenant_access_token + 消息发送）
- `automation/feishu/mock.py` —— `MockFeishuAdapter`：内存记录，测试/离线部署
- `automation/feishu/notifier.py` —— `FeishuNotifier`：状态变化通知桥

## 配置（.env / 环境变量）

```
EER_FEISHU_APP_ID=cli_xxx
EER_FEISHU_APP_SECRET=xxx
EER_FEISHU_DEFAULT_RECEIVER=analyst@company.com   # email / open_id / chat_id
```

未配置 → `available()==False` → 通知 no-op 并在事件日志显式记录（fail-closed，不静默丢弃）。

## 触发路径（表单 → 任务）

飞书表单 / 多维表格「新增记录」→ 配置 Webhook 回调到
`POST /api/v1/triggers/feishu`（body 见 `FeishuFormPayload`：requested_by/company/country/
region/product/research_type/topics/priority/notes）。n8n 版本见 `automation/n8n/`。

## 通知时机

`FeishuNotifier.NOTIFY_ON = {REVIEW_REQUIRED, PUBLISHED, FAILED, BLOCKED, REJECTED}`：
- REVIEW_REQUIRED → 通知评审人介入
- PUBLISHED → 通知需求方交付
- FAILED/BLOCKED/REJECTED → 通知异常与人工决策

通知失败只写 warning 日志 + 事件，绝不影响 run 状态推进。
