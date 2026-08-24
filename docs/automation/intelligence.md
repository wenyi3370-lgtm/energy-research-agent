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
  → 业务范围去重 → 最多 5 条（无评分/可信度门槛，按发布时间由近及远排序）
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
- **NEW**：当前来源页面发布时间位于 72 小时内；转载、二次传播及历史已发现事件均可作为最新传播信息
- **UPDATED**：历史事件在 7 天更新检查内出现新政策文件、规模、价格、参数、合作方、订单金额、进度、官方解释或监管要求等实质事实
- **OLD**：当前页面明确发布时间早于 72 小时、时间晚于截止时刻，或缺少来源名称/URL；禁止入报
- 发布时间无法确认时可作为 LOW 可信候选保留，但不伪造发布时间并排在可核验时间之后；事件时间无法确认时保留为空并显示“不作推测”
- 发布时间与事件时间分离；旧事件今日发布时使用“今日披露/最新公开信息显示”，不得写成“今日发生”
- 同事件及最终列表先按可核验发布时间由近及远排序；时间相同时再按内部可信度、来源权威性和评分排序
- 最终 `DailyBrief` 再验证：有明确时间的 NEW 必须位于 72 小时恢复窗；无明确时间的 NEW 必须是 72 小时内抓取的 LOW 可信候选；UPDATED 必须有 7 天内精确更新时间与实质新增事实；OLD 不能构建日报
- 卡片顶部显示“情报截止：HH:MM｜24小时主搜｜72小时恢复｜7天更新检查”
- 最终选择不设评分或可信度门槛，但保留 V2G/储能/电力灵活性业务相关性硬过滤和最多 5 条上限
- 权重：政策/监管 30% · 与本公司业务相关性 30% · 潜在商业价值 20% · 行业影响 10% · 新鲜度 10%
- 评分仅用于重要性展示与相同时间/可信度下的次级排序；不再作为入选门槛
- LOW 可信度仅写入审计与持久化数据，不在飞书推送中展示“低可信”标签
- 真实性：只抽取页面明示事实；原始来源/URL/时间证据保留；缺失发布时间不补全、不推断
