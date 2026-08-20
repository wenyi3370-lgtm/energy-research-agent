# 配置清单（Configuration Checklist）

本文件逐项列出系统从"零配置能跑"到"生产真实运行"所需的全部配置。
标注：🟢 必填（缺失则功能不可用 / 无法启动）/ 🟡 可选（缺失只影响对应功能，fail-closed 保护）。

---

## 第 0 层：零配置基线（开箱即用）

**当前状态：不配置任何东西，API 就能跑** —— `EER_AUTOMATION_EXECUTOR` 默认
`synthetic`，用离线合成内核产出真实工件（excel/word/html），适合演示、联调、CI。
生产真实研究必须进入第 1~2 层。

## 第 1 层：生产部署基础（🟢 必需）

| 配置项 | 位置 | 说明 | 缺失后果 |
|---|---|---|---|
| Python 依赖 `api`+`database`+`models` | `pyproject.toml` extras | `pip install -e ".[api,database,models]"`；Dockerfile 已装 | API/DB/LLM 依赖缺失 |
| `EER_AUTOMATION_DATABASE_URL` | env | 自动化控制面 DB，生产用 `postgresql+psycopg://…`（docker-compose 已注入） | 默认 sqlite 可跑但生产建议 PG |
| `EER_AUTOMATION_WORKDIR` | env | evidence/工件工作目录（docker-compose 已注入 `/data/automation_work`，挂 volume） | 默认 `./automation_work` |
| vendor 嵌入技能 | `vendor/skills/` | anysearch / kimi-webbridge 等（Dockerfile 已 COPY） | 搜索适配器 fail-closed → BLOCKED |

## 第 2 层：真实研究编排（🟢 生产研究必需）

`EER_AUTOMATION_EXECUTOR=orchestrating` 后按需配置：

### 2.1 LLM 抽取网关（至少一个 provider）

| 配置项 | 说明 | 缺失后果 |
|---|---|---|
| `EER_DEEPSEEK_API_KEY` | 主 provider（deepseek-chat） | 全部不可用 → run FAILED（GatewayError） |
| `EER_OPENAI_API_KEY` | 兜底 provider | 仅影响 fallback |
| `EER_DEEPSEEK_API_BASE` / `EER_OPENAI_API_BASE` | 自定义端点 | 有默认值 |
| `litellm` 依赖 | `pip install -e ".[models]"` | GatewayError "LiteLLM is not installed" |

### 2.2 搜索适配器（至少一个可用，否则零证据 → BLOCKED）

| 适配器 | 依赖 | 说明 |
|---|---|---|
| AnySearch | `vendor/skills/anysearch`（完整脚本）+ `requests` + 联网 | **首次匿名调用会自动注册账号**并把凭证打印到 stdout（不是搜索结果！）。把生成的 `api_key` 写入 `vendor/skills/anysearch/scripts/.env`（`ANYSEARCH_API_KEY=as_sk_...`，该 .env 已被 .gitignore 忽略），容器重建后即直接可用 |
| Kimi WebBridge | ① 二进制 `~/.kimi-webbridge/bin/kimi-webbridge`；② daemon 运行（`kimi-webbridge start`，默认 127.0.0.1:10086）；③ 浏览器扩展已连接；④ `EER_KIMI_WEB_SESSION`（默认 `default`） | 三者任一缺失 → health 不可用 → 该适配器被过滤（不阻断 AnySearch）。注意：daemon 在宿主机时**容器内无法访问宿主 127.0.0.1**，容器部署下深度轮次（产品页）会 blocked——产品覆盖不完整会以 WARNING 呈现 |

### 2.3 验证命令

```bash
# 健康总览
curl -s http://localhost:8000/health
# 提交一个真实任务（orchestrating 模式）
curl -s -X POST http://localhost:8000/api/v1/research -H "Content-Type: application/json" \
  -d '{"task_id":"PROD-001","requested_by":"ops","company":"某储能企业","research_type":"company_profile"}'
```

## 第 3 层：飞书通知（🟡 可选）

| 配置项 | 说明 | 缺失后果 |
|---|---|---|
| `EER_FEISHU_APP_ID` / `EER_FEISHU_APP_SECRET` | 飞书开放平台自建应用凭证 | 通知 no-op（日志记录），研究不受影响 |
| `EER_FEISHU_DEFAULT_RECEIVER` | 接收人 email / open_id / chat_id | 同上 |
| 应用权限 | 飞书后台开启 `im:message`（发送消息权限）+ 发布应用 | API 403 → 通知 delivered=false |
| 表单触发 | 飞书表单/多维表格「新增记录」→ Webhook → `POST /api/v1/triggers/feishu` | 无自动触发（可手动/API 提交） |

## 第 4 层：n8n 工作流（🟡 可选）

| 配置项 | 说明 |
|---|---|
| n8n 服务 | `docker compose up` 已含（:5678）；导入 `automation/n8n/enterprise-research-workflow.json` |
| `research-api` 可达性 | 同网络内 `http://research-api:8000`（本机调试改 localhost） |
| Webhook 公网暴露 | 生产需 HTTPS 反代 + 飞书签名校验；webhook 路径 `/webhook/feishu-form-trigger` |
| Feedback 节点 body | 替换示例 JSON 为真实反馈表单字段 |

## 第 5 层：定时监测（🟡 可选）

| 配置项 | 说明 |
|---|---|
| `config/watchlist.yaml` | 按需 `enabled: true` 并确认 task 模板字段 |
| 外部调度 | cron / n8n Schedule Trigger 调 `MonitorRunner.run_due(datetime.now())`（见 docs/automation/monitor.md） |

## 第 6 层：策略调优（🟡 可选，改 YAML 即生效）

| 配置 | 文件 | 说明 |
|---|---|---|
| Review Gate | `config/review_policy.yaml` | 10 条 RV 规则独立开关/阈值；默认只启用 RV-01（与 V1 基线一致） |
| Retry | `config/retry_policy.yaml` | max_retries / 退避参数 |
| 预算/饱和 | `config/research_budgets.yaml`、`collection_saturation_policy.yaml` | 查询预算与三轮饱和门槛 |
| 监控项 | `config/watchlist.yaml` | 监控主体与字段 |

## 配置生效范围速查

| 配置 | 读入点（代码） |
|---|---|
| `EER_AUTOMATION_DATABASE_URL` | `automation/api/app.py:create_app` |
| `EER_AUTOMATION_WORKDIR` | 同上 |
| `EER_AUTOMATION_EXECUTOR` | `automation/api/app.py:_default_executor` |
| `EER_KIMI_WEB_SESSION` | `automation/orchestration.py:from_environment` |
| `EER_FEISHU_*` | `automation/feishu/lark.py` + `notifier.py` |
| `EER_DEEPSEEK_*` / `EER_OPENAI_*` | `settings.py` → `gateway/litellm_gateway.py` |
| `ENTERPRISE_ENERGY_SKILL_ROOT` | `vendor.py:repository_root`（覆盖 vendor 定位） |
| `config/*.yaml` | `ReviewPolicy.load` / `RetryPolicy.load` / `OrchestratingExecutor` / `load_watchlist` |
