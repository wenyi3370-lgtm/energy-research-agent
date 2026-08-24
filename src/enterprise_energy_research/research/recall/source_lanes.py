from __future__ import annotations

from pathlib import Path

from enterprise_energy_research.settings import load_yaml

from .models import QueryPriority, RecallQuerySpec, SearchPass, SourceLane


DEFAULT_ROSTER = Path(__file__).resolve().parents[4] / "config" / "intelligence_source_roster.yaml"


class SourceRoster:
    """Configuration-backed, bounded authority/watch-source patrol."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_ROSTER
        payload = load_yaml(self.path) if self.path.is_file() else {}
        self.sources = list(payload.get("sources", []))
        self.max_listing_pages_per_source = min(
            3, max(1, int(payload.get("max_listing_pages_per_source", 2)))
        )
        self.max_articles_per_source = max(1, int(payload.get("max_articles_per_source", 3)))

    def query_specs(self, *, start_date: str, end_date: str) -> list[RecallQuerySpec]:
        specs: list[RecallQuerySpec] = []
        for index, source in enumerate(self.sources):
            domain = str(source.get("domain", "")).strip()
            entry = str(source.get("entry", "")).strip()
            if not domain or not entry:
                continue
            lane = SourceLane(str(source.get("lane", SourceLane.MEDIA_DISCOVERY.value)))
            priority = QueryPriority(str(source.get("priority", QueryPriority.P1.value)))
            specs.append(RecallQuerySpec(
                query_id=f"RQ-SP-{index:03d}", topic=str(source.get("category", "source_patrol")),
                query=f"site:{domain} {entry} after:{start_date} before:{end_date}",
                search_pass=SearchPass.SOURCE_PATROL, source_lane=lane,
                language="zh-CN", priority=priority, desired_results=2,
                query_variant="source_roster", seed_query=False,
            ))
        return specs
