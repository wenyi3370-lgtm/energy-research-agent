# 🚀 小白上手指南（零基础，10 分钟跑通第一个研究）

不需要懂代码。所有操作都在浏览器和几个按钮里完成。

---

## 第 1 步：确认系统在跑（已完成）

你机器上现在有 3 个服务（Docker 里）：

| 服务 | 干什么 | 网址 |
|---|---|---|
| **研究服务** | 收任务、做研究、出报告 | http://localhost:8000 |
| **数据库** | 存任务和结果 | （不用管） |
| **n8n 自动化** | 每日情报定时推送 + 调查故障看门狗 | http://localhost:5678 |

> 想随时查看/重启：打开终端，进入项目目录后运行
> `docker compose ps`（看状态）、`docker compose restart`（重启）。

## 第 2 步：提交你的第一个研究任务（2 分钟）

1. 浏览器打开 **http://localhost:8000/docs**（这就是"操作面板"，自动生成，免费不用装）。
2. 找到 **POST /api/v1/research**，点右边的 **Try it out**。
3. 在请求框里把内容改成下面这样（**中文直接用**）：

```json
{
  "task_id": "MY-FIRST-001",
  "requested_by": "你的名字",
  "company": "宁德时代",
  "research_type": "company_profile",
  "topics": ["主营业务", "生产基地", "产品线"]
}
```

4. 点 **Execute**。返回里会给你一个 `run_id`（像 `RUN-xxx`），**记下它**。

> 💡 提示：`company` 是研究谁；`country`/`product` 也可以（研究市场用）。
> `task_id` 是任务编号，自己起个不重复的名字即可。

## 第 3 步：看研究结果（2 分钟）

1. 回到 /docs，找到 **GET /api/v1/research/{run_id}**，点 Try it out。
2. 把刚才的 `run_id` 填进去，Execute。
3. 看到 `"status": "PUBLISHED"` 就是**完成了**（一般 10 秒内）。
   - 如果 `"status": "BLOCKED"` —— 属于无可用证据或运行故障，不是待你裁决。
   - 如果 `"status": "FAILED"` —— 看 `error.message`，按提示处理（多半是配置问题）。

4. 看产出文件：**GET /api/v1/research/{run_id}/artifacts** → 你会看到
   `excel`（数据表格）、`word`（报告文档）、`enterprise_html`（网页版报告）三个文件。
   文件存在项目的 `automation_work/<run_id>/outputs/` 目录里。

## 第 4 步：自动裁决（无需操作）

公司简称有多个候选或不同来源数值冲突时，系统自动选择最可信项并继续；选择理由、
入选 claim 与备选 claim 都会保留在证据库。业务人员不需要批准、拒绝或恢复任务。

## 第 5 步：反馈和看回报（1 分钟）

做完研究后反馈一下，系统会帮你算"省了多少人工"：

- **POST /api/v1/research/{run_id}/feedback**，填上你的人工用时：
```json
{
  "submitted_by": "你的名字",
  "adoption_status": "ADOPTED",
  "manual_baseline_minutes": 480,
  "human_review_minutes": 30
}
```
- **GET /api/v1/roi/summary** 看汇总：节省了多少分钟、ROI 倍数、采纳数。

## 第 6 步：从本地网页启动企业研究（1 分钟）

打开 **http://localhost:8000**，填写研究对象并点击「准备任务」，核对后点击
「开始调查」。企业研究不会由定时器自动启动。

## 第 7 步：n8n 每日情报（可选）

1. 打开 **http://localhost:5678**（第一次会让你设管理员账号密码，自己设一个）。
2. 保持 **每日情报（V2G & 储能日报）** 和 **研究故障看门狗（只终止悬挂任务）** 为 Active：前者每天 10:00 推送，后者每小时只终止超过 120 分钟无进展的任务并发飞书通知。
3. `Energy Research Agent Automation` 与 `monitor-schedule-trigger-v1` 保持未发布，
   企业研究统一从本地网页启动。
4. 日报可在本地网页通过「停止推送 / 恢复推送」控制；暂停后定时调用会被 API 拦截。
5. 故障看门狗不会创建或自动重试研究任务，不受日报暂停开关影响。

## 第 8 步（进阶）：真实联网研究

当前默认是"演示模式"（合成数据，为了让你先跑通流程）。要研究**真实企业**，
需要两样东西：

1. **一个 LLM 密钥**（任选）：DeepSeek 官网注册拿 `EER_DEEPSEEK_API_KEY`，
   或在 `docker-compose.yml` 里打开对应配置行；
2. **浏览器调研工具**：运行 `kimi-webbridge` 程序并装上配套浏览器扩展
   （你机器上已有程序本体：`~/.kimi-webbridge/bin/`）。

然后改 `docker-compose.yml` 里的 `EER_AUTOMATION_EXECUTOR=orchestrating`，
`docker compose restart research-api`，就是真实研究了。

---

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 任务 FAILED，错误是 Permission denied | 容器目录权限问题（已修复过一次）；`docker compose restart research-api` 即可 |
| 状态一直是 QUEUED | 稍等几秒再查；或看 `docker compose logs research-api` |
| n8n 打不开 | `docker compose up -d` 重新拉起 |
| 想清空所有测试数据 | `docker compose down -v` 全部重置（会删掉 n8n 账号和数据） |

祝研究顺利！🎉
