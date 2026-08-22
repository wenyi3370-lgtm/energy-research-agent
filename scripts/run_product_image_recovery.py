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

from enterprise_energy_research.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter
from enterprise_energy_research.domain.enums import EnterpriseComplexity, RunStatus, VerificationStatus
from enterprise_energy_research.domain.models import RunManifest
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
from enterprise_energy_research.research.image_discovery import (
    ImageEvidenceBuilder,
    KimiImageDiscovery,
    KimiUsageTelemetry,
)
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.ingestor import EvidenceIngestor
from enterprise_energy_research.research.normalizer import NormalizedEvidence
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner, MergeEvidence
from enterprise_energy_research.research.product_detector import ProductDetector

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
    for source in evidence.sources:
        if "official" in (source.grading_reason or "").lower() and source.source_domain:
            official_domains.add(source.source_domain.lower().removeprefix("www."))

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
                "product_ids": set(),
            })
            entry["product_ids"].add(product.product_id)

    # Official catalog landing pages (SPA navigation on catl.com): these are
    # the pages that actually render product photos.  Register a source for
    # each when it is not already in evidence.
    catalog_pages = (
        ("https://www.catl.com/ess/", "储能系统"),
        ("https://www.catl.com/solution/passengerEV/", "乘用车解决方案"),
        ("https://www.catl.com/solution/commercialEV/", "商业应用解决方案"),
        ("https://www.catl.com/solution/recycling/", "循环回收"),
    )
    for url, title in catalog_pages:
        existing = next((source_id for source_id, source in source_by_id.items() if str(source.canonical_url) == url), None)
        if existing is not None:
            source_id = existing
        else:
            from enterprise_energy_research.domain.ids import new_sortable_id
            from enterprise_energy_research.domain.models import Source
            from enterprise_energy_research.domain.enums import SourceLevel
            source_id = new_sortable_id("source")
            evidence.sources.append(Source(
                source_id=source_id, canonical_url=url,  # type: ignore[arg-type]
                source_title=title, source_domain="catl.com", publisher="宁德时代官网",
                source_level=SourceLevel.SOURCE_A, content_type="text/html",
                grading_reason="official product catalog page",
            ))
            source_by_id[source_id] = evidence.sources[-1]
        if url not in pages:
            pages[url] = {
                "url": url, "kind": "product", "source_kind": "official_company",
                "publisher": "宁德时代官网", "source_id": source_id, "product_ids": set(),
            }
    page_list = sorted(pages.values(), key=lambda entry: -len(entry["product_ids"]))[: args.max_pages]
    if not page_list:
        print("[recovery] no navigable official product pages found")
        return 2
    print(f"[recovery] {len(page_list)} official product pages for discovery")

    discovery_pages = [
        {
            "url": entry["url"], "kind": "product", "source_kind": entry["source_kind"],
            "publisher": entry["publisher"],
            "product_key": next(iter(entry["product_ids"]), None),
        }
        for entry in page_list
    ]
    candidates = KimiImageDiscovery(kimi, telemetry).discover(discovery_pages)
    print(f"[recovery] discovery: {len(candidates)} candidates, status={telemetry.image_discovery_status}")
    if not candidates:
        print(f"[recovery] reason: {telemetry.reason}")
        return 2

    builder = ImageEvidenceBuilder(fetcher)
    known = {product.name: product.product_id for product in evidence.products if product.name}
    category_map: dict[str, str] = {
        (product.category or "").lower(): product.product_id for product in evidence.products if product.category
    }
    application_map: dict[str, str] = {}
    for product in evidence.products:
        for application in product.applications:
            application_map.setdefault(str(application).strip().lower(), product.product_id)
    canonical_entity_id = run_manifest.canonical_entity_id or (evidence.entities[0].entity_id if evidence.entities else None)
    new_images = []
    for candidate in candidates:
        page = pages.get(candidate.page_url)
        if page is None:
            continue
        product_id = candidate.product_key
        context = " ".join(filter(None, (candidate.alt or "", candidate.surrounding_text or "", candidate.page_title or "")))
        lowered = context.lower()
        # Binding priority: (1) explicit product name mention in the image
        # context, (2) page's own product ids, (3) application mention,
        # (4) category/family mention in the page title.
        matched = next(
            (product_id for name, product_id in known.items() if name and name in context),
            None,
        )
        if matched is not None:
            product_id = matched
        elif product_id is None and page["product_ids"]:
            product_id = next(iter(sorted(page["product_ids"])))
        if product_id is None:
            product_id = next(
                (product_id for application, product_id in application_map.items() if application and application in lowered),
                None,
            )
        if product_id is None:
            product_id = next(
                (product_id for category, product_id in category_map.items() if category and category in lowered),
                None,
            )
        image = builder.build(
            candidate, source_id=page["source_id"], entity_id=canonical_entity_id,
            product_id=product_id,
        )
        if image is None:
            telemetry.image_download_failures += 1
            continue
        new_images.append(image)

    telemetry.image_candidates_verified = len(new_images)
    print(f"[recovery] built {len(new_images)} image evidence records")

    validator = ImageValidator()
    new_images = validator.validate(new_images, evidence.entities, evidence.sources)
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
    round_evidence.images = new_images
    MergeEvidence.merge(runner.cumulative, round_evidence)
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

    from enterprise_energy_research.research.content_contract import CoreResearchReadinessGate
    readiness = CoreResearchReadinessGate().assess(
        entities=runner.cumulative.entities, claims=runner.cumulative.claims,
        edges=runner.cumulative.edges, factories=runner.cumulative.factories,
        products=runner.cumulative.products,
        is_large_enterprise=True, minimum_substantive_claims=20,
    )
    print("[recovery] readiness:", readiness["status"])
    (args.output / "02_research_quality").mkdir(parents=True, exist_ok=True)
    telemetry_path = args.output / "02_research_quality" / "image_recovery_telemetry.json"
    telemetry_path.write_text(json.dumps(telemetry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if readiness["status"] == "PASS":
        freeze_id = runner._freeze_and_publish(fix_store, run_id, args.output)
        print("[recovery] freeze:", freeze_id)
        return 0 if freeze_id else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
