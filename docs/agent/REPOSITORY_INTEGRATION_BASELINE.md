# Repository Integration Baseline

> 双仓融合基线审计。本文档由 Agent 融合工程于 2026-08-25 产出，作为 `Energy Research Agent`
> 重构的版本基准与职责边界记录。任何后续架构决策（ADR-AGENT-*）都以此文件为事实基础。

## 1. 仓库版本

| 仓库 | HEAD commit SHA | 分支 | 提交时间 | 版本标识 |
|---|---|---|---|---|
| `energy-research-agent`（主仓库，基线提交时旧名为 `enterprise-energy-research`） | `52d3d14c6003cafa4867a29ebaa325b0f5b47bd0` | `main` | 2026-08-25 00:39 +0800 | 0.9.0（pyproject），代码内另有 0.9.1 字样（production_runner.py:206） |
| `overseas-energy-market-research-skill`（专业能力仓库） | `ccc2a18b484efad919031a6b935021e67a0cb8f2` | `main` | 2026-08-12 23:01 +0800 | v1.2.9（CHANGELOG 最新） |

基线测试：主仓库 `530 passed, 1 skipped`（2026-08-25，`python -m pytest tests/ -q`）。
海外 skill 14 项官方离线 regression 结果见 §9。

## 2. 两仓当前能力

### 2.1 主仓库 energy-research-agent（Control Plane + Evidence Plane + Artifact Plane）

- **身份与规划**：CompanyResolver（置信度投票消歧）、EnterpriseComplexityClassifier（规则打分）、
  ResearchPlanner（60 个 Goal Family × R1/R2/R3 查询矩阵 + requirement 语义路由 + coverage 重试策略轮换）。
- **采集**：SearchExecutor（预算/电路断路器/canonical subject 锚定）、AnySearchAdapter（嵌入 3.0.1 CLI）、
  KimiWebBridgeAdapter（本机 daemon）、Recall Core（DEEP_RESEARCH / DAILY_INTELLIGENCE 双 profile，
  168 槽位预算、8 个 Source Lane、Frontier 扩张、覆盖率矩阵）。
- **证据**：EvidenceStore（SQLite 追加式四表 + PostgreSQL 迁移路径）、EvidenceNormalizer、
  ClaimValidator（置信度/冲突组）、SourceGrader（SOURCE_A-D）、FreezeService（SHA-256 + Merkle root 冻结）、
  FrozenResearchBundle（发布层只读）。
- **验证**：CoreValidator（EvidenceValidator 语义）、DataSaturationValidator、ResearchDataCoverageValidator、
  ImageValidator（视觉模型像素核验）、DecisionIntelligenceValidator、FormalPublicationEligibilityValidator、
  ArtifactConsistencyAuditor（CrossArtifactValidator 等价物）、渲染级 visual QA。
- **分析与叙事**：ResearchAnalysisEngine、StrategicInterpretationEngine（InterpretationLineage）、
  CooperationHypothesisEngine、DecisionSynthesisEngine、ResearchNarrative（Word/HTML 共享中间层）、
  PublicationBoilerplateFilter（去 AI 腔）。
- **发布**：ArtifactPlanner → Excel/Word/HTML/PPT 四个 FrozenPublisher → PackagePublisher；
  VisualSpec/VisualManifest、diagram-design 嵌入适配、visual_router/visual_policy。
- **自动化层**：TaskStateMachine（确定性状态机）、ResearchService、RetryPolicy、OrchestratingExecutor
  （portal 生产路径）、AdaptiveResearchRunner（自适应 R1-R4 生产循环 + MergeEvidence）、
  Daily Intelligence（10:00 调度、run lock、防重复推送）、监控/飞书/FastAPI portal。
- **基础设施**：FastAPI（`automation/api/app.py`，`/api/*` 全路由 + `/portal`）、PostgreSQL/SQLite、
  n8n（daily intelligence + failure watchdog）、Docker、uv 锁定依赖。
- **vendor 机制**：`vendor/skills/` 6 个嵌入 skill（anysearch、kimi-webbridge、excel-master、ppt-master、
  frontend-design、diagram-design），`vendor/manifest.json`（文件级哈希）+ `scripts/vendor_skills.py verify`。
  **缺陷：manifest 无 commit SHA / 版本 pin**（只有人类可读 source 字符串）——Phase B 需补。

### 2.2 专业能力仓库 overseas-energy-market-research-skill（Domain Capability Pack）

- **市场研究**：市场定义/规模/TAM-SAM-SOM、政策/电价/补贴/电网机制/准入/认证、
  客户需求/场景/负荷模型、产品工程、竞争格局/exact-model benchmark、价格/渠道/服务网络/用户评价/痛点、
  商业模式、NPV/IRR/Payback 经济性。
