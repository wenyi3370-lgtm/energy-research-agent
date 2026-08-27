"""升级前检查：列出正在执行（RESEARCHING）的任务，避免容器重建中断它们。

用法：python scripts/check_running_tasks.py
输出非空时请等待任务完成或先 retry，再进行 docker compose up -d --build。
"""
import sys
import urllib.request

try:
    import psycopg  # noqa
    from energy_research_agent.automation.db import AutomationDatabase
    from sqlalchemy import select
    from energy_research_agent.automation.db.models import ResearchRunRow

    db = AutomationDatabase("postgresql+psycopg://research:research@localhost:5432/research")
    session = db.session()
    rows = session.execute(
        select(ResearchRunRow).where(ResearchRunRow.status == "RESEARCHING")
    ).scalars().all()
    session.close()
    db.engine.dispose()
    if rows:
        print(f"⚠️  发现 {len(rows)} 个正在执行的任务：")
        for row in rows:
            print(f"    {row.run_id} | {row.task_id} | started_at={row.started_at}")
        print("请等待完成或先 POST /api/v1/research/{run_id}/retry 处理，再重建容器。")
        sys.exit(1)
    print("✅ 无正在执行的任务，可以安全重建容器。")
except Exception as exc:  # 直连失败时降级提示
    print(f"⚠️  无法检查（{exc}）。重建前请确认无 RESEARCHING 任务。")
    sys.exit(0)
