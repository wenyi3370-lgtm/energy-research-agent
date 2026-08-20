"""Run-status notification bridge (Phase 7).

The service calls the notifier at gate/terminal transitions; the notifier
dispatches to a configured Feishu adapter and always *surfaces* delivery
failures in the workflow event trail instead of dropping them.

On PUBLISHED the notifier also delivers the deliverable files (Excel +
Word, from the artifact manifest locations) straight into the chat, so the
final research product shows up where the business user already is.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..contracts import ResearchResult
from .base import FeishuAdapter, FeishuDelivery, FeishuMessage

logger = logging.getLogger("enterprise_energy_research.automation.feishu")

NOTIFY_ON = {"REVIEW_REQUIRED", "PUBLISHED", "FAILED", "BLOCKED", "REJECTED"}

# Deliverable types delivered as files on PUBLISHED (ordered).
FILE_DELIVERABLES = ("excel", "word", "enterprise_html")


class FeishuNotifier:
    """Notifies configured receivers on terminal/gate status changes."""

    def __init__(self, adapter: FeishuAdapter | None = None) -> None:
        self.adapter = adapter

    def notify(self, result: ResearchResult) -> FeishuDelivery | None:
        if self.adapter is None or not self.adapter.available():
            return None
        if str(result.status) not in NOTIFY_ON:
            return None
        deliveries: list[FeishuDelivery] = []
        deliveries.append(
            self.adapter.send(FeishuMessage(
                receiver="",
                text=self._status_text(result),
                run_id=result.run_id,
                task_id=result.task_id,
                status=str(result.status),
            ))
        )
        if str(result.status) == "PUBLISHED":
            deliveries.extend(self._deliver_artifacts(result))
        failed = [item for item in deliveries if item is not None and not item.delivered]
        if failed:
            logger.warning(
                "notification not delivered for run %s: %s",
                result.run_id,
                failed[0].diagnostics,
            )
        return deliveries[0]

    def send_text(self, text: str) -> FeishuDelivery | None:
        """Send an operational message without creating a research task.

        Scheduler summaries and service alerts must use this path.  Routing
        them through the Feishu form trigger would incorrectly interpret the
        notification as a new company-research request.
        """
        if self.adapter is None or not self.adapter.available():
            return None
        return self.adapter.send(FeishuMessage(receiver="", text=text))

    @staticmethod
    def _status_text(result: ResearchResult) -> str:
        """Status-specific notification copy; BLOCKED tells the reviewer how to proceed."""
        task = result.task_id
        run = result.run_id
        if str(result.status) == "PUBLISHED":
            return (
                f"[研究完成] {task}\nrun={run}\n"
                f"验证: {result.validation_status.value if result.validation_status else '-'} | "
                f"证据: {result.evidence_count} 条 | 冲突: {result.conflict_count} | 缺口: {result.gap_count}\n"
                "成果文件（Excel/Word/HTML）已随本条消息发送，请查收。"
            )
        if str(result.status) == "BLOCKED":
            return (
                f"[需人工处理] {task}\nrun={run}\n"
                "存在证据冲突（UNRESOLVED_CORE_CONFLICT），系统已停止发布。\n"
                "请查看 conflicts 详情后裁决：\n"
                "  POST /api/v1/research/{run_id}/conflicts/{conflict_id}/resolve\n"
                "  然后 POST /api/v1/research/{run_id}/resume 恢复发布。"
            )
        if str(result.status) == "REVIEW_REQUIRED":
            return (
                f"[需评审] {task}\nrun={run}\n"
                f"原因: {'; '.join(result.review_reasons[:3])}\n"
                "请评审后提交决策（APPROVE/REJECT/RESEARCH_AGAIN）。"
            )
        if str(result.status) == "REJECTED":
            return f"[已拒绝] {task}\nrun={run}\n任务已被评审拒绝，流程终止。"
        return (
            f"[研究失败] {task}\nrun={run}\n"
            f"error: {result.error.error_type if result.error else 'unknown'}: "
            f"{result.error.message if result.error else ''}"
        )

    def _deliver_artifacts(self, result: ResearchResult) -> list[FeishuDelivery]:
        """Upload PUBLISHED excel/word/html artifacts into the chat (成果文件送达)."""
        send_file = getattr(self.adapter, "send_file", None)
        if send_file is None:
            return []
        deliveries: list[FeishuDelivery] = []
        for ref in result.artifact_manifest:
            if (
                ref.artifact_type.value in FILE_DELIVERABLES
                and ref.status.value == "PUBLISHED"
                and ref.location
            ):
                deliveries.append(send_file("", ref.location))
        return deliveries

    @staticmethod
    def from_env() -> "FeishuNotifier":
        from .lark import LarkFeishuAdapter

        adapter = LarkFeishuAdapter()
        return FeishuNotifier(adapter if adapter.available() else None)


def make_notifier(adapter: FeishuAdapter | Callable[[], FeishuAdapter] | None) -> FeishuNotifier:
    if adapter is None:
        return FeishuNotifier()
    if isinstance(adapter, FeishuNotifier):
        return adapter
    if isinstance(adapter, FeishuAdapter) or hasattr(adapter, "notify_run"):
        return FeishuNotifier(adapter)
    return FeishuNotifier(adapter())  # type: ignore[misc]
