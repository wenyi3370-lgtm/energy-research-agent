"""Real Feishu/Lark client over the open-platform API (Phase 7).

Uses ``requests`` (already a core dependency). Credentials come from the
environment: ``EER_FEISHU_APP_ID`` / ``EER_FEISHU_APP_SECRET`` and
``EER_FEISHU_DEFAULT_RECEIVER``. Without credentials the adapter is
unavailable (fail-closed); tokens are cached per session and never logged.
Message text is plain text; rich cards are a later iteration.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from ..contracts import ResearchResult
from .base import FeishuAdapter, FeishuDelivery, FeishuMessage

logger = logging.getLogger("enterprise_energy_research.automation.feishu")

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
FILE_UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/files"


def _receive_id_type(receiver: str) -> str:
    """Infer the receive_id type from the receiver format.

    - ``oc_...`` -> chat_id (group chat)
    - ``ou_...`` -> open_id (user)
    - anything else (contains @) -> email
    """
    if receiver.startswith("oc_"):
        return "chat_id"
    if receiver.startswith("ou_"):
        return "open_id"
    return "email"


def _feishu_file_type(file_name: str) -> str:
    """Map a filename to the Feishu upload ``file_type`` enum.

    Allowed values: mp4 / opus / wav / pdf / doc / xls / ppt / stream.
    Unknown extensions fall back to ``stream`` (generic file message).
    """
    suffix = Path(file_name).suffix.lower()
    mapping = {
        ".xlsx": "xls", ".xls": "xls",
        ".docx": "doc", ".doc": "doc",
        ".pdf": "pdf",
        ".pptx": "ppt", ".ppt": "ppt",
    }
    return mapping.get(suffix, "stream")


class LarkFeishuAdapter:
    """Production adapter; requires EER_FEISHU_APP_ID + EER_FEISHU_APP_SECRET."""

    name = "lark-feishu"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        default_receiver: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id or os.environ.get("EER_FEISHU_APP_ID")
        self.app_secret = app_secret or os.environ.get("EER_FEISHU_APP_SECRET")
        self.default_receiver = default_receiver or os.environ.get("EER_FEISHU_DEFAULT_RECEIVER")
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def available(self) -> bool:
        return bool(self.app_id and self.app_secret and self.default_receiver)

    def _tenant_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            TOKEN_URL,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"feishu token error: {payload.get('msg')}")
        self._token = payload["tenant_access_token"]
        self._token_expires_at = time.time() + int(payload.get("expire", 7200))
        return self._token

    def send(self, message: FeishuMessage) -> FeishuDelivery:
        if not self.available():
            return FeishuDelivery(
                delivered=False,
                diagnostics=["Feishu not configured: set EER_FEISHU_APP_ID/SECRET/DEFAULT_RECEIVER"],
            )
        receiver = message.receiver or self.default_receiver
        try:
            resp = requests.post(
                f"{MESSAGE_URL}?receive_id_type={_receive_id_type(receiver)}",
                headers={"Authorization": f"Bearer {self._tenant_access_token()}"},
                json={
                    "receive_id": receiver,
                    "msg_type": "text",
                    # json.dumps 保证任意文本（引号/换行/特殊字符）不破坏消息 JSON
                    "content": json.dumps({"text": message.text}, ensure_ascii=False),
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                return FeishuDelivery(delivered=False, diagnostics=[payload.get("msg", "unknown")])
            message_id = (payload.get("data") or {}).get("message_id")
            return FeishuDelivery(delivered=True, message_id=message_id)
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning("feishu send failed: %s", exc)
            return FeishuDelivery(delivered=False, diagnostics=[str(exc)])

    def send_file(
        self, receiver: str, file_path: str, file_name: str | None = None
    ) -> FeishuDelivery:
        """Upload a file and send it as a file message to the receiver.

        Requires the ``im:resource`` scope on the app (upload files).
        Fails closed: any upload/send failure is returned as diagnostics.
        """
        if not self.available():
            return FeishuDelivery(
                delivered=False,
                diagnostics=["Feishu not configured: set EER_FEISHU_APP_ID/SECRET/DEFAULT_RECEIVER"],
            )
        receiver = receiver or self.default_receiver
        import mimetypes

        path = file_path
        name = file_name or Path(file_path).name
        file_type = _feishu_file_type(name)
        try:
            token = self._tenant_access_token()
            with open(path, "rb") as handle:
                upload = requests.post(
                    FILE_UPLOAD_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    data={
                        "file_name": name,
                        "file_type": file_type,
                        "parent_type": "chat",
                        "parent_id": receiver,
                    },
                    files={"file": (name, handle, mimetypes.guess_type(name)[0] or "application/octet-stream")},
                    timeout=self.timeout * 3,
                )
            upload.raise_for_status()
            payload = upload.json()
            if payload.get("code") != 0:
                return FeishuDelivery(delivered=False, diagnostics=[f"upload: {payload.get('msg')}"])
            file_key = payload["data"]["file_key"]
            resp = requests.post(
                f"{MESSAGE_URL}?receive_id_type={_receive_id_type(receiver)}",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receiver,
                    "msg_type": "file",
                    "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            message_payload = resp.json()
            if message_payload.get("code") != 0:
                return FeishuDelivery(delivered=False, diagnostics=[f"send: {message_payload.get('msg')}"])
            return FeishuDelivery(
                delivered=True,
                message_id=(message_payload.get("data") or {}).get("message_id"),
            )
        except (requests.RequestException, RuntimeError, OSError) as exc:
            logger.warning("feishu send_file failed: %s", exc)
            return FeishuDelivery(delivered=False, diagnostics=[str(exc)])

    def notify_run(self, result: ResearchResult) -> FeishuDelivery:
        text = (
            f"[研究任务] {result.task_id} run={result.run_id} "
            f"status={result.status.value} evidence={result.evidence_count}"
        )
        return self.send(
            FeishuMessage(
                receiver="",
                text=text,
                run_id=result.run_id,
                task_id=result.task_id,
                status=str(result.status),
            )
        )
