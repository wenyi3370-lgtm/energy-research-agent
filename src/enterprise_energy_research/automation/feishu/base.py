"""Feishu adapter port (Phase 7).

The adapter boundary mirrors the search/artifact adapter pattern: the
automation service depends only on this protocol, so tests and offline
deployments use :class:`MockFeishuAdapter` while production uses the
Lark client. Fail-closed rule: without credentials the adapter reports
``available=False`` and sending is a no-op that is *surfaced*, never
silently dropped.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..contracts import ResearchResult


class FeishuMessage(BaseModel):
    receiver: str  # chat_id, open_id or email
    text: str
    run_id: str | None = None
    task_id: str | None = None
    status: str | None = None


class FeishuDelivery(BaseModel):
    delivered: bool
    message_id: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


@runtime_checkable
class FeishuAdapter(Protocol):
    """Port for sending run notifications into Feishu/Lark."""

    name: str

    def available(self) -> bool: ...

    def send(self, message: FeishuMessage) -> FeishuDelivery: ...

    def send_file(self, receiver: str, file_path: str, file_name: str | None = None) -> FeishuDelivery:
        """Upload a deliverable file (excel/word) into the chat (成果文件送达)."""
        ...

    def notify_run(self, result: ResearchResult) -> FeishuDelivery:
        """Convenience: build a status notification from a ResearchResult."""
        ...
