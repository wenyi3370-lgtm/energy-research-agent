# 每日战略情报（V2G & 储能日报）

自动化模块：每天自动采集 V2G/储能/虚拟电厂等六大领域情报，按董事长日报格式
加工后发布到飞书群。

## 流程

```
n8n（每天 10:00）→ POST /api/v1/intelligence/daily
  → 12 个领域查询（anysearch + kimi-webbridge）
  → DeepSeek 逐页抽取（类别/事实/影响/来源/数字）
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
   或直接修改 `automation/n8n/daily-intelligence-workflow.json` 的 `triggerAtHour` 后重新导入。

## 使用

| 端点 | 说明 |
|---|---|
| `POST /api/v1/intelligence/daily` | 触发当日情报采集与发布（**每日一次**，同日重复调用返回已发布结果） |
| `GET /api/v1/intelligence/daily/latest` | 查看今日简报（不触发采集） |

- 简报保存在 `workdir/intelligence/<日期>.json`（防重依据）
- 需要 `EER_AUTOMATION_EXECUTOR=orchestrating` + LLM 网关（DeepSeek）
- 采集查询集可改：`automation/intelligence/collector.py` 的 `DAILY_QUERIES`

## 评分与筛选（用户规范实现）

- 权重：政策/监管 30% · 与本公司业务相关性 30% · 潜在商业价值 20% · 行业影响 10% · 新鲜度 10%
- 90-100 重大情报（即时快讯）；80-89 必入日报；70-79 当日不足时补位；<70 过滤
- 同类信息合并为趋势（同实体+类别只保留最高分）
- 真实性：只抽取页面明示事实；来源/URL 保留；缺失字段用页面信息补全（不编造数字）
