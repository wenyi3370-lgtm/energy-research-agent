from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from _common import now_iso, read_json, write_json
from collection_quantity_policy import (
    MANIFEST_FROZEN_AT_FIELD,
    MANIFEST_SHA256_FIELD,
    MANIFEST_SNAPSHOT_FIELD,
    MANIFEST_VERSION_FIELD,
    freeze_current_policy,
    load_project_policy,
    minimum_exact_models_per_market,
)


CSV_TARGETS = {
    "research_approval_template.csv": "00_Research_Approval.csv",
    "source_ledger_template.csv": "00_Source_Ledger.csv",
    "market_scan_template.csv": "01_Market_Scan.csv",
    "web_collection_tasks_template.csv": "02_Web_Collection_Tasks.csv",
    "competitor_list_template.csv": "02_Competitor_List.csv",
    "model_identifier_template.csv": "03_Model_Identifier_Check.csv",
    "product_parameters_template.csv": "04_Product_Parameters.csv",
    "pricing_channel_template.csv": "05_Pricing_Channel.csv",
    "channel_service_template.csv": "06_Channel_Service.csv",
    "raw_reviews_template.csv": "07_Raw_Reviews.csv",
    "review_coding_template.csv": "08_Review_Coding.csv",
    "integrated_matrix_template.csv": "09_Integrated_Matrix.csv",
    "swot_opportunity_template.csv": "10_SWOT_Opportunity.csv",
    "data_gaps_template.csv": "11_Evidence_Issues.csv",
    "model_assumptions_template.csv": "12_Model_Assumptions.csv",
    "model_results_template.csv": "13_Model_Results.csv",
    "simulated_modeling_data_template.csv": "14_Simulated_Modeling_Data.csv",
    "collection_record_registry_template.csv": "15_Collection_Record_Registry.csv",
}

MD_TARGETS = {
    "stage_brief_template.md": "stage_brief.md",
    "data_gap_log_template.md": "data_gap_log.md",
    "research_outline_template.md": "research_outline.md",
}

JSON_TARGETS = {
    "count_evidence_template.json": "audits/templates/count_evidence_template.json",
    "market_gap_evidence_template.json": "audits/templates/market_gap_evidence_template.json",
    "platform_limit_evidence_template.json": "audits/templates/platform_limit_evidence_template.json",
}

OFFICE_TARGETS = {
    ("word", "energy_market_research_report_template.docx"): "deliverables/templates/energy_market_research_report_template.docx",
    ("excel", "energy_market_research_workbook_template.xlsx"): "deliverables/templates/energy_market_research_workbook_template.xlsx",
    ("ppt", "energy_market_research_presentation_template.pptx"): "deliverables/templates/energy_market_research_presentation_template.pptx",
}

