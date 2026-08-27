# Energy Research Agent — 双仓融合实施报告

日期：2026-08-25

## A. 架构变化

**部署状态（2026-08-25 晚）**：Docker Compose 三服务已在融合后的新代码库重新部署并验证：
`postgres`（healthy）+ `research-api`（healthy，挂载宿主机 `/skill` 实时源码）+ `n8n`。
发现此前运行中的栈挂载的是旧 skill 副本（`.agents/skills/enterprise-energy-research`，
无 Agent 层），已 `down` 并从新仓库 `up -d --build`（pgdata/research-data/n8n-data
volume 复用，POSTGRES_PASSWORD 迁移保持数据一致）。
**代码库已迁移**至 `C:\Users\Wenyi Zhang\.agents\skills\energy-research-agent`
（按产品名命名，SKILL.md frontmatter name 同步更新；`COMPOSE_PROJECT_NAME` 保持
`enterprise-energy-research` 以复用原数据卷），Docker 挂载源已切换至新位置，
旧工作区目录已删除。
容器内验证：`/api/agent/health`（agent_enabled=true、gateway=true、双 Skill、策略生效）、
`/agent` 200、真实 DeepSeek structured 解析（HYBRID / parse_mode=llm / approval=PENDING /
12 企业核心 + 6 市场 + 2 跨域 Goal）、海外 vendored skill 路径可达。容器网络直连
DeepSeek 无需宿主机代理。

**旧架构**：确定性流水线 + 少量 LLM 抽取。两条手写生产循环
（`OrchestratingExecutor.research_and_validate`、`AdaptiveResearchRunner.run`），
自然语言需求靠关键词分支（PATCH_DEBT_AUDIT.md 记录 18 处硬编码）；两个能力仓库
（企业研究 / 海外市场研究）无法联合执行；无 Agent Loop、无统一 Evidence、无跨域综合。

**新架构**：

```text
USER → ResearchOrchestratorAgent（唯一 Orchestrator）
  ├─ MISSION_PARSE（LLM structured + 关键词兜底，保留原句）
  ├─ GOAL_PLAN（企业核心 12 Goal 永远保留 + 增量专项/市场 Goal，open-set CUSTOM）
  ├─ ROUTING（LLM 语义分类 + 代码主体边界校验 + routing_reason 审计）
  ├─ APPROVAL（统一人工审批；Agent 禁止自批）
  ├─ EXECUTE_SKILLS（ResearchSkillPort × 2：EnterpriseResearchSkill /
  │   OverseasMarketResearchAdapter，只消费 SkillRunResult 结构化返回）
  ├─ INGEST（MarketEvidenceImporter → 统一 EvidenceStore，五重边界隔离）
  ├─ GOAL_EVALUATION（确定性必需证据覆盖 + LLM 语义判定；禁止自宣成功）
  ├─ RECOVERY（不同策略/新 query；有效执行才计数；连续未执行 3 轮即 BLOCK；
  │   单目标上限来自 config/agent.yaml=10；耗尽 → Auditable Evidence Limitation）
  └─ SYNTHESIS（CrossDomainSynthesisEngine：只读 VERIFIED 证据，结论必须可追溯）
      → 交回主仓既有 UNIFIED_VALIDATE → FREEZE → ARTIFACT_PLAN → PUBLISH
      → CROSS_VALIDATE → PACKAGE（单 Artifact Owner）
```

LLM 负责：理解/规划/判断/补救/综合；代码负责：搜索执行/证据/预算/ID/审计/Schema/
冻结/发布（写入 ARCHITECTURE.md 作为 P0 Architectural Invariant）。

## B. 新增模块

