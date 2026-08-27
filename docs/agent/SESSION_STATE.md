# Session State — Energy Research Agent 融合实施（2026-08-25 交接文档 v2）

> 超长会话压缩交接点。后续任何会话先读此文件 + `docs/agent/IMPLEMENTATION_REPORT.md`。

## 1. 代码库位置与部署

- 代码库（唯一权威）：`C:\Users\Wenyi Zhang\.agents\skills\energy-research-agent`
  （git HEAD `52d3d14`，全部改动未提交）
- Docker Compose 三服务运行中（research-api 挂载该目录 `/skill`，改源码重启即生效）
- 本地 `.env`：EER_DEEPSEEK_API_KEY + POSTGRES_PASSWORD + 飞书三件套 +
  `EER_ANYSEARCH_API_KEY=as_sk_6c13...`（用户 2026-08-25 提供；**AnySearch 免费配额每日限量，重跑前先测搜索**）

## 2. 已完成（全部 in-source + 测试锁定）

- Agent 层 17 模块（models/policies/state/parser/planner/router/evaluator/recovery/
  synthesis/orchestrator/mission_store/api/publication/evals + tools×3）
- 领域扩展：ValueClass、Claim 统一字段、CrossDomainFinding、ExtractedClaim/Claim.goal_family、
  Bundle.cross_domain_findings、Manifest.sub_artifact_refs
- 核心规则（全部源码内，非探针）：
  ① 并行恢复（config `parallel_recovery_rounds: 4`）
  ② 恢复轮定向化（`research_and_validate(recovery_only=True)`）
  ③ 恢复轮证据合并入统一冻结（`publish_unified(recovery_run_ids)`）
  ④ 确定性恢复用 RECOVERY_STRATEGIES×10 轮换
  ⑤ 三层证据绑定（LLM goal_family → 查询 topic → 契约反查）
  ⑥ 审批双门（Mission 审批 → adapter `ensure_approved`）
  ⑦ 政策轮次下限（`_policy_floors`）
  ⑧ 跨域章节（narrative `cross_domain`）
  ⑨ Agent 指标（evals.py + run_agent_metrics.py）
  ⑩ Debug 页 `/agent/debug`
- 测试：**569 passed, 1 skipped**
- 文档：docs/agent/（BASELINE/PATCH_DEBT/REPORT/PERFORMANCE_POLICY/STRATEGY_ADOPTION_AUDIT/
  SESSION_STATE）+ ADR-AGENT-001~006

## 3. ✅ 终验完成（2026-08-25 14:09）

**宁德时代 × 德国户储 HYBRID 全链路闭环**（探针 agent-hybrid-mncrofwt，Docker 内持久卷）：

| 项 | 结果 |
|---|---|
| 交付物 | Word(docx) + Excel(xlsx) + 企业 HTML 驾驶舱（KPI/工厂地图图表） |
| 渲染质检 | QA pass（word）/ warn（html） |
| 统一冻结 | FREEZE-…（`-unified`，恢复轮证据全部并入） |
| 证据量 | 1034 条（verified 348，有效证据率 0.34） |
| 并行恢复 | 4 个目标恢复轮 50 秒并行（串行需 ~8 分钟） |
| 完成率 | 0.1（2 目标 SATISFIED；18 limitation 系探针 1 轮上限参数，生产 config 为 10 轮） |

**产物已复制到**：`C:\Users\Wenyi Zhang\Desktop\宁德时代终验产物\`
（enterprise_research.docx / .xlsx / _dashboard.html）

## 4. 已知事项 / 坑

- 容器重建会清 /tmp → 探针数据必须放 `/data/automation_work/agent_probes/`
- AnySearch 免费配额每日耗尽（重跑前先测 `AnySearchCliAdapter().search()`）
- 测试成本纪律：迭代期 `pytest --lf --ff`；全量只在里程碑
- 探针脚本（scripts/agent_hybrid_live.py 等 4 个）是验证工具，规则在 src/
- 两个仓库改动均在本地工作区，未提交

## 5. 下一步

1. **提交 git**（用户确认后；.env 不入库）—— enterprise 仓 + overseas 仓（overseas 上游克隆保留在 workspace）
2. 可选：Word 转 PDF / 飞书推送产物
3. 可选：正式企业任务（页面 `/agent`）跑一次真实交付验收（配额恢复后）
4. 可选：§59 指标持续采集（run_agent_metrics.py）
