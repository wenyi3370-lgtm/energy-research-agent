# Strategy Adoption Audit — 双仓策略逐一核查

日期：2026-08-25。核查对象：
- `enterprise-energy-research`（旧 skill 副本 = 融合基座同一提交 `52d3d14`，本审计对比的是**基座契约 vs 融合后 Agent 层是否绕过/未采用**）
- `overseas-energy-market-research-skill`（vendored v1.2.9，`ccc2a18`）

状态图例：✅ 已采用并生效 ｜ 🔧 本轮修复后采用 ｜ ⚠️ 保留在 vendored/基座中，Agent 路径不重复实现 ｜ ⏳ V1 边界（已文档化）

## A. 企业 skill 策略（SKILL.md / Search Recall contract / 第五轮质量契约）

| # | 策略/契约 | 状态 | 采用位置 |
|---|---|---|---|
| A1 | Search Recall：Seed→Query Expansion→Source Lane→Entity/Event Mining→Dynamic Frontier→Convergence→Verification | ✅ | `research/recall/` 原样；企业路径经 planner（R1-R4）+ hydration |
| A2 | 每 Goal R1 官方源覆盖→R2 原文/全文深度→R3 独立三角验证 | ✅ | `research/planner.py`；恢复轮经 `targeted_plan`（R1/R2/R3 补采查询） |
| A3 | 10 轮 audited recovery rounds with **distinct source strategies** | 🔧 | 确定性恢复改用 `RECOVERY_STRATEGIES`（10 条轮换）+ `coverage_queries`，替换原硬编码 6 车道；测试锁定（TestRecoveryUsesRepoStrategies） |
| A4 | 每条 query 锚定 canonical company | ✅ | SearchExecutor 强制 + recovery 查询锚定（测试断言） |
| A5 | 实体边界（目标/子公司/客户/供应商/竞对隔离，禁止跨实体事实） | ✅ | normalizer + §43 agent 侧（subject_role/competitor 实体） |
| A6 | 身份/官网域不匹配即阻断 | ✅ | CoreValidator（基座原样） |
| A7 | PublicationBoilerplateFilter（AI 腔短语零容忍） | ✅ | 发布器内（基座原样） |
| A8 | 第五轮契约：正文深度（15000 字）/PDF 渲染/分页门 | ✅ | `consulting_narrative`/`delivery_quality`——本次实跑**真实拦截**（6098<15000） |
| A9 | 图片：验证 URL→下载→SHA/MIME/尺寸→内嵌本地字节 | ✅ | image pipeline（基座原样） |
| A10 | 补充要求=一等章节（非轻量附录），同样 R1-R3 栈 | ✅ | narrative supplemental_requirements（基座）+ agent CUSTOM Goal 独立章节 |
| A11 | continuation 解析与分隔符无关 | ✅ | agent `continue_mission`（LLM 解析，无分隔符依赖） |
| A12 | 全量计划永不因专项需求缩减 | ✅ | planner 双通道设计（基座）+ §11 goal_planner 核心 12 Goal 恒存 |

## B. 海外 skill 策略（v1.2.9 vendored）

| # | 策略/契约 | 状态 | 采用位置 |
|---|---|---|---|
| B1 | Stage Gate 0-8 | ✅ | vendored `validate_stage_gate.py` 原样；adapter 默认 runner 走 `--check` |
| B2 | 人工审批 `00_Research_Approval.csv`（Stage 0） | 🔧 | 统一审批双门：Mission 审批 → adapter `ensure_approved` 自动创建（TestAgent08b） |
| B3 | R1/R2/R3 任务行（02_Web_Collection_Tasks.csv round 列） | ✅ | adapter `_write_tasks`（round 1/2/3 + round_goal） |
| B4 | anti-under-collection / anti-fake-completion | ✅ | vendored `validate_collection_attempts.py` 原样（默认 runner 执行） |
| B5 | **collection_quantity_policy 轮次下限（round_floor）** | 🔧 | adapter 任务行现读取 policy `families.<family>.rounds` 的 min_unique_sources/min_records/min_source_types/min_primary_sources（TestMarketTaskFloors）；同时修复了历史 `category` 未定义 bug |
| B6 | Source Ledger 38 列 / Attempt Journal / Record Registry | ✅ | adapter 收割 ledger/journal；record registry 由 vendored 脚本生成 |
| B7 | source_independence（root_domain 去重/独立来源） | ✅ | vendored `source_independence.py` 原样（gate 层） |
| B8 | critical_claim 哈希 + 双 evidence_binding（v8） | ✅ | vendored `critical_claim_evidence.py` 原样 |
| B9 | 建模链 G1-G6 + G2.5/G4.5 人工门 | ✅ | vendored 原样（market-only 自管线路径） |
| B10 | Five Views（宏观/行业/客户/竞争/自己） | ✅ | vendored 原样 |
| B11 | Word ≥15000 字 / Excel 公式重算+LibreOffice / PPT 渲染几何 | ✅ | vendored 原样；与企业侧 15000 门一致 |
| B12 | 市场目标 query 纪律（地理+品类+对象） | ✅ | adapter 任务 `region + category + goal name` |
| B13 | AnySearch 密钥优先级 + 匿名兜底 | ✅ | CLI 契约原样；密钥本轮更换并验证配额恢复 |

## C. 未采用项与理由（⏳ V1 边界，均已文档化于 IMPLEMENTATION_REPORT §H）

| 项 | 理由 |
|---|---|
| 海外 modeling/Excel/PPT 产物挂统一 manifest 的深度互操作 | §37 单 Owner：作为 validated sub-artifacts 引用，已在 manifest `sub_artifact_refs` 落地；建模输出仍需真实 market-only run 校准 |
| Agent 路径运行海外 Stage Gate 全量 0-8 | 默认 runner 已 `--check`；HYBRID 下最终交付由统一 Artifact Plane 生成，海外门保留在 vendored 供 market-only 全量运行 |
| Recall engine 用于企业恢复轮 | 企业恢复走 planner coverage_queries（RECOVERY_STRATEGIES），与基座企业路径一致；recall engine 保留给 daily intelligence/验收脚本 |

## D. 本轮修复清单（2026-08-25）

1. 恢复策略：RECOVERY_STRATEGIES×10 轮换引擎替换硬编码车道（A3）
2. 海外审批双门统一（B2）
3. 政策轮次下限采用 + category bug 修复（B5）
4. AnySearch 密钥更换并验证（B13）
5. 断点续跑（evidence 复用，不重采集）脚本 `agent_resume_eval.py`
