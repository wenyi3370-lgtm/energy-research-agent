# Energy Research Agent

面向新能源、储能、动力电池、V2G、企业与海外市场研究的证据驱动 Agent。

用户只需要描述研究对象和决策问题。一个 Orchestrator 会解析自然语言、建立研究任务、拆解开放式 Goals、选择受控研究能力、检查证据缺口、执行有审计记录的恢复轮次，并从同一份冻结证据生成 Word、Excel、HTML 和 PPT 交付物。

> 核心边界：Agent 负责理解、规划、判断、恢复和综合；代码负责搜索执行、证据、预算、ID、审计、冻结、发布和质量门禁。发布器不能联网补事实，也不能修改已冻结证据。

## Agent 能做什么

- **自然语言建任务**：保留用户原始需求，生成 `ResearchMission` 与开放式 `ResearchGoal`，不会把新问题压缩成模糊的“其他”。
- **自动规划与路由**：根据目标在企业深度研究、海外能源市场研究或混合模式之间路由，并保存路由理由。
- **统一人工审批**：Agent 先展示任务、Goals 与路线，只有用户批准后才开始执行；Agent 不能自我批准。
- **证据优先研究**：解析企业主体、来源、产品、工厂、财务、市场与图片证据，保留原始来源、时间、范围和主体归属。
- **冲突与缺口恢复**：证据不足时使用不同策略继续研究；只有实际执行的轮次才计数，耗尽后输出可审计限制，而不是用通用文案填空。
- **严格主体隔离**：客户、供应商、竞争对手和关联企业可以作为背景实体存在，但不能冒充目标企业事实。
- **决策综合**：把 Evidence 转换为研究分析、战略解释、合作假设、管理结论、行动建议与 Go / No-Go 条件。
- **继续深度研究**：在已有任务和冻结证据上追加新的自然语言要求，针对性补证、重新校验、重新冻结并发布。
- **统一交付**：Word、Excel、单文件离线 HTML 与 PPT 共享同一份证据、研究叙事和图表语义。
- **失败关闭**：主体不明确、核心证据缺失、图片未核验、关键链接损坏或跨产物不一致时，保留诊断并阻止正式发布。

## 工作流程

```text
自然语言需求
  → Mission 解析
  → Goal 规划
  → 能力路由
  → 用户审批
  → 研究执行
  → EvidenceStore 归一化
  → Goal 评估
  → 缺口恢复（按 Goal、有上限、可审计）
  → 决策综合
  → 统一校验与证据冻结
  → Word / Excel / HTML / PPT 发布
  → 跨产物校验与打包
```

研究能力通过适配器调用，Agent 不直接绕过边界：

- AnySearch：搜索与内容发现；
- Kimi WebBridge：动态网页、导航、分页与详情页检查；
- Excel Master、PPT Master、frontend-design、diagram-design：确定性交付与可视化；
- Overseas Energy Market Research：海外市场研究能力包。

这些能力随仓库固定在 `vendor/skills/`，并由 `vendor/manifest.json` 校验。Kimi 浏览器守护进程、浏览器、Office 渲染器和密钥属于机器运行环境，不会打包进仓库。

## 最快使用方式：作为 Codex Skill 安装

将仓库克隆到用户级 Skills 目录：

### Windows PowerShell

```powershell
git clone https://github.com/wenyi3370-lgtm/energy-research-agent.git `
  "$env:USERPROFILE\.agents\skills\energy-research-agent"
```

### macOS / Linux

```bash
git clone https://github.com/wenyi3370-lgtm/energy-research-agent.git \
  ~/.agents/skills/energy-research-agent
