from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from energy_research_agent.adapters.base import SearchResultEnvelope

from .models import (
    LaneCoverage, RecallProfile, RecallQuerySpec, RecallStatus,
    SearchCoverageMatrix, SourceLane, TopicCoverage,
)


class CoverageTracker:
    def __init__(self, profile: RecallProfile) -> None:
        self.profile = profile
        self._attempts: dict[tuple[str, SourceLane], int] = defaultdict(int)
        self._hits: dict[tuple[str, SourceLane], int] = defaultdict(int)
        self._domains: set[str] = set()
        self._domains_by_lane: dict[SourceLane, set[str]] = defaultdict(set)
        self._languages: dict[str, int] = defaultdict(int)

    def record(self, spec: RecallQuerySpec, envelope: SearchResultEnvelope) -> None:
        self._attempts[(spec.topic, spec.source_lane)] += 1
        self._languages[spec.language] += 1
        valid_hits = [hit for hit in envelope.hits if hit.final_url]
        self._hits[(spec.topic, spec.source_lane)] += len(valid_hits)
        for hit in valid_hits:
            domain = urlparse(hit.final_url or "").netloc.lower().split(":", 1)[0]
            if domain:
                self._domains.add(domain)
                self._domains_by_lane[spec.source_lane].add(domain)

    def matrix(self, *, status: RecallStatus = RecallStatus.PARTIAL_SOURCE_COVERAGE) -> SearchCoverageMatrix:
        topics: list[TopicCoverage] = []
        topic_names = sorted({topic for topic, _ in {*self._attempts, *self._hits}})
        for topic in topic_names:
            payload = {"topic": topic}
            for lane in SourceLane:
                payload[lane.value] = LaneCoverage(
                    attempted=self._attempts[(topic, lane)], hits=self._hits[(topic, lane)],
                )
            topics.append(TopicCoverage.model_validate(payload))
        return SearchCoverageMatrix(
            profile=self.profile, topics=topics,
            chinese_query_count=sum(value for key, value in self._languages.items() if key.lower().startswith("zh")),
            english_query_count=sum(value for key, value in self._languages.items() if key.lower().startswith("en")),
            unique_domain_count=len(self._domains),
            official_domain_count=len(self._domains_by_lane[SourceLane.CORPORATE_OFFICIAL]),
            government_domain_count=len(self._domains_by_lane[SourceLane.GOVERNMENT_REGULATORY]),
            media_domain_count=len(self._domains_by_lane[SourceLane.MEDIA_DISCOVERY]),
            tender_domain_count=len(self._domains_by_lane[SourceLane.TENDER_PROCUREMENT]),
            coverage_complete=False, status=status,
        )
