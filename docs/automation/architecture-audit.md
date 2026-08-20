# Architecture Audit — Enterprise Energy Research Skill（自动化改造前审计）

- 审计日期：2026-08-19
- 审计对象：`C:/Users/Wenyi Zhang/.agents/skills/enterprise-energy-research/`（v0.9.0 升级前基线）
- 审计方式：文档全读（10 份顶层 Markdown + references/）+ `src/` 全量代码审阅 + tests/config/evals/schemas/scripts 检查 + 测试实跑
- 测试基线：**51 / 51 通过**（`PYTHONPATH="src;tests" python -m unittest discover -s tests -v`，34.5s，0 失败 0 跳过）

> 本报告是后续所有自动化改造 Phase 的基线。凡本报告记录的 Architecture Gap / Inconsistency，后续 Phase 不得"顺手重构"掩盖，只能在对应 Phase 显式处理。

---

## 1. Repository Tree（裁剪后关键结构）

```
enterprise-energy-research/
├── README.md  SKILL.md  ARCHITECTURE.md  WORKFLOW.md  DATA_SCHEMA.md
├── VALIDATION_SPEC.md  ARTIFACT_SPEC.md  SOURCE_POLICY.md  IMPLEMENTATION_PLAN.md
├── pyproject.toml                # v0.9.0, src 布局, 唯一 console script: enterprise-energy-research
├── agents/openai.yaml            # 仅 UI 元数据（展示卡片），无运行时逻辑
├── config/                       # 7 个 YAML（default/source_policy/enterprise_rules/
│                                 #   artifact_profiles/collection_saturation_policy/
│                                 #   office_visual_policy/research_budgets）
├── schemas/                      # 11 个 JSON Schema（由 scripts/generate_schemas.py 生成）
├── evals/evals.json              # 3 个 eval case
├── references/                   # 4 份迁移/嵌入说明
├── scripts/                      # 13 个脚本（6 通用 + 7 杉杉专案一次性脚本）
├── src/enterprise_energy_research/
│   ├── cli.py                    # 仅 2 命令：synthetic-run / settings
│   ├── settings.py               # pydantic-settings, env_prefix=EER_（不读 .env 文件）
│   ├── vendor.py                 # vendor skill 白名单与根目录解析
│   ├── domain/                   # models.py（全部 Pydantic 领域模型）、enums.py、ids.py
│   ├── research/                 # planner/executor/extractor/normalizer/resolver/classifier/
│   │                             #   entity_mapper/source_grader/saturation/claim_validator/
│   │                             #   image_validator/image_archiver/product_detector
│   ├── analysis/                 # energy.py、solutions.py（只读证据）
│   ├── evidence/                 # store.py（SQLite append-only）、freeze.py、exports.py
│   ├── validation/               # core.py（结构校验）、delivery_quality.py（交付深度/视觉门）
│   ├── artifacts/                # publisher/planner/word/excel/ppt/html/visuals/
│   │                             #   image_publication/presentation_contract
│   ├── graph/                    # state.py、runner.py（Phase2）、phase3_runner.py、
│   │                             #   build.py（可选 LangGraph）、preflight.py
│   ├── gateway/                  # base.py（ModelGateway Protocol）、litellm_gateway.py
│   ├── adapters/                 # base/anysearch/kimi_webbridge/fixture/unconfigured
│   └── release/                  # audit.py（跨制品一致性审计）、package.py（确定性 ZIP）
├── tests/                        # 16 个文件、51 个 unittest 测试 + 3 个 fixture JSON
└── vendor/skills/                # 5 个嵌入 skill（anysearch/excel-master/frontend-design/
                                  #   kimi-webbridge/ppt-master），含 manifest.json 哈希清单
```

不存在：`docs/`（本次新建）、`automation/`、`Dockerfile`、`docker-compose.yml`、`.env`（有 `.env.example`，9 个 `EER_*` 变量）。

