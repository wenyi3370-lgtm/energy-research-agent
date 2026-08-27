from __future__ import annotations

"""Product Image Recovery (P0 third round): discover/bind/verify product photos.

Runs ONLY the image pipeline for verified products that still lack photos.
Pages come from the products' OWN verified source pages (official catalog
URLs already in evidence) — no new searching, no unrelated pages:

  product source pages
    -> Kimi WebBridge DOM image discovery
    -> ImageEvidence build (hash / dimensions / MIME)
    -> technical validation + product binding
    -> local archiving + vision verification
    -> ProductDetector rebinding
    -> new evidence version + freeze + republish

Usage:
    PYTHONPATH=src python scripts/run_product_image_recovery.py \
        --evidence build/live_acceptance/<run>/evidence_fixed2.sqlite3 \
        --output build/live_acceptance/<run>
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path

from energy_research_agent.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter
from energy_research_agent.adapters.anysearch import AnySearchCliAdapter
from energy_research_agent.adapters.base import SearchRequest
from energy_research_agent.domain.enums import EnterpriseComplexity, RunStatus, VerificationStatus
from energy_research_agent.domain.models import RunManifest
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.research.image_archiver import ImageAssetArchiver
from energy_research_agent.research.image_discovery import (
    ImageEvidenceBuilder,
    KimiImageDiscovery,
    KimiUsageTelemetry,
)
from energy_research_agent.research.image_validator import ImageValidator
from energy_research_agent.research.ingestor import EvidenceIngestor
from energy_research_agent.research.normalizer import NormalizedEvidence
from energy_research_agent.research.production_runner import AdaptiveResearchRunner, MergeEvidence
from energy_research_agent.research.product_detector import ProductDetector

ROOT = Path(__file__).resolve().parents[1]

NON_PAGE_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


def load_existing(store: EvidenceStore, run_id: str) -> NormalizedEvidence:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session", default="enterprise-product-image-recovery")
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()

    store = EvidenceStore(args.evidence)
    con = store.connect()
    row = con.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
    con.close()
    if row is None:
        print("no run found in evidence store")
        return 1
    run_id = row[0]
    run_manifest = store.get_run(run_id)

    # Fresh fix store per recovery round (previous rounds are frozen).
    counter = 1
    fix_path = args.output / "evidence_fixed.sqlite3"
    while fix_path.exists():
        counter += 1
        fix_path = args.output / f"evidence_fixed{counter}.sqlite3"
    fix_store = EvidenceStore(fix_path)
    fix_store.create_run(RunManifest(
        run_id=run_id, request_id=run_manifest.request_id, status=RunStatus.RUNNING,
        config_hash=run_manifest.config_hash, code_version=run_manifest.code_version,
        model_gateway=run_manifest.model_gateway,
        client_profile=run_manifest.client_profile,
        client_profile_hash=run_manifest.client_profile_hash,
    ))

    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    archiver = ImageAssetArchiver()
    fetcher = lambda url, referer: archiver._fetch_direct(url, referer)[0]
    kimi = KimiWebBridgeSearchAdapter(session=args.session)
    telemetry = KimiUsageTelemetry()
    runner = AdaptiveResearchRunner(
        {"kimi_webbridge": kimi}, fetcher=fetcher, store=fix_store,
        enable_image_archiving=True, enable_publication=False,
    )
    runner.cumulative = load_existing(store, run_id)
    evidence = runner.cumulative

    # Official domains: entity websites + sources the resolver explicitly
    # graded as the company's own pages.
    official_domains: set[str] = set()
    for entity in evidence.entities:
        if entity.official_website and entity.official_website.host:
            official_domains.add(str(entity.official_website.host).lower().removeprefix("www."))
    # Source grading alone must never promote a third-party portal to an
    # official company domain.  A previous recovery treated an automotive
    # database as official because its grading note contained the word
    # "official", then attached unrelated exhibition photos to products.
    # Only entity-owned websites are authoritative here.
    # When extraction missed the entity website, restore it from the derived
    # official domain so the image validator can grant the official_domain
    # signal (which gates VERIFIED -> archiving -> vision verification).
    canonical_entity = next(
        (entity for entity in evidence.entities if entity.entity_id == run_manifest.canonical_entity_id),
        evidence.entities[0] if evidence.entities else None,
    )
    if canonical_entity is not None and not canonical_entity.official_website and official_domains:
        from pydantic import HttpUrl
        domain = sorted(official_domains)[0]
        patched = canonical_entity.model_copy(update={"official_website": HttpUrl(f"https://{domain}/")})
        evidence.entities = [
            patched if entity.entity_id == canonical_entity.entity_id else entity
            for entity in evidence.entities
        ]
        canonical_entity = patched

    def on_official_domain(domain: str) -> bool:
        host = (domain or "").lower().removeprefix("www.")
        return any(host == allowed or host.endswith("." + allowed) for allowed in official_domains)

    # Remove previously accumulated third-party image bindings when a frozen
    # recovery store is used as the next round's input.  Other evidence is
    # preserved; products whose selected image disappears are reset so the
    # detector can select a valid official replacement later in this run.
    evidence.images = [image for image in evidence.images if on_official_domain(image.source_domain)]
    valid_image_ids = {image.image_id for image in evidence.images}
    evidence.products = [
        product.model_copy(update={"image_id": None})
        if product.image_id and product.image_id not in valid_image_ids else product
        for product in evidence.products
    ]

    # Pages = verified product source pages on OFFICIAL domains only
    # (spec: official product pages first, search thumbnails never publish).
    source_by_id = {source.source_id: source for source in evidence.sources}
    products = [
        product for product in evidence.products
        if product.verification_status == VerificationStatus.VERIFIED
    ]
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
                "publisher": source.source_title, "source_id": source_id,
                "product_ids": set(), "specific": False,
            })
            entry["product_ids"].add(product.product_id)
            entry["specific"] = len(entry["product_ids"]) == 1

    # Catalog landing pages come from verified catalog-scope claims and
    # official sources already discovered in research. No company/domain
    # special cases are allowed in the portable recovery path.
    catalog_pages: list[tuple[str, str]] = []
    for claim in evidence.claims:
        if claim.verification_status != VerificationStatus.VERIFIED or claim.field_name != "product_catalog_scope":
            continue
        if not isinstance(claim.value, dict):
            continue
        for url in claim.value.get("official_product_centers") or []:
            if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                catalog_pages.append((url, "官方产品中心"))
    for source in evidence.sources:
        host = source.source_domain.lower().removeprefix("www.")
        url = str(source.canonical_url)
        if host in official_domains and any(token in url.lower() for token in ("/product", "/solution", "/catalog", "/products", "/ess/")):
            catalog_pages.append((url, source.source_title or "官方产品页面"))
    catalog_pages = list(dict.fromkeys(catalog_pages))
    for url, title in catalog_pages:
        existing = next((source_id for source_id, source in source_by_id.items() if str(source.canonical_url) == url), None)
        if existing is not None:
            source_id = existing
        else:
            from energy_research_agent.domain.ids import new_sortable_id
            from energy_research_agent.domain.models import Source
            from energy_research_agent.domain.enums import SourceLevel
            source_id = new_sortable_id("source")
            evidence.sources.append(Source(
                source_id=source_id, canonical_url=url,  # type: ignore[arg-type]
                source_title=title, source_domain=(url.split("/", 3)[2].lower().removeprefix("www.")),
                publisher=(canonical_entity.canonical_name if canonical_entity else "企业官网"),
                source_level=SourceLevel.SOURCE_A, content_type="text/html",
                grading_reason="official product catalog page",
            ))
            source_by_id[source_id] = evidence.sources[-1]
        if url not in pages:
            pages[url] = {
                "url": url, "kind": "product", "source_kind": "official_company",
                "publisher": (canonical_entity.canonical_name if canonical_entity else "企业官网"), "source_id": source_id,
                "product_ids": set(), "specific": False,
            }

    # Product records often originate from annual reports, whose source page
    # is not where the official product photo lives. Discover one page on any
    # configured official domain per sufficiently specific verified product.
    branded_products = [
        product for product in products
        if product.model or product.series or len(product.name.strip()) >= 4
    ]
    branded_products.sort(key=lambda product: (-len(product.name), product.name))
    def normalized_name(value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    anysearch = AnySearchCliAdapter()
    if anysearch.health().available:
        for product in branded_products[: min(12, args.max_pages)]:
            found = False
            # Search engines treat parenthesized multi-domain expressions
            # inconsistently. Query each configured official domain directly
            # and stop at the first exact official hit.
            for domain in sorted(official_domains)[:3]:
                envelope = anysearch.search(SearchRequest(
                    query_id=f"IMG-{product.product_id}-{domain}",
                    # Quote the canonical product name.  Without a phrase
                    # constraint the search backend can return a company
                    # profile that happens to contain only a few generic
                    # product tokens, while omitting the exact detail page.
                    # Do not append the full legal entity name here.  Search
                    # backends often treat it as another mandatory phrase;
                    # official product news pages commonly use only the
                    # consumer brand and then disappear from the result set.
                    query=f'site:{domain} "{product.name}"',
                    entity_id=canonical_entity.entity_id if canonical_entity else "PENDING-ENTITY",
                    purpose="official product image page discovery",
                    max_results=6,
                    topic="image_evidence",
                ))
                product_key = normalized_name(product.name)
                for hit in envelope.hits:
                    url = str(hit.final_url or "")
                    from urllib.parse import urlparse
                    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
                    if not any(host == allowed or host.endswith("." + allowed) for allowed in official_domains):
                        continue
                    if url.lower().split("?", 1)[0].endswith(NON_PAGE_SUFFIXES):
                        continue
                    parsed_url = urlparse(url)
                    path = parsed_url.path.rstrip("/").casefold()
                    if not path or path.endswith("/about/profile"):
                        continue
                    hit_context = normalized_name(f"{hit.title or ''} {hit.text or ''}")
                    # A site-restricted engine can still rank the corporate
                    # homepage above the named product. Page-level exact
                    # binding is granted only when the result itself names
                    # the product; otherwise keep searching.
                    if product_key not in hit_context:
                        continue
                    entry = pages.setdefault(url, {
                        "url": url, "kind": "product", "source_kind": "official_company",
                        "publisher": product.name, "source_id": None,
                        "product_ids": set(), "specific": True,
                    })
                    entry["product_ids"].add(product.product_id)
                    entry["specific"] = len(entry["product_ids"]) == 1
                    found = True
                    break
                if found:
                    break

    page_list = sorted(
        pages.values(),
        key=lambda entry: (not entry.get("specific", False), -len(entry["product_ids"]), entry["url"]),
    )[: args.max_pages]
    if not page_list:
        print("[recovery] no navigable official product pages found")
        return 2
    print(f"[recovery] {len(page_list)} official product pages for discovery")

    discovery_pages = [
        {
            "url": entry["url"], "kind": "product", "source_kind": entry["source_kind"],
            "publisher": entry["publisher"],
            # Page-level binding is exact only when this source belongs to one
            # and only one verified product.  Generic catalog pages must bind
            # from the image card's own title/context instead.
            "product_key": next(iter(entry["product_ids"])) if len(entry["product_ids"]) == 1 else None,
        }
        for entry in page_list
    ]
    candidates = KimiImageDiscovery(kimi, telemetry).discover(discovery_pages)
    print(f"[recovery] discovery: {len(candidates)} candidates, status={telemetry.image_discovery_status}")
    if not candidates:
        print(f"[recovery] reason: {telemetry.reason}")
        return 2

    # Reuse the production handoff: URL de-duplication, per-product diversity,
    # exact name/page binding, 48-candidate cap and six-way bounded downloads.
    image_round = NormalizedEvidence()
    # _attach_discovered_images uses the first entity as the binding owner;
    # keep the manifest's canonical company first, never an incidental entity
    # extracted from a supplier/customer page.
    image_round.entities = (
        [canonical_entity] + [entity for entity in evidence.entities if entity.entity_id != canonical_entity.entity_id]
        if canonical_entity is not None else list(evidence.entities)
    )
    image_round.factories = list(evidence.factories)
    image_round.products = list(evidence.products)
    runner._pending_image_candidates = candidates
    runner._attach_discovered_images(
        image_round, telemetry, official_domains,
        canonical_entity_id=canonical_entity.entity_id if canonical_entity is not None else None,
    )
    new_images = image_round.images
    new_sources = image_round.sources
    print(f"[recovery] built {len(new_images)} image evidence records")

    validator = ImageValidator()
    new_images = validator.validate(new_images, evidence.entities, [*evidence.sources, *new_sources])
    if not new_images:
        print("[recovery] all images failed technical validation")
        return 2
    # Archive into the RUN directory (production layout): the publication
    # resolver searches artifact parents + run dir for "assets/images/...".
    archived = ImageAssetArchiver(fetcher=lambda url, referer: (fetcher(url, referer), None)).archive(
        new_images, args.output,
    )
    new_images = validator.visual_verify(archived.images, base_dir=args.output)
    print(f"[recovery] archived={len(archived.archived_image_ids)}, failed={len(archived.failed_image_ids)}, visual_verified={sum(1 for image in new_images if image.visual_verified)}")

    round_evidence = NormalizedEvidence()
    round_evidence.sources = new_sources
    round_evidence.images = new_images
    MergeEvidence.merge(runner.cumulative, round_evidence)

    # Multi-product launch pages can contain several unrelated hero images.
    # Page text is too broad for exact binding; use the pixel-derived vision
    # description to rebind only when it explicitly names one verified,
    # sufficiently specific product.  Otherwise clear the page-level product
    # binding and keep the image as unbound evidence.
    shared_product_pages = {
        entry["url"] for entry in page_list if len(entry["product_ids"]) > 1
    }
    specific_products = [
        product for product in runner.cumulative.products
        if product.verification_status == VerificationStatus.VERIFIED
        and (product.model or product.series)
        and len(normalized_name(product.name)) >= 4
    ]
    repaired_images = []
    for image in runner.cumulative.images:
        if str(image.source_page_url) not in shared_product_pages:
            repaired_images.append(image)
            continue
        context = normalized_name(" ".join(filter(None, (
            image.visual_description, image.alt_text, image.source_title,
        ))))
        matches = [product for product in specific_products if normalized_name(product.name) in context]
        matches.sort(key=lambda product: len(normalized_name(product.name)), reverse=True)
        if matches:
            target = matches[0]
            repaired_images.append(image.model_copy(update={
                "product_id": target.product_id,
                "target_entity_id": target.product_id,
                "target_entity_type": "product",
            }))
        else:
            repaired_images.append(image.model_copy(update={
                "product_id": None, "target_entity_id": None,
            }))
    runner.cumulative.images = repaired_images
    runner.cumulative.products, _ = ProductDetector().detect(
        runner.cumulative.products, runner.cumulative.images, runner.cumulative.sources,
        runner.cumulative.claims,
    )
    bound = [product.product_id for product in runner.cumulative.products if product.image_id]
    print(f"[recovery] products with bound images: {len(bound)}")

    EvidenceIngestor(fix_store).ingest(run_id, 1, runner.cumulative)
    manifest = fix_store.get_run(run_id)
    manifest.canonical_entity_id = run_manifest.canonical_entity_id
    manifest.complexity = run_manifest.complexity
    fix_store.replace_run_manifest(manifest)

    from energy_research_agent.research.content_contract import CoreResearchReadinessGate
    readiness = CoreResearchReadinessGate().assess(
        entities=runner.cumulative.entities, claims=runner.cumulative.claims,
        edges=runner.cumulative.edges, factories=runner.cumulative.factories,
        products=runner.cumulative.products,
        is_large_enterprise=True, minimum_substantive_claims=20,
    )
    print("[recovery] readiness:", readiness["status"])
    from energy_research_agent.research.data_coverage import ResearchDataCoverageValidator
    coverage = ResearchDataCoverageValidator().audit(
        entity_name=(canonical_entity.canonical_name if canonical_entity else "目标企业"), claims=runner.cumulative.claims,
        products=runner.cumulative.products, factories=runner.cumulative.factories,
        images=runner.cumulative.images,
        complexity=run_manifest.complexity or EnterpriseComplexity.UNKNOWN,
        has_stock_code=any(
            claim.verification_status == VerificationStatus.VERIFIED and claim.field_name == "stock_code"
            for claim in runner.cumulative.claims
        ),
    )
    high_gaps = [gap.gap_code for gap in coverage.gaps if gap.severity == "high"]
    print("[recovery] high coverage gaps:", high_gaps)
    (args.output / "02_research_quality").mkdir(parents=True, exist_ok=True)
    telemetry_path = args.output / "02_research_quality" / "image_recovery_telemetry.json"
    telemetry_path.write_text(json.dumps(telemetry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "02_research_quality" / "image_recovery_coverage.json").write_text(
        json.dumps(coverage.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if readiness["status"] == "PASS" and not high_gaps:
        freeze_id, used_claim_ids = runner._freeze_and_publish(fix_store, run_id, args.output)
        print("[recovery] freeze:", freeze_id)
        if not freeze_id:
            return 2
        artifact_root = args.output / "artifacts"
        final_summary = {
            "run_id": run_id,
            "run_status": "COMPLETED",
            "network_mode": "direct" if not os.getenv("ERA_OUTBOUND_PROXY") else "proxy",
            "recovered_from": str(args.evidence),
            "evidence_store": str(fix_path),
            "freeze_id": freeze_id,
            "used_claim_count": len(used_claim_ids),
            "product_image_recovery": {
                "official_pages": len(page_list),
                "candidates": len(candidates),
                "built": len(new_images),
                "archived": len(archived.archived_image_ids),
                "visual_verified": sum(1 for image in new_images if image.visual_verified),
                "products_with_bound_images": len(bound),
            },
            "coverage": coverage.model_dump(mode="json"),
            "artifacts": {
                "word": str(artifact_root / "enterprise_research.docx"),
                "excel": str(artifact_root / "enterprise_research.xlsx"),
                "html": str(artifact_root / "enterprise_research_dashboard.html"),
                "word_qa": str(artifact_root / "enterprise_research_assets" / "publication_qa_report.json"),
                "html_qa": str(artifact_root / "enterprise_research_dashboard_assets" / "publication_qa_report.json"),
            },
        }
        (args.output / "acceptance_summary_final.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
