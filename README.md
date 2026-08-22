# Enterprise Energy Research v0.9.0 — 企业研究与决策智能平台

将新能源 / 电池 / 储能 / V2G / 海外市场研究，从"人工 + AI 客户端"升级为
**企业员工可自助使用的自动化研究平台**：一句话发起调研 → 真实联网研究 →
身份与证据冲突自动裁决 → 成果文件直达飞书群；每天自动推送
**V2G & 储能行业情报日报**。

> Evidence-first：研究产出证据 → 校验冻结 → 发布器只消费冻结快照。
> 发布器禁止联网、禁止补事实、禁止修改证据。

---

## 功能特性

- 🔍 **真实联网研究**：AnySearch 搜索 + Kimi WebBridge 浏览器深度调研 + DeepSeek 结构化抽取
- 🗣️ **自然语言发起**：一句话描述需求，AI 自动解析参数（引导页 http://localhost:8000）
- 🛡️ **冲突自动裁决**：按来源权威性、独立支持数、时效与精确度选择最可信说法，备选值完整留痕
- 📄 **同源交付**：Excel 数据总表 + 咨询级 Word + 融合管理驾驶舱与产品数据库的单文件 HTML（直发飞书群）
- 📊 **diagram-design 同源图表**：VisualSpec 业务语义 → Visual Router 反滥用路由 → diagram-design 设计系统确定性渲染；离线 HTML（内联 SVG）+ 可编辑 SVG + 同源 HTML 渲染的高清 PNG；HTML 与 Word 共用同一套图，无双重绘图逻辑
- 📊 **研究质量量化**：逐 Goal 饱和度、官方来源比例、三角验证率、目录/参数/图片覆盖率与关键缺口显式输出
- 📰 **每日情报日报**：每天 10:00 执行 24 小时主搜、72 小时恢复检索和近 7 天重要事件更新检查；经历史日报去重后仅推送 NEW/UPDATED，转载、重发与无实质更新内容直接剔除
- 🖱️ **网页手动触发**：企业研究只由本地引导页确认后启动；不启用定时研究
- 🧟 **僵尸任务自愈**：进程中断的悬挂任务自动发现、通知、一键重试
- 🐳 **全 Docker 化**：一键部署，开机自启，无人值守

---

## 依赖要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Docker Desktop | 4.x+ | 唯一必需软件（Windows/macOS/Linux 均可） |
| 可选的 LLM API Key | DeepSeek 或 OpenAI | 真实抽取必需（DeepSeek 注册即可，低成本） |
| 可选：飞书开放平台应用 | - | 群通知 / 表单触发（无则通知跳过，研究不受影响） |
| 可选：Kimi WebBridge | v1.11.x | 浏览器深度调研（宿主机运行 daemon + 浏览器扩展） |

Python / Node 均**无需**安装（全部在容器内）。

---

## 快速开始（5 分钟）

```bash
# 1. 克隆仓库
git clone https://github.com/wenyi3370-lgtm/enterprise-energy-research.git
cd enterprise-energy-research

# 2. 配置密钥（复制模板并填入）
cp .env.example .env
#   编辑 .env：填入 EER_DEEPSEEK_API_KEY（必填，真实抽取用）
#              EER_FEISHU_APP_ID / APP_SECRET / DEFAULT_RECEIVER（可选，飞书通知）

# 3. 一键启动（首次构建约 5-10 分钟）
docker compose up -d --build

# 4. 打开引导页
#   http://localhost:8000  —— 一句话发起调研 / 触发情报 / 查看成果
#   http://localhost:8000/docs —— 高级操作面板（状态/反馈/ROI）
```

启动后验证：`curl http://localhost:8000/health` → `{"status":"ok"}`

---

## 部署教程（详细）

### 1. 系统组件

| 服务 | 端口 | 职责 |
|---|---|---|
| research-api | 8000 | 研究服务（引导页 / API / 自动化编排 / 飞书通知） |
| n8n | 5678 | 定时调度（仅每日情报 10:00；企业研究由本地网页触发） |
| postgres | 5432 | 控制面数据库（任务/运行/自动裁决审计/指标） |

### 2. 环境变量（.env，全部可选按需填）