---

## 2. Current Architecture

### 2.1 声明架构（文档目标态）

四平面划分（ARCHITECTURE.md:20-26）：

- **Control plane**：LangGraph 状态图、路由、预算、重试、门控、run 状态
- **Evidence plane**：规范化 claims/sources/images/图实体/冲突/冻结快照
- **Analysis plane**：产业、能源与合作引擎，只读证据
- **Artifact plane**：publisher 与 validator，只读冻结版本

声明流水线（ARCHITECTURE.md:7-18）：
`Company input → Identity/Scope → Adapter-mediated research → Evidence store → Validation → Immutable freeze → Artifact manifest → Publishers → Cross-artifact validation → Package 或 BLOCKED`

### 2.2 实际架构（代码现状）

**证据平面实现度高；控制平面基本缺失。** 一句话：当前是"可运行的证据内核 + 未接线的研究/发布外围"。

实际可调用的调用链（两段，中间断裂）：

1. **Phase2 链**（`graph/runner.py:29-73`，`Phase2Runner.finalize_evidence`）：
   `VALIDATE(CoreValidator) → FREEZE(FreezeService) → ARTIFACT_PLAN(ArtifactPlanner) → EXPORT(export_bundle)`
2. **Phase3 链**（`graph/phase3_runner.py:38-143`，`Phase3Runner.process_batches`）：
   `COMPANY_RESOLVER → EVIDENCE_NORMALIZER → EVIDENCE_VALIDATOR(claim/entity/image/product) → ENTERPRISE_CLASSIFIER → ENERGY_ANALYST → SOLUTION_ENGINE → EVIDENCE_INGEST → finalize_evidence`
   —— 输入是**外部准备好的** `ExtractedEvidenceBatch` 列表，仅被 tests/ 与 scripts/ 调用。

**断裂段**：`ResearchPlanner → SearchExecutor → EvidenceExtractor → DataSaturationValidator` 已实现但**无任何 runner 编排**；`ArtifactPublicationService`、`ArtifactConsistencyAuditor`、`ReleasePackageBuilder` 同样无 src 内调用方。真实端到端运行靠 `scripts/run_shanshan_*.py` 手工拼装。

---

## 3. Current Entry Points

| 入口 | 位置 | 说明 |
|---|---|---|
| CLI `synthetic-run` | `cli.py:40-128` | 合成数据演示，不联网；是唯一直接可跑的 run 入口 |
| CLI `settings` | `cli.py:133-135` | 打印脱敏配置 |
| console script | `pyproject.toml:35-36` | `enterprise-energy-research = cli:main` |
| Skill 入口 | `SKILL.md` | 供 Agent（如本会话）按文档驱动执行，非程序入口 |
| 一次性脚本 | `scripts/run_shanshan_live_validation.py` 等 | 真实调研跑批的唯一现存路径，手工拼 store/manifest/state |
| LangGraph 构建器 | `graph/build.py:23` | 可选 extra，**仅 test_domain.py 调用**，生产路径不走 |

**结论：当前是纯 CLI / Skill 形态，无任何 HTTP/API 层、无队列、无调度入口。**

---

## 4. Existing Domain Boundaries（必须保留）

以下边界在代码中真实存在，是本次改造的**不可动红线**：

