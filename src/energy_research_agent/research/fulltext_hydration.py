"""Shared search-result hydration for every research entry point.

AnySearch search responses contain discovery snippets.  They are useful for
finding URLs but are not evidence.  This module is the single bridge used by
the local portal, the adaptive runner and "continue deep research": it opens
the target URL, keeps only material page text, and restores the originating
enterprise/Goal-Family context on the hydrated envelope.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

from energy_research_agent.adapters.base import (
    SearchAdapter,
    SearchRequest,
    SearchResultEnvelope,
)


NON_BROWSER_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
)
SEARCH_RESULT_HOSTS = {
    "bing.com", "www.bing.com", "google.com", "www.google.com",
    "baidu.com", "www.baidu.com", "so.com", "www.so.com",
}

POLICY_RELEVANCE_TERMS = (
    "充电", "新能源汽车", "电动汽车", "充换电",
    "charging infrastructure", "electric vehicle", "ev charging",
)


def _normalized(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def discovery_hit_is_relevant(envelope: SearchResultEnvelope, hit: object) -> bool:
    """Gate discovery leads before spending a full-text/LLM call.

    Target-enterprise and ecosystem routes must mention the canonical company
    in the search result. Policy-authority originals may not name the company,
    so that lane also accepts explicit charging/EV-infrastructure terminology.

    Real-world search snippets rarely repeat the canonical company name even
    for company-anchored queries, so a substantive snippet from a real page
    (not a search-results page) is also accepted for company lanes — the
    evidence validators, not this funnel gate, decide whether the fetched
    page becomes a verified source.
    """
    haystack = " ".join(filter(None, [
        str(getattr(hit, "title", "") or ""),
        str(getattr(hit, "text", "") or ""),
        str(getattr(hit, "final_url", "") or ""),
    ]))
    normalized_haystack = _normalized(haystack)
    company_names = {
        _normalized(value) for value in [
            envelope.canonical_company_name,
            *envelope.canonical_company_aliases,
        ] if _normalized(value)
    }
    if any(company in normalized_haystack for company in company_names):
        return True
    if envelope.evidence_lane == "policy_context":
        return any(_normalized(term) in normalized_haystack for term in POLICY_RELEVANCE_TERMS)
    if not company_names:
        return True
    return len(normalized_haystack) >= 12


@dataclass
class HydrationOutcome:
    envelopes: list[SearchResultEnvelope]
    attempted_urls: int = 0
    hydrated_urls: int = 0
    failures: list[str] = field(default_factory=list)


def is_search_result_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(str(url))
    host = parsed.netloc.casefold().split(":", 1)[0]
    if host not in SEARCH_RESULT_HOSTS:
        return False
    path = parsed.path.rstrip("/").casefold()
    return path in {"", "/search", "/s"} or "search" in path


def is_material_envelope(envelope: SearchResultEnvelope) -> bool:
    """True only when an envelope contains a real target-page body."""
    return any(
        hit.text
        and bool(hit.final_url)
        and str(hit.final_url).casefold().startswith(("http://", "https://"))
        and not hit.metadata.get("snippet")
        and not is_search_result_url(hit.final_url)
        for hit in envelope.hits
    )


def hydrate_target_pages(
    envelopes: list[SearchResultEnvelope],
    adapters: dict[str, SearchAdapter],
    *,
    pages_per_query: int = 3,
    workers: int = 6,
    minimum_text_chars: int = 20,
) -> HydrationOutcome:
    """Append full target-page envelopes for all AnySearch discovery hits.

    The page limit is applied independently to every query.  Identical URLs
    are fetched once, then rebound to each originating goal.  When the fast
    AnySearch extractor cannot obtain material text, an available Kimi bridge
    may open the real URL as a browser fallback (never a search-results page).
    """
    anysearch = adapters.get("anysearch")
    if anysearch is None:
        return HydrationOutcome(envelopes=list(envelopes))
    browser = adapters.get("kimi_webbridge")
    limit = max(1, int(pages_per_query))
    tasks_by_url: dict[str, list[tuple[SearchResultEnvelope, object]]] = {}
    for envelope in envelopes:
        if envelope.adapter != "anysearch" or envelope.status in {"blocked", "error"}:
            continue
        candidates = [
            hit for hit in envelope.hits
            if hit.final_url and hit.metadata.get("snippet")
            and not is_search_result_url(hit.final_url)
        ]
        selected = [
            hit for hit in candidates
            if discovery_hit_is_relevant(envelope, hit)
        ][:limit]
        for hit in selected:
            url = str(hit.final_url).split("#", 1)[0]
            tasks_by_url.setdefault(url, []).append((envelope, hit))

    if not tasks_by_url:
        return HydrationOutcome(envelopes=list(envelopes))

    def request_page(adapter: SearchAdapter, url: str, *, browser_mode: bool = False):
        return adapter.search(SearchRequest(
            query_id="FULLTEXT",
            query=url,
            entity_id="PENDING-ENTITY",
            purpose="enterprise research target-page hydration",
            max_results=1,
            requires_browser=browser_mode,
            metadata={"url": url, "extract": True},
        ))

    def material(envelope: SearchResultEnvelope | None):
        if envelope is None or envelope.status in {"blocked", "error"}:
            return []
        return [
            hit for hit in envelope.hits
            if hit.text and len(str(hit.text).strip()) >= minimum_text_chars
            and not is_search_result_url(hit.final_url)
        ]

    def fetch(url: str):
        primary = request_page(anysearch, url)
        if material(primary):
            return primary
        plain_path = urlparse(url).path.casefold()
        if browser is not None and not plain_path.endswith(NON_BROWSER_SUFFIXES):
            fallback = request_page(browser, url, browser_mode=True)
            if material(fallback):
                return fallback
            diagnostics = [*primary.diagnostics, *fallback.diagnostics]
            return fallback.model_copy(update={"diagnostics": diagnostics})
        return primary

    fetched: dict[str, SearchResultEnvelope] = {}
    with ThreadPoolExecutor(max_workers=min(max(1, workers), len(tasks_by_url))) as pool:
        futures = {pool.submit(fetch, url): url for url in tasks_by_url}
        for future in as_completed(futures):
            url = futures[future]
            try:
                fetched[url] = future.result()
            except Exception as exc:  # noqa: BLE001 - one URL must not sink a round
                fetched[url] = SearchResultEnvelope(
                    adapter="anysearch", query_id="FULLTEXT", status="error",
                    diagnostics=[f"target-page hydration failed: {type(exc).__name__}: {exc}"],
                )

    hydrated: list[SearchResultEnvelope] = []
    failures: list[str] = []
    hydrated_urls = 0
    for url, origins in tasks_by_url.items():
        full = fetched.get(url)
        hits = material(full)
        if not hits:
            diagnostic = "; ".join((full.diagnostics if full is not None else [])[:2])
            failures.append(f"{url}: {diagnostic or 'no material target-page text'}")
            continue
        hydrated_urls += 1
        for envelope, discovery_hit in origins:
            full_hit = hits[0]
            hydrated.append(SearchResultEnvelope(
                adapter=full.adapter if full is not None else "anysearch",
                query_id=envelope.query_id,
                status="ok",
                hits=[full_hit.model_copy(update={
                    "requested_url": full_hit.requested_url or url,
                    "final_url": full_hit.final_url or url,
                    "title": full_hit.title or discovery_hit.title,
                    "metadata": {
                        **full_hit.metadata,
                        "snippet": False,
                        "target_page": True,
                        "hydrated_from": url,
                    },
                })],
                diagnostics=list(full.diagnostics if full is not None else []),
                topic=envelope.topic,
                purpose=envelope.purpose,
                collection_round=envelope.collection_round,
                round_goal=envelope.round_goal,
                trigger=envelope.trigger,
                target_gap_ids=list(envelope.target_gap_ids),
                target_conflict_ids=list(envelope.target_conflict_ids),
                target_claim_ids=list(envelope.target_claim_ids),
                canonical_company_name=envelope.canonical_company_name,
                canonical_company_aliases=list(envelope.canonical_company_aliases),
                expected_fields=list(envelope.expected_fields),
                goal_domain=envelope.goal_domain,
                subject_role=envelope.subject_role,
                evidence_lane=envelope.evidence_lane,
                evidence_use=envelope.evidence_use,
                requirement_text=envelope.requirement_text,
            ))
    return HydrationOutcome(
        envelopes=[*envelopes, *hydrated],
        attempted_urls=len(tasks_by_url),
        hydrated_urls=hydrated_urls,
        failures=failures,
    )
