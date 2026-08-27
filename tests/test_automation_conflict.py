"""冲突裁决机制 tests: BLOCKED -> resolve_conflict -> resume -> PUBLISHED."""

import tempfile
import unittest
from pathlib import Path

from energy_research_agent.automation.contracts import ResearchRequest
from energy_research_agent.automation.db import AutomationDatabase
from energy_research_agent.automation.enums import TaskStatus
from energy_research_agent.automation.executor import ExecutionOutcome
from energy_research_agent.automation.feishu import FeishuNotifier, MockFeishuAdapter
from energy_research_agent.automation.service import (
    ConflictNotFoundError,
    ConflictResolutionError,
    ResearchService,
)
from energy_research_agent.automation.state_machine import InvalidTransitionError
from energy_research_agent.domain.enums import ConflictStatus, RunStatus, ValidationStatus
from energy_research_agent.domain.models import ConflictGroup, RunManifest
from energy_research_agent.evidence.store import EvidenceStore


def make_request(task_id: str = "TH_BESS_001") -> ResearchRequest:
    return ResearchRequest(
        task_id=task_id, requested_by="user_001", country="Thailand",
        product="Residential BESS", research_type="market_entry",
        topics=["market_size"],
    )


class StubExecutor:
    def __init__(self, outcome=None, freeze_outcome=None) -> None:
        self.outcome = outcome or ExecutionOutcome(validation_status=ValidationStatus.BLOCKED)
        self.freeze_outcome = freeze_outcome or ExecutionOutcome(validation_status=ValidationStatus.PASS)

    def research_and_validate(self, run_id, request, workdir):
        return self.outcome

    def freeze_and_publish(self, run_id, workdir):
        return self.freeze_outcome


class ConflictAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AutomationDatabase(f"sqlite:///{Path(self.tmp.name) / 'conflict.db'}")
        self.executor = StubExecutor()
        self.service = ResearchService(self.db, self.executor, Path(self.tmp.name))

    def tearDown(self):
        self.db.engine.dispose()
        self.tmp.cleanup()

    def _blocked_run(self, task_id: str = "TH_BESS_001") -> str:
        submitted = self.service.submit(make_request(task_id))
        final = self.service.execute_run(submitted.run_id)
        self.assertEqual(final.status, TaskStatus.BLOCKED)
        # 预置 evidence store 中的 BLOCKING 冲突（模拟真实研究发现的冲突）
        run_dir = Path(self.tmp.name) / submitted.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        store = EvidenceStore(run_dir / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=submitted.run_id, request_id="REQ-1", status=RunStatus.RUNNING,
            config_hash="x", code_version="test", model_gateway={},
        ))
        store.add(submitted.run_id, 1, "conflict", ConflictGroup(
            conflict_group_id="CFG-PRICE", entity_id="E1", field_name="price",
            claim_ids=["C1", "C2"], status=ConflictStatus.BLOCKING,
            rationale="two sources disagree on price",
        ))
        store.add(submitted.run_id, 1, "conflict", ConflictGroup(
            conflict_group_id="CFG-OTHER", entity_id="E1", field_name="owner",
            claim_ids=["C3", "C4"], status=ConflictStatus.BLOCKING,
            rationale="ownership dispute",
        ))
        return submitted.run_id

    def test_list_conflicts(self):
        run_id = self._blocked_run()
        conflicts = self.service.list_conflicts(run_id)
        self.assertEqual(
            {c["conflict_group_id"] for c in conflicts}, {"CFG-PRICE", "CFG-OTHER"}
        )

    def test_resolve_then_resume_to_published(self):
        run_id = self._blocked_run()
        queued = self.service.resolve_conflict(
            run_id, "CFG-PRICE",
            decision="select_authoritative", reviewer="analyst_01",
            rationale="以官方公告为准", selected_claim_id="C2",
        )
        self.assertEqual(queued.status, TaskStatus.QUEUED)
        final = self.service.resume(run_id)
        self.assertEqual(final.status, TaskStatus.PUBLISHED, final.error)

    def test_resolve_coexist_decision(self):
        run_id = self._blocked_run()
        queued = self.service.resolve_conflict(
            run_id, "CFG-OTHER", decision="coexist", reviewer="analyst_01", rationale="口径差异可共存"
        )
        self.assertEqual(queued.status, TaskStatus.QUEUED)
        # 未裁决的冲突仍在快照之外
        from energy_research_agent.automation.db import TaskRepository

        session = self.db.session()
        try:
            resolutions = TaskRepository(session).list_conflict_resolutions(run_id)
            self.assertEqual(len(resolutions), 1)
            self.assertEqual(resolutions[0].decision, "coexist")
            self.assertEqual(resolutions[0].conflict_group_id, "CFG-OTHER")
        finally:
            session.close()

    def test_resolve_requires_blocked_run(self):
        submitted = self.service.submit(make_request())
        with self.assertRaises(InvalidTransitionError):
            self.service.resolve_conflict(
                submitted.run_id, "CFG-PRICE", decision="coexist", reviewer="r"
            )

    def test_resolve_unknown_conflict(self):
        run_id = self._blocked_run()
        with self.assertRaises(ConflictNotFoundError):
            self.service.resolve_conflict(run_id, "CFG-NOPE", decision="coexist", reviewer="r")

    def test_select_authoritative_requires_claim_in_group(self):
        run_id = self._blocked_run()
        with self.assertRaises(ConflictResolutionError):
            self.service.resolve_conflict(
                run_id, "CFG-PRICE", decision="select_authoritative",
                reviewer="r", selected_claim_id="C999",
            )
        with self.assertRaises(ConflictResolutionError):
            self.service.resolve_conflict(
                run_id, "CFG-PRICE", decision="select_authoritative", reviewer="r"
            )

    def test_resume_requires_recorded_resolution(self):
        run_id = self._blocked_run()
        # BLOCKED -> retry (无裁决) -> QUEUED 后 resume 应被拒绝
        self.service.retry(run_id)
        with self.assertRaises(ConflictResolutionError):
            self.service.resume(run_id)


class StaleRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AutomationDatabase(f"sqlite:///{Path(self.tmp.name) / 'stale.db'}")
        self.executor = StubExecutor()
        self.service = ResearchService(self.db, self.executor, Path(self.tmp.name))

    def tearDown(self):
        self.db.engine.dispose()
        self.tmp.cleanup()

    def _researching_run(self, hours_ago: float) -> str:
        from datetime import datetime, timedelta, timezone

        submitted = self.service.submit(make_request(task_id=f"STALE-{int(hours_ago)}"))
        run_id = submitted.run_id
        session = self.db.session()
        try:
            from energy_research_agent.automation.db import TaskRepository

            repo = TaskRepository(session)
            repo.update_run_status(run_id, TaskStatus.RESEARCHING, started=True)
            row = repo.get_run(run_id)
            row.started_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
            session.commit()
        finally:
            session.close()
        return run_id

    def test_stale_run_recovered_to_failed_retryable(self):
        run_id = self._researching_run(hours_ago=3)
        recovered = self.service.recover_stale_runs(max_minutes=120)
        self.assertEqual(len(recovered), 1)
        result = recovered[0]
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertTrue(result.error.retryable)
        self.assertIn("interrupted", result.error.message)
        # 恢复后可重试
        requeued = self.service.retry(run_id)
        self.assertEqual(requeued.status, TaskStatus.QUEUED)

    def test_stale_recovery_terminates_and_sends_failure_notification(self):
        adapter = MockFeishuAdapter()
        self.service.notifier = FeishuNotifier(adapter)
        run_id = self._researching_run(hours_ago=3)

        recovered = self.service.recover_stale_runs(max_minutes=120)

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, TaskStatus.FAILED)
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].run_id, run_id)
        self.assertEqual(adapter.sent[0].status, "FAILED")
        self.assertIn("研究失败", adapter.sent[0].text)

    def test_fresh_researching_run_not_touched(self):
        self._researching_run(hours_ago=0.2)  # 12 分钟前开始（正常范围）
        recovered = self.service.recover_stale_runs(max_minutes=120)
        self.assertEqual(recovered, [])

    def test_retried_run_gets_fresh_started_at(self):
        """重试后 started_at 必须刷新：僵尸检测不得误伤刚重跑的任务。"""
        run_id = self._researching_run(hours_ago=3)
        # 僵尸检测先把它标记 FAILED
        recovered = self.service.recover_stale_runs(max_minutes=120)
        self.assertEqual(len(recovered), 1)
        # retry → execute_run（RESEARCHING，刷新 started_at）
        self.service.retry(run_id)
        self.service.execute_run(run_id)
        session = self.db.session()
        try:
            from energy_research_agent.automation.db import TaskRepository
            from datetime import datetime, timezone

            row = TaskRepository(session).get_run(run_id)
            started = row.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            self.assertGreater((datetime.now(timezone.utc) - started).total_seconds(), -60)
            # 刚重跑的任务不应被僵尸检测误伤
            again = self.service.recover_stale_runs(max_minutes=120)
            self.assertEqual(again, [])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
