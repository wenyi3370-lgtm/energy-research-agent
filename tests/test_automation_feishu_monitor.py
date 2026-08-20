"""Phase 7/14 tests: Feishu adapters/notifier, monitor schedule/watchlist/change."""

import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path

from enterprise_energy_research.automation.contracts import ResearchResult
from enterprise_energy_research.automation.db import AutomationDatabase
from enterprise_energy_research.automation.enums import TaskStatus
from enterprise_energy_research.automation.executor import ExecutionOutcome, SyntheticKernelExecutor
from enterprise_energy_research.automation.feishu import FeishuNotifier, MockFeishuAdapter
from enterprise_energy_research.automation.feishu.base import FeishuMessage
from enterprise_energy_research.automation.monitor import (
    Change,
    ChangeDetector,
    MonitorRunner,
    ScheduleRule,
    WatchlistItem,
    load_watchlist,
    next_run_after,
)
from enterprise_energy_research.automation.service import ResearchService
from enterprise_energy_research.domain.enums import ValidationStatus
from enterprise_energy_research.domain.models import Claim

ROOT = Path(__file__).resolve().parents[1]


class FeishuTests(unittest.TestCase):
    def test_mock_adapter_records(self):
        adapter = MockFeishuAdapter()
        result = ResearchResult(run_id="R1", task_id="T1", status=TaskStatus.PUBLISHED)
        delivery = adapter.notify_run(result)
        self.assertTrue(delivery.delivered)
        self.assertEqual(len(adapter.sent), 1)
        self.assertIn("PUBLISHED", adapter.sent[0].text)

    def test_unavailable_adapter_fail_closed(self):
        adapter = MockFeishuAdapter(available=False)
        delivery = adapter.send(FeishuMessage(receiver="x", text="hi"))
        self.assertFalse(delivery.delivered)

    def test_notifier_skips_when_no_adapter(self):
        notifier = FeishuNotifier()
        result = ResearchResult(run_id="R1", task_id="T1", status=TaskStatus.PUBLISHED)
        self.assertIsNone(notifier.notify(result))

    def test_notifier_only_on_selected_statuses(self):
        adapter = MockFeishuAdapter()
        notifier = FeishuNotifier(adapter)
        queued = ResearchResult(run_id="R1", task_id="T1", status=TaskStatus.QUEUED)
        notifier.notify(queued)
        self.assertEqual(len(adapter.sent), 0)
        gated = ResearchResult(run_id="R2", task_id="T2", status=TaskStatus.REVIEW_REQUIRED)
        notifier.notify(gated)
        self.assertEqual(len(adapter.sent), 1)

    def test_operational_text_does_not_create_research_result(self):
        adapter = MockFeishuAdapter()
        delivery = FeishuNotifier(adapter).send_text("[定时监测] 到期任务 1 个")
        self.assertTrue(delivery.delivered)
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].text, "[定时监测] 到期任务 1 个")


