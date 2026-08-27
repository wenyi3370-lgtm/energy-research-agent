from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from _common import Issue, add_common_args, is_asin, is_url, print_report, read_csv, require_columns, resolve_project_file, row_label
from collection_quantity_policy import (
    coverage_requirement as policy_coverage_requirement,
    load_project_policy,
    market_goal_families,
    minimum_exact_models_per_market,
    model_goal_families,
    round_floor,
)
from source_independence import evaluate_claim_independence
from market_gap_exception import GAP_AUDIT_FIELDS, validate_market_gap_exception
from platform_limit_exception import validate_platform_limit_exception
from collection_record_registry import validate_record_registry
from critical_claim_evidence import validate_critical_claims


REQUIRED = [
    "task_id", "stage", "platform", "market", "goal_family", "collection_goal",
    "target_brand", "exact_model", "identifier_type", "identifier_value",
    "starting_url_or_query", "required_tool", "output_file", "raw_capture_path",
    "planned_fields", "target_unique_sources", "actual_unique_sources", "target_records",
    "actual_records", "source_type_count", "platform_count", "primary_source_count",
    "coverage_requirement", "critical_claim_count", "dual_sourced_claim_count",
    "remaining_high_priority_count", "no_new_high_priority_batches", "count_evidence_refs", "platform_limit_evidence",
    "quantity_exception_type", "quantity_exception_refs", "round", "round_goal",
    "saturation_evidence", "status", "notes",
]

WEB_TOOLS = {"kimi-webbridge", "anysearch"}
PRODUCT_GOALS = {"asin_verify", "identifier_verify", "price", "promotion", "parameters", "reviews", "channel", "service", "listing_rank"}
AMAZON_ASIN_GOALS = {"asin_search", "asin_verify", "identifier_verify"}
AMAZON_DATA_GOALS = {"price", "promotion", "parameters", "reviews", "channel", "service", "listing_rank"}

ROUNDS = {"1", "2", "3"}
ROUND_GOALS = {"coverage", "depth", "triangulation"}
ROUND_GOAL_MAP = {"1": "coverage", "2": "depth", "3": "triangulation"}

def parse_nonnegative_int(value: str) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def split_refs(value: str) -> list[str]:
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


