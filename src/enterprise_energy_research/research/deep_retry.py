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
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
from enterprise_energy_research.research.fulltext_hydration import (
    hydrate_target_pages,
    is_material_envelope,
)
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
from enterprise_energy_research.research.image_discovery import (
    KimiImageDiscovery,
    KimiUsageTelemetry,
)
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.normalizer import EvidenceNormalizer, NormalizedEvidence
from enterprise_energy_research.research.planner import RECOVERY_STRATEGIES, ResearchPlanner
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner, MergeEvidence
from enterprise_energy_research.research.product_detector import ProductDetector
from enterprise_energy_research.research.requirement_routing import routing_manifest
from enterprise_energy_research.research.entity_scope import (
    allowed_publication_entity_ids,
    entity_name_matches,
    rebind_target_alias_entities,
)

NON_PAGE_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


def exact_product_key(product_ids: set[str]) -> str | None:
    """Return a page-level binding only for a provably single-product page."""
    return next(iter(product_ids)) if len(product_ids) == 1 else None


def revalidate_product_state(
    evidence: NormalizedEvidence,
    *,
    require_archived_images: bool = False,
):
    """Recompute text-evidence product status independently of image recovery.

    ``Product.verification_status`` is determined by product identity and its
    A/B-level textual sources.  Images decide only whether a visual product
    dashboard can be generated.  Keeping this as an unconditional post-merge
    step prevents an EMPTY/failed image pass from leaving newly sourced
    products stuck at a stale ``UNVERIFIED`` state.
    """
    evidence.products, detection = ProductDetector().detect(
        evidence.products,
        evidence.images,
        evidence.sources,
        evidence.claims,
        require_archived_images=require_archived_images,
    )
    return detection


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
        candidates.extend(root.rglob("evidence_fixed*.sqlite3"))
        candidates.extend(root.rglob("evidence.sqlite3"))
    unique = {path.resolve(): path for path in candidates}
    # A continuation must start from the latest immutable fix store, not the
    # original evidence.sqlite3.  mtime is authoritative across numbered and
    # unnumbered fixed stores; the path is only a deterministic tie-breaker.
    ordered = sorted(unique.values(), key=lambda path: (path.stat().st_mtime_ns, str(path)), reverse=True)
    for path in ordered:
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
) -> tuple[NormalizedEvidence, list[str], dict[str, Any]]:
    """Execute queries, extract and normalize; merge into ``evidence`` in place."""
    mini_plan = ResearchPlan(
        plan_id=new_sortable_id("PLAN"), run_id=new_sortable_id("RUN"),
        complexity=EnterpriseComplexity.GROUP_LARGE, queries=queries,
        budget={
            "max_queries": len(queries) + 1,
            # SearchExecutor accounts every discovery hit against max_pages;
            # hydration has its own pages_per_query limit below.  Budgeting
            # only the hydrated pages starved all late requirement/readiness
            # queries after the first few ten-hit searches.
            "max_pages": max(80, sum(query.max_results for query in queries)),
        },
        completion_contract=[query.topic for query in queries],
        canonical_company_name=(queries[0].canonical_company_name if queries else None),
    )
    envelopes = SearchExecutor(adapters).execute(mini_plan)
    active_envelopes = [
        envelope for envelope in envelopes
        if envelope.status not in {"blocked", "error"}
    ]
    active_topics = sorted({
        str(envelope.topic) for envelope in active_envelopes if envelope.topic
    })
    diagnostics: list[str] = []
    diagnostics.extend(
        f"query {envelope.query_id} {envelope.status}: " + "; ".join(envelope.diagnostics[:2])
        for envelope in envelopes
        if envelope.status in {"blocked", "error"}
    )
    hydration = hydrate_target_pages(
        envelopes, adapters,
        pages_per_query=fulltext_pages_per_query,
        workers=4,
    )
    envelopes = hydration.envelopes
    diagnostics.append(
        f"target-page hydration attempted={hydration.attempted_urls} "
        f"succeeded={hydration.hydrated_urls}"
    )
    diagnostics.extend(hydration.failures)
    batches: list[ExtractedEvidenceBatch] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        material = [envelope for envelope in envelopes if is_material_envelope(envelope)]
        # EvidenceExtractor keeps per-call failure state. Sharing one instance
        # across worker threads races that state and previously produced the
        # false outcome "hydrated pages > 0, extracted batches = 0". Give
        # every page its own extractor while retaining the shared model gateway.
        for _, extracted, failures in pool.map(
            _extract_one, [(gateway, envelope) for envelope in material]
        ):
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
    return evidence, diagnostics, {
        "query_count": len(queries),
        "envelope_count": len(envelopes),
        "active_query_count": len(active_envelopes),
        "blocked_query_count": len(envelopes) - len(active_envelopes),
        "queried_topics": sorted({query.topic for query in queries}),
        "active_topics": active_topics,
        "hydrated_pages": hydration.hydrated_urls,
        "material_envelopes": len(material),
        "extracted_batches": len(batches),
    }


