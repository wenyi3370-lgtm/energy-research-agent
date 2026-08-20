# ADR-0007: 定时监测不引入新调度依赖与状态表

- 状态：Accepted
- 日期：2026-08-19

## 背景
Phase 14 需要周期重跑 + 变化检测；但原则 4 禁止过度工程（不引入 Redis/Kafka/
自研调度器），且新增表应克制。

## 决策
- `automation/monitor/schedule.py` 用纯 stdlib 实现 four-cadence 规则
  （hourly/daily/weekly/monthly），不依赖 croniter。
- 调度状态从 `research_runs` 推导（active_run.created_at 作为 last_run_at），
  不建新表；`run_due` 用 `watch:{name}:{cadence}` 幂等键防重复触发。
- 实际定时执行交给外部（cron / n8n Schedule Trigger）调用 `MonitorRunner.run_due(now)`。
- 变化检测是纯函数（claims diff），对比同一任务最近两个 PUBLISHED run 的 evidence。

## 后果
- 零新增依赖、零新增表；调度语义全部可单测。
- 若未来需要"到点自动执行"，在 n8n 加 Schedule Trigger 即可，无需改代码。
