from __future__ import annotations

from .models import (
    FrontierEntry, FrontierPriority, QueryPriority, RecallQuerySpec,
    SearchPass, SourceLane,
)


class AnomalyHunter:
    """Finite P0/P1 critical-gap expansion, never a general query generator."""

    def queries(
        self,
        entries: list[FrontierEntry],
        *,
        critical_gap: bool,
        max_queries: int = 3,
    ) -> list[RecallQuerySpec]:
        if not critical_gap:
            return []
        specs: list[RecallQuerySpec] = []
        for entry in entries:
            if entry.priority not in {FrontierPriority.P0, FrontierPriority.P1}:
                continue
            aliases = " ".join(entry.aliases[:3])
            query = (
                f'"{entry.canonical_name}" {aliases} 曾用名 子公司 文件编号 '
                "PDF 客户 供应商 合作伙伴 地方政府 披露"
            ).strip()
            specs.append(RecallQuerySpec(
                query_id=f"RQ-A-{len(specs):03d}", topic=entry.entry_type,
                query=query, search_pass=SearchPass.ANOMALY,
                source_lane=SourceLane.GOVERNMENT_REGULATORY,
                language="zh-CN", priority=QueryPriority(entry.priority.value),
                desired_results=2, parent_frontier_id=entry.frontier_id,
                query_variant="critical_gap_anomaly",
            ))
            if len(specs) >= max_queries:
                break
        return specs