1. **Research ↔ Publish 分离**：`artifacts/` 全目录 grep `urllib|requests|httpx|subprocess` **零命中**；所有 publish 方法签名只接收 `FrozenResearchBundle`（由 `FreezeService.load_bundle` 从冻结版本读出）。图片只取研究期已归档的本地 `local_asset_ref`（`image_publication.py:94-104`）。
2. **Validation Gate 先于 Freeze**：`FreezeService.create()` 拒绝 BLOCKED 报告及含 ERROR/BLOCKER finding 的报告（`evidence/freeze.py:30-33`）。
3. **Freeze 不可变（应用层强制）**：`EvidenceStore.add()` 若目标版本已被冻结则拒绝写入（`store.py:178-185`）；无 UPDATE/DELETE 接口；每版本 `UNIQUE(run_id, evidence_version)` 只冻结一次；全量 SHA-256 root_hash。
4. **Publisher 不补事实**：`ArtifactPlanner.plan()` 只为 VERIFIED 的 claim/image 建绑定（`artifacts/planner.py:32-40`）；缺失可选值渲染为 `—`；release 审计会拒绝 publisher 引入了绑定外事实的产物（`release/audit.py:64-67`）。
5. **来源分级与冲突保留**：SOURCE_A–D（`research/source_grader.py:14`），snippet 恒为 D；冲突为一等记录，禁止静默平均/覆盖（`research/claim_validator.py`）。
6. **联网收敛**：对外联网仅在 `adapters/`（AnySearch 子进程 / kimi-webbridge loopback）与研究层 `image_archiver.py`；fail-closed，禁止切换未批准搜索提供方。

---

## 5. Reusable Components（直接复用，不重写）

| 组件 | 位置 | 复用方式 |
|---|---|---|
| 全部 Pydantic 领域模型 | `domain/models.py`（ResearchRequest、RunManifest、Claim、DataFreeze、ArtifactManifest、ValidationReport 等） | 自动化层的契约直接扩展/包装这些模型 |
| Evidence Store（SQLite append-only） | `evidence/store.py` | 自动化层**不另建 evidence 库**；新增自动化表（tasks/runs/events/reviews/metrics）与 evidence 库分离 |
| Freeze / Exports | `evidence/freeze.py`、`exports.py` | 冻结语义原样保留 |
| CoreValidator + delivery_quality | `validation/` | Review Gate 规则引擎直接消费 ValidationReport/深度检查结果 |
| Artifact 发布器全家桶 | `artifacts/`（word/excel/ppt/html/visuals/image_publication） | API 层只负责编排调用，不改 publisher 内部 |
| Release 审计与打包 | `release/audit.py`、`package.py` | 发布前一致性门槛复用 |
| ModelGateway Protocol + LiteLLM 实现 | `gateway/` | token/cost 追踪在 gateway 外围包一层，不改协议 |
| 搜索/浏览器适配器 + fixture 适配器 | `adapters/` | MockFeishuAdapter 等按同样的 Port 模式新增 |
| 研究内核（planner/executor/extractor/…/saturation） | `research/` | Phase 2 需要补的是"编排接线"，不是重写内核 |
| config YAML（预算/来源策略/饱和策略/质量门） | `config/` | 作为 Review Policy、Retry Policy 的取值来源 |
| 51 个 unittest 回归测试 + 3 fixtures | `tests/` | 全部保留，新测试按同风格追加 |
| schemas 生成机制 | `scripts/generate_schemas.py` + `schemas/` | 新增契约模型后重新生成 |
| vendor 嵌入与供应链校验 | `vendor.py`、`scripts/vendor_skills.py` | 不动 |

## 6. Required New Components（新增，而非修改）

