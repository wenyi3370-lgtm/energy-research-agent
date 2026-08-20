# 定时监测与变化检测（Phase 14）

> 当前部署策略：研究定时触发已停用。`MonitorRunner` 代码保留用于历史审计和
> 手工差异分析，但不得接入 cron/n8n Schedule；企业研究统一从本地网页启动。

`automation/monitor/`

## 组件

- `schedule.py` —— `ScheduleRule`（hourly/daily/weekly/monthly + at_time/weekday/day_of_month）
  与 `next_run_after()`；纯 stdlib，无 cron 依赖。
- `watchlist.py` —— `WatchlistItem`（任务模板 + 周期 + 监控字段），
  配置 `config/watchlist.yaml`（含泰国户储月度、产品参数周度、德国政策每日示例，默认 disabled）。
- `change_detection.py` —— `ChangeDetector`：对同一主体的新旧两 run 按 `field_name`
  比对 claims，输出 `ChangeReport`（changed/added/removed + 新旧值 + 来源 id）。
- `runner.py` —— `MonitorRunner`：
  - `run_due(now)`：对到期项以 `watch:{name}:{cadence}` 幂等键提交并执行研究任务；
  - `detect_change(item)`：取该任务最近两个 PUBLISHED run 的 evidence 做差异。

## 调度状态

不引入新表：`last_run_at` 从 `research_runs`（active_run 的 created_at）推导，
重启不丢、不重复触发。以下代码仅用于开发测试，不应接入生产定时器：

```python
from enterprise_energy_research.automation.monitor import MonitorRunner, load_watchlist
runner = MonitorRunner(service, load_watchlist(Path("config/watchlist.yaml")))
for result in runner.run_due(datetime.now()):
    print(result.run_id, result.status)
```
