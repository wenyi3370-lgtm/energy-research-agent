from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _common import now_iso, read_csv, write_csv
from _kimi_webbridge import BridgePreflightError, command, default_bridge_binary, ensure_ready
from collection_quantity_policy import coverage_requirement, load_project_policy, round_floor


TASK_FIELDS = [
    "task_id",
    "stage",
    "platform",
    "market",
    "language",
    "goal_family",
    "collection_goal",
    "target_geography",
    "target_brand",
    "exact_model",
    "identifier_type",
    "identifier_value",
    "starting_url_or_query",
    "required_tool",
    "source_tier",
    "planned_fields",
    "completion_contract",
    "target_unique_sources",
    "actual_unique_sources",
    "target_records",
    "actual_records",
    "source_type_count",
    "platform_count",
    "primary_source_count",
    "coverage_requirement",
    "critical_claim_count",
    "dual_sourced_claim_count",
    "remaining_high_priority_count",
    "no_new_high_priority_batches",
    "count_evidence_refs",
    "platform_limit_evidence",
    "quantity_exception_type",
    "quantity_exception_refs",
    "round",
    "round_goal",
    "output_file",
    "raw_capture_path",
    "saturation_evidence",
    "status",
    "notes",
]

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def render_template(template: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def append_tasks(project_dir: Path, new_rows: list[dict[str, str]]) -> None:
    path = project_dir / "02_Web_Collection_Tasks.csv"
    rows: list[dict[str, str]] = []
    if path.exists():
        _, rows = read_csv(path)
    rows.extend(new_rows)
    write_csv(path, TASK_FIELDS, rows)


def update_task_status(project_dir: Path, task_id: str, status: str, note: str) -> None:
    path = project_dir / "02_Web_Collection_Tasks.csv"
    _, rows = read_csv(path)
    for row in rows:
        if row.get("task_id") == task_id:
            row["status"] = status
            row["notes"] = f"{row.get('notes', '')} {note}".strip()
            break
    write_csv(path, TASK_FIELDS, rows)


def run_bridge(product_url: str, session: str, bridge_bin: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        status = ensure_ready(bridge_bin)
        navigation = command(
            "navigate",
            {"url": product_url, "newTab": True, "group_title": "精确型号评论语料采集"},
            session,
        )
        snapshot = command("snapshot", {}, session)
        payload = {
            "status": status,
            "session": session,
            "product_url": product_url,
            "navigate": navigation,
            "snapshot": snapshot,
            "next_action": "Continue in the same session, verify the exact model, paginate or expand reviews, and save raw review rows before coding.",
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except BridgePreflightError as exc:
        output_path.write_text(
            json.dumps({"error": str(exc), "status": exc.status}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and optionally seed a Kimi WebBridge exact-model review corpus task.")
    parser.add_argument("--project-dir", default=".", help="Research project directory.")
    parser.add_argument("--platform", required=True, help="Amazon, Reddit, YouTube, retailer, forum, etc.")
    parser.add_argument("--market", default="target market")
    parser.add_argument("--brand", required=True)
    parser.add_argument("--exact-model", required=True)
    parser.add_argument("--identifier-type", required=True, help="ASIN, SKU, model_code, product_url, etc.")
    parser.add_argument("--identifier-value", required=True)
    parser.add_argument("--product-url", required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--run", action="store_true", help="Open the product page and save the first Kimi WebBridge snapshot.")
    parser.add_argument("--bridge-bin", default=str(default_bridge_binary()))
    parser.add_argument("--session", default="", help="Stable Kimi WebBridge session name. Defaults to the generated task ID.")
    args = parser.parse_args()

    if "amazon" in args.platform.lower():
        if args.identifier_type.strip().lower() != "asin" or not ASIN_RE.match(args.identifier_value.strip()):
            parser.error("Amazon review corpus tasks must use --identifier-type ASIN and a valid 10-character ASIN value.")

    project_dir = Path(args.project_dir).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    try:
        quantity_policy = load_project_policy(project_dir)
    except ValueError as exc:
        parser.error(str(exc))
    raw_dir = project_dir / "raw" / "kimi-webbridge"
    raw_dir.mkdir(parents=True, exist_ok=True)

    task_id = args.task_id or f"KWB-REVIEWS-{now_iso().replace(':', '').replace('+', '-')}"
    session = args.session or task_id.lower().replace("_", "-")
    prompt_path = raw_dir / f"{task_id}_review_corpus_prompt.md"
    raw_output = raw_dir / f"{task_id}_review_corpus_snapshot.json"

    template = (skill_root() / "assets" / "prompts" / "web_collection_prompts" / "review_corpus.md").read_text(encoding="utf-8")
    prompt = render_template(
        template,
        {
            "platform": args.platform,
            "market": args.market,
            "brand": args.brand,
            "exact_model": args.exact_model,
            "identifier_type": args.identifier_type,
            "identifier_value": args.identifier_value,
            "product_url": args.product_url,
        },
    )
    prompt_path.write_text(prompt, encoding="utf-8")

    common = {
            "stage": "4",
            "platform": args.platform,
            "market": args.market,
            "language": "",
            "goal_family": "reviews_and_user_voice",
            "collection_goal": "reviews",
            "target_geography": args.market,
            "target_brand": args.brand,
            "exact_model": args.exact_model,
            "identifier_type": args.identifier_type,
            "identifier_value": args.identifier_value,
            "starting_url_or_query": args.product_url,
            "required_tool": "kimi-webbridge",
            "source_tier": "Tier 3",
            "completion_contract": "exact-model raw corpus; review URLs; platform limit note",
            "output_file": "07_Raw_Reviews.csv; 00_Source_Ledger.csv",
            "raw_capture_path": str(raw_output if args.run else prompt_path),
            "planned_fields": "review URL, rating, original text, crawl date, model identifier, review limit note",
            "status": "planned",
            "notes": "Raw exact-model review corpus must be saved before review coding or synthesis.",
    }
    round_rows = []
    for rnd, rnd_goal, evidence in (
        ("1", "coverage", "planned criterion: enumerate accessible review platforms and visible corpus boundaries"),
        ("2", "depth", "planned criterion: collect the policy minimum raw reviews per exact model or the proven visible-platform maximum"),
        ("3", "triangulation", "planned criterion: cross-check every critical theme across the policy minimum platforms and record residual market-only gaps"),
    ):
        floor = round_floor("reviews_and_user_voice", rnd, quantity_policy)
        row = dict(common)
        row.update({"task_id": f"{task_id}-R{rnd}", "round": rnd, "round_goal": rnd_goal, "target_unique_sources": str(floor["min_unique_sources"]), "target_records": str(floor["min_records"]), "coverage_requirement": coverage_requirement("reviews_and_user_voice", quantity_policy), "saturation_evidence": evidence})
        round_rows.append(row)
    append_tasks(project_dir, round_rows)

    print(f"Wrote prompt: {prompt_path}")
    print(f"Updated collection tasks: {project_dir / '02_Web_Collection_Tasks.csv'}")
    if args.run:
        code = run_bridge(args.product_url, session, Path(args.bridge_bin).expanduser(), raw_output)
        update_task_status(
            project_dir,
            f"{task_id}-R1",
            "seeded" if code == 0 else "blocked",
            "Initial browser snapshot saved; continue in the same session." if code == 0 else "Kimi WebBridge preflight or initial navigation failed; inspect raw capture.",
        )
        print(f"Wrote raw output: {raw_output}")
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