| 文件 | 职责 |
|---|---|
| `src/enterprise_energy_research/agent/models.py` | ResearchMission/ResearchGoal/RoutingDecision/SkillPlan/SkillRunResult/GoalEvaluation/RecoveryPlan/CrossDomainFinding/MissionApproval/AgentCostRecord + 枚举（全部 strict，extra=forbid） |
| `agent/policies.py` | config/agent.yaml 策略加载（含 value_class 映射、轮次上限） |
| `agent/state.py` | AgentState（§29 状态机 17 阶段 + checkpoint） |
| `agent/mission_parser.py` | LLM structured 解析 + 关键词降级兜底（parse_mode 标记） |
| `agent/goal_planner.py` | 企业核心 12 Goal + 增量 Custom Goal + 6 类市场 Goal + HYBRID 跨域 Goal |
| `agent/router.py` | LLM RoutingBatch + 主体边界强制覆盖 + 确定性兜底（带理由） |
| `agent/evaluator.py` | 必需证据覆盖（确定性）+ LLM 语义评估合并 |
| `agent/recovery.py` | RecoveryPlanner（不同策略）+ RecoveryLedger（§24 有效轮计数）+ Auditable Limitation |
| `agent/synthesis.py` | CrossDomainSynthesisEngine（引用必须可解析，否则丢弃） |
| `agent/orchestrator.py` | ResearchOrchestratorAgent 核心循环 + 模式护栏（市场目标+企业主体→HYBRID）+ continue_mission（§12/§28） |
| `agent/market_evidence.py` | MarketEvidenceImporter：海外 ledger → Source/Claim（含竞争主体隔离 entity_id=competitor:<name>） |
| `agent/mission_store.py` | Mission/Approval/SkillRun/Trace 持久化（SQLite，Agent Trace 后台） |
| `agent/api.py` | FastAPI 路由（parse/approve/start/continue/status/missions/health）+ 企业执行器接线 |
| `agent/tools/base.py` | ResearchSkillPort Protocol + fail-closed helper |
| `agent/tools/enterprise_research.py` | 企业 Skill 端口（包装既有研究内核，可注入执行器） |
| `agent/tools/overseas_market_research.py` | 海外 Adapter（审批门 + 结构化产物收割 + R1/R2/R3 任务生成 + 默认 subprocess 执行器） |
| `config/agent.yaml` | Agent 控制面配置（§53） |
| `schemas/research-mission|research-goal|routing-decision|skill-run-result|goal-evaluation|recovery-plan.schema.json` | §54 六份 JSON Schema（由 pydantic 生成） |
| `src/.../automation/api/portal/agent.html` | Agent 引导页（业务语言审批流） |
| `scripts/agent_live_probe.py` / `scripts/agent_live_loop.py` | 真实 LLM 探针与全链路 live 集成脚本 |
| `docs/agent/REPOSITORY_INTEGRATION_BASELINE.md` | 双仓基线（§1） |
| `docs/agent/PATCH_DEBT_AUDIT.md` | 18 处硬编码分类（KEEP/MIGRATE_TO_AGENT） |
| `docs/adr/ADR-AGENT-001..006.md` | 6 份架构决策记录（§72） |
| `vendor/skills/overseas-energy-market-research/` + `VENDOR_INFO.md` | 版本锁定能力包 |

## C. 复用模块（未重写）

- 研究内核全套：ResearchPlanner/SearchExecutor/Recall/EvidenceStore/FreezeService/
  CoreValidator/饱和与覆盖率校验/分析引擎/Artifact 发布器——零重写。
- `ModelGateway`（LiteLLM）与 `CountingGateway`——Agent 全部 LLM 决策走同一网关。
- `automation` 层（TaskStateMachine/ResearchService/Daily Intelligence/飞书/n8n）——未触碰；
  Daily Intelligence 保持原工作流（§47）。
- 海外 Skill 全部 Stage Gate / 建模链 / Word-Excel-PPT 管线——原样 vendored，仅 1 处必要补丁。

## D. Overseas Skill 集成

- 版本固定：commit `ccc2a18b484efad919031a6b935021e67a0cb8f2`（v1.2.9），
  LICENSE + THIRD_PARTY_NOTICES + VENDOR_INFO.md 随包保存；
  `vendor/manifest.json` 覆盖全部 24,594 文件 SHA-256，`vendor_skills.py verify` PASS。
- 接入方式：`OverseasMarketResearchAdapter` 经 `ResearchSkillPort` 调用；默认执行器为
  vendored `run_workflow.py` subprocess（--check --collect），结果优先读取
  source ledger / attempt journal / market scan / stage_status / data_gap_log
  等结构化产物，绝不读 Word 正文。
