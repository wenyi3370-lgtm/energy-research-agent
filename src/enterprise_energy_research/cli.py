from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from enterprise_energy_research.domain.enums import (
    EnterpriseComplexity,
    ProductDashboardDecision,
    RunStatus,
    SourceLevel,
    VerificationStatus,
)
from enterprise_energy_research.domain.ids import RunSequence, new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim,
    Entity,
    ProductDetection,
    ResearchRequest,
    RunManifest,
    Source,
)
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.runner import Phase2Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import Settings
from enterprise_energy_research import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enterprise-energy-research")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("synthetic-run", help="Run the Phase 2 evidence/freeze/export loop without network access")
    demo.add_argument("company_name")
    demo.add_argument("--workdir", type=Path, default=Path(".phase2-demo"))
    subparsers.add_parser("settings", help="Print non-secret effective settings")
    return parser


def synthetic_run(company_name: str, workdir: Path) -> dict[str, object]:
    workdir.mkdir(parents=True, exist_ok=True)
    settings = Settings(output_root=workdir / "outputs")
    request = ResearchRequest(
        request_id=new_sortable_id("REQ"),
        raw_company_name=company_name,
    )
    run_id = new_sortable_id("RUN")
    entity_id = new_sortable_id("ENT")
    sequence = RunSequence()
    run = RunManifest(
        run_id=run_id,
        request_id=request.request_id,
        status=RunStatus.RUNNING,
        canonical_entity_id=entity_id,
        complexity=EnterpriseComplexity.ENTERPRISE_NORMAL,
        config_hash=settings.config_hash(),
        code_version=__version__,
        model_gateway={
            "primary_provider": settings.primary_provider,
            "fallback_provider": settings.fallback_provider,
            "mode": "synthetic-no-model",
        },
    )
    store = EvidenceStore(workdir / "evidence.sqlite3")
    store.create_run(run)
    source_id = sequence.next("source")
    claim_id = sequence.next("claim")
    store.add(run_id, 1, "entity", Entity(
        entity_id=entity_id,
        canonical_name=company_name,
        registered_name=company_name,
        verification_status=VerificationStatus.VERIFIED,
        supporting_claim_ids=[claim_id],
    ))
    store.add(run_id, 1, "source", Source(
        source_id=source_id,
        canonical_url="https://example.com/official/company-profile",
        source_title="Synthetic official company profile",
        source_domain="example.com",
        publisher=company_name,
        source_level=SourceLevel.SOURCE_A,
        grading_reason="official_company synthetic fixture",
        content_type="text/html",
    ))
    store.add(run_id, 1, "claim", Claim(
        claim_id=claim_id,
        entity_id=entity_id,
        field_name="canonical_company_name",
        value=company_name,
        value_type="string",
        qualifier="exact",
        source_id=source_id,
        raw_text=company_name,
        context_text=f"企业名称：{company_name}",
        verification_status=VerificationStatus.VERIFIED,
        confidence=1.0,
    ))
    state = ResearchState(
        run_id=run_id,
        request_id=request.request_id,
        status=RunStatus.RUNNING,
        canonical_entity_id=entity_id,
        complexity=EnterpriseComplexity.ENTERPRISE_NORMAL,
    )
    detection = ProductDetection(
        has_physical_products=False,
        product_confidence=1.0,
        product_count=0,
        qualifying_product_ids=[],
        dashboard_decision=ProductDashboardDecision.SKIP_PRODUCT_DASHBOARD,
        reason="Synthetic fixture contains no verified physical products",
    )
    output_dir = settings.output_root / company_name / run_id / "01_evidence"
    final_state, manifest = Phase2Runner(store).finalize_evidence(
        state,
        output_dir=output_dir,
        product_detection=detection,
    )
    return {
        "run_id": run_id,
        "status": final_state.status.value,
        "freeze_id": final_state.freeze_id,
        "artifact_manifest_id": final_state.artifact_manifest_id,
        "output_dir": str(output_dir.resolve()),
        "product_dashboard": next(
            item.status.value for item in manifest.artifacts if item.type.value == "product_html"
        ) if manifest else None,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "settings":
        print(json.dumps(Settings().safe_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "synthetic-run":
        print(json.dumps(synthetic_run(args.company_name, args.workdir), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