- **结构化采集**：18 张 CSV（01 Market Scan … 15 Record Registry）+ `02_Web_Collection_Tasks.csv`
  按 goal 的 R1/R2/R3 三行制；AnySearch（内嵌 3.0.1 CLI）+ Kimi WebBridge 双采集路由；
  Source Ledger（38 列）、Collection Attempt Journal、Record Registry（content_sha256 去重）。
- **质量门**：Stage Gate 0–8（`validate_stage_gate.py` + 20 个 validate_* 脚本）、
  anti-under-collection / anti-fake-completion（BLOCKING_ERROR_CLASSES + raw_capture 存在性）、
  source independence、critical claim 哈希 + 双 evidence_binding、建模 G1–G6 + 人工 G2.5/G4.5、
  Word ≥15000 字、Excel 重算、PPT 渲染几何、figure 质量。
- **建模链**：`references/modeling-chain-adaptation.md` 契约，`create_modeling_artifacts.py` 生成
  12_Model_Assumptions / 13_Model_Results / 14_Simulated_Modeling_Data（唯一写入者），
  frozen_numbers.json 机制。
- **Five Views**：宏观/行业/客户/竞争/自己五看报告，`【证据：ID】` 锚点可解析校验。
- **人工审批**：`00_Research_Approval.csv`（Stage 0 强制）、建模 `decided_by: human`、
  政策升级/例外审批——均不可被程序自动通过。
- **交付**：Word（build_template_report.py + IB 风格后处理 + 渲染 QA）、Excel（公式编译 + LibreOffice 重算）、
  PPT（high_fidelity SVG→DrawingML 或 fallback）、evidence_audit_report.md、production manifest。
- **可编程接口**：`scripts/run_workflow.py`（--init/--check/--collect/--modeling/--audit/--all）、
  `web_collection/cli.py`（JSON 输出）、`validate_stage_gate.py`；模块级函数可 import
  （run_collect/run_modeling/run_task/CollectionJournal 等）。无库级 `__init__`，需 sys.path 接入。

## 3. 重复能力（去重决策）