| 新组件 | 建议位置 | 对应 Phase |
|---|---|---|
| `ResearchRequest`（自动化版，含 task_id/requested_by/country/product/topics/priority…）与 `ResearchResult` | `src/enterprise_energy_research/automation/contracts.py`（新子包，避免污染 domain） | Phase 1 |
| FastAPI API 层 + Application Service | `automation/api/` + `automation/service/`；核心业务逻辑不 import FastAPI | Phase 2 |
| TaskStateMachine（14 状态，含合法转移表） | `automation/state_machine.py` | Phase 3 |
| 自动化持久化（research_tasks/research_runs/workflow_events/human_reviews/run_metrics/user_feedback） | `automation/db/`（SQLAlchemy，PostgreSQL；dev 可 SQLite 起步）；**不碰 evidence 库表结构** | Phase 4 |
| Review Policy 规则引擎（10 条触发规则）+ Review 记录 | `automation/review.py` | Phase 5 |
| n8n workflow JSON + 导入说明 | `automation/n8n/` | Phase 6 |
| FeishuAdapter Interface + MockFeishuAdapter + `.env.example` 扩展 | `automation/feishu/` | Phase 7 |
| RetryPolicy（区分 transient/permanent） | `automation/retry.py` | Phase 8 |
| 幂等键（task_id + idempotency_key） | 落 db 层唯一约束 + service 层判重 | Phase 9 |
| 结构化日志 + RunMetrics（token/cost 在 gateway 外包装饰器采集） | `automation/observability.py` + gateway 包装 | Phase 10 |
| ROI 指标（人工工时 vs 机器时长分离） | `automation/roi.py` + run_metrics 表字段 | Phase 11 |
| Golden eval 扩展（≥10 任务，复用 evals/ 机制） | `evals/` 扩充 | Phase 12 |
| Failure Case Library | `docs/failure-cases/` | Phase 13 |
| Schedule Trigger + watchlist.yaml + Change Detection | `automation/monitor/` | Phase 14 |
| Dockerfile / docker-compose.yml（research-api + postgres + n8n） | 仓库根 | v0.9.0 部署层 |
| 12 份自动化文档 + 7 份 ADR | `docs/automation/`、`docs/adr/` | 全程 |

**编排接线（关键新增）**：在 Application Service 内把已断裂的 `ResearchPlanner → SearchExecutor → EvidenceExtractor → Phase3Runner → finalize_evidence → ArtifactPublicationService → ArtifactConsistencyAuditor` 接成一条由状态机驱动的确定性流水线——这是"新增编排代码"，不是重构研究内核。

## 7. Potential Risks

1. **编排断链是最大工作量**：真实研究路径目前只存在于杉杉一次性脚本中；把 planner→search→extract 接成可恢复的服务级流水线，比写 API 层本身风险更高。需要 fixture 驱动的集成测试兜底。
2. **fixture 模式后门**：Word/PPT publisher 在 fixture 模式下跳过图片缺失 fail 与深度门槛（`word.py:69-70`、`release/audit.py:81,94,129`）。自动化路径必须确保生产 run 不落入 fixture 模式，否则质量门形同虚设。
3. **LLM 抽取依赖未接线**：`EvidenceExtractor` 走 `ModelGateway.structured()`，但 `LiteLLMModelGateway` 在 src 内无实例化点；自动化服务需要负责装配 gateway 并处理无凭据场景的 fail-closed。
4. **evidence 多版本机制不完整**（见 §8.5）：同一 record 实际无法多版本并存。"修改后重新研究（RESEARCH_AGAIN）"语义需通过新 `evidence_version` + 新 record_id 命名空间规避，不能依赖原地改版。
5. **freeze 完整性校验单向**：`load_bundle()` 不重算 record_hashes。自动化层任何人写库路径都必须走 `EvidenceStore` API，禁止裸 SQL 写 evidence_records。
6. **客户特定硬编码**：`analysis/solutions.py:45,60` 含杉杉专属文案；`word.py:22-33`、`html.py:17-28` 的 FIELD_LABELS 含客户特定字段。通用化（尤其海外市场研究场景）是独立工作量，记入 Gap，不在自动化 Phase 顺手改。
7. **一次性脚本含真实企业名**：scripts/ 下 7 个杉杉脚本与 README "仓库不包含运行时企业采集记录"的声明有张力；对外开源/共享前需处理。
8. **环境缺口**：系统 Python 无 pytest、包未 pip install；CI/Docker 化前测试入口依赖 `PYTHONPATH` 手工设置。
9. **51 个测试恰为回归红线**：用户要求"51 项以上测试必须继续全部通过"，当前恰好 51，任何误删即破线。
10. **LLM cost 数据缺失**：`ModelResponse.usage` 存在但被 `structured()` 丢弃；ROI/成本指标需要在 gateway 外围补采集，且早期数据为"可采集但无历史基线"，ROI 数字禁止编造。

