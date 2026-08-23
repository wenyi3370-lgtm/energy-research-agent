"""Deterministic removal of model/process boilerplate from publications.

The evidence store retains the original text.  This filter is applied only to
the publication DTO so a management dashboard can state the fact, implication
and action without repeatedly narrating how the research system works.
"""

from __future__ import annotations

import re
from typing import Any


HTML_ZERO_PHRASES: tuple[str, ...] = (
    "基于当前冻结公开事实",
    "证据边界",
    "本节判断由",
    "该信息用于判断",
    "不能替代",
    "不足以证明",
    "后续需要验证",
)


class PublicationBoilerplateFilter:
    """Clean publication strings while preserving their business meaning."""

    REPLACEMENTS: tuple[tuple[str, str], ...] = (
        ("基于当前冻结公开事实", "按已披露事实"),
        ("基于当前冻结的公开事实", "按已披露事实"),
        ("当前冻结的公开事实", "已披露事实"),
        ("证据边界", "适用范围"),
        ("本节判断由", "本节结论依据"),
        ("该信息用于判断", "该信息支持评估"),
        ("该信息用于", "该信息支持"),
        ("不能替代", "不等同于"),
        ("不足以证明", "尚未显示"),
        ("后续需要验证", "待核验"),
        ("后续评审应", "评审时应"),
        ("不用于制造确定性", "不作确定性承诺"),
        ("现有证据可归纳为", "已披露事实显示"),
        ("事实链尚未闭合", "关键事实仍有缺口"),
        ("So What：", ""),
    )

    def filter_text(self, value: str) -> str:
        text = value
        for source, replacement in self.REPLACEMENTS:
            text = text.replace(source, replacement)
        text = re.sub(r"\s+([，。；：！？])", r"\1", text)
        text = re.sub(r"([，；：]){2,}", r"\1", text)
        text = re.sub(r"。{2,}", "。", text)
        return text.strip(" ；，")

    def filter_value(self, value: Any) -> Any:
        """Recursively clean a JSON-compatible publication payload."""
        if isinstance(value, str):
            return self.filter_text(value)
        if isinstance(value, list):
            return [self.filter_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.filter_value(item) for item in value)
        if isinstance(value, dict):
            return {key: self.filter_value(item) for key, item in value.items()}
        return value

    @staticmethod
    def zero_phrase_counts(value: Any) -> dict[str, int]:
        text = str(value)
        return {phrase: text.count(phrase) for phrase in HTML_ZERO_PHRASES}
