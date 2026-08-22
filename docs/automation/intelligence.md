# 每日战略情报（V2G & 储能日报）

自动化模块：每天自动采集 V2G/储能/虚拟电厂等六大领域情报，按董事长日报格式
加工后发布到飞书群。

## 流程

```
n8n（每天 10:00）→ POST /api/v1/intelligence/daily
  → 获取 Asia/Shanghai 当前准确时间并冻结 REPORT_CUTOFF_TIME
  → Primary Search：12 个领域查询过去 24 小时
  → Recovery Search：同领域恢复查询过去 72 小时，补偿延迟索引/延迟发现
  → Update Search：对近 7 天历史重要事件检查实质更新
  → DeepSeek 逐页抽取来源、发布/更新/事件时间、实体、主题及新增事实
  → 计算 crawl_at、first_seen_at、content_hash，载入历史日报与发现台账
  → Freshness Gate 判定 NEW / UPDATED / OLD，OLD 禁止入报
  → Strategic Intelligence Score 评分
    （政策30% + 业务相关性30% + 商业价值20% + 行业影响10% + 新鲜度10%）
  → 去重合并趋势 → Top 3-5 条（宁缺毋滥，≥70 分）
  → 生成今日判断（LLM 30-50 字）
  → 飞书群发布日报（350-600 字，每条附「查看原文」URL）
  → ≥90 分条目：额外发布「重大情报即时快讯」
```

## 触发方式（三种）

1. **自动定时（推荐）**：n8n 工作流「每日情报（V2G & 储能日报）」每天 **10:00** 自动触发。
   Docker 启动后 n8n 即运行，无需任何操作。
2. **手动触发**：`POST /api/v1/intelligence/daily`（操作面板 /docs 或任何调用方）——
   立即采集并发布当日日报；同日重复调用不会重复采集。
3. **定时器调整**：改 n8n 工作流 Schedule 节点（n8n 界面 :5678 → 每日情报 → 触发节点），
   或修改 `automation/n8n/daily-intelligence-workflow.json` 中
   `rule.interval[0].triggerAtHour` / `triggerAtMinute` 后重新导入；这两个字段不得放在 `rule` 根层。

## 使用

| 端点 | 说明 |
|---|---|
| `POST /api/v1/intelligence/daily` | 触发当日情报采集与发布（**每日一次**，同日重复调用返回已发布结果） |
| `GET /api/v1/intelligence/daily/latest` | 查看今日简报（不触发采集） |

- 简报保存在 `workdir/intelligence/<日期>.json`（防重依据）
- 全部候选审计保存在 `workdir/intelligence/freshness-audit/<日期>.json`
- 跨日报首次发现与内容版本保存在 `workdir/intelligence/freshness-ledger.json`
- 需要 `EER_AUTOMATION_EXECUTOR=orchestrating` + LLM 网关（DeepSeek）
- 采集查询集可改：`automation/intelligence/collector.py` 的 `DAILY_QUERIES`

## Freshness Gate 与筛选

- 每个候选必须保留 `title/source/source_url/published_at/updated_at/event_at/first_seen_at/crawl_at/company/entity/topic/content_hash`
- **NEW**：首次发现、原始发布时间位于 72 小时内、历史日报未发送、不是转载或重复报道
- **UPDATED**：历史事件在 7 天更新检查内出现新政策文件、规模、价格、参数、合作方、订单金额、进度、官方解释或监管要求等实质事实
- **OLD**：历史已推送、转载、标题改写、旧文重发/重编辑、无新数据；一律禁止入报
- 发布时间无法确认时降为低可信，且不能满足 NEW；事件时间无法确认时保留为空并显示“不作推测”
- 发布时间与事件时间分离；旧事件今日发布时使用“今日披露/最新公开信息显示”，不得写成“今日发生”
- 同事件来源优先级：官方最新来源 > 企业官方公告 > 政府/招投标平台 > 权威媒体 > 行业媒体 > 转载媒体
- 最终 `DailyBrief` 再验证：NEW 必须位于 72 小时恢复窗；UPDATED 必须有 7 天内精确更新时间与实质新增事实；OLD 不能构建日报
- 卡片顶部显示“情报截止：HH:MM｜24小时主搜｜72小时恢复｜7天更新检查”
- 合格重要信息不足时宁缺毋滥；没有合格信息时明确输出未发现符合 NEW/UPDATED 标准的重大新增信息
- 权重：政策/监管 30% · 与本公司业务相关性 30% · 潜在商业价值 20% · 行业影响 10% · 新鲜度 10%
- 90-100 重大情报（即时快讯）；80-89 必入日报；70-79 当日不足时补位；<70 过滤
- 同一事件跨来源合并，按 UPDATED、来源权威性、最新版本、评分的顺序选择
- 真实性：只抽取页面明示事实；原始来源/URL/时间证据保留；缺失发布时间不补全、不推断
