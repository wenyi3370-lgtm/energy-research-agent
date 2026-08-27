from __future__ import annotations

import hashlib
import re

from .models import FrontierEntry, FrontierPriority, RecallProfile


class EntityEventMiner:
    """Lightweight lead miner for hydrated pages.

    This is deliberately a discovery helper, not an evidence extractor.  Its
    output may generate a bounded follow-up query but can never become a Claim.
    """

    PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("subsidiary", re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()·-]{2,45}(?:股份有限公司|有限公司))")),
        ("project", re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()·-]{3,55}(?:试点项目|示范项目|项目|基地))")),
        ("policy", re.compile(r"(?:《([^》]{3,70})》|([\u4e00-\u9fffA-Za-z0-9（）()·-]{3,60}(?:办法|意见|通知|规定|政策)))")),
        ("tender", re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()·-]{3,60}(?:招标|中标|采购公告))")),
        ("product_model", re.compile(r"\b([A-Z][A-Z0-9-]{2,24})\b")),
    )

    def mine(
        self,
        text: str,
        *,
        run_id: str,
        origin_query_id: str,
        origin_url: str,
        profile: RecallProfile,
        discovery_round: int = 1,
        parent_frontier_id: str | None = None,
        expansion_depth: int = 0,
        max_entries: int = 12,
    ) -> list[FrontierEntry]:
        compact = re.sub(r"\s+", " ", text or "")[:50000]
        entries: list[FrontierEntry] = []
        seen: set[str] = set()
        for entry_type, pattern in self.PATTERNS:
            for match in pattern.finditer(compact):
                name = next((group for group in match.groups() if group), match.group(0)).strip(" ，。；：:（）()")
                name = self._clean_name(entry_type, name)
                canonical = self._canonical(name)
                if len(canonical) < 2 or canonical in seen or self._noise(name):
                    continue
                seen.add(canonical)
                priority = self._priority(entry_type, compact[max(0, match.start() - 80): match.end() + 80])
                max_depth = 1 if profile == RecallProfile.DAILY_INTELLIGENCE else 2
                allowed = priority in {FrontierPriority.P0, FrontierPriority.P1} and expansion_depth < max_depth
                entries.append(FrontierEntry(
                    frontier_id="FRONTIER-" + hashlib.sha1(f"{run_id}:{entry_type}:{canonical}".encode("utf-8")).hexdigest()[:16].upper(),
                    run_id=run_id, entry_type=entry_type, canonical_name=name,
                    aliases=[name], origin_query_id=origin_query_id, origin_url=origin_url,
                    parent_frontier_id=parent_frontier_id, discovery_round=discovery_round,
                    discovery_reason=f"hydrated page contained a named {entry_type}",
                    priority=priority, expansion_allowed=allowed,
                    expansion_depth=expansion_depth, max_expansion_depth=max_depth,
                    suggested_topics=self._topics(entry_type), confidence=0.75,
                    promote_reason="named high-value event/entity" if priority == FrontierPriority.P0 else "named material participant",
                ))
                if len(entries) >= max_entries:
                    return entries
        return entries

    @staticmethod
    def _canonical(value: str) -> str:
        return re.sub(r"[\s\-—_（）()·,，.。]+", "", value).casefold()

    @staticmethod
    def _noise(value: str) -> bool:
        upper = value.upper()
        return (
            value in {"有限公司", "股份有限公司", "项目", "示范项目", "基地"}
            or value.startswith(("本项目", "经营范围", "公司类型", "更名为"))
            or any(token in value for token in ("更名为股份有限公司", "经批准的项目"))
            or (re.fullmatch(r"[A-Z][A-Z0-9-]{2,24}", upper) is not None and not any(char.isdigit() for char in upper))
        )

    @staticmethod
    def _clean_name(entry_type: str, value: str) -> str:
        cleaned = value
        if entry_type == "subsidiary":
            for marker in ("子公司", "公司名称", "控股公司", "参股公司"):
                if marker in cleaned:
                    cleaned = cleaned.rsplit(marker, 1)[-1]
            if "-" in cleaned and cleaned.rsplit("-", 1)[-1].endswith(("有限公司", "股份有限公司")):
                cleaned = cleaned.rsplit("-", 1)[-1]
        return cleaned.strip(" -—，。；：:（）()")

    @staticmethod
    def _priority(entry_type: str, context: str) -> FrontierPriority:
        if entry_type in {"policy", "tender", "project"}:
            return FrontierPriority.P0
        if entry_type == "product_model" and any(token in context for token in ("发布", "新品", "参数")):
            return FrontierPriority.P0
        if entry_type in {"subsidiary", "product_model"}:
            return FrontierPriority.P1
        return FrontierPriority.P2

    @staticmethod
    def _topics(entry_type: str) -> list[str]:
        return {
            "subsidiary": ["subsidiaries", "factories", "products"],
            "project": ["project", "tender", "progress"],
            "policy": ["policy", "official_document"],
            "tender": ["tender", "award", "price"],
            "product_model": ["product", "technical_document"],
        }.get(entry_type, ["discovery"])
