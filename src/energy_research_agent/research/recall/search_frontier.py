from __future__ import annotations

import re

from .models import (
    FrontierEntry, FrontierPriority, FrontierStatus, QueryPriority,
    RecallProfile, RecallQuerySpec, RecallStatus, SearchPass, SourceLane,
)


class SearchFrontier:
    def __init__(self, profile: RecallProfile, *, max_entries: int | None = None) -> None:
        self.profile = profile
        self.max_entries = max_entries or (64 if profile == RecallProfile.DAILY_INTELLIGENCE else 200)
        self._entries: dict[str, FrontierEntry] = {}
        self._aliases: dict[str, str] = {}

    @property
    def entries(self) -> list[FrontierEntry]:
        return list(self._entries.values())

    def add(self, entries: list[FrontierEntry]) -> list[FrontierEntry]:
        added: list[FrontierEntry] = []
        for entry in entries:
            if len(self._entries) >= self.max_entries:
                break
            keys = {self._canonical(entry.canonical_name), *(self._canonical(alias) for alias in entry.aliases)}
            existing_id = next((self._aliases[key] for key in keys if key in self._aliases), None)
            if existing_id:
                current = self._entries[existing_id]
                merged_aliases = list(dict.fromkeys([*current.aliases, entry.canonical_name, *entry.aliases]))
                self._entries[existing_id] = current.model_copy(update={"aliases": merged_aliases})
                continue
            self._entries[entry.frontier_id] = entry
            for key in keys:
                self._aliases[key] = entry.frontier_id
            added.append(entry)
        return added

    def followup_specs(self, *, max_queries: int = 8) -> list[RecallQuerySpec]:
        specs: list[RecallQuerySpec] = []
        eligible = sorted(
            (entry for entry in self.entries if self._can_expand(entry)),
            key=lambda item: ({FrontierPriority.P0: 0, FrontierPriority.P1: 1}.get(item.priority, 9), item.frontier_id),
        )
        for index, entry in enumerate(eligible[:max_queries]):
            lane, suffix = self._lane_and_suffix(entry)
            search_pass = (
                SearchPass.FRONTIER if self.profile == RecallProfile.DAILY_INTELLIGENCE
                else SearchPass.ENTERPRISE_FRONTIER
            )
            query = f'"{entry.canonical_name}" {suffix}'
            specs.append(RecallQuerySpec(
                query_id=f"RQ-F-{index:03d}", topic=entry.suggested_topics[0] if entry.suggested_topics else entry.entry_type,
                query=query, search_pass=search_pass, source_lane=lane,
                language="zh-CN", priority=QueryPriority(entry.priority.value),
                desired_results=3, parent_frontier_id=entry.frontier_id,
                query_variant="frontier_followup",
            ))
            self._entries[entry.frontier_id] = entry.model_copy(update={
                "generated_queries": [*entry.generated_queries, query],
                "status": FrontierStatus.QUEUED,
            })
        return specs

    def mark_searched(self, frontier_ids: list[str]) -> None:
        for frontier_id in frontier_ids:
            entry = self._entries.get(frontier_id)
            if entry is not None:
                self._entries[frontier_id] = entry.model_copy(update={"status": FrontierStatus.SEARCHED})

    def _can_expand(self, entry: FrontierEntry) -> bool:
        if not entry.expansion_allowed or entry.priority not in {FrontierPriority.P0, FrontierPriority.P1}:
            return False
        limit = 1 if self.profile == RecallProfile.DAILY_INTELLIGENCE else entry.max_expansion_depth
        return entry.expansion_depth < limit

    @staticmethod
    def _lane_and_suffix(entry: FrontierEntry) -> tuple[SourceLane, str]:
        return {
            "policy": (SourceLane.GOVERNMENT_REGULATORY, "官方 文件 原文 最新"),
            "tender": (SourceLane.TENDER_PROCUREMENT, "公告 中标 价格 官方"),
            "project": (SourceLane.GOVERNMENT_REGULATORY, "官方 规模 进度 参与方"),
            "subsidiary": (SourceLane.CORPORATE_OFFICIAL, "官网 产品 工厂 环评 产能"),
            "product_model": (SourceLane.TECHNICAL_DOCUMENT, "产品 参数 datasheet PDF"),
        }.get(entry.entry_type, (SourceLane.MEDIA_DISCOVERY, "官方 最新 进展"))

    @staticmethod
    def _canonical(value: str) -> str:
        return re.sub(r"[\s\-—_（）()·,，.。]+", "", value).casefold()


class RecallConvergenceTracker:
    """Profile-aware convergence; budget exhaustion can never be complete."""

    def __init__(self, profile: RecallProfile) -> None:
        self.profile = profile
        self.round_new_high: list[int] = []
        self.budget_exhausted = False
        self.source_unavailable = False

    def record_round(self, new_p0_p1: int) -> RecallStatus | None:
        self.round_new_high.append(max(0, new_p0_p1))
        return self.status()

    def status(self) -> RecallStatus | None:
        if self.source_unavailable:
            return RecallStatus.SOURCE_UNAVAILABLE
        if self.budget_exhausted:
            return RecallStatus.RECALL_BUDGET_EXHAUSTED
        if self.profile == RecallProfile.DAILY_INTELLIGENCE:
            if len(self.round_new_high) >= 2 and self.round_new_high[-1] == 0:
                return RecallStatus.RECALL_SATURATED
            return None
        if len(self.round_new_high) >= 3 and self.round_new_high[-2:] == [0, 0]:
            return RecallStatus.RECALL_SATURATED
        return None
