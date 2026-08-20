# 自动化改造阶段总览（Phase 1-15）

基线：`architecture-audit.md`（51/51 测试通过时审计）。截至 2026-08-19 各阶段状态：

| Phase | 交付物 | 状态 |
|---|---|---|
| 1 | 契约层 `automation/contracts.py` + `enums.py`（63 测试） | ✅ |
| 3 | `automation/state_machine.py` 14 状态合法转移表（73 测试） | ✅ |
| 4 | `automation/db/` SQLAlchemy 持久化 + venv（88 测试） | ✅ |
| 2 | `automation/service.py` + `automation/api/` FastAPI（122 测试） | ✅ |
| 5 | Review Gate 规则引擎 `automation/review.py`（10 条 RV 规则） | ✅ |
| 6 | n8n 工作流 `automation/n8n/enterprise-research-workflow.json` | ✅ |
| 7 | Feishu 适配层 `automation/feishu/`（协议/Mock/Lark/Notifier） | ✅ |
| 8 | RetryPolicy `automation/retry.py`（transient/permanent + 退避） | ✅ |
| 9 | 幂等（DB 唯一约束 + service 判重，Phase 2/4 内完成） | ✅ |
| 10 | 观测 `automation/observability.py`（CountingGateway/run_span/log_event） | ✅ |
| 11 | ROI `automation/roi.py`（人工工时 vs 机器时长） | ✅ |
| 12 | Eval 扩充至 10 条 + `scripts/run_automation_eval.py` | ✅ |
| 13 | Failure Case Library `docs/failure-cases/`（6 案例） | ✅ |
| 14 | `automation/monitor/` Schedule + watchlist + Change Detection | ✅ |
| 15 | Dockerfile + docker-compose.yml（research-api + postgres + n8n） | ✅ |
| 全程 | 12 份文档 + 7 份 ADR | ✅ |
| 编排接线 | `automation/orchestration.py` planner→search→extract→phase3 确定性流水线 | ✅ |

## 关键决策摘要

- **Human Gate 在 Freeze 之前**：`Phase3Runner.process_batches` 拆出
  `process_batches_until_ingest`（ADRT-0003），评审未通过不得创建 freeze。
- **Review/Retry 全部声明式**（config YAML），默认配置保持 V1 基线不收紧（ADR-0006）。
- **Fail-closed**：适配器不可用 → blocked envelope → BLOCKED，绝不猜测数据（ADR-0004）。
- **ROI 不编造**：只有落库的 feedback + metrics 才参与汇总（Phase 11）。

## 测试基线

- 全量 `PYTHONPATH="src;tests" ./.venv/Scripts/python.exe -m unittest discover -s tests`
- Eval 回归 `PYTHONPATH="src" ./.venv/Scripts/python.exe scripts/run_automation_eval.py`