## 8. Architecture Inconsistencies（记录，不偷偷重构）

1. **控制平面名实不符**：ARCHITECTURE.md 称控制面是 LangGraph 状态图；实际生产路径是自研 `ResearchState.transition()`（`graph/state.py:27-36`），无合法转移约束、无持久化；`build_langgraph()` 仅测试调用。
2. **测试栈声明不一致**：README 用 `unittest discover`；ARCHITECTURE.md:206 声明 pytest/syrupy/Playwright；pyproject test extra 只有 pytest。实际 51 个测试全为 unittest 风格。
3. **Python 版本**：pyproject `>=3.10` vs ARCHITECTURE.md:193 "Python 3.11+"。
4. **组件缺失**：ARCHITECTURE.md:49 的 `InputNormalizer` 无对应实现（仅 LangGraph 节点名）；计划的 `graph/nodes/`、`templates/`、`tests/{unit,integration,golden,e2e}` 目录结构不存在。
5. **evidence 版本机制**：`evidence_records` 主键 `(run_id, kind, record_id)` 不含 `evidence_version`（`store.py:113`），"冻结后写新版本"（`store.py:184` 错误文案）对同 record_id 实际做不到。
6. **升级前版本问题**：`graph/runner.py:19-21` 曾有过期 docstring；CLI 曾硬编码旧 `code_version`，现统一由包版本读取。
7. **schemas 数量**：ARCHITECTURE.md:179 列 6 个，磁盘 11 个。
8. **VALIDATION_SPEC 场景编号**：标题称 24 个场景，实际列到 40，且 34/35 各出现两次。
9. **`.env` 支持半成品**：`Settings` 未配置 `env_file`，`.env.example` 仅是文档。
10. **两套验证体系未统一**：`CoreValidator` 产出 `ValidationFinding`（Pydantic）；`delivery_quality` 产出纯字符串 findings，且只在 release 审计阶段生效，不进 ValidationReport。
11. **声明的 Phase 完成度有留白**：SKILL.md:47 称 Phase 4/5 完成，但 IMPLEMENTATION_PLAN.md:118,138 明确 PPT 渲染一致性、golden 图像 diff、性能/resume 压测仍未完成。
12. **未消费的配置/依赖**：`Settings.database_url`、pyproject `database` extra（SQLAlchemy/psycopg）、`ResearchState.budgets`、`graph/preflight.py` 在代码中均无消费方。

## 9. 最小改造计划（摘要）

**直接复用**：领域模型、evidence store/freeze/exports、全部 validator、publisher、release audit、gateway 协议、adapters、config YAML、51 测试 + fixtures、vendor 机制。

**新增（不动旧代码内部逻辑）**：`automation/` 子包（contracts/api/service/state_machine/db/review/retry/feishu/observability/roi）、编排接线层、n8n JSON、Docker、docs。

**绝对不重写**：
- `evidence/store.py` / `freeze.py` 的不可变语义；
- `validation/` 两套门槛的规则本身；
- `artifacts/` 任何 publisher 的"只消费冻结包"约束；
- `research/` 内核模块的判定逻辑（source 分级、冲突保留、饱和策略）；
- 51 个现有测试（只能追加，不能删改通过条件）。

**改造顺序**：按 Phase 1（契约）→ 3（状态机）→ 4（持久化）→ 2（API 层，依赖前三者）→ 5（Review Gate）→ 8/9（Retry/幂等）→ 10/11（观测/ROI）→ 6/7（n8n/飞书）→ 12-14（Eval/Failure/Monitor）→ Docker/文档收尾执行；每个 Phase 结束跑全量 51+ 测试并输出 Commit-ready Summary。

---

*Audit 完成。等待确认后进入 Phase 1。*
