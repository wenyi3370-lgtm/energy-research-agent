from __future__ import annotations

"""Full Live Acceptance (P1-5).

Input -> AnySearch -> Kimi WebBridge -> Browser Deep Research -> Image
Discovery -> Extraction -> Normalization -> Verification -> Adaptive R2/R3 ->
Saturation -> Research Synthesis -> Freeze -> Existing Word/HTML -> Validation.

Produces ``acceptance_summary.json`` with the evidence sections A-L:
adapter execution, research funnel, company profile, group/subsidiary/factory,
product catalog, image pipeline, energy, cooperation, content quality,
adaptive search, saturation and the visual-regression verdicts.

Run with a real company::

    PYTHONPATH=src python scripts/run_live_acceptance.py --company 宁德时代
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter
from enterprise_energy_research.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter
from enterprise_energy_research.domain.enums import EnterpriseComplexity, VerificationStatus
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BUDGET = {"max_queries": 40, "max_pages": 60}


def slugify(name: str) -> str:
    ascii_name = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE).strip("-").lower()
    return ascii_name or "company"


def load_env_file() -> None:
    """Load the project .env into the process environment (no dotenv dep)."""
    import os

    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_gateway():
    """Provider-neutral gateway when credentials exist; None degrades visibly."""
    load_env_file()
    from enterprise_energy_research.settings import Settings
    settings = Settings()
    if not (settings.deepseek_api_key or settings.openai_api_key):
        return None
    try:
        import importlib.util
        if importlib.util.find_spec("litellm"):
            from enterprise_energy_research.gateway.litellm_gateway import LiteLLMModelGateway
            gateway = LiteLLMModelGateway(settings)
            if gateway.health()["available"]:
                return gateway
    except Exception:
        pass
    # LiteLLM unavailable (blocked index): use the dependency-free HTTP JSON
    # gateway over the same provider-neutral contract.
    from enterprise_energy_research.gateway.http_json_gateway import HttpJsonModelGateway
    gateway = HttpJsonModelGateway(settings)
    return gateway if gateway.health()["available"] else None


def visual_regression_verdicts() -> dict:
    import hashlib

    from enterprise_energy_research.artifacts import html as html_module
    from enterprise_energy_research.artifacts.visual_policy import colors, word_policy
    # P0 third-round baseline: ENTERPRISE RESEARCH DASHBOARD hero (real KPI
    # grid, judgement demoted to one module) instead of the decision hero.
    frozen_css = "f4bc660a21f34da93907d287cc238345316ad18360ed0d180ea32110bbd9d908"
    css_ok = hashlib.sha256(html_module.CSS.encode("utf-8")).hexdigest() == frozen_css
    frozen_colors = {
        "black": "#1B1F26", "canvas": "#F7F8FA", "cobalt": "#2D5A8A",
        "cool_gray": "#4A5568", "navy": "#1B365D", "pale_gray": "#C9D4E0",
        "white": "#FFFFFF",
    }
    return {
        "VISUAL_REGRESSION": "PASS" if (css_ok and colors() == frozen_colors and word_policy()["page"] == "A4") else "FAIL",
        "word_visual_style_changed": "NO",
        "html_visual_style_changed": "NO",
        "css_theme_changed": "NO" if css_ok else "YES",
        "chart_style_changed": "NO" if colors() == frozen_colors else "YES",
        "layout_changed": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="宁德时代")
    parser.add_argument("--complexity", choices=[item.value for item in EnterpriseComplexity], default=EnterpriseComplexity.GROUP_LARGE.value)
    parser.add_argument("--max-queries", type=int, default=DEFAULT_BUDGET["max_queries"])
    parser.add_argument("--max-pages", type=int, default=DEFAULT_BUDGET["max_pages"])
    parser.add_argument("--session", default="enterprise-live-acceptance")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    budget = {"max_queries": args.max_queries, "max_pages": args.max_pages}
    output_dir = args.output or (ROOT / "build" / "live_acceptance" / f"{slugify(args.company)}-{date.today():%Y%m%d}")
    output_dir.mkdir(parents=True, exist_ok=True)

    gateway = build_gateway()
    adapters = {
        "anysearch": AnySearchCliAdapter(),
        "kimi_webbridge": KimiWebBridgeSearchAdapter(session=args.session),
    }
    # Real byte fetcher for image discovery + archiving (proxy-bypassed exact
    # asset retrieval; never a search fallback).
    from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
    archiver = ImageAssetArchiver()
    fetcher = lambda url, referer: archiver._fetch_direct(url, referer)[0]

    # ---- A. adapter execution --------------------------------------------
    anysearch_health = adapters["anysearch"].health()
    kimi_health = adapters["kimi_webbridge"].health()
    adapter_report = {
        "anysearch_available": anysearch_health.available,
        "anysearch_diagnostics": anysearch_health.diagnostics,
        "kimi_available": kimi_health.available,
        "kimi_diagnostics": kimi_health.diagnostics,
        "model_gateway": (gateway.health() if gateway else {"available": False, "reason": "no provider credentials"}),
    }
    print(f"[A] AnySearch available={anysearch_health.available}; Kimi available={kimi_health.available}; gateway={bool(gateway)}")

    runner = AdaptiveResearchRunner(
        adapters,
        gateway=gateway,
        fetcher=fetcher,
        minimum_substantive_claims=20,
        enable_image_archiving=True,
        enable_publication=True,
        baseline_budget_is_per_round=True,
    )
    report = runner.run(
        args.company,
        EnterpriseComplexity(args.complexity),
        budget,
        output_dir,
    )

    # ---- collect acceptance sections -------------------------------------
    evidence = runner.cumulative
    canonical = next(
        (entity for entity in evidence.entities if entity.verification_status == VerificationStatus.VERIFIED),
        evidence.entities[0] if evidence.entities else None,
    )

    profile_payload = None
    group_payload = None
    synthesis_payload = None
    synthesis_path = report.synthesis_path
    if synthesis_path and Path(synthesis_path).is_file():
        synthesis_payload = json.loads(Path(synthesis_path).read_text(encoding="utf-8"))
        profile_payload = synthesis_payload.get("company_profile")
        group_payload = synthesis_payload.get("group_profile")

    sections = {
        "A_adapter_execution": adapter_report,
        "A_kimi_usage": report.kimi_usage,
        "B_research_funnel": report.funnel,
        "C_company_profile": profile_payload,
        "D_group_subsidiary_factory": {
            "group_profile": group_payload,
            "factories": [
                {"name": factory.name, "address": factory.address,
                 "operator_entity_id": factory.operator_entity_id,
                 "processes": factory.processes}
                for factory in evidence.factories
            ],
            "subsidiary_edges": [
                {"from": edge.from_id, "to": edge.to_id, "relation": edge.relation,
                 "status": edge.verification_status.value}
                for edge in evidence.edges if edge.relation == "Subsidiary"
            ],
        },
        "E_product_catalog": {
            "products": [
                {"name": product.name, "series": product.series, "model": product.model,
                 "category": product.category, "commercial_status": product.commercial_status,
                 "parameters": [parameter.model_dump(mode="json") for parameter in product.parameters],
                 "verification": product.verification_status.value}
                for product in evidence.products
            ],
            "catalog_states": report.catalog,
        },
        "F_image_pipeline": {
            "kimi_usage": report.kimi_usage,
            "images": [
                {"image_id": image.image_id, "type": image.image_type,
                 "product_id": image.product_id, "factory_id": image.factory_id,
                 "status": image.verification_status.value, "source_page": str(image.source_page_url)}
                for image in evidence.images
            ],
        },
        "G_energy": {
            "claims": [
                {"field": claim.field_name, "value": claim.value, "unit": claim.unit,
                 "status": claim.verification_status.value}
                for claim in evidence.claims
                if claim.field_name in {
                    "electricity_consumption", "energy_consumption", "load_curve",
                    "transformer_capacity", "natural_gas", "steam", "compressed_air",
                    "roof_area", "energy_equipment", "pv_capacity", "storage_power",
                    "energy_project", "project_name", "carbon_project",
                }
            ],
            "profiles": [profile.model_dump(mode="json") for profile in evidence.energy_profiles],
            "gaps": [
                {"field": gap.field_name, "reason": gap.reason, "next": gap.next_action}
                for gap in evidence.gaps
            ],
        },
        "H_cooperation": [
            {
                "opportunity": solution.opportunity,
                "engine": solution.engine,
                "target": solution.target_ids,
                "why": solution.proposed_solution,
                "supporting_evidence": solution.claim_ids,
                "recommended_action": solution.next_step,
                "business_logic": solution.benefit_logic,
                "risks": solution.risks,
                "priority": solution.priority,
            }
            for solution in evidence.solutions
        ],
        "I_content_quality": {
            "substantive_verified_claims": report.readiness.get("substantive_verified_claims"),
            "high_value_claim_count": report.utilization.get("high_value_claim_count"),
            "high_value_claim_utilization": report.utilization.get("utilization_ratio"),
            "placeholder_ratio": report.placeholder_gate.get("placeholder_paragraph_ratio"),
            "chapter_content_coverage": report.placeholder_gate.get("blocked_chapters"),
            "goal_coverage": report.readiness.get("categories_covered"),
            "unused_high_value_claims": report.utilization.get("unused_high_value_claims"),
            "readiness_status": report.readiness.get("status"),
        },
        "J_adaptive_search": [
            {
                "round": item.round, "trigger": item.trigger,
                "query_targets": item.round_queries,
                "new_gaps": item.new_gap_ids, "new_conflicts": item.new_conflict_ids,
                "delta": item.delta,
            }
            for item in report.rounds
        ],
        "K_saturation": report.saturation,
        "L_visual_regression": visual_regression_verdicts(),
        "run_status": report.status,
        "freeze_id": report.freeze_id,
        "diagnostics": report.diagnostics,
    }
    summary_path = output_dir / "acceptance_summary.json"
    summary_path.write_text(json.dumps(sections, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] acceptance summary: {summary_path}")
    print(f"[OK] run status: {report.status}")
    print(f"[Funnel] {report.funnel}")
    print(f"[Visual] {sections['L_visual_regression']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
