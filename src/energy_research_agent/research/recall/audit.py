from __future__ import annotations

import json
from pathlib import Path

from energy_research_agent.adapters.base import SearchResultEnvelope

from .coverage import CoverageTracker
from .models import (
    QueryRecallAudit, RecallFunnel, RecallProfile, RecallQuerySpec, RecallRunResult,
    RecallStatus, SourcePatrolAudit, UrlDispositionReason, UrlDispositionRecord,
)


class RecallAudit:
    def __init__(self, profile: RecallProfile, specs: list[RecallQuerySpec], *, total_budget: int) -> None:
        self.profile = profile
        self.specs = {spec.query_id: spec for spec in specs}
        self.deferred: list[RecallQuerySpec] = []
        self.query_audits: dict[str, QueryRecallAudit] = {
            spec.query_id: QueryRecallAudit(
                query_id=spec.query_id, topic=spec.topic,
                search_pass=spec.search_pass.value, source_lane=spec.source_lane.value,
                language=spec.language, priority=spec.priority.value,
                requested_results=spec.requested_results,
            ) for spec in specs
        }
        self.coverage = CoverageTracker(profile)
        self.dispositions: list[UrlDispositionRecord] = []
        self.frontier_entries = []
        self.source_patrol: dict[str, SourcePatrolAudit] = {
            spec.query_id: SourcePatrolAudit(source_id=spec.query_id)
            for spec in specs if spec.search_pass.value == "SOURCE_PATROL"
        }
        self.total_budget = total_budget
        self.funnel = RecallFunnel(
            seed_query_count=sum(
                1 for item in specs
                if item.seed_query and item.search_pass.value == "PRIMARY"
            ),
            expanded_query_count=sum(1 for item in specs if not item.seed_query and item.search_pass.value == "PRIMARY"),
            source_patrol_query_count=sum(1 for item in specs if item.search_pass.value == "SOURCE_PATROL"),
            total_query_count=len(specs), budget_used=sum(item.requested_results for item in specs),
            budget_remaining=max(0, total_budget - sum(item.requested_results for item in specs)),
        )

    def add_specs(self, specs: list[RecallQuerySpec]) -> None:
        for spec in specs:
            self.specs[spec.query_id] = spec
            self.query_audits[spec.query_id] = QueryRecallAudit(
                query_id=spec.query_id, topic=spec.topic,
                search_pass=spec.search_pass.value, source_lane=spec.source_lane.value,
                language=spec.language, priority=spec.priority.value,
                requested_results=spec.requested_results,
            )
        self.funnel.frontier_followup_query_count += sum(1 for item in specs if "FRONTIER" in item.search_pass.value)
        self.funnel.total_query_count += len(specs)
        self.funnel.budget_used += sum(item.requested_results for item in specs)
        self.funnel.budget_remaining = max(0, self.total_budget - self.funnel.budget_used)

    def record_envelope(self, envelope: SearchResultEnvelope) -> None:
        audit = self.query_audits.get(envelope.query_id)
        spec = self.specs.get(envelope.query_id)
        if audit is None or spec is None:
            return
        audit.returned_results += len(envelope.hits)
        self.funnel.search_hits += len(envelope.hits)
        self.coverage.record(spec, envelope)
        patrol = self.source_patrol.get(envelope.query_id)
        if patrol is not None:
            patrol.source_attempted = True
            patrol.article_links_discovered += sum(1 for hit in envelope.hits if hit.final_url)

    def disposition(self, query_id: str, url: str, reason: UrlDispositionReason, *, canonical_url: str = "", detail: str = "") -> None:
        self.dispositions.append(UrlDispositionRecord(
            query_id=query_id, url=url, reason=reason,
            canonical_url=canonical_url, detail=detail,
        ))
        audit = self.query_audits.get(query_id)
        if audit is None:
            return
        if reason == UrlDispositionReason.ACCEPTED:
            audit.unique_urls += 1
        else:
            audit.filtered_items += 1
            audit.filter_reasons[reason.value] = audit.filter_reasons.get(reason.value, 0) + 1
        if reason == UrlDispositionReason.DUPLICATE_URL:
            audit.duplicate_urls += 1
        elif reason == UrlDispositionReason.LISTING_ROOT:
            audit.listing_root_skipped += 1
        elif reason == UrlDispositionReason.SEARCH_RESULT_PAGE:
            audit.search_page_skipped += 1

    def hydration(self, query_id: str, *, success: bool) -> None:
        audit = self.query_audits.get(query_id)
        if audit is None:
            return
        audit.hydration_attempted += 1
        self.funnel.hydration_attempts += 1
        if success:
            audit.hydration_success += 1
            self.funnel.hydration_successes += 1
            patrol = self.source_patrol.get(query_id)
            if patrol is not None:
                patrol.article_pages_hydrated += 1
        else:
            audit.hydration_failed += 1

    def extraction(self, query_id: str, *, success: bool) -> None:
        audit = self.query_audits.get(query_id)
        if audit is None:
            return
        self.funnel.extraction_attempts += 1
        if success:
            audit.extracted_items += 1
            self.funnel.extraction_successes += 1

    def frontier(self, query_id: str, entries: list) -> None:
        self.frontier_entries.extend(entries)
        audit = self.query_audits.get(query_id)
        if audit is not None:
            audit.frontier_entries_discovered += len(entries)

    def finalize(self, status: RecallStatus, *, stop_reason: str, diagnostics: list[str] | None = None) -> RecallRunResult:
        accepted_urls = {item.canonical_url or item.url for item in self.dispositions if item.reason == UrlDispositionReason.ACCEPTED}
        self.funnel.unique_urls = len(accepted_urls)
        self.funnel.unique_domains = self.coverage.matrix(status=status).unique_domain_count
        self.funnel.candidate_items = self.funnel.extraction_successes
        self.funnel.stop_reason = stop_reason
        return RecallRunResult(
            profile=self.profile, status=status, query_specs=list(self.specs.values()),
            deferred_queries=self.deferred, frontier_entries=self.frontier_entries,
            url_dispositions=self.dispositions, query_audits=list(self.query_audits.values()),
            source_patrol=list(self.source_patrol.values()),
            coverage=self.coverage.matrix(status=status), funnel=self.funnel,
            diagnostics=diagnostics or [],
        )

    @staticmethod
    def write(result: RecallRunResult, directory: Path, stem: str) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        audit_path = directory / f"{stem}.json"
        coverage_path = directory / "search_coverage_matrix.json"
        audit_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        coverage_path.write_text(json.dumps(result.coverage.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return audit_path, coverage_path