MARKET_INSIGHT_METHOD_ID = "embedded-market-insight-five-views-v1"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copy_template(src: Path, dst: Path, force: bool) -> str:
    if dst.exists() and not force:
        return "exists"
    was_existing = dst.exists()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "updated" if was_existing else "created"


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a domestic or global energy market research project folder.")
    parser.add_argument("--project-dir", required=True, help="Output project directory.")
    parser.add_argument("--region", required=True, help="Target region, e.g. Europe, Germany, US, Japan.")
    parser.add_argument("--target-market", action="append", default=[], help="Repeat for each target market. Defaults to --region.")
    parser.add_argument("--market-model-pair", action="append", default=[], metavar="MARKET::EXACT_MODEL", help=f"Repeat for each approved market/exact-model pair; the current YAML policy requires at least {minimum_exact_models_per_market()} distinct exact models per target market before collection.")
    parser.add_argument("--category", required=True, help="Product category, e.g. V2H, V2G, residential storage.")
    parser.add_argument("--language", default="zh-CN", help="Deliverable language. Default: zh-CN.")
    parser.add_argument("--stages", default="0-8", help="Stage range or list, e.g. 0-8 or 1,2,3,6.")
    parser.add_argument("--local-parameter-path", default="", help="User-confirmed local product parameter path, if available.")
    parser.add_argument("--decision-question", default="", help="Decision question the research must answer.")
    parser.add_argument("--outline-version", default="v1", help="Current outline version requiring human approval.")
    parser.add_argument("--analysis-branch", choices=["auto", "modeling", "market-insight"], default="auto")
    parser.add_argument("--currency", default="", help="Primary reporting currency.")
    parser.add_argument("--tax-basis", default="", help="Price tax basis.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing template files.")
    args = parser.parse_args()

    root = skill_root()
    project_dir = Path(args.project_dir).expanduser().resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project_dir / "project_manifest.json"
    existing_manifest = read_json(manifest_path, {})

    if existing_manifest:
        try:
            load_project_policy(project_dir, existing_manifest)
        except ValueError as exc:
            parser.error(
                "Existing project does not have a valid frozen collection-quantity policy. "
                "Run upgrade_collection_policy.py with explicit human confirmation before reinitializing. "
                f"Details: {exc}"
            )
        policy_fields = {
            field: existing_manifest[field]
            for field in (
                MANIFEST_VERSION_FIELD,
                MANIFEST_SHA256_FIELD,
                MANIFEST_SNAPSHOT_FIELD,
                MANIFEST_FROZEN_AT_FIELD,
            )
        }
    else:
        frozen_at = now_iso()
        policy_fields = freeze_current_policy(project_dir, frozen_at)

    created: list[dict[str, str]] = []
    created.append(
        {
            "path": str(project_dir / str(policy_fields[MANIFEST_SNAPSHOT_FIELD])),
            "status": "preserved" if existing_manifest else "created",
        }
    )
    for src_name, dst_name in CSV_TARGETS.items():
        status = copy_template(root / "assets" / "templates" / "csv" / src_name, project_dir / dst_name, args.force)
        created.append({"path": str(project_dir / dst_name), "status": status})
    for src_name, dst_name in MD_TARGETS.items():
        status = copy_template(root / "assets" / "templates" / "markdown" / src_name, project_dir / dst_name, args.force)
        created.append({"path": str(project_dir / dst_name), "status": status})
    for src_name, dst_name in JSON_TARGETS.items():
        status = copy_template(root / "assets" / "templates" / "json" / src_name, project_dir / dst_name, args.force)
        created.append({"path": str(project_dir / dst_name), "status": status})
    for (folder, src_name), dst_name in OFFICE_TARGETS.items():
        src = root / "assets" / "templates" / folder / src_name
        if src.exists():
            status = copy_template(src, project_dir / dst_name, args.force)
            created.append({"path": str(project_dir / dst_name), "status": status})

    (project_dir / "raw").mkdir(exist_ok=True)
    (project_dir / "deliverables").mkdir(exist_ok=True)
    (project_dir / "intermediate").mkdir(exist_ok=True)

    # Embedded qualitative branch workspace. The external market-insight Skill is optional.
    market_insight_root = project_dir / "intermediate" / "market-insight"
    if args.analysis_branch in {"auto", "market-insight"}:
        market_insight_root.mkdir(parents=True, exist_ok=True)
        insight_src = root / "assets" / "templates" / "markdown" / "market_insight_report_template.md"
        insight_dst = market_insight_root / "market_insight_report.md"
        if insight_src.exists():
            status = copy_template(insight_src, insight_dst, args.force)
            created.append({"path": str(insight_dst), "status": status})
            if status != "exists":
                text = insight_dst.read_text(encoding="utf-8")
                text = text.replace("[[OUTLINE_VERSION]]", args.outline_version)
                text = text.replace("[[项目名称]]", f"{args.region}{args.category}")
                insight_dst.write_text(text, encoding="utf-8")

    # Modeling workspace skeleton (used when analysis_branch == modeling or is unresolved).
    modeling_root = project_dir / "intermediate" / "modeling"
    if args.analysis_branch in {"auto", "modeling"}:
        modeling_root.mkdir(parents=True, exist_ok=True)
        for sub in ("planning", "workspace", "methods", "code", "results", "robustness"):
            (modeling_root / sub).mkdir(exist_ok=True)
        (modeling_root / "workspace" / "data").mkdir(parents=True, exist_ok=True)
        simulation_src = root / "assets" / "templates" / "csv" / "simulated_modeling_data_template.csv"
        simulation_dst = modeling_root / "workspace" / "data" / "simulated_modeling_data.csv"
        if simulation_src.exists():
            status = copy_template(simulation_src, simulation_dst, args.force)
            created.append({"path": str(simulation_dst), "status": status})
        claude_src = root / "assets" / "templates" / "modeling" / "modeling_claude_template.md"
        claude_dst = modeling_root / "CLAUDE.md"
        if claude_src.exists():
            status = copy_template(claude_src, claude_dst, args.force)
            created.append({"path": str(claude_dst), "status": status})

    target_markets = [item.strip() for item in args.target_market if item.strip()] or [args.region]
    market_model_pairs = []
    for item in args.market_model_pair:
        if "::" not in item:
            parser.error("--market-model-pair must use MARKET::EXACT_MODEL")
        market, exact_model = (part.strip() for part in item.split("::", 1))
        if not market or not exact_model:
            parser.error("--market-model-pair requires nonblank market and exact model")
        if market.casefold() not in {value.casefold() for value in target_markets}:
            parser.error(f"Market '{market}' in --market-model-pair is not declared by --target-market")
        market_model_pairs.append({"market": market, "exact_model": exact_model})

    manifest = {
        "modeling_workspace": str(modeling_root),
        "market_insight_workspace": str(market_insight_root),
        "market_insight_method_id": MARKET_INSIGHT_METHOD_ID,
        "project_dir": str(project_dir),
        "region": args.region,
        "target_markets": target_markets,
        "market_model_pairs": market_model_pairs,
        "category": args.category,
        "language": args.language,
        "stages": args.stages,
        "local_parameter_path": args.local_parameter_path,
        "decision_question": args.decision_question,
        "outline_version": args.outline_version,
        "analysis_branch": args.analysis_branch,
        "currency": args.currency,
        "tax_basis": args.tax_basis,
        "created_at": now_iso(),
        "template_files": created,
        **policy_fields,
    }
    write_json(manifest_path, manifest)
    write_json(project_dir / "stage_status.json", {"created_at": now_iso(), "stages": {}, "notes": []})

    print(f"Initialized research project: {project_dir}")
    print(f"Region: {args.region}")
    print(f"Category: {args.category}")
    print(f"Files: {len(created)} templates + manifest/status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