def validate(path: Path, require_actual: bool = False) -> list[Issue]:
    fieldnames, rows = read_csv(path)
    issues = require_columns(fieldnames, REQUIRED)
    if issues:
        return issues

    goal_rounds: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    market_families: dict[str, set[str]] = defaultdict(set)
    model_families: dict[tuple[str, str], set[str]] = defaultdict(set)
    goal_family_assignments: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    markets: set[str] = set()
    market_model_pairs: set[tuple[str, str]] = set()
    task_ids: set[str] = set()

    gap_fieldnames: list[str] = []
    market_gaps: dict[str, dict[str, str]] = {}
    gap_path = path.parent / "11_Evidence_Issues.csv"
    if gap_path.exists():
        gap_fieldnames, gap_rows = read_csv(gap_path)
        gap_id_counts: dict[str, int] = defaultdict(int)
        for gap_row in gap_rows:
            gap_id = gap_row.get("issue_id", "").strip()
            if gap_id:
                gap_id_counts[gap_id] += 1
        for gap_id, count in sorted(gap_id_counts.items()):
            if count > 1:
                issues.append(Issue("fail", "11_Evidence_Issues.csv", "issue_id", f"Duplicate market-gap issue ID: {gap_id}"))
        market_gaps = {
            row.get("issue_id", "").strip(): row
            for row in gap_rows
            if row.get("issue_id", "").strip()
        }

    source_ledger: dict[str, dict[str, str]] = {}
    source_path = path.parent / "00_Source_Ledger.csv"
    if source_path.exists():
        _, source_rows = read_csv(source_path)
        source_ledger = {
            row.get("source_id", "").strip(): row
            for row in source_rows
            if row.get("source_id", "").strip()
        }

    declared_markets: set[str] = set()
    declared_pairs: set[tuple[str, str]] = set()
    manifest_scope_loaded = False
    quantity_policy: dict | None = None
    manifest_path = path.parent / "project_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            quantity_policy = load_project_policy(path.parent, manifest)
            declared_markets = {
                str(item).strip().casefold()
                for item in (manifest.get("target_markets") or [manifest.get("region", "")])
                if str(item).strip()
            }
            declared_pairs = {
                (str(item.get("market", "")).strip().casefold(), str(item.get("exact_model", "")).strip().casefold())
                for item in manifest.get("market_model_pairs", [])
                if isinstance(item, dict) and str(item.get("market", "")).strip() and str(item.get("exact_model", "")).strip()
            }
            manifest_scope_loaded = True
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            issues.append(Issue("fail", "project_manifest.json", "collection_quantity_policy", f"Cannot load frozen collection policy and declared scope: {exc}"))
    else:
        issues.append(Issue("fail", "project_manifest.json", "collection_quantity_policy", "Project manifest and frozen collection policy are required"))

    if quantity_policy is None:
        return issues

    required_market_families = market_goal_families(quantity_policy)
    required_model_families = model_goal_families(quantity_policy)
    all_goal_families = required_market_families | required_model_families
    minimum_model_pairs_per_market = minimum_exact_models_per_market(quantity_policy)
    completed_statuses = {str(item) for item in quantity_policy["completed_statuses"]}
    quantity_exception_types = {""} | {str(item) for item in quantity_policy["quantity_exception_types"]}
    r3_policy = quantity_policy["r3_saturation"]
    independence_policy = quantity_policy.get("source_independence")
    market_gap_policy = quantity_policy.get("market_gap_exception")
    platform_limit_policy = quantity_policy.get("platform_limit_exception")
    record_registry_policy = quantity_policy.get("record_registry")
    source_dimension_policy = quantity_policy.get("source_dimension_derivation")
    primary_qualification_policy = quantity_policy.get("primary_source_qualification")
    claim_evidence_policy = quantity_policy.get("critical_claim_evidence")
    task_rows_by_id = {
        row.get("task_id", "").strip(): row
        for row in rows
        if row.get("task_id", "").strip()
    }
    registry_by_ref: dict[str, dict[str, str]] = {}
    registry_countable_refs: set[str] = set()
    used_registry_refs: set[str] = set()
    record_file_cache: dict[Path, list[dict[str, str]]] = {}
    if record_registry_policy:
        registry_result = validate_record_registry(
            path.parent.resolve(),
            task_rows_by_id,
            source_ledger,
            record_registry_policy,
            source_dimension_policy,
        )
        registry_by_ref = registry_result.by_ref
        registry_countable_refs = registry_result.countable_refs
        for registry_label, message in registry_result.problems:
            issues.append(Issue("fail", f"registry:{registry_label}", "record_registry", message))

    for index, row in enumerate(rows, start=2):
        label = row_label(index, row)
        tool = row.get("required_tool", "").strip()
        platform = row.get("platform", "").strip().lower()
        market = row.get("market", "").strip().casefold()
        exact_model = row.get("exact_model", "").strip().casefold()
        family = row.get("goal_family", "").strip().lower()
        goal = row.get("collection_goal", "").strip().lower()
        identifier_type = row.get("identifier_type", "").strip().lower()
        identifier_value = row.get("identifier_value", "").strip()
        rnd = row.get("round", "").strip()
        rnd_goal = row.get("round_goal", "").strip().lower()
        saturation = row.get("saturation_evidence", "").strip()

        for field in ("task_id", "stage", "platform", "market", "goal_family", "collection_goal", "required_tool", "round", "round_goal", "saturation_evidence", "status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required value is blank"))

        task_id = row.get("task_id", "").strip()
        if task_id:
            if task_id in task_ids:
                issues.append(Issue("fail", label, "task_id", f"Duplicate task_id: {task_id}"))
            task_ids.add(task_id)

        if market:
            markets.add(market)
            if exact_model:
                market_model_pairs.add((market, exact_model))
        if family and family not in all_goal_families:
            issues.append(Issue("fail", label, "goal_family", f"Unknown goal_family '{family}'"))
        elif family in required_market_families and market:
            market_families[market].add(family)
        elif family in required_model_families:
            if not exact_model:
                issues.append(Issue("fail", label, "exact_model", f"Model-level goal_family '{family}' requires exact_model"))
            elif market:
                pair = (market, exact_model)
                model_families[pair].add(family)

        scoped_model = exact_model if family in required_model_families else ""
        scoped_goal = (market, scoped_model, family, goal)
        named_scope = (market, scoped_model, goal)
        if market and family and goal:
            goal_family_assignments[named_scope].add(family)

        if tool and tool not in WEB_TOOLS:
            issues.append(Issue("fail", label, "required_tool", "Web collection tasks must use kimi-webbridge or anysearch"))

        query = row.get("starting_url_or_query", "")
        if not query:
            issues.append(Issue("fail", label, "starting_url_or_query", "Task must include a URL or exact query"))
        elif query.lower().startswith(("http://", "https://")) and not is_url(query):
            issues.append(Issue("fail", label, "starting_url_or_query", "URL must be http(s)"))

        if rnd:
            if rnd not in ROUNDS:
                issues.append(Issue("fail", label, "round", f"round must be one of 1/2/3, got '{rnd}'"))
            elif market and family and goal:
                goal_rounds[scoped_goal].add(rnd)
        if rnd_goal:
            if rnd_goal not in ROUND_GOALS:
                issues.append(Issue("fail", label, "round_goal", f"round_goal must be one of coverage/depth/triangulation, got '{rnd_goal}'"))
            elif rnd in ROUNDS and ROUND_GOAL_MAP[rnd] != rnd_goal:
                issues.append(Issue("fail", label, "round_goal", f"round {rnd} must use round_goal={ROUND_GOAL_MAP[rnd]}, got '{rnd_goal}'"))
        if rnd == "3" and not saturation and not row.get("cross_check_source", "").strip():
            issues.append(Issue("fail", label, "saturation_evidence", "Round 3 must declare saturation evidence or a cross-check source"))

        if family in all_goal_families and rnd in ROUNDS:
            floor = round_floor(family, rnd, quantity_policy)
            min_sources = floor["min_unique_sources"]
            min_records = floor["min_records"]
            min_types = floor["min_source_types"]
            min_platforms = floor["min_platforms"]
            min_primary = floor["min_primary_sources"]
            target_sources = parse_nonnegative_int(row.get("target_unique_sources", ""))
            target_records = parse_nonnegative_int(row.get("target_records", ""))
            if target_sources is None:
                issues.append(Issue("fail", label, "target_unique_sources", "A nonnegative integer target is required for every R1/R2/R3 task"))
            elif target_sources < min_sources:
                issues.append(Issue("fail", label, "target_unique_sources", f"{family} round {rnd} requires at least {min_sources} unique sources"))
            if target_records is None:
                issues.append(Issue("fail", label, "target_records", "A nonnegative integer target is required for every R1/R2/R3 task"))
            elif target_records < min_records:
                issues.append(Issue("fail", label, "target_records", f"{family} round {rnd} requires at least {min_records} structured records"))

            expected_coverage = policy_coverage_requirement(family, quantity_policy)
            if row.get("coverage_requirement", "").strip().lower() != expected_coverage:
                issues.append(Issue("fail", label, "coverage_requirement", f"{family} must use coverage_requirement={expected_coverage}"))

            exception_type = row.get("quantity_exception_type", "").strip().lower()
            if exception_type not in quantity_exception_types:
                issues.append(Issue("fail", label, "quantity_exception_type", "Use blank, market_gap, or platform_limit"))

            if require_actual:
                status = row.get("status", "").strip().lower()
                if status not in completed_statuses:
                    issues.append(Issue("fail", label, "status", f"Final collection audit requires a completed status; got '{status}'"))

                actual_sources = parse_nonnegative_int(row.get("actual_unique_sources", ""))
                actual_records = parse_nonnegative_int(row.get("actual_records", ""))
                source_types = parse_nonnegative_int(row.get("source_type_count", ""))
                platforms = parse_nonnegative_int(row.get("platform_count", ""))
                primary_sources = parse_nonnegative_int(row.get("primary_source_count", ""))
                critical_claims = parse_nonnegative_int(row.get("critical_claim_count", ""))
                dual_sourced = parse_nonnegative_int(row.get("dual_sourced_claim_count", ""))
                remaining_priority = parse_nonnegative_int(row.get("remaining_high_priority_count", ""))
                no_new_batches = parse_nonnegative_int(row.get("no_new_high_priority_batches", ""))
                actual_values = {
                    "actual_unique_sources": actual_sources,
                    "actual_records": actual_records,
                    "source_type_count": source_types,
                    "platform_count": platforms,
                    "primary_source_count": primary_sources,
                    "critical_claim_count": critical_claims,
                    "dual_sourced_claim_count": dual_sourced,
                    "remaining_high_priority_count": remaining_priority,
                    "no_new_high_priority_batches": no_new_batches,
                }
                for field, value in actual_values.items():
                    if value is None:
                        issues.append(Issue("fail", label, field, "Final collection audit requires a nonnegative integer actual count"))

                exception_valid = False
                exception_refs = split_refs(row.get("quantity_exception_refs", ""))
                if exception_type == "market_gap":
                    if family == "economics_and_model_inputs":
                        issues.append(Issue("fail", label, "quantity_exception_type", "Missing mathematical-model inputs must be simulated and cannot use a market-gap quantity exception"))
                    elif not exception_refs:
                        issues.append(Issue("fail", label, "quantity_exception_refs", "market_gap exception requires linked 11_Evidence_Issues IDs"))
                    unknown = sorted(set(exception_refs) - set(market_gaps))
                    if unknown:
                        issues.append(Issue("fail", label, "quantity_exception_refs", f"Unknown market-gap IDs: {unknown}"))
                    gap_problems: list[tuple[str, str]] = []
                    if market_gap_policy and exception_refs and not unknown:
                        missing_gap_headers = sorted(GAP_AUDIT_FIELDS - set(gap_fieldnames))
                        if missing_gap_headers:
                            gap_problems.append(("quantity_exception_refs", f"11_Evidence_Issues.csv is missing policy-v3 gap-audit fields: {missing_gap_headers}"))
                        else:
                            for gap_id in exception_refs:
                                gap_problems.extend(
                                    validate_market_gap_exception(
                                        path.parent.resolve(),
                                        row,
                                        task_rows_by_id,
                                        market_gaps[gap_id],
                                        source_ledger,
                                        market_gap_policy,
                                        completed_statuses,
                                    )
                                )
                        for field, message in gap_problems:
                            issues.append(Issue("fail", label, field, message))
                    elif exception_refs and not unknown:
                        non_market = [
                            gap_id
                            for gap_id in exception_refs
                            if market_gaps[gap_id].get("data_domain", "").strip().casefold() != "market"
                        ]
                        if non_market:
                            gap_problems.append(("quantity_exception_refs", f"Non-market gap IDs: {non_market}"))
                            for field, message in gap_problems:
                                issues.append(Issue("fail", label, field, message))
                    exception_valid = (
                        family != "economics_and_model_inputs"
                        and bool(exception_refs)
                        and not unknown
                        and not gap_problems
                    )
                elif exception_type == "platform_limit":
                    if platform_limit_policy:
                        platform_problems = validate_platform_limit_exception(
                            path.parent.resolve(),
                            row,
                            task_rows_by_id,
                            source_ledger,
                            platform_limit_policy,
                            completed_statuses,
                        )
                        for field, message in platform_problems:
                            issues.append(Issue("fail", label, field, message))
                        exception_valid = not platform_problems
                    elif family != "reviews_and_user_voice" or rnd != "2":
                        issues.append(Issue("fail", label, "quantity_exception_type", "platform_limit is allowed only for reviews_and_user_voice round 2"))
                    elif not row.get("platform_limit_evidence", "").strip():
                        issues.append(Issue("fail", label, "platform_limit_evidence", "Review corpus below the configured target requires evidence of the visible platform limit"))
                    else:
                        exception_valid = True

                if actual_sources is not None and target_sources is not None and actual_sources < target_sources:
                    if not (exception_type == "market_gap" and exception_valid):
                        issues.append(Issue("fail", label, "actual_unique_sources", f"Actual unique sources {actual_sources} are below target {target_sources}"))
                if actual_records is not None and target_records is not None and actual_records < target_records:
                    if not exception_valid:
                        issues.append(Issue("fail", label, "actual_records", f"Actual records {actual_records} are below target {target_records}"))
                if source_types is not None and source_types < min_types:
                    issues.append(Issue("fail", label, "source_type_count", f"Round floor is {min_types} source types"))
                if platforms is not None and platforms < min_platforms:
                    issues.append(Issue("fail", label, "platform_count", f"Round floor is {min_platforms} platforms"))
                if primary_sources is not None and primary_sources < min_primary:
                    issues.append(Issue("fail", label, "primary_source_count", f"Round floor is {min_primary} primary/official sources"))
                audit_value = row.get("count_evidence_refs", "").strip()
                if not audit_value:
                    issues.append(Issue("fail", label, "count_evidence_refs", "Actual counts require a project-relative count-evidence JSON path"))
                else:
                    audit_path = (path.parent / audit_value).resolve()
                    project_root = path.parent.resolve()
                    if not audit_path.is_relative_to(project_root):
                        issues.append(Issue("fail", label, "count_evidence_refs", "Count-evidence JSON must remain inside the project directory"))
                    elif not audit_path.exists():
                        issues.append(Issue("fail", label, "count_evidence_refs", f"Count-evidence JSON does not exist: {audit_value}"))
                    else:
                        try:
                            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
                        except (OSError, json.JSONDecodeError) as exc:
                            issues.append(Issue("fail", label, "count_evidence_refs", f"Unreadable count-evidence JSON: {exc}"))
                            audit = None
                        if isinstance(audit, dict):
                            if str(audit.get("task_id", "")).strip() != task_id:
                                issues.append(Issue("fail", label, "count_evidence_refs", "Count-evidence task_id must match the task row"))
                            audit_source_ids = {str(item).strip() for item in audit.get("unique_source_ids", []) if str(item).strip()}
                            record_ref_items = [str(item).strip() for item in audit.get("record_refs", []) if str(item).strip()]
                            record_refs = set(record_ref_items)
                            if len(record_ref_items) != len(record_refs):
                                issues.append(Issue("fail", label, "count_evidence_refs", "record_refs cannot contain duplicates"))
                            source_type_items = audit.get("source_types", [])
                            platform_items = audit.get("platforms", [])
                            if not isinstance(source_type_items, list):
                                issues.append(Issue("fail", label, "count_evidence_refs", "source_types must be an array"))
                                source_type_items = []
                            if not isinstance(platform_items, list):
                                issues.append(Issue("fail", label, "count_evidence_refs", "platforms must be an array"))
                                platform_items = []
                            source_types_audit = {str(item).strip().casefold() for item in source_type_items if str(item).strip()}
                            platforms_audit = {str(item).strip().casefold() for item in platform_items if str(item).strip()}
                            primary_id_items = audit.get("primary_source_ids", [])
                            if not isinstance(primary_id_items, list):
                                issues.append(Issue("fail", label, "count_evidence_refs", "primary_source_ids must be an array"))
                                primary_id_items = []
                            primary_ids = {str(item).strip() for item in primary_id_items if str(item).strip()}
                            claims = audit.get("critical_claims", []) if isinstance(audit.get("critical_claims", []), list) else []
                            remaining_ids = {str(item).strip() for item in audit.get("high_priority_remaining_ids", []) if str(item).strip()}
                            batches = audit.get("query_batches", []) if isinstance(audit.get("query_batches", []), list) else []

                            unknown_sources = sorted(audit_source_ids - set(source_ledger))
                            if unknown_sources:
                                issues.append(Issue("fail", label, "count_evidence_refs", f"Unknown source-ledger IDs: {unknown_sources}"))
                            known_audit_sources = audit_source_ids & set(source_ledger)
                            derived_source_types = {
                                source_ledger[source_id].get("source_type", "").strip().casefold()
                                for source_id in known_audit_sources
                                if source_ledger[source_id].get("source_type", "").strip()
                            }
                            platform_id_field = str((source_dimension_policy or {}).get("platform_id_field", "platform_id"))
                            derived_platforms = {
                                source_ledger[source_id].get(platform_id_field, "").strip().casefold()
                                for source_id in known_audit_sources
                                if source_ledger[source_id].get(platform_id_field, "").strip()
                            }
                            if source_dimension_policy:
                                missing_source_types = sorted(
                                    source_id for source_id in known_audit_sources
                                    if not source_ledger[source_id].get("source_type", "").strip()
                                )
                                missing_platform_ids = sorted(
                                    source_id for source_id in known_audit_sources
                                    if not source_ledger[source_id].get(platform_id_field, "").strip()
                                )
                                if missing_source_types:
                                    issues.append(Issue("fail", label, "count_evidence_refs", f"Counted sources lack controlled source_type values: {missing_source_types}"))
                                if source_dimension_policy["require_platform_id_for_counted_sources"] and missing_platform_ids:
                                    issues.append(Issue("fail", label, "count_evidence_refs", f"Counted sources lack platform_id values: {missing_platform_ids}"))
                                if source_dimension_policy["require_declarations_match_derived"]:
                                    if source_types_audit != derived_source_types:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Declared source_types must exactly match source-ledger-derived values: {sorted(derived_source_types)}"))
                                    if platforms_audit != derived_platforms:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Declared platforms must exactly match source-ledger-derived platform_id values: {sorted(derived_platforms)}"))
                            if not primary_ids.issubset(audit_source_ids):
                                issues.append(Issue("fail", label, "count_evidence_refs", "primary_source_ids must be a subset of unique_source_ids"))
                            derived_primary_ids = set(primary_ids)
                            if primary_qualification_policy:
                                eligible_types = {
                                    str(item).strip().casefold()
                                    for item in primary_qualification_policy["eligible_source_types_by_goal_family"].get(family, [])
                                    if str(item).strip()
                                }
                                eligible_statuses = {
                                    str(item).strip().casefold()
                                    for item in primary_qualification_policy["countable_verification_statuses"]
                                    if str(item).strip()
                                }
                                eligible_relations = {
                                    str(item).strip().casefold()
                                    for item in primary_qualification_policy["countable_relation_types"]
                                    if str(item).strip()
                                }
                                allowed_tiers_by_type = {
                                    str(source_type).strip().casefold(): {
                                        str(tier).strip().casefold() for tier in tiers if str(tier).strip()
                                    }
                                    for source_type, tiers in primary_qualification_policy["allowed_tiers_by_source_type"].items()
                                }
                                derived_primary_ids = set()
                                for source_id in known_audit_sources:
                                    source = source_ledger[source_id]
                                    source_type = source.get("source_type", "").strip().casefold()
                                    tier = source.get("reliability_tier", "").strip().casefold().replace(" ", "")
                                    relation = source.get("source_relation_type", "").strip().casefold()
                                    verification = source.get("verification_status", "").strip().casefold()
                                    if (
                                        source_type in eligible_types
                                        and tier in allowed_tiers_by_type.get(source_type, set())
                                        and relation in eligible_relations
                                        and verification in eligible_statuses
                                    ):
                                        derived_primary_ids.add(source_id)
                                if primary_qualification_policy["require_declaration_match_derived"] and primary_ids != derived_primary_ids:
                                    issues.append(
                                        Issue(
                                            "fail",
                                            label,
                                            "count_evidence_refs",
                                            f"Declared primary_source_ids must exactly match task-qualified source-ledger values: {sorted(derived_primary_ids)}",
                                        )
                                    )
                            else:
                                for source_id in sorted(primary_ids & set(source_ledger)):
                                    tier = source_ledger[source_id].get("reliability_tier", "").strip().lower().replace(" ", "")
                                    if tier not in {"tier0", "tier1"}:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Primary source {source_id} must be Tier 0 or Tier 1"))
                            registry_source_ids_for_audit: set[str] = set()
                            for ref in sorted(record_refs):
                                if "#" not in ref:
                                    issues.append(Issue("fail", label, "count_evidence_refs", f"Record ref must use relative.csv#row_number: {ref}"))
                                    continue
                                rel_name, row_number_text = ref.rsplit("#", 1)
                                try:
                                    row_number = int(row_number_text)
                                except ValueError:
                                    row_number = 0
                                record_path = (project_root / rel_name).resolve()
                                if not record_path.is_relative_to(project_root) or record_path.suffix.lower() != ".csv" or not record_path.exists():
                                    issues.append(Issue("fail", label, "count_evidence_refs", f"Invalid record-ref file: {ref}"))
                                    continue
                                if record_path in record_file_cache:
                                    referenced_rows = record_file_cache[record_path]
                                else:
                                    _, referenced_rows = read_csv(record_path)
                                    record_file_cache[record_path] = referenced_rows
                                if row_number < 2 or row_number > len(referenced_rows) + 1:
                                    issues.append(Issue("fail", label, "count_evidence_refs", f"Record-ref row is out of range: {ref}"))
                                if record_registry_policy:
                                    registry_row = registry_by_ref.get(ref)
                                    if registry_row is None:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Counted record is not registered: {ref}"))
                                    elif registry_row.get("owner_task_id", "").strip() != task_id:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Counted record is owned by another task: {ref}"))
                                    elif registry_row.get("counts_toward_floor", "").strip().casefold() not in {"true", "1", "yes"}:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Registry record is not countable: {ref}"))
                                    elif not set(split_refs(registry_row.get("source_ids", ""))).issubset(audit_source_ids):
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Registry record source_ids are not listed in the owner task count audit: {ref}"))
                                    else:
                                        registry_source_ids_for_audit.update(split_refs(registry_row.get("source_ids", "")))
                                        used_registry_refs.add(ref)

                            if (
                                source_dimension_policy
                                and source_dimension_policy["require_every_counted_source_linked_to_record"]
                                and registry_source_ids_for_audit != audit_source_ids
                            ):
                                unused = sorted(audit_source_ids - registry_source_ids_for_audit)
                                extra = sorted(registry_source_ids_for_audit - audit_source_ids)
                                issues.append(
                                    Issue(
                                        "fail",
                                        label,
                                        "count_evidence_refs",
                                        f"Counted sources must be exactly the sources linked by current-task record_refs; unused={unused}, extra={extra}",
                                    )
                                )

                            dual_claims = 0
                            if claim_evidence_policy:
                                _, dual_claims, claim_problems = validate_critical_claims(
                                    claims,
                                    task_id,
                                    audit_source_ids,
                                    record_refs,
                                    project_root,
                                    registry_by_ref,
                                    source_ledger,
                                    record_file_cache,
                                    claim_evidence_policy,
                                    independence_policy,
                                )
                                for message in claim_problems:
                                    issues.append(Issue("fail", label, "count_evidence_refs", message))
                            else:
                                for claim in claims:
                                    if not isinstance(claim, dict) or not str(claim.get("claim_id", "")).strip():
                                        issues.append(Issue("fail", label, "count_evidence_refs", "Every critical claim requires a claim_id"))
                                        continue
                                    claim_sources = {str(item).strip() for item in claim.get("source_ids", []) if str(item).strip()}
                                    unknown_claim_sources = sorted(claim_sources - audit_source_ids)
                                    if unknown_claim_sources:
                                        issues.append(Issue("fail", label, "count_evidence_refs", f"Critical claim uses unlisted source IDs: {unknown_claim_sources}"))
                                    if independence_policy:
                                        independent, _, reasons = evaluate_claim_independence(
                                            claim_sources,
                                            source_ledger,
                                            independence_policy,
                                        )
                                        if independent:
                                            dual_claims += 1
                                        else:
                                            issues.append(
                                                Issue(
                                                    "fail",
                                                    label,
                                                    "count_evidence_refs",
                                                    f"Critical claim {claim.get('claim_id')} lacks independent triangulation: {'; '.join(reasons)}",
                                                )
                                            )
                                    elif len(claim_sources) >= 2:
                                        dual_claims += 1

                            trailing_no_new = 0
                            for batch in reversed(batches):
                                if not isinstance(batch, dict) or batch.get("new_high_priority_ids"):
                                    break
                                trailing_no_new += 1

                            derived_counts = {
                                "actual_unique_sources": len(audit_source_ids),
                                "actual_records": len(record_refs),
                                "source_type_count": len(derived_source_types) if source_dimension_policy else len(source_types_audit),
                                "platform_count": len(derived_platforms) if source_dimension_policy else len(platforms_audit),
                                "primary_source_count": len(derived_primary_ids),
                                "critical_claim_count": len(claims),
                                "dual_sourced_claim_count": dual_claims,
                                "remaining_high_priority_count": len(remaining_ids),
                                "no_new_high_priority_batches": trailing_no_new,
                            }
                            for field, derived in derived_counts.items():
                                if actual_values.get(field) is not None and actual_values[field] != derived:
                                    issues.append(Issue("fail", label, field, f"Self-reported count {actual_values[field]} does not match count-evidence JSON value {derived}"))
                if rnd == "3":
                    min_claims = int(r3_policy["minimum_critical_claims"])
                    # CHANGELOG v1.2.6: "verified saturation claim" exemption.
                    # A task may close R3 without a dual-sourced claim when all
                    # of the following hold:
                    #   1) an approved market_gap exception is in force for this
                    #      task (exception_valid),
                    #   2) the count-evidence JSON has no remaining high-priority
                    #      discoveries,
                    #   3) the linked gap evidence JSON documents real R3
                    #      attempts (rounds[3].failure_reasons non-blank),
                    # which means the market itself verified the gap.
                    saturation_ok = False
                    if (
                        critical_claims is not None
                        and critical_claims < min_claims
                        and exception_type == "market_gap"
                        and exception_valid
                        and not remaining_ids
                    ):
                        for gid in sorted(exception_refs):
                            gap_row = market_gaps.get(gid)
                            if not gap_row:
                                continue
                            ev_value = str(gap_row.get("gap_evidence_path", "")).strip()
                            if not ev_value:
                                continue
                            ev_path = Path(ev_value)
                            if not ev_path.is_absolute():
                                ev_path = path.parent / ev_path
                            try:
                                ev = json.loads(ev_path.read_text(encoding="utf-8-sig"))
                            except (OSError, ValueError):
                                continue
                            round3 = [
                                r for r in ev.get("rounds", [])
                                if isinstance(r, dict) and str(r.get("round", "")).strip() == "3"
                            ]
                            if round3 and any(str(f).strip() for f in (round3[0].get("failure_reasons") or [])):
                                saturation_ok = True
                                break
                    if critical_claims is not None and critical_claims < min_claims and not saturation_ok:
                        issues.append(Issue("fail", label, "critical_claim_count", f"Round 3 requires at least {min_claims} critical claim(s) or a verified saturation claim (approved market_gap with documented R3 attempts)"))
                    if critical_claims is not None and dual_sourced is not None and dual_sourced < critical_claims and not saturation_ok:
                        issues.append(Issue("fail", label, "dual_sourced_claim_count", "Every Round 3 critical claim must have at least two independent sources"))
                    if bool(r3_policy["require_zero_remaining_high_priority"]) and remaining_priority is not None and remaining_priority != 0:
                        issues.append(Issue("fail", label, "remaining_high_priority_count", "Round 3 cannot close while high-priority discoveries remain unexpanded"))
                    min_batches = int(r3_policy["minimum_no_new_high_priority_batches"])
                    if no_new_batches is not None and no_new_batches < min_batches:
                        issues.append(Issue("fail", label, "no_new_high_priority_batches", f"Round 3 requires at least {min_batches} consecutive final query batches with no new high-priority discoveries"))

        if goal in PRODUCT_GOALS:
            if not row.get("exact_model"):
                issues.append(Issue("fail", label, "exact_model", "Product-level collection requires exact_model"))
            if not row.get("identifier_type") or not row.get("identifier_value"):
                issues.append(Issue("fail", label, "identifier", "Product-level collection requires identifier_type and identifier_value"))

        if "amazon" in platform and goal in ({"asin_verify"} | AMAZON_DATA_GOALS):
            if identifier_type != "asin":
                issues.append(Issue("fail", label, "identifier_type", "Amazon product tasks must use identifier_type=ASIN"))
            if identifier_value and not is_asin(identifier_value.upper()):
                issues.append(Issue("fail", label, "identifier_value", "Amazon ASIN should be 10 uppercase letters/digits"))

        if "amazon" in platform and goal in AMAZON_DATA_GOALS:
            brand = row.get("target_brand", "").strip().casefold()
            model = exact_model
            has_prior_asin_task = False
            for prior in rows[: index - 2]:
                if "amazon" not in prior.get("platform", "").strip().lower():
                    continue
                if prior.get("collection_goal", "").strip().lower() not in AMAZON_ASIN_GOALS:
                    continue
                prior_brand = prior.get("target_brand", "").strip().casefold()
                prior_model = prior.get("exact_model", "").strip().casefold()
                if brand and prior_brand and prior_brand != brand:
                    continue
                if model and prior_model and prior_model != model:
                    continue
                prior_asin = prior.get("identifier_value", "").strip().upper()
                current_asin = identifier_value.upper()
                if prior_asin and current_asin and prior_asin != current_asin:
                    continue
                has_prior_asin_task = True
                break
            if not has_prior_asin_task:
                issues.append(Issue("fail", label, "amazon_asin_sequence", "Amazon product data requires an earlier ASIN discovery/verification task for the same exact model"))

        if goal in {"reviews", "parameters"} and not row.get("raw_capture_path"):
            issues.append(Issue("warn", label, "raw_capture_path", "Review or parameter tasks should save raw capture output"))
        if not row.get("output_file"):
            issues.append(Issue("warn", label, "output_file", "Task should define the target output file"))

    if require_actual and record_registry_policy:
        orphan_countable_refs = sorted(registry_countable_refs - used_registry_refs)
        for ref in orphan_countable_refs:
            issues.append(Issue("fail", "record_registry", "record_ref", f"Countable registry record is not used by its owner task audit: {ref}"))

    if not rows:
        issues.append(Issue("fail", "collection_plan", "rows", "Collection plan must contain saturated goals and cannot be empty"))
    if rows and not markets:
        issues.append(Issue("fail", "collection_plan", "market", "At least one target market is required"))

    if manifest_scope_loaded:
        for market in sorted(declared_markets - markets):
            issues.append(Issue("fail", market, "declared_market_scope", "Declared target market has no collection goals"))
        for market in sorted(markets - declared_markets):
            issues.append(Issue("fail", market, "declared_market_scope", "Collection market is not registered in project_manifest.json; update the approved scope"))
        for market, model in sorted(declared_pairs - market_model_pairs):
            issues.append(Issue("fail", f"{market}/{model}", "declared_model_scope", "Declared market-model pair has no collection goals"))
        for market, model in sorted(market_model_pairs - declared_pairs):
            issues.append(Issue("fail", f"{market}/{model}", "declared_model_scope", "Discovered market-model pair must be registered in project_manifest.json before continuing"))

    quota_markets = declared_markets if manifest_scope_loaded else markets
    quota_pairs = declared_pairs if manifest_scope_loaded else market_model_pairs

    for market in sorted(quota_markets):
        pair_count = len({model for pair_market, model in quota_pairs if pair_market == market})
        if pair_count < minimum_model_pairs_per_market:
            issues.append(
                Issue(
                    "fail",
                    market,
                    "declared_model_quota",
                    f"Each target market requires at least {minimum_model_pairs_per_market} distinct exact-model pairs; found {pair_count}",
                )
            )

    for market in sorted(markets):
        missing = sorted(required_market_families - market_families[market])
        if missing:
            issues.append(Issue("fail", market, "market_goal_families", f"Missing required market-level goal families: {missing}"))

    for market, model in sorted(market_model_pairs):
        missing = sorted(required_model_families - model_families[(market, model)])
        if missing:
            issues.append(Issue("fail", f"{market}/{model}", "model_goal_families", f"Missing required model-level goal families: {missing}"))

    for scope, families in sorted(goal_family_assignments.items()):
        if len(families) > 1:
            issues.append(Issue("fail", "/".join(scope), "goal_family", f"One scoped collection_goal cannot map to multiple families: {sorted(families)}"))

    minimum_pair_count = max(len(quota_pairs), len(quota_markets) * minimum_model_pairs_per_market)
    minimum_goals = len(quota_markets) * len(required_market_families) + minimum_pair_count * len(required_model_families)
    actual_goals = len(goal_rounds)
    if actual_goals < minimum_goals:
        issues.append(Issue("fail", "collection_plan", "goal_count", f"Saturated floor is {minimum_goals} scoped goals (={len(required_market_families)} x {len(quota_markets)} markets + {len(required_model_families)} x at least {minimum_pair_count} market-model pairs, loaded from the frozen project YAML policy); found {actual_goals}"))
    minimum_rows = minimum_goals * 3
    if len(rows) < minimum_rows:
        issues.append(Issue("fail", "collection_plan", "task_row_count", f"Saturated three-round floor is {minimum_rows} task rows; found {len(rows)}"))

    for scoped_goal, rounds in sorted(goal_rounds.items()):
        missing = sorted(ROUNDS - rounds)
        if missing:
            display = "/".join(part for part in scoped_goal if part)
            issues.append(Issue("fail", display, "round_sequence", f"Scoped collection_goal must have rounds 1/2/3; missing: {missing}. Three rounds are mandatory"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate saturated collection goals and mandatory three-round tasks before crawling.")
    parser.add_argument("--project-dir", default=".", help="Project directory containing 02_Web_Collection_Tasks.csv.")
    parser.add_argument("--file", help="Explicit collection task CSV path.")
    parser.add_argument("--require-actual", action="store_true", help="Require completed status and actual source/record counts for final audit.")
    add_common_args(parser)
    args = parser.parse_args()
    path = resolve_project_file(Path(args.project_dir).resolve(), args.file, ["02_Web_Collection_Tasks.csv", "web_collection_tasks.csv"])
    return print_report("Web collection task validation (saturated goals + 3 rounds)", validate(path, require_actual=args.require_actual), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