class MonitorWorkflowContractTests(unittest.TestCase):
    def test_failure_watchdog_only_recovers_stale_runs(self):
        workflow = json.loads(
            (ROOT / "automation" / "n8n" / "failure-watchdog-workflow.json").read_text(
                encoding="utf-8"
            )
        )
        schedule_nodes = [
            node for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.scheduleTrigger"
        ]
        self.assertEqual(len(schedule_nodes), 1)
        self.assertEqual(
            schedule_nodes[0]["parameters"]["rule"]["interval"],
            [{"field": "hours", "hoursInterval": 1}],
        )
        urls = [
            node.get("parameters", {}).get("url")
            for node in workflow["nodes"]
            if node.get("parameters", {}).get("url")
        ]
        self.assertEqual(
            urls,
            ["http://research-api:8000/api/v1/maintenance/recover-stale"],
        )
        serialized = json.dumps(workflow, ensure_ascii=False).lower()
        for forbidden in (
            "/api/v1/research",
            "/api/v1/monitor/run",
            "/retry",
            "watchlist",
            "/api/v1/triggers/feishu",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_monitor_workflow_is_inactive_and_never_submits_research(self):
        workflow = json.loads(
            (ROOT / "automation" / "n8n" / "monitor-schedule-workflow.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(workflow["active"])
        schedule_nodes = [
            node for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.scheduleTrigger"
        ]
        self.assertEqual(len(schedule_nodes), 1)
        self.assertTrue(schedule_nodes[0].get("disabled"))
        urls = [
            node.get("parameters", {}).get("url")
            for node in workflow["nodes"]
            if node.get("parameters", {}).get("url")
        ]
        self.assertEqual(urls, ["http://research-api:8000/api/v1/monitor/run"])
        self.assertNotIn("/api/v1/triggers/feishu", json.dumps(workflow, ensure_ascii=False))

    def test_feishu_research_workflow_is_inactive(self):
        workflow = json.loads(
            (ROOT / "automation" / "n8n" / "enterprise-research-workflow.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(workflow["active"])
        webhook_nodes = [
            node for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.webhook"
        ]
        self.assertEqual(len(webhook_nodes), 1)
        self.assertTrue(webhook_nodes[0].get("disabled"))


class ScheduleTests(unittest.TestCase):
    def test_daily_next_run_after(self):
        rule = ScheduleRule(cadence="daily", interval=1, at_time="09:00")
        anchor = datetime(2026, 8, 19, 9, 0)
        nxt = next_run_after(anchor, rule, datetime(2026, 8, 20, 10, 0))
        self.assertEqual(nxt, datetime(2026, 8, 20, 9, 0))

    def test_first_run_anchored_in_future(self):
        rule = ScheduleRule(cadence="weekly", interval=1, at_time="08:30", weekday=1)
        now = datetime(2026, 8, 19, 12, 0)  # Wednesday
        nxt = next_run_after(None, rule, now)
        self.assertEqual(nxt, datetime(2026, 8, 25, 8, 30))  # next Monday

    def test_hourly_interval(self):
        rule = ScheduleRule(cadence="hourly", interval=2)
        anchor = datetime(2026, 8, 19, 10, 0)
        nxt = next_run_after(anchor, rule, datetime(2026, 8, 19, 12, 1))
        self.assertEqual(nxt, datetime(2026, 8, 19, 12, 0))

    def test_monthly_rollover(self):
        rule = ScheduleRule(cadence="monthly", interval=1, day_of_month=1)
        anchor = datetime(2026, 11, 1, 9, 0)
        nxt = next_run_after(anchor, rule, datetime(2026, 12, 2, 9, 0))
        self.assertEqual(nxt.month, 12)
        self.assertEqual(nxt.day, 1)

    def test_watchlist_load(self):
        items = load_watchlist(ROOT / "config" / "watchlist.yaml")
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(items[0].enabled)  # 前两项已启用（小白开箱配置）
        self.assertTrue(items[0].task.task_id.startswith("MON_"))
        self.assertFalse(items[2].enabled)  # 第三项（每日政策）保持关闭

    def test_watchlist_due(self):
        item = WatchlistItem.model_validate({
            "name": "t", "enabled": True,
            "schedule": {"cadence": "daily", "interval": 1, "at_time": "09:00"},
            "task": {
                "task_id": "T1", "requested_by": "u", "country": "Thailand",
                "research_type": "market_monitor",
            },
            "monitor_fields": ["price"],
        })
        self.assertTrue(item.is_due(datetime(2026, 8, 20, 10, 0), last_run_at=datetime(2026, 8, 19, 9, 0)))
        self.assertFalse(item.is_due(datetime(2026, 8, 19, 12, 0), last_run_at=datetime(2026, 8, 19, 9, 0)))


class ChangeDetectionTests(unittest.TestCase):
    def _claim(self, field, value, source_id="S1"):
        return Claim(
            claim_id=f"C-{field}", entity_id="E1", field_name=field, value=value,
            value_type="string", qualifier="exact", source_id=source_id,
            raw_text=str(value), context_text=str(value),
            verification_status="VERIFIED", confidence=1.0,
        )

    def test_detects_changed_added_removed(self):
        old = [self._claim("price", "1.2"), self._claim("policy", "old")]
        new = [self._claim("price", "1.5"), self._claim("capacity", "10")]
        report = ChangeDetector().detect("subject", old, new)
        kinds = {change.kind for change in report.changes}
        self.assertEqual(kinds, {"changed", "removed", "added"})
        changed = next(c for c in report.changes if c.kind == "changed")
        self.assertEqual(changed.field_name, "price")
        self.assertEqual(changed.old_value, "1.2")
        self.assertEqual(changed.new_value, "1.5")
        self.assertTrue(report.has_changes)

    def test_no_changes(self):
        old = [self._claim("price", "1.2")]
        new = [self._claim("price", "1.2")]
        report = ChangeDetector().detect("subject", old, new)
        self.assertFalse(report.has_changes)

    def test_scoped_fields(self):
        old = [self._claim("price", "1.2"), self._claim("policy", "x")]
        new = [self._claim("price", "1.5"), self._claim("policy", "y")]
        report = ChangeDetector().detect("subject", old, new, fields=["price"])
        self.assertEqual(report.changed_fields, ["price"])


class MonitorRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AutomationDatabase(f"sqlite:///{Path(self.tmp.name) / 'm.db'}")
        self.executor = SyntheticKernelExecutor()
        self.service = ResearchService(self.db, self.executor, Path(self.tmp.name) / "work")
        item = WatchlistItem.model_validate({
            "name": "mon", "enabled": True,
            "schedule": {"cadence": "daily", "interval": 1},
            "task": {
                "task_id": "MON_TASK", "requested_by": "watchdog", "company": "某储能企业",
                "research_type": "market_monitor",
            },
            "monitor_fields": [],
        })
        self.runner = MonitorRunner(self.service, [item])

    def tearDown(self):
        self.db.engine.dispose()
        self.tmp.cleanup()

    def test_run_due_submits_and_executes(self):
        results = self.runner.run_due(datetime(2026, 8, 19, 12, 0))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, TaskStatus.PUBLISHED)
        # not due again on the same day: last run just happened
        again = self.runner.run_due(datetime(2026, 8, 19, 13, 0))
        self.assertEqual(len(again), 0)


if __name__ == "__main__":
    unittest.main()