- 人工审批双重门：Adapter 校验 `00_Research_Approval.csv` approved 行；
  未审批 → BLOCKED/AUTH_REQUIRED（TEST-AGENT-08 锁定）。
- Evidence 映射：value_class 经 config/agent.yaml 映射
  （observed→OBSERVED、derived→DERIVED、modeled_estimate→MODEL_ESTIMATE、
  simulated→SIMULATED、scenario_assumption→ASSUMPTION、pending_verification→TO_BE_CONFIRMED，
  未知值→TO_BE_CONFIRMED 不丢弃）；建模三类行保留在 Skill 自身审计链，不重复入库。
- 上游必要补丁（1 处，记录于 VENDOR_INFO.md）：`resolve_presentation_images.py`
  `output_manifest` 赋值顺序修复（上游 HEAD 自身缺陷，任何环境必现）。

## E. Agent 工作流程（实际 State Flow）

见 `agent/state.py` 的 `AgentPhase`（17 阶段，§29 目标状态机）。生产路径为
`ResearchOrchestratorAgent.parse_and_plan → run_approved`（或 `run` 一键），
核心循环为 §21 的 PLAN→ROUTE→ACT→INGEST→EVALUATE→(RECOVERY→ACT)*→SYNTHESIZE，
迭代与轮次均受 config/agent.yaml 上限约束；LangGraph stub（graph/build.py）未参与
生产路径，Agent 控制层采用与既有 ResearchState 同构的显式 pydantic 状态（ADR-AGENT-001）。

## F. Recovery（动态补救机制）

1. 评估不满足 → `RecoveryPlanner` 产出【不同】策略（新来源类别 + 新 query），
   LLM 结构化输出；LLM 不可用时确定性来源车道轮换（环评/投产公告/政府招标/年报/
   地方工信/行业平台）。
2. `RecoveryLedger` 只对"真实执行了不同策略"计数（§24）：adapter 完全失败、
   未执行搜索、重复相同 query 一律不计数；连续 3 轮未计数 → 目标 BLOCK，防止空转。
3. 单目标上限默认 10（config/agent.yaml），耗尽产出 `AUDITABLE_EVIDENCE_LIMITATION`
   （含已执行轮数与缺失证据），第一次缺数据绝不直接"资料有限"（§25）。
4. Live 验证：真实 LLM 补救规划在集成探针中实际运行并消耗轮次直至预算上限。

## G. 测试结果

| 套件 | 结果 |
|---|---|
| Enterprise Regression（pytest 全量） | **551 passed, 1 skipped**（基线 530+1 全保留，新增 20 项 Agent 测试 + 1 项 vendor 测试） |
| Enterprise Regression（官方 `unittest discover`） | exit 0 全通过 |
| Overseas Regression（14 项官方脚本） | **14/14 PASS**（anysearch 需 LF 归一化——环境工件；PPT 需预置 presentation_project + 上游补丁） |
| Agent Tests（TEST-AGENT-01~15 + Hybrid Golden + API） | **20/20 PASS**（离线，fake gateway/skills；live 能力由 scripts/agent_live_*.py + run_live_acceptance.py 验证，非 mock 冒充） |
| Live Probe（真实 DeepSeek） | structured 解析 3/3 `parse_mode=llm`；全链路 HYBRID 集成闭环（解析→路由→执行→补救→预算上限） |
| vendor manifest verify | PASS（24,594 文件） |
| schemas JSON 语法 | 6 个新 schema + 11 个既有 schema 全部有效 |

环境说明（非代码缺陷，已记录于基线文档）：
- 本机 Windows 注册表代理对 Python 客户端不可用（SSL EOF）；需显式
  `HTTPS_PROXY=http://127.0.0.1:7897` 或直连。litellm 1.98.0 在 Python 3.10 下
  无法导入（上游 NotRequired 兼容性缺陷），本机 venv 已固定 1.89.7；
  生产 Docker 为 Python 3.11 不受影响。tiktoken 编码缓存已预置。
- 上游 `resolve_presentation_images.py` UnboundLocalError 修复（见 §D）。

## H. Remaining Risk

