"""Deep-research retry core (P0 third round).

Shared engine for "继续深度研究": load an existing run's evidence,
execute TARGETED searches (coverage gaps + user requirement clauses),
recover missing product images from official pages, revalidate, and
return the merged evidence ready for a new freeze + publication.

Used by ``scripts/run_incremental_gap_fix.py``-style workflows AND by the
local portal's deep-research endpoint.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise_energy_research.adapters.base import SearchAdapter, SearchRequest
from enterprise_energy_research.domain.enums import EnterpriseComplexity, SourceLevel, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, ResearchPlan, ResearchQuery, Source
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.data_coverage import ResearchDataCoverageValidator
from enterprise_energy_research.research.entity_mapper import EntityMapper
from enterprise_energy_research.research.executor import SearchExecutor
from enterprise_energy_research.research.extractor import EvidenceExtractor
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
from enterprise_energy_research.research.image_discovery import (
    KimiImageDiscovery,
    KimiUsageTelemetry,
)
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.normalizer import EvidenceNormalizer, NormalizedEvidence
from enterprise_energy_research.research.planner import ResearchPlanner
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner, MergeEvidence
from enterprise_energy_research.research.product_detector import ProductDetector

NON_PAGE_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


def exact_product_key(product_ids: set[str]) -> str | None:
    """Return a page-level binding only for a provably single-product page."""
    return next(iter(product_ids)) if len(product_ids) == 1 else None


def load_evidence(store: EvidenceStore, run_id: str) -> NormalizedEvidence:
    evidence = NormalizedEvidence()
    kinds = {
        "entity": "entities", "factory": "factories", "edge": "edges",
        "source": "sources", "retrieval": "retrievals", "claim": "claims",
        "conflict": "conflicts", "gap": "gaps", "image": "images",
        "product": "products", "energy_profile": "energy_profiles", "solution": "solutions",
    }
    for kind, attr in kinds.items():
        setattr(evidence, attr, store.list(run_id, kind))
    return evidence


def find_evidence_store(run_id: str, search_roots: list[Path]) -> EvidenceStore | None:
    """Locate the newest evidence store that contains ``run_id``."""
    candidates: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        direct = root / run_id / "evidence.sqlite3"
        if direct.is_file():
            candidates.append(direct)
        candidates.extend(sorted(root.glob(f"*/{run_id}/evidence.sqlite3")))
        candidates.extend(sorted(root.glob("evidence_fixed*.sqlite3")))
    for path in candidates:
        try:
            store = EvidenceStore(path)
            with store.connect() as con:
                row = con.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is not None:
                return store
        except Exception:
            continue
    return None


def run_search_round(
    evidence: NormalizedEvidence,
    queries: list[ResearchQuery],
    adapters: dict[str, SearchAdapter],
    gateway: Any,
    *,
    fulltext_pages_per_query: int = 3,
) -> tuple[NormalizedEvidence, list[str]]:
    """Execute queries, extract and normalize; merge into ``evidence`` in place."""
    mini_plan = ResearchPlan(
        plan_id=new_sortable_id("PLAN"), run_id=new_sortable_id("RUN"),
        complexity=EnterpriseComplexity.GROUP_LARGE, queries=queries,
        budget={"max_queries": len(queries) + 1, "max_pages": 80},
        completion_contract=[query.topic for query in queries],
        canonical_company_name=(queries[0].canonical_company_name if queries else None),
    )
    envelopes = SearchExecutor(adapters).execute(mini_plan)
    diagnostics: list[str] = []
    # AnySearch fulltext extraction (fast HTTP) — same path as production.
    anysearch = adapters.get("anysearch")
    if anysearch is not None:
        tasks = [
            (envelope, hit) for envelope in envelopes
            if envelope.adapter == "anysearch"
            for hit in envelope.hits if hit.final_url and hit.metadata.get("snippet")
        ]
        workers = max(2, min(4, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(AdaptiveResearchRunner._extract_fulltext, anysearch, envelope, hit): (envelope, hit)
                for envelope, hit in tasks[: fulltext_pages_per_query * len(queries)]
            }
            from concurrent.futures import as_completed
            for future in as_completed(futures):
                try:
                    full = future.result()
                except Exception:  # noqa: BLE001
                    continue
                if full is None:
                    continue
                for full_hit in full.hits:
                    if not full_hit.text:
                        continue
                    envelopes.append(full.model_copy(update={
                        "hits": [full_hit.model_copy(update={"metadata": {**full_hit.metadata, "snippet": False}})],
                        "topic": full.topic, "purpose": full.purpose,
                        "collection_round": full.collection_round,
                        "canonical_company_name": full.canonical_company_name,
                        "expected_fields": full.expected_fields,
                    }))
    extractor = EvidenceExtractor(gateway)
    batches: list[ExtractedEvidenceBatch] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _, extracted, failures in pool.map(_extract_one, [(extractor, envelope) for envelope in envelopes]):
            batches.extend(extracted)
            diagnostics.extend(failures[:3])
    round_evidence = NormalizedEvidence()
    for single in batches:
        try:
            piece = EvidenceNormalizer().normalize([single])
        except ValueError:
            continue
        MergeEvidence.merge(round_evidence, piece)
    MergeEvidence.merge(evidence, round_evidence)
    return evidence, diagnostics


def _extract_one(pair):
    extractor, envelope = pair
    return envelope, extractor.extract(envelope), extractor.last_failures


def recover_product_images(
    evidence: NormalizedEvidence,
    kimi: Any,
    fetcher: Any,
    output_dir: Path,
    *,
    canonical_entity_id: str | None,
    max_pages: int = 20,
    catalog_pages: list[tuple[str, str]] | None = None,
) -> tuple[NormalizedEvidence, KimiUsageTelemetry]:
    """Official-domain product image discovery + verify + archive + bind.

    ``catalog_pages`` lets callers supply known official product-center URLs
    (e.g. CATL's /ess/ and /solution/ pages) when product source pages alone
    are not enough — they are only visited when their domain is official.
    """
    telemetry = KimiUsageTelemetry()
    official_domains: set[str] = set()
    for entity in evidence.entities:
        if entity.official_website and entity.official_website.host:
            official_domains.add(str(entity.official_website.host).lower().removeprefix("www."))
    for source in evidence.sources:
        if "official" in (source.grading_reason or "").lower() and source.source_domain:
            official_domains.add(source.source_domain.lower().removeprefix("www."))
    if not official_domains:
        telemetry.image_discovery_status = "BLOCKED"
        telemetry.reason = "no official domains derivable from evidence"
        return evidence, telemetry

    # Restore the entity website when extraction missed it (needed for the
    # official_domain signal in ImageValidator).
    canonical = next(
        (entity for entity in evidence.entities if entity.entity_id == canonical_entity_id),
        evidence.entities[0] if evidence.entities else None,
    )
    if canonical is not None and not canonical.official_website:
        from pydantic import HttpUrl
        patched = canonical.model_copy(update={"official_website": HttpUrl(f"https://{sorted(official_domains)[0]}/")})
        evidence.entities = [
            patched if entity.entity_id == canonical.entity_id else entity for entity in evidence.entities
        ]

    source_by_id = {source.source_id: source for source in evidence.sources}
    products = [product for product in evidence.products if product.verification_status == VerificationStatus.VERIFIED]
    pages: dict[str, dict] = {}
    for product in products:
        for source_id in product.source_ids:
            source = source_by_id.get(source_id)
            if source is None or not source.canonical_url:
                continue
            url = str(source.canonical_url)
            if not url.lower().startswith(("http://", "https://")):
                continue
            if url.lower().split("?")[0].endswith(NON_PAGE_SUFFIXES):
                continue
            host = url.split("/", 2)[2].split(":")[0].lower().removeprefix("www.")
            if host not in official_domains and not any(
                host == domain or host.endswith("." + domain) for domain in official_domains
            ):
                continue
            entry = pages.setdefault(url, {
                "url": url, "kind": "product", "source_kind": "official_company",
                "publisher": source.source_title, "source_id": source_id, "product_ids": set(),
            })
            entry["product_ids"].add(product.product_id)

    for url, title in (catalog_pages or []):
        host = url.split("/", 2)[2].split(":")[0].lower().removeprefix("www.")
        if not any(host == domain or host.endswith("." + domain) for domain in official_domains):
            continue
        existing = next((sid for sid, s in source_by_id.items() if str(s.canonical_url) == url), None)
        if existing is None:
            from enterprise_energy_research.domain.models import Source as _Source
            from enterprise_energy_research.domain.enums import SourceLevel as _SourceLevel
            existing = new_sortable_id("source")
            evidence.sources.append(_Source(
                source_id=existing, canonical_url=url,  # type: ignore[arg-type]
                source_title=title, source_domain=host, publisher="企业官网",
                source_level=_SourceLevel.SOURCE_A, content_type="text/html",
                grading_reason="official product catalog page",
            ))
            source_by_id[existing] = evidence.sources[-1]
        if url not in pages:
            pages[url] = {
                "url": url, "kind": "product", "source_kind": "official_company",
                "publisher": "企业官网", "source_id": existing, "product_ids": set(),
            }

    page_list = sorted(pages.values(), key=lambda entry: -len(entry["product_ids"]))[:max_pages]
    if not page_list:
        telemetry.image_discovery_status = "EMPTY"
        telemetry.reason = "no navigable official product pages found"
        return evidence, telemetry

    discovery_pages = [
        {
            "url": entry["url"], "kind": "product", "source_kind": entry["source_kind"],
            "publisher": entry["publisher"],
            # A shared catalog page is not evidence for one arbitrary product.
            # Only single-product pages may carry a page-level exact binding;
            # shared pages must bind from the image card's own DOM context.
            "product_key": exact_product_key(entry["product_ids"]),
        }
        for entry in page_list
    ]
    candidates = KimiImageDiscovery(kimi, telemetry).discover(discovery_pages)
    if not candidates:
        return evidence, telemetry

    # Reuse the production handoff instead of maintaining a second image
    # binding implementation.  This preserves URL de-duplication, bounded
    # concurrency, product diversity, exact product matching and canonical
    # entity ownership on every machine that installs the Skill.
    runner = AdaptiveResearchRunner(
        {}, fetcher=fetcher, enable_image_archiving=False,
        enable_publication=False,
    )
    runner.cumulative = evidence
    image_round = NormalizedEvidence()
    image_round.entities = list(evidence.entities)
    image_round.factories = list(evidence.factories)
    image_round.products = list(evidence.products)
    runner._pending_image_candidates = candidates
    runner._attach_discovered_images(
        image_round, telemetry, official_domains,
        canonical_entity_id=canonical_entity_id,
    )
    new_images = image_round.images
    new_sources = image_round.sources

    validator = ImageValidator()
    new_images = validator.validate(new_images, evidence.entities, [*evidence.sources, *new_sources])
    if new_images:
        archived = ImageAssetArchiver(fetcher=lambda url, referer: (fetcher(url, referer), None)).archive(new_images, output_dir)
        new_images = validator.visual_verify(archived.images, base_dir=output_dir)
    round_evidence = NormalizedEvidence()
    round_evidence.sources = new_sources
    round_evidence.images = new_images
    MergeEvidence.merge(evidence, round_evidence)
    evidence.products, _ = ProductDetector().detect(evidence.products, evidence.images, evidence.sources, evidence.claims)
    return evidence, telemetry


def coverage_audit(evidence: NormalizedEvidence, company: str) -> Any:
    return ResearchDataCoverageValidator().audit(
        entity_name=company,
        claims=evidence.claims,
        products=evidence.products,
        factories=evidence.factories,
        images=evidence.images,
        complexity=EnterpriseComplexity.GROUP_LARGE,
        has_stock_code=True,
    )


def deep_retry(
    evidence_store: EvidenceStore,
    output_dir: Path,
    *,
    requirements: str = "",
    company: str,
    adapters: dict[str, SearchAdapter],
    gateway: Any,
    fetcher: Any | None,
    include_images: bool = True,
    max_pages: int = 20,
    catalog_pages: list[tuple[str, str]] | None = None,
) -> dict:
    """One deep-research continuation round; returns a summary dict."""
    with evidence_store.connect() as con:
        row = con.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
    if row is None:
        return {"status": "failed", "reason": "no run in evidence store"}
    run_id = row[0]
    run_manifest = evidence_store.get_run(run_id)
    canonical_entity_id = run_manifest.canonical_entity_id

    evidence = load_evidence(evidence_store, run_id)
    if not company:
        canonical = next(
            (entity for entity in evidence.entities if entity.entity_id == canonical_entity_id),
            evidence.entities[0] if evidence.entities else None,
        )
        company = canonical.canonical_name if canonical is not None else company
    before_claims = len([c for c in evidence.claims if c.verification_status == VerificationStatus.VERIFIED])
    planner = ResearchPlanner()
    queries: list[ResearchQuery] = []
    if requirements.strip():
        queries.extend(planner.requirement_queries(company, requirements)[:6])
    audit = coverage_audit(evidence, company)
    retry_gaps = [gap for gap in audit.gaps if gap.searchable and gap.severity in {"high", "medium"}]
    queries.extend(planner.coverage_queries(company, retry_gaps)[:4])
    queries = queries[:8]

    diagnostics: list[str] = []
    if queries:
        try:
            evidence, diagnostics = run_search_round(evidence, queries, adapters, gateway)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(f"search round failed: {type(exc).__name__}: {str(exc)[:160]}")
    evidence.claims, evidence.conflicts = ClaimValidator().validate(evidence.claims, evidence.sources)
    evidence.entities, evidence.edges = EntityMapper().apply_evidence(evidence.entities, evidence.edges, evidence.claims)

    image_report: dict = {"status": "skipped"}
    if include_images and fetcher is not None:
        try:
            evidence, telemetry = recover_product_images(
                evidence, adapters.get("kimi_webbridge"), fetcher, output_dir,
                canonical_entity_id=canonical_entity_id, max_pages=max_pages,
                catalog_pages=catalog_pages,
            )
            image_report = {
                "status": telemetry.image_discovery_status,
                "candidates": telemetry.image_candidates_found,
                "visual_verified": sum(1 for image in evidence.images if image.visual_verified),
                "reason": telemetry.reason,
            }
        except Exception as exc:  # noqa: BLE001
            image_report = {"status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}

    after_claims = len([c for c in evidence.claims if c.verification_status == VerificationStatus.VERIFIED])
    result = {
        "status": "completed",
        "run_id": run_id,
        "company": company,
        "requirements": requirements,
        "queries": [{"topic": q.topic, "query": q.query} for q in queries],
        "verified_claims_before": before_claims,
        "verified_claims_after": after_claims,
        "coverage_gaps": [gap.gap_code for gap in audit.gaps],
        "image_report": image_report,
        "diagnostics": diagnostics,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    # Persist the merged evidence into a NEW fix store so the caller can
    # freeze + publish immutably.
    fix_path = output_dir / "evidence_fixed.sqlite3"
    counter = 1
    while fix_path.exists():
        counter += 1
        fix_path = output_dir / f"evidence_fixed{counter}.sqlite3"
    from enterprise_energy_research.domain.enums import RunStatus
    from enterprise_energy_research.domain.models import RunManifest
    from enterprise_energy_research.research.ingestor import EvidenceIngestor
    fix_store = EvidenceStore(fix_path)
    fix_store.create_run(RunManifest(
        run_id=run_id, request_id=run_manifest.request_id, status=RunStatus.RUNNING,
        config_hash=run_manifest.config_hash, code_version=run_manifest.code_version,
        model_gateway=run_manifest.model_gateway,
    ))
    EvidenceIngestor(fix_store).ingest(run_id, 1, evidence)
    manifest = fix_store.get_run(run_id)
    manifest.canonical_entity_id = canonical_entity_id
    manifest.complexity = run_manifest.complexity
    fix_store.replace_run_manifest(manifest)

    from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner
    runner = AdaptiveResearchRunner({}, store=fix_store, enable_publication=False)
    try:
        freeze_id, used = runner._freeze_and_publish(fix_store, run_id, output_dir)
        result["freeze_id"] = freeze_id
        result["published"] = freeze_id is not None
    except Exception as exc:  # noqa: BLE001
        result["published"] = False
        result["publish_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result