```ini
# —— LLM 抽取（真实研究必需，至少一个 provider）——
EER_DEEPSEEK_API_KEY=sk-xxx
# EER_OPENAI_API_KEY=sk-xxx

# —— 飞书通知（可选；不配则通知 fail-closed，研究照常）——
EER_FEISHU_APP_ID=cli_xxx
EER_FEISHU_APP_SECRET=xxx
EER_FEISHU_DEFAULT_RECEIVER=oc_xxx    # 群 chat_id / 邮箱 / open_id

# —— Kimi WebBridge 浏览器深度调研（可选，宿主机运行 daemon）——
# EER_KIMI_WEB_SESSION=default
# EER_KIMI_WEB_DAEMON_URL=http://127.0.0.1:10086   # 容器内自动用 host.docker.internal
```

> AnySearch 无需手动配置：首次匿名调用会自动注册账号，把生成的
> `api_key` 写入 `vendor/skills/anysearch/scripts/.env`（该文件已被 .gitignore 忽略）。

### 3. 飞书应用配置（可选）

1. https://open.feishu.cn 创建企业自建应用 → 启用**机器人**能力
2. 权限：`im:message`（发消息）、`im:chat:readonly`（查群）、如需上传文件加 `im:resource`
3. 发布版本；把机器人**添加进目标群**
4. 群 chat_id 获取：机器人入群后调用 `GET /open-apis/im/v1/chats`（见 docs/automation/feishu.md）

### 4. Kimi WebBridge（可选，深度调研）

1. 宿主机安装 `kimi-webbridge` 二进制并启动 daemon（默认 127.0.0.1:10086）
2. 浏览器安装配套扩展并连接（daemon 状态显示 extension_connected=true）
3. 容器内经 `host.docker.internal:10086` 自动访问宿主 daemon

### 5. 触发与定时任务说明

- **每日情报 10:00**（北京时间）：n8n 工作流 `daily-intelligence-v1` 已内置（TZ=Asia/Shanghai）
- **企业研究**：不定时自动运行，只能在本地网页 `http://localhost:8000` 准备并点击「开始调查」
- **失败即终止**：明确异常立即进入 `FAILED` 并通知飞书；`research-failure-watchdog-v1` 每小时只检查并终止超过 120 分钟无进展的悬挂任务，不创建任务、不自动重试
- 旧工作流 `monitor-schedule-trigger-v1` 已停用，Schedule 节点也被禁用，误发布不会创建研究任务
- 工作流导入：n8n 界面（:5678）→ Import from File → `automation/n8n/*.json`

### 6. 开机自启（可选）

- Docker Desktop 设置勾选"登录时启动"
- 将 `start-services.bat` 快捷方式放入启动文件夹（`shell:startup`）

---

## 使用指南

| 操作 | 入口 |
|---|---|
| 一句话发起调研 | 引导页 http://localhost:8000 → 输入描述 → 解析确认 → 开始调查 |
| 精确参数调研 | `POST /api/v1/research/prepare` + `/start` |
| 查看任务状态 / 自动裁决记录 / 反馈 / ROI | http://localhost:8000/docs |
| 每日情报（手动触发） | `POST /api/v1/intelligence/daily` |
| 飞书群 | 情报日报 / 完成通知 / 成果文件 / 失败提醒 |

详细文档见 `docs/automation/`（架构、API、自动裁决、情报、监控、Runbook、部署、配置清单）。

---

## 开发与测试

```bash
pip install -e ".[api,database,models]"
PYTHONPATH="src;tests" python -m unittest discover -s tests   # 210 个测试
PYTHONPATH="src" python scripts/run_automation_eval.py        # 自动化回归 eval
```

## 目录结构（要点）

```
automation/          自动化层（服务/API/情报/监控/飞书/n8n 工作流）
src/enterprise_energy_research/
  artifacts/         发布器（word/excel/html，配置驱动视觉规范）
  research/          研究内核（搜索/抽取/规范化/冲突自动裁决）
  evidence/          证据库（append-only / 冻结 / 哈希）
  automation/        控制面（状态机/自动裁决审计/重试/ROI/情报）
config/              YAML 配置（视觉规范/自动裁决策略/重试/watchlist）
docs/automation/     完整文档（12 份 + ADR）
tests/               210 个回归测试
```

## 安全说明

- 所有密钥只存在于本地 `.env`（已被 .gitignore 忽略），仓库不含任何真实凭证
- 证据冻结不可变（全量 SHA-256）；发布器禁止联网、禁止补事实
- 冲突、机器选择理由与备选值全程留痕，可审计可追溯
