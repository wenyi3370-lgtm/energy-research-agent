"""小白一键监测调度器（Phase 14）。

用法：
    python scripts/run_monitor.py                 # 跑所有到期的监测任务
    python scripts/run_monitor.py --check        # 只查看下次到期时间，不执行

行为：
1. 读 config/watchlist.yaml，找出"到期"的监测项（按各自周期/时间）；
2. 对每个到期项自动提交并执行研究任务（幂等，不会重复跑）；
3. 对已有两次以上历史的任务做变化检测，打印变化报告。

第一次跑时所有启用项都视为"到期"（没有历史）。之后按各自周期触发。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from energy_research_agent.automation.api.app import _default_executor
from energy_research_agent.automation.db import AutomationDatabase
from energy_research_agent.automation.monitor import MonitorRunner, load_watchlist
from energy_research_agent.automation.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor runner (Phase 14)")
    parser.add_argument("--check", action="store_true", help="只打印到期计划，不执行")
    parser.add_argument("--now", default=None, help="指定当前时间 ISO 格式（测试用）")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    watchlist = load_watchlist(ROOT / "config" / "watchlist.yaml")
    db = AutomationDatabase("sqlite:///" + str(ROOT / "automation_monitor.db"))
    mode = os.environ.get("ERA_AUTOMATION_EXECUTOR", "synthetic")
    print(f"运行模式: {mode}")
    service = ResearchService(
        db, _default_executor(), ROOT / "automation_work"
    )
    runner = MonitorRunner(service, watchlist, db=db, workdir=ROOT / "automation_work")

    due = runner.due_items(now)
    print(f"[{now:%Y-%m-%d %H:%M}] 监测项共 {len(watchlist)} 个，到期 {len(due)} 个")
    for item in watchlist:
        print(f"  - {'✅' if item in due else '⏳'} {item.name}（{item.schedule.describe()}）")

    if args.check:
        db.engine.dispose()
        return 0

    results = runner.run_due(now)
    print(f"\n本次执行 {len(results)} 个研究任务：")
    for result in results:
        print(f"  - {result.task_id} run={result.run_id} -> {result.status.value}")
        item = next(
            (w for w in watchlist if result.task_id.startswith(w.task.task_id + ":")),
            None,
        )
        report = runner.detect_change(item, result.run_id) if item else None
        if report is not None and report.has_changes:
            print(f"    变化检测：{len(report.changes)} 处变化")
            for change in report.changes:
                print(f"      [{change.kind}] {change.field_name}: "
                      f"{change.old_value} -> {change.new_value}")
        elif report is not None:
            print("    变化检测：无变化（符合预期）")
    db.engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