def _extract_one(pair):
    gateway, envelope = pair
    extractor = EvidenceExtractor(gateway)
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
    revalidate_product_state(evidence)
    return evidence, telemetry


def coverage_audit(
    evidence: NormalizedEvidence,
    company: str,
    *,
    canonical_entity_id: str | None,
    complexity: EnterpriseComplexity | None,
) -> Any:
    from enterprise_energy_research.domain.models import DataFreeze, FrozenResearchBundle, RunManifest
    # Reuse the publication entity graph boundary: financial facts are only
    # the canonical enterprise's facts; products/factories may include verified
    # controlled group members.  Adjacent companies never satisfy coverage.
    pseudo = FrozenResearchBundle(
        freeze=DataFreeze(
            freeze_id="FREEZE-SCOPE-AUDIT", run_id="RUN-SCOPE-AUDIT",
            evidence_version=1, included_record_ids={}, record_hashes={},
            root_hash="0" * 64, validation_report_id="VAL-SCOPE-AUDIT",
        ),
        run_manifest=RunManifest(
            run_id="RUN-SCOPE-AUDIT", request_id="REQ-SCOPE-AUDIT",
            canonical_entity_id=canonical_entity_id, complexity=complexity,
            config_hash="scope-audit", code_version="scope-audit", model_gateway={},
        ),
        entities=evidence.entities, factories=evidence.factories, edges=evidence.edges,
        claims=evidence.claims, products=evidence.products, images=evidence.images,
    )
    allowed = allowed_publication_entity_ids(pseudo)
    claims = [claim for claim in evidence.claims if claim.entity_id == canonical_entity_id]
    products = [product for product in evidence.products if product.entity_id in allowed]
    factories = [factory for factory in evidence.factories if factory.operator_entity_id in allowed]
    return ResearchDataCoverageValidator().audit(
        entity_name=company,
        claims=claims,
        products=products,
        factories=factories,
        images=evidence.images,
        complexity=complexity,
        has_stock_code=any(claim.field_name == "stock_code" for claim in claims),
    )