```

若仓库是私有仓库，请先在目标机器用 Git Credential Manager 或 `gh auth login` 完成 GitHub 登录。已有安装可在 Skill 目录执行 `git pull --ff-only` 更新；卸载时删除整个 `energy-research-agent` 目录即可。

也可以使用发布 ZIP：将 `energy-research-agent.zip` 解压到用户级 `.agents/skills/`，确保最终文件为 `.agents/skills/energy-research-agent/SKILL.md`，而不是多嵌套一层目录。ZIP 安装的更新方式是先保留自己的 `.env`，再用新版目录整体替换旧版。

重新打开 Codex，在 Skills 列表中确认出现 `energy-research-agent`。若未出现，先检查上述 `SKILL.md` 路径；若要运行完整网页/API Agent，还需按下文安装 Python 或 Docker 运行时。进入 Skill 目录并安装 Python 运行时后，可用以下命令验证：

```bash
uv run energy-research-agent --version
uv run energy-research-agent settings
```

然后可以直接提出任务，例如：

```text
调研宁德时代，重点判断欧洲储能布局、核心产品、产能变化、主要风险，
并给四川动力电池产业创新中心形成可执行的合作建议和正式报告。
```

```text
研究西班牙户用储能市场，覆盖市场规模、政策、渠道、竞品、价格、认证和进入路径，
要求给出证据来源、反证和 Go / No-Go 条件。
```

Skill 的权威执行契约见 [SKILL.md](SKILL.md)。

## 使用网页 Agent

网页模式提供任务解析、Goal 预览、审批、启动、停止、继续研究、深度研究、Trace 与产物下载。

### 方式一：Docker（推荐）

要求：Git、Docker Desktop 或 Docker Engine + Compose。

```bash
git clone https://github.com/wenyi3370-lgtm/energy-research-agent.git
cd energy-research-agent
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，必须把 `POSTGRES_PASSWORD` 换成随机强密码，并配置至少一个与模型名称匹配的 LLM Provider。真实联网研究建议同时配置 AnySearch；需要动态网页时再启动 Kimi WebBridge：

```dotenv
ERA_DEEPSEEK_API_KEY=your-key
ERA_ANYSEARCH_API_KEY=your-key
```

默认 `ERA_PRIMARY_MODEL=deepseek-chat`，因此上例配置 DeepSeek。若只使用 OpenAI，应同时设置 `ERA_OPENAI_API_KEY`，并把 `ERA_PRIMARY_MODEL` 改为当前 OpenAI 账户可用的模型名称。不要保留没有对应密钥的主模型配置。

启动：

```bash
docker compose up -d --build
```

打开：

- Agent：<http://localhost:8000/>
- Agent 调试页：<http://localhost:8000/agent/debug>
- API 文档：<http://localhost:8000/docs>
- n8n（仅启用 `automation` profile 后）：<http://localhost:5678>

常用维护命令：

```bash
docker compose logs -f research-api
docker compose restart research-api
docker compose down
```

n8n 不参与交互式 Agent 的基本运行。只有需要定时情报与故障看门狗时才启动：

```bash
docker compose --profile automation up -d --build
```

Docker 使用由 Compose 自动创建的项目级命名卷。导出文件默认写入仓库的 `outputs/`；可在 `.env` 中用 `ERA_EXPORT_PATH` 改为其他绝对路径。

### 方式二：本地 Python

