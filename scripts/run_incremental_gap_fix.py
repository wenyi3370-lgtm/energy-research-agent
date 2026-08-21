from __future__ import annotations

"""Incremental gap fix (只跑有问题的部分).

Loads an existing run's evidence, executes ONLY the requested goal families
(discovery -> full-text -> product deep browsing -> image discovery ->
extraction), merges the new evidence with the existing evidence, re-validates
the merged set, and re-runs the content gates and publication. Nothing else
is re-collected.

    PYTHONPATH=src python scripts/run_incremental_gap_fix.py \\
        --evidence build/live_acceptance/<run>/evidence.sqlite3 \\
        --topics products product_series product_models product_parameters \\
        --output build/live_acceptance/<run>
"""

import argparse
import json
from pathlib import Path

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter
from enterprise_energy_research.domain.enums import EnterpriseComplexity, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ResearchPlan, RunManifest
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner, MergeEvidence
from enterprise_energy_research.research.normalizer import NormalizedEvidence

ROOT = Path(__file__).resolve().parents[1]


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
    parser.add_argument("--topics", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--company", default="宁德时代")
    parser.add_argument("--session", default="enterprise-incremental-fix")
    parser.add_argument("--max-pages", type=int, default=80)
    args = parser.parse_args()

    store = EvidenceStore(args.evidence)
    import sqlite3
    con = store.connect()
    row = con.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
    if row is None:
        print("no run found in evidence store")
        return 1
    run_id = row[0]

    # Fresh collection store for the gap-fix round; existing evidence is merged in.
    fix_store = EvidenceStore(args.output / "evidence_fixed.sqlite3")
    run_manifest = store.get_run(run_id)
    fix_store.create_run(RunManifest(
        run_id=run_id, request_id=run_manifest.request_id, status=RunStatus.RUNNING,
        config_hash=run_manifest.config_hash, code_version=run_manifest.code_version,
        model_gateway=run_manifest.model_gateway,
    ))
    from enterprise_energy_research.gateway.http_json_gateway import HttpJsonModelGateway
    from enterprise_energy_research.settings import Settings
    from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
    import os

    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    gateway = HttpJsonModelGateway(Settings())
    archiver = ImageAssetArchiver()
    fetcher = lambda url, referer: archiver._fetch_direct(url, referer)[0]

    runner = AdaptiveResearchRunner(
        {
            "anysearch": AnySearchCliAdapter(),
            "kimi_webbridge": KimiWebBridgeSearchAdapter(session=args.session),
        },
        gateway=gateway,
        fetcher=fetcher,
        store=fix_store,
        enable_image_archiving=True,
        enable_publication=False,
        fulltext_pages_per_query=3,
    )

    # Existing evidence first (stable IDs), then one gap-fix round.
    runner.cumulative = load_existing(store, run_id)

    plan = __import__("enterprise_energy_research.research.planner", fromlist=["ResearchPlanner"]).ResearchPlanner().build(
        run_id, "PENDING-ENTITY", args.company, EnterpriseComplexity.GROUP_LARGE,
        {"max_queries": len(args.topics) * 3, "max_pages": args.max_pages},
        only_topics=args.topics,
    )
    fix_queries = [q for q in plan.queries if q.topic in args.topics]
    if not fix_queries:
        print("no queries planned for topics:", args.topics)
        return 1
    print(f"[incremental] {len(fix_queries)} queries for {args.topics}")

    mini = ResearchPlan(
        plan_id=new_sortable_id("PLAN"), run_id=run_id,
        complexity=EnterpriseComplexity.GROUP_LARGE, queries=fix_queries,
        budget={"max_queries": len(fix_queries) + 1, "max_pages": args.max_pages},
        completion_contract=args.topics,
        canonical_company_name=args.company,
    )
    from enterprise_energy_research.research.executor import SearchExecutor
    from enterprise_energy_research.research.image_discovery import KimiUsageTelemetry
    telemetry = KimiUsageTelemetry()
    envelopes = SearchExecutor(runner.adapters).execute(mini)
    envelopes = runner._fulltext_pass(envelopes, fix_queries)
    envelopes = runner._browser_depth_pass(envelopes, fix_queries, telemetry)
    runner._image_pass(envelopes, telemetry)

    batches: list = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _, extracted, _failures in pool.map(runner._extract_one, envelopes):
            batches.extend(extracted)

    from enterprise_energy_research.research.identity_evidence import IdentityEvidenceSynthesizer
    from enterprise_energy_research.research.resolver import CompanyResolver
    from enterprise_energy_research.research.claim_validator import ClaimValidator
    from enterprise_energy_research.research.entity_mapper import EntityMapper
    from enterprise_energy_research.research.image_validator import ImageValidator
    from enterprise_energy_research.research.product_detector import ProductDetector
    from enterprise_energy_research.analysis.energy import EnergyAnalyst
    from enterprise_energy_research.analysis.solutions import SolutionEngine

    resolution = CompanyResolver().resolve(args.company, batches)
    official_domains = {
        str(candidate.official_website.host).lower().removeprefix("www.")
        for candidate in resolution.candidates if candidate.official_website
    } if resolution.status == "RESOLVED" else set()
    from urllib.parse import urlparse
    upgraded = []
    for batch in batches:
        host = urlparse(str(batch.source_url)).netloc.lower().removeprefix("www.")
        if host and any(host == d or host.endswith("." + d) for d in official_domains):
            upgraded.append(batch.model_copy(update={"source_kind": "official_company"}))
        else:
            upgraded.append(batch)
    batches = upgraded

    from enterprise_energy_research.research.normalizer import EvidenceNormalizer
    round_evidence = EvidenceNormalizer().normalize(batches, official_domains=official_domains)
    round_evidence.claims.extend(IdentityEvidenceSynthesizer().synthesize(
        resolution, batches, round_evidence.entities, round_evidence.sources,
    ))
    runner._attach_discovered_images(round_evidence, telemetry, official_domains)
    MergeEvidence.merge(runner.cumulative, round_evidence)
    runner.cumulative.claims, runner.cumulative.conflicts = ClaimValidator().validate(
        runner.cumulative.claims, runner.cumulative.sources,
    )
    runner.cumulative.entities, runner.cumulative.edges = EntityMapper().apply_evidence(
        runner.cumulative.entities, runner.cumulative.edges, runner.cumulative.claims,
    )
    runner.cumulative.images = ImageValidator().validate(
        runner.cumulative.images, runner.cumulative.entities, runner.cumulative.sources,
    )
    runner.cumulative.products, _ = ProductDetector().detect(
        runner.cumulative.products, runner.cumulative.images, runner.cumulative.sources,
        runner.cumulative.claims,
    )
    runner.cumulative.energy_profiles, energy_gaps = EnergyAnalyst().analyze(
        runner.cumulative.entities, runner.cumulative.factories, runner.cumulative.claims,
    )
    runner.cumulative.solutions = SolutionEngine().generate(
        runner.cumulative.entities, runner.cumulative.energy_profiles, runner.cumulative.claims,
    )
    runner.cumulative.gaps.extend(energy_gaps)

    from enterprise_energy_research.research.ingestor import EvidenceIngestor
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
    print("[incremental] readiness:", readiness["status"], readiness["verified_company_identity"],
          readiness["substantive_verified_claims"], readiness["categories_covered"])
    (args.output / "02_research_quality").mkdir(parents=True, exist_ok=True)
    (args.output / "02_research_quality" / "readiness.json").write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    # Publish when the gates pass (freeze -> existing Word/HTML publishers).
    if readiness["status"] == "PASS":
        from enterprise_energy_research.graph.phase3_runner import Phase3Runner
        from enterprise_energy_research.graph.state import ResearchState
        from enterprise_energy_research.research.content_contract import PlaceholderContentGate, chapter_substantive_facts, CHAPTER_CONTRACTS
        body_paragraphs: list[str] = []
        for key, contract in CHAPTER_CONTRACTS.items():
            facts = chapter_substantive_facts(
                key, entities=runner.cumulative.entities, claims=runner.cumulative.claims,
                edges=runner.cumulative.edges, factories=runner.cumulative.factories,
                products=runner.cumulative.products, energy_profiles=runner.cumulative.energy_profiles,
            )
            ok, message = contract.assess(facts)
            body_paragraphs.extend(f"{fact}" for fact in facts)
            if not ok and contract.fallback_behavior == "block_report":
                print("[incremental] chapter blocked:", key, message)
        placeholder = PlaceholderContentGate(body_paragraphs=body_paragraphs).assess()
        print("[incremental] placeholder gate:", placeholder["status"])
        if not placeholder["blocked"]:
            freeze_id = runner._freeze_and_publish(fix_store, run_id, args.output)
            print("[incremental] freeze:", freeze_id)
            return 0 if freeze_id else 2
    return 2 if readiness["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
