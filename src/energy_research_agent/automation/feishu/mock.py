"""In-memory Feishu adapter for tests and offline deployments (Phase 7)."""

from __future__ import annotations

from ..contracts import ResearchResult
from .base import FeishuAdapter, FeishuDelivery, FeishuMessage


class MockFeishuAdapter:
    """Records every message; nothing ever leaves the process."""

    name = "mock-feishu"

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.sent: list[FeishuMessage] = []
        self.sent_files: list[tuple[str, str]] = []  # (file_path, file_name)

    def available(self) -> bool:
        return self._available

    def send(self, message: FeishuMessage) -> FeishuDelivery:
        if not self._available:
            return FeishuDelivery(delivered=False, diagnostics=["mock adapter marked unavailable"])
        self.sent.append(message)
        return FeishuDelivery(delivered=True, message_id=f"mock-{len(self.sent)}")

    def send_file(self, receiver: str, file_path: str, file_name: str | None = None) -> FeishuDelivery:
        if not self._available:
            return FeishuDelivery(delivered=False, diagnostics=["mock adapter marked unavailable"])
        self.sent_files.append((file_path, file_name or file_path.rsplit("/", 1)[-1]))
        return FeishuDelivery(delivered=True, message_id=f"mock-file-{len(self.sent_files)}")

    def notify_run(self, result: ResearchResult) -> FeishuDelivery:
        text = (
            f"[研究任务] {result.task_id} run={result.run_id} "
            f"status={result.status.value} evidence={result.evidence_count}"
        )
        return self.send(
            FeishuMessage(
                receiver="mock-room",
                text=text,
                run_id=result.run_id,
                task_id=result.task_id,
                status=str(result.status),
            )
        )
