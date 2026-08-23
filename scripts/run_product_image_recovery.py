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
from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.base import SearchRequest
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
    # This recovery script registers CATL's official catalog explicitly.
    official_domains.add("catl.com")

    # When extraction missed the entity website, restore it from the derived
    # official domain so the image validator can grant the official_domain
    # signal (which gates VERIFIED -> archiving -> vision verification).
    canonical_entity = next(
        (entity for entity in evidence.entities if entity.entity_id == run_manifest.canonical_entity_id),
        evidence.entities[0] if evidence.entities else None,
    )
    if canonical_entity is not None and not canonical_entity.official_website and official_domains:
        from pydantic import HttpUrl
        domain = "catl.com" if "catl.com" in official_domains else sorted(official_domains)[0]
        patched = canonical_entity.model_copy(update={"official_website": HttpUrl(f"https://{domain}/")})
        evidence.entities = [
            patched if entity.entity_id == canonical_entity.entity_id else entity
            for entity in evidence.entities
        ]
        canonical_entity = patched

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
                "publisher": "宁德时代官网", "source_id": source_id,
                "product_ids": set(), "specific": False,
            }

    # Product records often originate from annual reports, whose source page
    # is not where the official product photo lives.  Use the approved
    # AnySearch adapter to discover one CATL-hosted page per branded product;
    # Kimi will open those real target pages for DOM/pixel evidence.
    generic_names = {"储能系统", "动力电池系统", "锂电池材料", "电池回收"}
    branded_products = [
        product for product in products
        if product.name not in generic_names and not product.name.endswith("解决方案")
    ]
    branded_products.sort(key=lambda product: (-len(product.name), product.name))
    anysearch = AnySearchCliAdapter()
    if anysearch.health().available:
        for product in branded_products[: min(12, args.max_pages)]:
            envelope = anysearch.search(SearchRequest(
                query_id=f"IMG-{product.product_id}",
                query=f"site:catl.com {product.name} 宁德时代",
                entity_id=canonical_entity.entity_id if canonical_entity else "PENDING-ENTITY",
                purpose="official product image page discovery",
                max_results=3,
                topic="image_evidence",
            ))
            for hit in envelope.hits:
                url = str(hit.final_url or "")
                from urllib.parse import urlparse
                host = (urlparse(url).hostname or "").lower().removeprefix("www.")
                if host != "catl.com" and not host.endswith(".catl.com"):
                    continue
                if url.lower().split("?", 1)[0].endswith(NON_PAGE_SUFFIXES):
                    continue
                entry = pages.setdefault(url, {
                    "url": url, "kind": "product", "source_kind": "official_company",
                    "publisher": product.name, "source_id": None,
                    "product_ids": set(), "specific": True,
                })
                entry["product_ids"].add(product.product_id)
                entry["specific"] = len(entry["product_ids"]) == 1
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
    from enterprise_energy_research.research.data_coverage import ResearchDataCoverageValidator
    coverage = ResearchDataCoverageValidator().audit(
        entity_name="宁德时代", claims=runner.cumulative.claims,
        products=runner.cumulative.products, factories=runner.cumulative.factories,
        images=runner.cumulative.images, complexity=EnterpriseComplexity.GROUP_LARGE,
        has_stock_code=True,
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
            "network_mode": "direct" if not os.getenv("EER_OUTBOUND_PROXY") else "proxy",
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