要求：Python 3.10+；推荐安装 [uv](https://docs.astral.sh/uv/)。完整 Word/PPT 渲染检查还需要 LibreOffice 和 Chrome/Chromium。

```bash
git clone https://github.com/wenyi3370-lgtm/energy-research-agent.git
cd energy-research-agent
uv sync --all-extras
uv run playwright install chromium
cp .env.example .env
uv run energy-research-agent serve --host 0.0.0.0 --port 8000
```

Linux 若缺少 Chromium 系统库，可按 Playwright 提示改用 `uv run playwright install --with-deps chromium`（通常需要系统包安装权限）。不需要 Playwright 图像栅格化时，可只安装运行所需的 extras，并使用本机 Chrome/Edge 作为回退。

Windows 也可以在完成 `uv sync --all-extras` 后双击 `start-agent.bat`；macOS/Linux 可以运行：

```bash
chmod +x start-agent.sh
./start-agent.sh
```

代理不是默认依赖。只有当前网络确实需要代理时，才在 `.env` 中设置：

```dotenv
ERA_OUTBOUND_PROXY=http://127.0.0.1:7897
```

## 网页操作步骤

1. 打开 <http://localhost:8000/>，选择企业研究、海外市场研究或混合研究。
2. 输入完整自然语言需求，点击解析。
3. 检查 Agent 生成的研究对象、模式、Goals 与路由结果；必要时编辑 Goals。
4. 批准统一研究任务。
5. 启动研究并查看状态、Evidence 缺口、恢复轮次、Trace 和产物。
6. 需要补充时使用“继续研究”或“继续深度研究”，输入新的完整要求。
7. 只有校验通过的产物才可下载或推送。

## Agent API

Agent API 前缀为 `/api/agent`：

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/agent/parse` | 解析自然语言并建立 Mission/Goals |
| `POST` | `/api/agent/mission/{id}/approve` | 批准或拒绝任务 |
| `POST` | `/api/agent/mission/{id}/start` | 启动已批准任务 |
| `POST` | `/api/agent/mission/{id}/continue` | 追加要求并继续 |
| `POST` | `/api/agent/mission/{id}/deep-research` | 在累计证据上执行深度补证 |
| `POST` | `/api/agent/mission/{id}/stop` | 停止任务 |
| `POST` | `/api/agent/mission/{id}/goals` | 审批前修改 Goals |
| `GET` | `/api/agent/mission/{id}` | 获取任务、Goals、Trace 与产物 |
| `GET` | `/api/agent/missions` | 查询任务列表 |
| `GET` | `/api/agent/health` | Agent 运行状态 |

完整调用示例（`approve` 会在批准后自动启动；`start` 主要用于重新触发已批准但未运行的任务）：

```bash
BASE=http://localhost:8000

# 1. 解析请求；从返回 JSON 保存 mission_id，并先把 Goals 展示给人确认
curl -X POST "$BASE/api/agent/parse" \
  -H "Content-Type: application/json" \
  -d '{"raw_request":"调研宁德时代欧洲储能业务与合作机会","track":"enterprise"}'

# 2. 可选：在审批前提交最终 Goals；保留已有 goal_id，新增项留空
curl -X POST "$BASE/api/agent/mission/MISSION_ID/goals" \
  -H "Content-Type: application/json" \
  -d '{"goals":[{"goal_id":"GOAL_ID","goal_name":"欧洲储能布局","goal_description":"核验产品、项目和合作伙伴"},{"goal_id":"","goal_name":"反证检查","goal_description":"寻找可推翻核心判断的证据"}]}'

# 3. 只有人明确同意后才批准；批准会自动启动后台研究
curl -X POST "$BASE/api/agent/mission/MISSION_ID/approve" \
  -H "Content-Type: application/json" \
  -d '{"approve":true,"message":"按当前 Goals 执行"}'

# 拒绝则使用：-d '{"approve":false,"message":"范围需要重做"}'

# 4. 轮询状态、Trace 和产物路径，直到终态
curl "$BASE/api/agent/mission/MISSION_ID"

# 5. 为任务追加新 Goals；返回新预览后再次让人审批
curl -X POST "$BASE/api/agent/mission/MISSION_ID/continue" \
  -H "Content-Type: application/json" \
  -d '{"raw_request":"补充德国渠道伙伴和 2025 年认证变化"}'

# 6. 仅对已有成果的任务做深度补证；空字符串表示只修复当前缺口
curl -X POST "$BASE/api/agent/mission/MISSION_ID/deep-research" \
  -H "Content-Type: application/json" \
  -d '{"raw_request":"强化项目级证据并核验反例"}'
```

Windows PowerShell 可使用等价的 `Invoke-RestMethod`；交互式字段定义始终以 <http://localhost:8000/docs> 为准。HTTP `409` 通常表示审批或任务状态不满足操作前提；先读取任务详情和 `/api/agent/health`，修正状态或依赖后再执行，不要跳过审批门禁。

## 配置

所有 Agent 环境变量统一使用 `ERA_` 前缀。

| 变量 | 用途 | 必需 |
|---|---|---|
| `ERA_DEEPSEEK_API_KEY` | DeepSeek 研究与结构化抽取 | 与 OpenAI 二选一 |
| `ERA_OPENAI_API_KEY` | OpenAI 备用或主模型 | 与 DeepSeek 二选一 |
| `ERA_PRIMARY_MODEL` / `ERA_FALLBACK_MODEL` | 模型名称 | 否 |
| `ERA_ANYSEARCH_API_KEY` | AnySearch 额度；能力包也支持匿名路径 | 建议 |
| `ERA_KIMI_WEB_DAEMON_URL` | Kimi WebBridge 守护进程地址 | 动态网页研究时 |
| `ERA_DOCKER_KIMI_WEB_DAEMON_URL` | Docker 容器可访问的 Kimi 地址 | 否，默认宿主机 `10086` |
| `ERA_KIMI_WEB_SESSION` | Kimi 浏览器会话名 | 否 |
| `ERA_VISION_API_KEY` / `ERA_VISION_API_BASE` | 独立图片像素核验端点 | 图片正式发布时建议 |
| `ERA_OUTBOUND_PROXY` | 仅当前网络需要时使用的进程级代理 | 否 |
| `ERA_FEISHU_APP_ID` / `ERA_FEISHU_APP_SECRET` | 飞书交付 | 否 |
| `ERA_FEISHU_DEFAULT_RECEIVER` | 默认飞书接收人或群 | 否 |
| `ERA_EXPORT_PATH` | Docker 导出目录 | 否，默认 `./outputs` |
| `ERA_AUTOMATION_EXECUTOR` | `orchestrating` 或 `synthetic` | 否 |

完整模板见 [.env.example](.env.example)。`.env`、数据库、运行日志和研究产物均被 Git 忽略。

## 交付与证据目录

正式运行使用：

```text
outputs/{canonical_company}/{run_id}/
```

典型内容包括：

- 结构化 Evidence、来源台账、冲突与 Data Gaps；
- 冻结快照及内容哈希；
- Word 决策报告；
- Excel 研究数据表；
- 离线单文件 HTML；
- PPT（通过确认与渲染门禁后）；
- 图片、图表、视觉清单、QA 报告和可复现打包信息。

成功任务最终状态为 `PASS` 或 `PASS_WITH_WARNINGS`。被阻止的任务会保留证据、诊断和缺失原因，不生成误导性的正式交付物。

## 跨机器可移植性

- 源码包名、CLI、Skill 名和仓库名统一为 `energy-research-agent` / `energy_research_agent`。
- 所有机器相关路径均通过环境变量或运行时发现，不写死用户名、桌面、代理端口或 Docker 安装目录。
- Docker 卷由 Compose 自动创建；Linux 使用 `host-gateway` 访问宿主机 Kimi daemon。
- 第三方能力固定在 `vendor/skills/`；发布前必须校验 manifest。
- 密钥和登录态不进入仓库或 Skill 包。
- Kimi daemon、浏览器扩展、LibreOffice 与浏览器属于外部运行时，需要在目标机器上安装或使用 Docker 镜像提供的组件。
- Docker 镜像已包含 Chromium 与 LibreOffice；本地 Python 安装需单独执行 Playwright 浏览器安装，完整 Office 渲染仍依赖本机 LibreOffice。

构建可移植 Skill 包：

```bash
uv run python scripts/vendor_skills.py verify
uv run python scripts/package_skill.py dist/energy-research-agent.zip
```

## 开发与验证

```bash
uv sync --all-extras
uv run pytest -q
uv run python scripts/vendor_skills.py verify
uv run python scripts/package_skill.py dist/energy-research-agent.zip
```

快速验证：

```bash
uv run energy-research-agent settings
uv run energy-research-agent synthetic-run "示例企业"
```

关键设计文档：

- [ARCHITECTURE.md](ARCHITECTURE.md)：Agent、Evidence、分析与发布架构；
- [WORKFLOW.md](WORKFLOW.md)：执行状态机与阶段门禁；
- [DATA_SCHEMA.md](DATA_SCHEMA.md)：Mission、Goal、Evidence 与产物数据结构；
- [SOURCE_POLICY.md](SOURCE_POLICY.md)：来源与证据政策；
- [ARTIFACT_SPEC.md](ARTIFACT_SPEC.md)：输出目录和交付物契约；
- [VALIDATION_SPEC.md](VALIDATION_SPEC.md)：发布与一致性门禁；
- [config/agent.yaml](config/agent.yaml)：Agent 循环、恢复、审批和发布策略。

## 安全与限制

- 不绕过付费数据库、认证或站点访问控制。
- 不把搜索摘要当作正式 Claim；必须获取并校验原文。
- 不自动生成审计、估值、工程设计或可融资可研结论。
- 没有真实 Provider、搜索适配器或浏览器能力时，Agent 会明确阻止或降级，不会用模拟结果冒充真实研究。
- 研究与交付可能消耗模型、搜索和浏览器额度；正式任务应在审批页确认范围后启动。

## License 与第三方声明

项目自身及各嵌入能力的许可与声明分别保存在根目录、`third_party/` 和对应的 `vendor/skills/*` 目录中。重新分发前请保留这些文件并运行 vendor manifest 校验。