| 能力 | 主仓实现 | 海外实现 | 决策 |
|---|---|---|---|
| 搜索适配 | SearchExecutor + AnySearchAdapter（3.0.1） | web_collection/router.py + anysearch_backend.py（3.0.1） | **V1 不合并**。各自保留 Runtime；Agent 统一 Goal/Result/Evidence/Audit（规格 §46） |
| Kimi WebBridge | KimiWebBridgeSearchAdapter（daemon 10086） | _kimi_webbridge.py + kimi_adapter.py | **V1 不合并**，同上 |
| R1/R2/R3 概念 | planner.py ROUND_SUFFIXES | 02_Web_Collection_Tasks.csv round 列 | 语义一致（R1 广度/R2 深度/R3 三角验证），保留各自执行 |
| Word/Excel/PPT | artifacts/* FrozenPublisher | build_*.py 官方生成器 | 主仓 Artifact Plane 为最终交付 Owner；海外产物作为 validated sub-artifact |
| 冻结 | FreezeService（Merkle） | frozen_numbers.json（建模参数） | 主仓 Freeze 为统一冻结 |
| Source 分级 | SOURCE_A-D | reliability_tier + VALUE_CLASSES | 主仓 Evidence 验收取更严格规则；海外领域路由保留 |
| 人工审批 | portal 解析确认 | 00_Research_Approval.csv | **统一为 Unified Research Mission Approval**（规格 §27） |

## 4. 必须保留的能力

- 主仓：§2.1 全部（规格 §4.1 清单），特别是 SearchExecutor 的 canonical subject 锚定、
  FreezeService、PublicationBoilerplateFilter、Daily Intelligence 原样（规格 §47）。
- 海外：§2.2 全部 Stage Gate、attempt journal、anti-fake-completion、建模链、人工闸门（规格 §26）。

## 5. 将迁移给 Agent 的职责（LLM 负责不确定性）

- 自然语言理解与 Mission 解析（保留原始句子，禁止丢弃）
- Research Goal 拆解 / 优先级 / Open-set Dynamic Custom Goal
- Skill Routing 语义分类（含 routing_reason 审计）
- Gap Reasoning / Recovery 策略制定（每轮新策略，受上一轮结果影响）
- Cross-domain Synthesis / Decision Interpretation
- Continuation 模式语义解析（禁止把分隔符当语义边界）

## 6. 将继续由代码负责的职责（代码负责确定性）

- ID/Schema/数据库、Search API 调用、URL 去重/Hash、Evidence 写入/版本
- Budget、Retry Ceiling、Recovery Round 有效执行计数、Citation、Source Ledger
- Freeze、Artifact Manifest、文件生成、飞书/n8n、并发、Run Lock、日志、安全、审计
- 全部质量 Gate（两套 Skill 原有 Gate 继续生效）

## 7. 兼容性风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 主仓生产路径不经 LangGraph（两条手写循环） | 高 | Agent Control Layer 采用 pydantic typed state + 显式节点链（沿用 graph/ 现状），不强行迁移生产循环 |
| vendor manifest 无版本 pin | 中 | Phase B 扩展 manifest schema（commit SHA + 版本）并保持 `vendor_skills.py verify` 兼容 |
| 海外 skill 无库级 package | 中 | Adapter 经 `run_workflow.py` CLI（subprocess）+ sys.path 导入，读结构化产物而非 Word 正文 |
| value_class 值域差异 | 低 | 映射：observed→OBSERVED, derived→DERIVED, modeled_estimate→MODEL_ESTIMATE, simulated→SIMULATED, scenario_assumption→ASSUMPTION, pending_verification→TO_BE_CONFIRMED |
| LLM structured output 仅 JSON mode（无 function calling） | 中 | Agent 决策全部走 ModelGateway.structured（JSON Schema + repair），不引入新调用路径 |
| 两套测试体系（unittest 主仓 / 脚本式回归海外） | 低 | 分别保留，Phase I 汇总双份结果 |
| 海外 PPT 资产巨大（templates/icons 33MB） | 低 | vendor 时保留完整能力包（与现有 ppt-master 60MB 实践一致），manifest 哈希覆盖关键文件 |

## 8. 最终集成方式

```text
energy-research-agent/                         # 主仓库 = Agent Host + Control/Evidence/Artifact Plane
└─ vendor/skills/overseas-energy-market-research/   # 版本锁定能力包（commit SHA + LICENSE + NOTICES + manifest）
src/enterprise_energy_research/
└─ agent/                                      # 新增 Agent Control Layer
   ├─ models.py        # ResearchMission / ResearchGoal / RoutingDecision / SkillRunResult / ...
   ├─ mission_parser.py / goal_planner.py / router.py
   ├─ evaluator.py / recovery.py / synthesis.py
   ├─ orchestrator.py / state.py / policies.py
   └─ tools/
      ├─ base.py                  # ResearchSkillPort Protocol
      ├─ enterprise_research.py   # 包装主仓现有研究内核
      └─ overseas_market_research.py  # OverseasMarketResearchAdapter（CLI + 结构化产物映射）
```

集成原则：Adapter / Skill Port，不暴力合仓；不修改 upstream 文件（除非必要且记录）；
Agent 只消费 SkillRunResult 结构化返回值；Evidence 一律归一入主仓 Unified Evidence Store。

## 9. 基线测试记录

### 主仓库

```
530 passed, 1 skipped — python -m pytest tests/ -q（2026-08-25，3:22）
（skip 为 test_phase2_runner.py 的合成运行断言跳过，属既有设计）
```

### 海外 skill 官方回归（scripts/regression_test_*.py）

| 脚本 | 结果 |
|---|---|
| regression_test_anysearch_embed | PASS（工作树 CRLF 归一化为 LF 后通过；git blob 本身与 manifest 一致，属环境工件非代码缺陷） |
| regression_test_kimi_embed | PASS (7/7) |
| regression_test_web_collection | PASS (5/5) |
| regression_test_modeling_chain | PASS (14/14) |
| regression_test_word_delivery | PASS |
| regression_test_excel_delivery | PASS |
| regression_test_figure_delivery | PASS |
| regression_test_workflow_runner | PASS (12/12) |
| regression_test_collection_audits | PASS |
| regression_test_doctor | PASS (8/8) |
| regression_test_final_report_package | PASS |
| regression_test_font_discovery | PASS (10/10) |
| regression_test_text_only_visuals | PASS (7 类图表 / 7 版式族) |
| regression_test_ppt_delivery | PASS（需预置 presentation_project 目录；见下方 patch 说明） |

> 环境修复说明（均已在 vendored 快照中同步并记录于 VENDOR_INFO.md）：
> 1. `scripts/resolve_presentation_images.py` 上游 HEAD `ccc2a18` 存在 `output_manifest` 使用先于赋值的
>    UnboundLocalError（:118/:120），任何环境均会失败；已做最小两行重排补丁，未改变行为语义。
> 2. 上游 regression 不归一化 CRLF，Windows 检出需对 `scripts/anysearch/` 文本文件做 LF 归一化。
> 两项均为环境/上游缺陷，非本集成引入。任何因环境缺失（无 LibreOffice/浏览器/凭证）导致的跳过
> 一律标注 `SKIPPED_ENVIRONMENT`，不写 PASS。
