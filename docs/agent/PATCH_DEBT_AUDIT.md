# Patch Debt Audit

> 对主仓库 `src/enterprise_energy_research/` 中与 special requirement / competition / policy /
> channel / customer / custom goal / continuation / recovery 相关的硬编码分支审计。
> 分类规则：`KEEP`（确定性业务规则，保留在代码）、`MIGRATE_TO_AGENT`（自然语言推理，迁移给 Agent 层）、
> `DELETE_AFTER_AGENT`（Agent 层落地后删除）。**迁移顺序：先迁移 → 再回归 → 再删除**，
> 不删除没有测试覆盖的逻辑。

## 1. 审计清单

| # | 位置 | 内容 | 分类 | 处置计划 |
|---|---|---|---|---|
| 1 | `automation/orchestration.py:693-749` `_publication_repair_requirements` | 8 个 `if any(token in text ...)` 分支（length/depth、image、product、map/factory、chart、source、channel/渠道、policy/政策、compet/竞品），每条硬编码中文补采需求文本，末尾强制追加 `RECOVERY_STRATEGIES[n%10]` | **MIGRATE_TO_AGENT** | 该函数是"发布失败→定向补采"的语义理解逻辑。Agent 化后由 `agent/recovery.py` 的 LLM RecoveryPlan（结构化输出）替换；`RECOVERY_STRATEGIES` 轮换作为 RecoveryPlan 的候选集保留为工具输入。迁移后删除 8 条 if 链 |
| 2 | `automation/api/app.py:181-215` `_keyword_parse` | LLM 不可用时的关键词兜底（竞品/政策/市场进入/监测/产品/公司）→ ResearchType | **KEEP**（降级路径） | 保留为 LLM 解析失败时的 fail-safe 兜底，但标注 `degraded` 并降级处理（不允许产出"已完整研究"声明）。Agent 路径主用 `agent/mission_parser.py` |
| 3 | `research/planner.py:262-299` `REQUIREMENT_TOPIC_KEYWORDS` + `requirement_intents` | 37 组中文关键词→goal family 映射 + custom_requirement 兜底 | **MIGRATE_TO_AGENT** | 关键词表保留为 Router 的先验候选（candidate generation），最终 intent 判定由 Agent Router 的 LLM 语义分类完成；`custom_requirement` 通道升级为 Dynamic Custom Goal（agent/goal_planner.py） |
| 4 | `research/requirement_routing.py:70-90` `route_for_topic` | 4 个 topic 集合 if 分支 + image_evidence/custom_requirement 特判 | **KEEP** | 确定性执行路由（goal_domain/subject_role/evidence_lane 三维），属于代码负责的确定性部分；Agent Router 只决定"哪个 Skill 处理哪些 Goal"，执行细节仍走此路由 |
| 5 | `research/decision_synthesis.py:128-137` `semantic_domain` | ENERGY/MANUFACTURING/FINANCIAL/PRODUCT 字段集合 if 链 | **KEEP** | 字段语义域判定是确定性数据治理规则，非自然语言推理 |
| 6 | `research/fulltext_hydration.py:62` | `evidence_lane == "policy_context"` 特判（豁免公司名锚定） | **KEEP** | 搜索主体约束的显式豁免规则（政策通道），与 §41 主体约束一致 |
| 7 | `research/recall/query_expander.py:78-84` `lane_by_topic` | 主题→SourceLane 硬映射 | **KEEP** | 来源车道分配为确定性 Source Policy |
| 8 | `research/recall/entity_miner.py:102-108` `_topics` | entry_type→topic 映射 | **KEEP** | 同上，确定性挖掘规则 |
| 9 | `research/recall/search_frontier.py:79-86` `_lane_and_suffix` | policy/tender/project/subsidiary/product_model→(lane,后缀) | **KEEP** | 同上 |
| 10 | `research/recall/models.py` + `recall_engine.py:90-99` | SearchPass 8 种→轮次映射 | **KEEP** | 召回预算分配确定性规则 |
| 11 | `artifacts/narrative.py:373-382` | 章节标题硬映射（policy_regulation→政策与监管…） | **KEEP** | 发布术语规范，非推理 |
| 12 | `artifacts/visual_router.py:95,133` | 视觉类型路由表 | **KEEP** | 确定性视觉策略 |
| 13 | `research/entity_scope.py:191-242` | 反向集团关系/身份 claim 匹配 elif | **KEEP** | 实体边界规则（§43 竞争隔离依赖它） |
| 14 | `research/image_discovery.py:281` `_classify` | 图片语义分类分支 | **KEEP** | 确定性分类器（可由视觉模型增强，但不迁移） |
| 15 | `research/opportunity_assessment.py:192-234` | solution 类型→优先级/可行性/场景 if/else | **KEEP** | 机会评估引擎的确定性打分，输入是结构化 Solution |
| 16 | `research/recall/budget.py:115-117` | P0 seed 最小槽位特判 | **KEEP** | 预算政策 |
| 17 | `research/production_runner.py:530-560` | deep_retry 就绪主题四条集合差链 | **MIGRATE_TO_AGENT** | "哪些字段缺失→补什么"由 Agent 的 Goal Evaluation + RecoveryPlan 表达；当前实现作为 ENTERPRISE 工具内部的确定性 fallback 保留一期（Phase D 落地后评估删除） |
| 18 | `graph/build.py:44-51` | LangGraph stub 3 个 route_* 状态字符串分支 | **KEEP** | stub 本身不参与生产；Agent Control Layer 落地时基于同一状态语义重写（§29 目标状态机），届时自然替换 |

## 2. 未命中的关键词

`special requirement` / `custom goal` / `mining` / `founder_relation` / `continuation` 未命中硬编码 if/else：
- continuation 语义只存在于注释与 docstring（orchestration.py:524/697、deep_retry.py:106/497/543/774 的"续轮"）；
- 因此 **Continuation 模式（§12）与 Dynamic Custom Goal（§10）此前没有一等公民实现**，是本次 Agent 化的新增能力而非迁移负担。

## 3. 执行纪律

1. 迁移后的 Agent 决策一律经 `ModelGateway.structured`（Pydantic/JSON Schema），禁止正则解析自然语言。
2. 被 MIGRATE_TO_AGENT 的分支删除前，先由 `tests/agent/` 的 TEST-AGENT-* 覆盖新行为并全量回归。
3. `_keyword_parse` 保留为降级路径期间，其输出必须携带 `parse_mode: keyword_fallback` 标记，
   供 Agent Trace 与质量评估统计（Goal Routing Accuracy 口径见 §59）。