1. **V1 未合并两套搜索 Runtime**（§46 允许）：AnySearch/Kimi 各自保留，Agent 统一
   Goal/Result/Evidence/Audit；后续 Shared Acquisition Refactor 才有统一查询面。
2. **Enterprise 工具的真实执行器接线**：已修复——`build_enterprise_executor` 现将专项需求
   写入 `optional_scope.notes`（既有管线 `automation/orchestration.py:163` 的实际读取位置），
   恢复轮 query 以"第N轮补采"行并入；仍建议做一次真实企业全量 run 校准。
3. **Overseas 默认执行器的任务 CSV 生成**：生成 R1/R2/R3 行满足上游模板列契约，
   但上游 anti-under-collection 政策 floor 的完全对齐需一次真实市场 run 校准。
   AnySearch 无 key 时走匿名模式（配额受限），有 `EER_ANYSEARCH_API_KEY` 更稳。
4. **structured() 的 token 计量**：LiteLLMModelGateway.structured 合成 ModelResponse
   时不回填 usage，AgentCostRecord 的 token 统计暂时为 0（既有网关行为，修复属网关层小改动）。
5. **LLM 路由/评估质量**：受模型能力影响；离线兜底路径已保证降级可用，且
   Goal Routing Accuracy 等 §59 指标需在真实任务集上持续采集。

## I. 最终判断

**READY_WITH_LIMITATIONS**

Definition of Done 核对：双仓基线记录 ✅ / 版本固定 ✅ / ResearchMission-Goal-Dynamic
Goal ✅ / Router ✅ / 双工具 ✅ / Hybrid 路由 ✅ / Unified Evidence ✅ / 主体隔离 ✅ /
Recovery Loop + 上限 ✅ / 人工审批 ✅ / 跨域综合 ✅ / 统一 Freeze-Publication 路径 ✅
（编排器交回主仓 Artifact Plane）/ 原 Enterprise 回归 ✅ / 原 Overseas 回归 ✅ /
新 Agent 测试 ✅ / Daily Intelligence 无回归 ✅ / 文档 ✅。

Limitations 来源仅 §H 的 5 项工程性风险（其中 1-3 为 V1 明确的接线深度问题，
4-5 为观测与模型质量层面），不构成功能缺失，不涉及真实凭证或外部服务缺失。

## J. 四 Tab 门户增量（2026-08-25 v3，已部署验证）

用户三项新需求全部落地，页面 `/agent` 重构为四 Tab：

1. **企业调查 / 海外市场调研分轨**：各自独立 Tab，流程均为解析需求（带 `track`
   轨道参数，不匹配时仅出“轨道提示”诊断，不覆盖解析结果）→ 可编辑 goal 框架
   （改名/删除/新增，`POST /mission/{id}/goals`，最终状态语义，新增 goal 自动路由）→
   批准 → 轮询目标进展，均带停止按钮。
2. **深度研究**：按名称关键词锁定已产出成果的任务（`GET /missions?query=&status=`），
   `POST /mission/{id}/deep-research` 可附加自然语言增量需求并修复所有非 SATISFIED
   目标；EXHAUSTED 目标重置恢复预算（`deep_recovery_rounds: 5`，ledger 以持久化
   recovery_rounds 为基线），修复后统一重新发布；带停止按钮。
3. **每日情报回归门户**：第四 Tab 复用既有 `/api/v1/intelligence/*` 端点（n8n 每日
   10:00 定时触发不变），支持立即生成/暂停/恢复/查看最新日报。

停止机制设计：per-mission `threading.Event` 协作检查点（skill 组前/recovery 轮前/
收尾前）+ `MissionStatus.CANCELLED` 终态 + 陈旧事件 reset；海外 adapter 以 Popen 追踪
采集进程并在 stop 时强杀进程树；CANCELLED 任务拒绝 approve（409）。

验证：tests/test_agent_portal_features.py 新增 20 个用例（TEST-AGENT-16~19 + API
surface），全量回归 **589 passed, 1 skipped**；镜像 rebuild 后容器 healthy，页面与
API 冒烟（parse → goal 编辑 → stop → deep-research 守卫 409 → 名称查找）全部通过。
