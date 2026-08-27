"""Feishu/Lark integration (Phase 7): adapter protocol, real client, mock, notifier."""

from .base import FeishuAdapter, FeishuMessage
from .mock import MockFeishuAdapter
from .notifier import FeishuNotifier

__all__ = ["FeishuAdapter", "FeishuMessage", "MockFeishuAdapter", "FeishuNotifier"]