def sanitize_referential_integrity(evidence: NormalizedEvidence) -> dict[str, int]:
    """Remove only records/references whose parent evidence no longer exists.

    Repeated immutable-store merges can deduplicate a source while an older
    product still names the discarded round-local source id. A verified
    product with zero surviving sources is removed instead of being silently
    published as sourced. The same deterministic boundary is applied to all
    record types checked by EvidenceStore.assert_referential_integrity.
    """
    before = {
        "claims": len(evidence.claims), "retrievals": len(evidence.retrievals),
        "products": len(evidence.products), "factories": len(evidence.factories),
        "images": len(evidence.images), "edges": len(evidence.edges),
        "conflicts": len(evidence.conflicts), "energy_profiles": len(evidence.energy_profiles),
    }
    entity_ids = {item.entity_id for item in evidence.entities}
    source_ids = {item.source_id for item in evidence.sources}
    evidence.claims = [
        item for item in evidence.claims
        if item.entity_id in entity_ids and item.source_id in source_ids
    ]
    claim_ids = {item.claim_id for item in evidence.claims}
    evidence.retrievals = [
        item for item in evidence.retrievals if item.source_id in source_ids
    ]
    evidence.factories = [
        item.model_copy(update={
            "supporting_claim_ids": [value for value in item.supporting_claim_ids if value in claim_ids]
        })
        for item in evidence.factories if item.operator_entity_id in entity_ids
    ]
    factory_ids = {item.factory_id for item in evidence.factories}
    products = []
    for item in evidence.products:
        valid_sources = list(dict.fromkeys(
            value for value in item.source_ids if value in source_ids
        ))
        if item.entity_id not in entity_ids or not valid_sources:
            continue
        parameters = [
            parameter.model_copy(update={
                "claim_ids": [value for value in parameter.claim_ids if value in claim_ids]
            })
            for parameter in item.parameters
        ]
        products.append(item.model_copy(update={
            "source_ids": valid_sources, "parameters": parameters,
        }))
    evidence.products = products
    product_ids = {item.product_id for item in evidence.products}
    evidence.images = [
        item for item in evidence.images
        if item.source_id in source_ids
        and (not item.entity_id or item.entity_id in entity_ids)
        and (not item.factory_id or item.factory_id in factory_ids)
        and (not item.product_id or item.product_id in product_ids)
    ]
    graph_ids = entity_ids | factory_ids | product_ids
    evidence.edges = [
        item for item in evidence.edges
        if item.from_id in graph_ids and item.to_id in graph_ids
    ]
    evidence.conflicts = [
        item.model_copy(update={
            "claim_ids": valid,
            "selected_claim_ids": [value for value in item.selected_claim_ids if value in valid],
        })
        for item in evidence.conflicts
        if len((valid := [value for value in item.claim_ids if value in claim_ids])) >= 2
    ]
    evidence.energy_profiles = [
        item.model_copy(update={
            "claim_ids": [value for value in item.claim_ids if value in claim_ids]
        })
        for item in evidence.energy_profiles
        if item.entity_id in entity_ids
        and (not item.factory_id or item.factory_id in factory_ids)
    ]
    evidence.entities = [
        item.model_copy(update={
            "supporting_claim_ids": [value for value in item.supporting_claim_ids if value in claim_ids]
        })
        for item in evidence.entities
    ]
    return {
        key: before[key] - len(getattr(evidence, key))
        for key in before
    }


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
    recovery_round: int = 1,
    scope_requirement: str | None = None,
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
    original_canonical = next(
        (entity for entity in evidence.entities if entity.entity_id == canonical_entity_id),
        evidence.entities[0] if evidence.entities else None,
    )
    canonical_name = original_canonical.canonical_name if original_canonical is not None else company
    if not company:
        canonical = next(
            (entity for entity in evidence.entities if entity.entity_id == canonical_entity_id),
            evidence.entities[0] if evidence.entities else None,
        )
        company = canonical.canonical_name if canonical is not None else company
    before_claims = len([c for c in evidence.claims if c.verification_status == VerificationStatus.VERIFIED])
    declared_requirement = requirements if scope_requirement is None else scope_requirement
    requirement_key = hashlib.sha256(
        " ".join((declared_requirement or "").split()).encode("utf-8")
    ).hexdigest()
    planner = ResearchPlanner()
    queries: list[ResearchQuery] = []
    if requirements.strip():
        queries.extend(planner.requirement_queries(
            company, requirements, recovery_round=recovery_round,
        ))
    audit_before = coverage_audit(
        evidence, company,
        canonical_entity_id=canonical_entity_id,
        complexity=run_manifest.complexity,
    )
    retry_gaps = [gap for gap in audit_before.gaps if gap.searchable and gap.severity in {"high", "medium"}]
    queries.extend(
        planner.coverage_queries(
            company, retry_gaps, retry_round=recovery_round,
        )[:8]
    )

    # Coverage gaps and formal-publication readiness are separate contracts.
    # The former can be green while the latter is still missing an entire
    # business/financial/factory/product category.  Every continuation round
    # therefore explicitly searches the categories that are not yet backed by
    # a VERIFIED target-enterprise claim.  These are internal repair queries:
    # requirement_text intentionally stays empty so their facts cannot appear
    # in an unrelated supplemental chapter.
    verified_target_fields = {
        claim.field_name for claim in evidence.claims
        if claim.entity_id == canonical_entity_id
        and claim.verification_status == VerificationStatus.VERIFIED
        and claim.value not in (None, "", [])
    }
    readiness_topics: list[str] = []
    if not verified_target_fields.intersection({"core_business", "business_segment"}):
        readiness_topics.append("company_identity")
    if not verified_target_fields.intersection({
        "revenue", "profit", "gross_profit", "total_assets",
        "total_liabilities", "employee_count", "investment",
    }):
        readiness_topics.extend(["financials", "employees"])
    if not verified_target_fields.intersection({
        "factory_name", "capacity", "process", "subsidiary_name",
    }):
        readiness_topics.extend(["factories", "capacity", "production_lines"])
    if not verified_target_fields.intersection({
        "product_family", "model", "parameter_name", "series",
    }):
        readiness_topics.extend(["products", "product_parameters"])

    official_host = ""
    if original_canonical is not None and original_canonical.official_website:
        official_host = (
            urlparse(str(original_canonical.official_website)).hostname or ""
        ).lower().removeprefix("www.")
    if official_host:
        source_by_id = {source.source_id: source for source in evidence.sources}
        identity_fields = {"canonical_company_name", "registered_name", "aliases", "former_names"}
        supported_by_official_source = any(
            claim.entity_id == canonical_entity_id
            and claim.verification_status == VerificationStatus.VERIFIED
            and claim.field_name in identity_fields
            and (
                (source_by_id.get(claim.source_id).source_domain or "")
                .lower().removeprefix("www.") == official_host
                if source_by_id.get(claim.source_id) is not None else False
            )
            for claim in evidence.claims
        )
        supported_by_website_claim = any(
            claim.entity_id == canonical_entity_id
            and claim.verification_status == VerificationStatus.VERIFIED
            and claim.field_name == "official_website"
            and (urlparse(str(claim.value)).hostname or "").lower().removeprefix("www.") == official_host
            for claim in evidence.claims
        )
        if not (supported_by_official_source or supported_by_website_claim):
            readiness_topics.insert(0, "company_identity")

    readiness_topics = list(dict.fromkeys(readiness_topics))
    if readiness_topics:
        readiness_plan = planner.build(
            run_id=run_id,
            entity_id=canonical_entity_id or "UNKNOWN",
            canonical_name=company,
            complexity=run_manifest.complexity or EnterpriseComplexity.GROUP_LARGE,
            budget={
                "max_queries": len(readiness_topics) * 3,
                "max_pages": max(60, len(readiness_topics) * 30),
                "max_results_per_query": 10,
            },
            only_topics=readiness_topics,
        )
        recovery_strategy = RECOVERY_STRATEGIES[
            (max(1, recovery_round) - 1) % len(RECOVERY_STRATEGIES)
        ]
        for query in readiness_plan.queries:
            query.query = f"{query.query} {recovery_strategy}".strip()
            if query.topic == "company_identity" and official_host:
                query.query = f"{query.query} site:{official_host}".strip()
            query.purpose = (
                f"formal publication readiness recovery round={recovery_round}; "
                f"category_topic={query.topic}; {query.purpose}"
            )
            query.requirement_text = None
        queries.extend(readiness_plan.queries)
    deduped: list[ResearchQuery] = []
    seen_queries: set[str] = set()
    for query in queries:
        key = " ".join(query.query.casefold().split())
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped.append(query)
    # Do not truncate late/new requirement families.  Every recognized or
    # open-ended supplemental route must retain its R1/R2/R3 queries; the
    # research plan's explicit page budget remains the bounded control.
    queries = deduped
    verified_target_names = list(dict.fromkeys(
        str(value).strip()
        for value in (
            [canonical_name]
            + ([original_canonical.registered_name] if original_canonical is not None else [])
            + (list(original_canonical.aliases) if original_canonical is not None else [])
            + (list(original_canonical.former_names) if original_canonical is not None else [])
        )
        if value and str(value).strip()
    ))
    for query in queries:
        query.canonical_company_aliases = verified_target_names

    diagnostics: list[str] = []
    round_metrics: dict[str, Any] = {
        "query_count": len(queries),
        "active_query_count": 0,
        "blocked_query_count": 0,
        "queried_topics": sorted({query.topic for query in queries}),
        "active_topics": [],
        "hydrated_pages": 0,
        "material_envelopes": 0,
        "extracted_batches": 0,
    }
    if queries:
        try:
            evidence, diagnostics, round_metrics = run_search_round(
                evidence, queries, adapters, gateway,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(f"search round failed: {type(exc).__name__}: {str(exc)[:160]}")
            round_metrics["execution_status"] = "failed"

    # Resolve the canonical website entry URL through the same auditable
    # AnySearch extractor. Corporate sites commonly redirect an old group
    # domain to a new global/brand domain. Keeping the stale entry URL on the
    # entity while storing the final page under another host makes an honest
    # identity source fail the host gate forever. We only update the website
    # after a material final page was extracted as the already-verified target
    # (canonical name or one of its verified aliases); requested and final URL
    # are both retained on the Retrieval record.
    official_url = (
        str(original_canonical.official_website)
        if original_canonical is not None and original_canonical.official_website
        else ""
    )
    anysearch = adapters.get("anysearch")
    if official_url and anysearch is not None:
        try:
            official_result = anysearch.search(SearchRequest(
                query_id=new_sortable_id("QRY-OFFICIAL-HOME"),
                query=official_url,
                entity_id=canonical_entity_id or "UNKNOWN",
                purpose="canonical official website redirect and identity verification",
                max_results=1,
                metadata={"url": official_url, "extract": True},
                topic="company_identity",
                collection_round="R1",
                round_goal="coverage",
                trigger="official_discovery",
                canonical_company_name=canonical_name,
                canonical_company_aliases=verified_target_names,
                expected_fields=list(
                    planner.build(
                        run_id=run_id,
                        entity_id=canonical_entity_id or "UNKNOWN",
                        canonical_name=canonical_name,
                        complexity=run_manifest.complexity or EnterpriseComplexity.GROUP_LARGE,
                        budget={"max_queries": 3, "max_pages": 3},
                        only_topics=["company_identity"],
                    ).queries[0].expected_fields
                ),
            ))
            official_result = official_result.model_copy(update={
                "topic": "company_identity",
                "purpose": "canonical official website redirect and identity verification",
                "collection_round": "R1",
                "round_goal": "coverage",
                "trigger": "official_discovery",
                "canonical_company_name": canonical_name,
                "canonical_company_aliases": verified_target_names,
                "expected_fields": [
                    "canonical_company_name", "registered_name", "aliases",
                    "official_website", "core_business", "business_segment",
                ],
            })
            material_hits = [
                hit for hit in official_result.hits
                if hit.final_url and hit.text and len(str(hit.text).strip()) >= 20
            ]
            official_batches = EvidenceExtractor(gateway).extract(official_result) if material_hits else []
            if official_batches:
                final_url = str(material_hits[0].final_url)
                official_domains = {
                    (urlparse(official_url).hostname or "").lower().removeprefix("www."),
                    (urlparse(final_url).hostname or "").lower().removeprefix("www."),
                } - {""}
                official_evidence = EvidenceNormalizer().normalize(
                    official_batches,
                    official_domains=official_domains,
                    query_ids=[official_result.query_id] * len(official_batches),
                )
                for retrieval in official_evidence.retrievals:
                    retrieval.requested_url = official_url
                    retrieval.final_url = final_url
                    retrieval.diagnostics = {
                        **retrieval.diagnostics,
                        "official_website_redirect_verified": official_url != final_url,
                    }
                MergeEvidence.merge(evidence, official_evidence)
                from pydantic import HttpUrl
                evidence.entities = [
                    entity.model_copy(update={"official_website": HttpUrl(final_url)})
                    if entity.entity_id == canonical_entity_id else entity
                    for entity in evidence.entities
                ]
                diagnostics.append(
                    f"official website resolved and extracted: {official_url} -> {final_url}"
                )
            else:
                diagnostics.append("official website resolution returned no target-bound material page")
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                f"official website resolution failed: {type(exc).__name__}: {str(exc)[:160]}"
            )
    round_metrics.setdefault(
        "execution_status",
        (
            "blocked" if round_metrics.get("active_query_count", 0) <= 0
            else "extraction_failed"
            if round_metrics.get("material_envelopes", 0) > 0
            and round_metrics.get("extracted_batches", 0) <= 0
            else "completed"
        ),
    )
    # Each continuation round normalizes pages independently, so the same
    # enterprise can arrive under fresh temporary entity IDs. Consolidate the
    # merged cross-round set and rebind every claim/product/factory/image/edge
    # before coverage and publication QA. Without this step, valid target
    # facts are incorrectly counted as out-of-scope and supplementation can
    # make the enterprise-specific ratio appear worse.
    EvidenceNormalizer._canonicalize(evidence)
    evidence = EvidenceNormalizer._consolidate_duplicate_entities(evidence)
    rebound_canonical = next(
        (entity for entity in evidence.entities if entity_name_matches(entity, canonical_name)),
        None,
    )
    if rebound_canonical is None:
        raise RuntimeError(
            f"supplemented evidence no longer maps to canonical enterprise: {canonical_name}"
        )
    canonical_entity_id = rebind_target_alias_entities(
        evidence, rebound_canonical.entity_id, canonical_name,
    )
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

    integrity_cleanup = sanitize_referential_integrity(evidence)
    removed_integrity_records = {
        key: value for key, value in integrity_cleanup.items() if value
    }
    if removed_integrity_records:
        diagnostics.append(
            "referential integrity cleanup removed dangling/unsourced records: "
            + json.dumps(removed_integrity_records, ensure_ascii=False, sort_keys=True)
        )

    # This must run even when image discovery returned EMPTY/BLOCKED/failed.
    # Product text evidence and product-image readiness are separate states:
    # reliable text evidence publishes a product record, while images control
    # only visual-card/dashboard eligibility and their own recovery gate.
    product_detection = revalidate_product_state(
        evidence,
        require_archived_images=include_images,
    )

    after_claims = len([c for c in evidence.claims if c.verification_status == VerificationStatus.VERIFIED])
    audit_after = coverage_audit(
        evidence, company,
        canonical_entity_id=canonical_entity_id,
        complexity=run_manifest.complexity,
    )
    result = {
        "status": "completed" if not audit_after.high_gaps else "research_data_blocked",
        "run_id": run_id,
        "company": company,
        "requirements": requirements,
        "recovery_round": recovery_round,
        "queries": [{
            "topic": q.topic,
            "query": q.query,
            "goal_domain": q.goal_domain,
            "subject_role": q.subject_role,
            "evidence_lane": q.evidence_lane,
            "evidence_use": q.evidence_use,
        } for q in queries],
        "verified_claims_before": before_claims,
        "verified_claims_after": after_claims,
        "coverage_gaps_before": [gap.gap_code for gap in audit_before.gaps],
        "coverage_gaps": [gap.gap_code for gap in audit_after.gaps],
        "high_coverage_gaps": [gap.gap_code for gap in audit_after.high_gaps],
        "product_integrity": {
            "product_records": len(evidence.products),
            "verified_products": product_detection.verified_product_count,
            "image_ready_products": product_detection.product_count,
            "dashboard_decision": product_detection.dashboard_decision.value,
        },
        "image_report": image_report,
        "diagnostics": diagnostics,
        "search_execution_status": round_metrics.get("execution_status"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if round_metrics.get("execution_status") == "blocked":
        result["status"] = "search_blocked"
    elif round_metrics.get("execution_status") == "extraction_failed":
        result["status"] = "extraction_blocked"
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
    declared_topics = [
        family for family, _focus in planner.requirement_intents(declared_requirement)
    ]
    previous_scope = run_manifest.research_scope or {}
    previous_history = list(previous_scope.get("supplemental_attempt_history") or [])
    if previous_scope.get("supplemental_requirement_key") != requirement_key:
        previous_history = []
    attempt_record = {
        "requirement_key": requirement_key,
        "round": recovery_round,
        "strategy": RECOVERY_STRATEGIES[
            (max(1, recovery_round) - 1) % len(RECOVERY_STRATEGIES)
        ],
        **round_metrics,
        "verified_claims_before": before_claims,
        "verified_claims_after": after_claims,
        "diagnostics": diagnostics[:50],
        "completed_at": result["completed_at"],
    }
    previous_history = [
        item for item in previous_history
        if not (
            item.get("requirement_key") == requirement_key
            and int(item.get("round") or 0) == recovery_round
        )
    ]
    previous_history.append(attempt_record)
    fix_store.create_run(RunManifest(
        run_id=run_id, request_id=run_manifest.request_id, status=RunStatus.RUNNING,
        config_hash=run_manifest.config_hash, code_version=run_manifest.code_version,
        model_gateway=run_manifest.model_gateway,
        client_profile=run_manifest.client_profile,
        client_profile_hash=run_manifest.client_profile_hash,
        research_scope={
            **run_manifest.research_scope,
            "mode": "full_enterprise_plus_supplements",
            "requirements": declared_requirement or run_manifest.research_scope.get("requirements", ""),
            "supplemental_requirement_key": requirement_key,
            "requirement_routes": (
                routing_manifest(declared_topics)
                if declared_topics else run_manifest.research_scope.get("requirement_routes", [])
            ),
            "supplemental_attempts": max(
                (
                    int(run_manifest.research_scope.get("supplemental_attempts") or 0)
                    if previous_scope.get("supplemental_requirement_key") == requirement_key
                    else 0
                ),
                recovery_round,
            ),
            "supplemental_attempt_history": previous_history,
        },
    ))
    EvidenceIngestor(fix_store).ingest(run_id, 1, evidence)
    manifest = fix_store.get_run(run_id)
    manifest.canonical_entity_id = canonical_entity_id
    manifest.complexity = run_manifest.complexity
    fix_store.replace_run_manifest(manifest)
    result["evidence_store"] = str(fix_path)

    from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner
    runner = AdaptiveResearchRunner({}, store=fix_store, enable_publication=False)
    try:
        freeze_id, used = runner._freeze_and_publish(fix_store, run_id, output_dir)
        result["freeze_id"] = freeze_id
        result["published"] = freeze_id is not None
    except Exception as exc:  # noqa: BLE001
        result["published"] = False
        result["publish_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        if result["status"] == "completed":
            result["status"] = "publication_blocked"
    return result
