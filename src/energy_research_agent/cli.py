from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from energy_research_agent.domain.enums import (
    EnterpriseComplexity,
    ProductDashboardDecision,
    RunStatus,
    SourceLevel,
    VerificationStatus,
)
from energy_research_agent.domain.ids import RunSequence, new_sortable_id
from energy_research_agent.domain.models import (
    Claim,
    Entity,
    ProductDetection,
    ResearchRequest,
    RunManifest,
    Source,
)
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.graph.runner import Phase2Runner
from energy_research_agent.graph.state import ResearchState
from energy_research_agent.settings import Settings
from energy_research_agent import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energy-research-agent",
        description="Run and inspect the Energy Research Agent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the Agent web UI and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="Reload when source files change")
    demo = subparsers.add_parser(
        "synthetic-run",
        help="Run an offline evidence/freeze/export smoke test",
    )
    demo.add_argument("company_name")
    demo.add_argument("--workdir", type=Path, default=Path(".agent-demo"))
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
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit(
                "The web API dependencies are not installed. Run: pip install -e '.[api,database,models]'"
            ) from exc
        uvicorn.run(
            "energy_research_agent.automation.api.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0
    if args.command == "synthetic-run":
        print(json.dumps(synthetic_run(args.company_name, args.workdir), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
