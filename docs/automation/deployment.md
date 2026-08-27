# v0.9.0 部署

## Docker 全栈

```
docker compose up -d --build
```

- `research-api`（:8000）—— FastAPI，`create_app` factory 模式启动；
  环境变量 `ERA_AUTOMATION_DATABASE_URL` 指向 postgres（docker-compose 已注入）。
- `postgres`（:5432）—— 自动化控制面数据库（自动化表，evidence 仍在 workdir 内 SQLite）。
- `n8n`（:5678）—— 工作流编排，导入 `automation/n8n/energy-research-agent-workflow.json`。

首次启动后：`curl http://localhost:8000/health` → `{"status":"ok"}`。

## 生产清单

1. 修改 postgres 默认密码；禁止把 `research/research` 用于生产。
2. 配置 `ERA_FEISHU_*`（Phase 7 通知）与 LLM gateway 密钥（真实抽取）。
3. 若要真实研究编排：将 API 默认 executor 换成 `OrchestratingExecutor.from_environment()`
   （或注入适配器/gateway）；未配置时保持 fail-closed（BLOCKED）。
4. review_policy.yaml / retry_policy.yaml 按业务节奏调规则，改配置无需改代码。
5. n8n 的 webhook 生产需 HTTPS 反代 + 飞书签名校验。

## 本地开发

```
pip install -e ".[api,database]"
PYTHONPATH="src" uvicorn energy_research_agent.automation.api.app:create_app --factory --reload
```
