from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - depends on the host runtime
    raise RuntimeError(
        "The overseas-energy-market-research quantity policy requires PyYAML. "
        "Install it in the Python runtime used to run this skill."
    ) from exc


POLICY_PATH = Path(__file__).resolve().parents[1] / "assets" / "config" / "collection_quantity_policy.yaml"
POLICY_SNAPSHOT_RELATIVE_PATH = Path("policy_snapshot") / "collection_quantity_policy.yaml"
MANIFEST_VERSION_FIELD = "collection_quantity_policy_version"
MANIFEST_SHA256_FIELD = "collection_quantity_policy_sha256"
MANIFEST_SNAPSHOT_FIELD = "collection_quantity_policy_snapshot_path"
MANIFEST_FROZEN_AT_FIELD = "collection_quantity_policy_frozen_at"
FLOOR_KEYS = (
    "min_unique_sources",
    "min_records",
    "min_source_types",
    "min_platforms",
    "min_primary_sources",
)


def validate_policy(data: object, path: Path) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"Quantity policy must be a YAML mapping: {path}")
    required = {
        "policy_version",
        "minimum_exact_models_per_market",
        "market_goal_families",
        "model_goal_families",
        "default_coverage_requirement",
        "completed_statuses",
        "quantity_exception_types",
        "r3_saturation",
        "families",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"Quantity policy missing keys: {missing}")

    market_families = {str(item) for item in data["market_goal_families"]}
    model_families = {str(item) for item in data["model_goal_families"]}
    configured = set(data["families"])
    if configured != market_families | model_families:
        raise ValueError("Quantity policy family list and families mapping must match exactly")
    for family, family_policy in data["families"].items():
        rounds = family_policy.get("rounds", {})
        if set(str(key) for key in rounds) != {"1", "2", "3"}:
            raise ValueError(f"{family} must define rounds 1/2/3")
        for round_number, floor in rounds.items():
            missing_floor = [key for key in FLOOR_KEYS if key not in floor]
            if missing_floor:
                raise ValueError(f"{family} round {round_number} missing floor keys: {missing_floor}")
            if any(not isinstance(floor[key], int) or floor[key] < 0 for key in FLOOR_KEYS):
                raise ValueError(f"{family} round {round_number} floors must be nonnegative integers")
    if int(data["minimum_exact_models_per_market"]) < 1:
        raise ValueError("minimum_exact_models_per_market must be positive")
    if int(data["policy_version"]) >= 2:
        independence = data.get("source_independence")
        if not isinstance(independence, dict):
            raise ValueError("Policy version 2+ requires source_independence")
        independence_keys = {
            "minimum_independent_sources_per_critical_claim",
            "minimum_distinct_source_types_per_critical_claim",
            "require_distinct_publisher_groups",
            "require_distinct_root_domains",
            "require_distinct_canonical_sources",
            "allowed_source_types",
            "allowed_relation_types",
            "derivative_relation_types",
        }
        missing_independence = sorted(independence_keys - set(independence))
        if missing_independence:
            raise ValueError(f"source_independence missing keys: {missing_independence}")
        for key in (
            "minimum_independent_sources_per_critical_claim",
            "minimum_distinct_source_types_per_critical_claim",
        ):
            if not isinstance(independence[key], int) or independence[key] < 2:
                raise ValueError(f"source_independence.{key} must be an integer >= 2")
        allowed_types = {str(item).strip() for item in independence["allowed_source_types"] if str(item).strip()}
        allowed_relations = {str(item).strip() for item in independence["allowed_relation_types"] if str(item).strip()}
        derivative_relations = {str(item).strip() for item in independence["derivative_relation_types"] if str(item).strip()}
        if not allowed_types or not allowed_relations:
            raise ValueError("source_independence allowed source/relation type lists cannot be empty")
        if not derivative_relations.issubset(allowed_relations):
            raise ValueError("source_independence derivative relations must be allowed relation types")
    if int(data["policy_version"]) >= 3:
        gap_policy = data.get("market_gap_exception")
        if not isinstance(gap_policy, dict):
            raise ValueError("Policy version 3+ requires market_gap_exception")
        gap_keys = {
            "required_rounds",
            "required_issue_type",
            "require_zero_remaining_high_priority",
            "approval_status",
            "minimum_attempted_sources_per_round",
            "minimum_queries_per_round",
            "minimum_failure_reasons_per_round",
            "minimum_raw_capture_refs_per_round",
            "required_gap_fields",
        }
        missing_gap = sorted(gap_keys - set(gap_policy))
        if missing_gap:
            raise ValueError(f"market_gap_exception missing keys: {missing_gap}")
        if {str(item) for item in gap_policy["required_rounds"]} != {"1", "2", "3"}:
            raise ValueError("market_gap_exception.required_rounds must contain exactly 1/2/3")
        for key in (
            "minimum_attempted_sources_per_round",
            "minimum_queries_per_round",
            "minimum_failure_reasons_per_round",
            "minimum_raw_capture_refs_per_round",
        ):
            if not isinstance(gap_policy[key], int) or gap_policy[key] < 1:
                raise ValueError(f"market_gap_exception.{key} must be a positive integer")
        if not str(gap_policy["approval_status"]).strip():
            raise ValueError("market_gap_exception.approval_status cannot be blank")
        if not str(gap_policy["required_issue_type"]).strip():
            raise ValueError("market_gap_exception.required_issue_type cannot be blank")
        if not {str(item).strip() for item in gap_policy["required_gap_fields"] if str(item).strip()}:
            raise ValueError("market_gap_exception.required_gap_fields cannot be empty")
    if int(data["policy_version"]) >= 4:
        platform_policy = data.get("platform_limit_exception")
        if not isinstance(platform_policy, dict):
            raise ValueError("Policy version 4+ requires platform_limit_exception")
        platform_keys = {
            "required_goal_family",
            "required_round",
            "required_rounds",
            "minimum_platform_entries",
            "minimum_attempt_methods_per_platform",
            "minimum_raw_capture_refs_per_platform",
            "minimum_source_ids_per_platform",
            "require_collected_equals_accessible_max",
            "require_zero_remaining_high_priority",
            "approval_status",
        }
        missing_platform = sorted(platform_keys - set(platform_policy))
        if missing_platform:
            raise ValueError(f"platform_limit_exception missing keys: {missing_platform}")
        if {str(item) for item in platform_policy["required_rounds"]} != {"1", "2", "3"}:
            raise ValueError("platform_limit_exception.required_rounds must contain exactly 1/2/3")
        if str(platform_policy["required_round"]) != "2":
            raise ValueError("platform_limit_exception.required_round must be 2")
        if str(platform_policy["required_goal_family"]).strip() != "reviews_and_user_voice":
            raise ValueError("platform_limit_exception.required_goal_family must be reviews_and_user_voice")
        for key in (
            "minimum_platform_entries",
            "minimum_attempt_methods_per_platform",
            "minimum_raw_capture_refs_per_platform",
            "minimum_source_ids_per_platform",
        ):
            if not isinstance(platform_policy[key], int) or platform_policy[key] < 1:
                raise ValueError(f"platform_limit_exception.{key} must be a positive integer")
        for key in ("require_collected_equals_accessible_max", "require_zero_remaining_high_priority"):
            if not isinstance(platform_policy[key], bool):
                raise ValueError(f"platform_limit_exception.{key} must be true or false")
        if not str(platform_policy["approval_status"]).strip():
            raise ValueError("platform_limit_exception.approval_status cannot be blank")
    if int(data["policy_version"]) >= 5:
        registry = data.get("record_registry")
        if not isinstance(registry, dict):
            raise ValueError("Policy version 5+ requires record_registry")
        registry_keys = {
            "file_name",
            "hash_algorithm",
            "allowed_novelty_types",
            "countable_novelty_types",
            "countable_statuses",
            "require_unique_record_ref",
            "require_unique_countable_content_hash",
            "require_owner_scope_match",
            "require_material_enrichment_for_reused_canonical_key",
            "excluded_hash_fields",
            "excluded_hash_field_prefixes",
        }
        missing_registry = sorted(registry_keys - set(registry))
        if missing_registry:
            raise ValueError(f"record_registry missing keys: {missing_registry}")
        if Path(str(registry["file_name"])).name != str(registry["file_name"]) or not str(registry["file_name"]).endswith(".csv"):
            raise ValueError("record_registry.file_name must be a simple CSV file name")
        if str(registry["hash_algorithm"]).casefold() != "sha256":
            raise ValueError("record_registry.hash_algorithm must be sha256")
        allowed_novelty = {str(item).strip() for item in registry["allowed_novelty_types"] if str(item).strip()}
        countable_novelty = {str(item).strip() for item in registry["countable_novelty_types"] if str(item).strip()}
        statuses = {str(item).strip() for item in registry["countable_statuses"] if str(item).strip()}
        if not allowed_novelty or not countable_novelty.issubset(allowed_novelty):
            raise ValueError("record_registry countable novelty types must be a nonempty subset of allowed types")
        if not statuses:
            raise ValueError("record_registry.countable_statuses cannot be empty")
        for key in (
            "require_unique_record_ref",
            "require_unique_countable_content_hash",
            "require_owner_scope_match",
            "require_material_enrichment_for_reused_canonical_key",
        ):
            if not isinstance(registry[key], bool):
                raise ValueError(f"record_registry.{key} must be true or false")
        if not isinstance(registry["excluded_hash_fields"], list) or not isinstance(registry["excluded_hash_field_prefixes"], list):
            raise ValueError("record_registry hash exclusions must be arrays")
    if int(data["policy_version"]) >= 6:
        dimensions = data.get("source_dimension_derivation")
        if not isinstance(dimensions, dict):
            raise ValueError("Policy version 6+ requires source_dimension_derivation")
        dimension_keys = {
            "platform_id_field",
            "platform_id_pattern",
            "require_web_platform_id_equals_root_domain",
            "local_platform_id",
            "require_platform_id_for_counted_sources",
            "require_declarations_match_derived",
            "require_every_counted_source_linked_to_record",
            "require_root_domain_platform_consistency",
            "require_canonical_platform_consistency",
            "review_goal_family",
            "review_record_platform_field",
            "require_review_record_platform_match",
        }
        missing_dimensions = sorted(dimension_keys - set(dimensions))
        if missing_dimensions:
            raise ValueError(f"source_dimension_derivation missing keys: {missing_dimensions}")
        if str(dimensions["platform_id_field"]).strip() != "platform_id":
            raise ValueError("source_dimension_derivation.platform_id_field must be platform_id")
        try:
            re.compile(str(dimensions["platform_id_pattern"]))
        except re.error as exc:
            raise ValueError(f"source_dimension_derivation.platform_id_pattern is invalid: {exc}") from exc
        if str(dimensions["review_goal_family"]).strip() != "reviews_and_user_voice":
            raise ValueError("source_dimension_derivation.review_goal_family must be reviews_and_user_voice")
        if str(dimensions["review_record_platform_field"]).strip() != "platform":
            raise ValueError("source_dimension_derivation.review_record_platform_field must be platform")
        if not re.fullmatch(str(dimensions["platform_id_pattern"]), str(dimensions["local_platform_id"])):
            raise ValueError("source_dimension_derivation.local_platform_id must match platform_id_pattern")
        for key in dimension_keys - {
            "platform_id_field",
            "platform_id_pattern",
            "local_platform_id",
            "review_goal_family",
            "review_record_platform_field",
        }:
            if not isinstance(dimensions[key], bool):
                raise ValueError(f"source_dimension_derivation.{key} must be true or false")
    if int(data["policy_version"]) >= 7:
        qualification = data.get("primary_source_qualification")
        if not isinstance(qualification, dict):
            raise ValueError("Policy version 7+ requires primary_source_qualification")
        qualification_keys = {
            "allowed_reliability_tiers",
            "allowed_tiers_by_source_type",
            "countable_verification_statuses",
            "countable_relation_types",
            "eligible_source_types_by_goal_family",
            "require_declaration_match_derived",
            "require_existing_local_file_for_tier0",
        }
        missing_qualification = sorted(qualification_keys - set(qualification))
        if missing_qualification:
            raise ValueError(f"primary_source_qualification missing keys: {missing_qualification}")
        allowed_tiers = {str(item).strip().casefold() for item in qualification["allowed_reliability_tiers"] if str(item).strip()}
        if allowed_tiers != {"tier0", "tier1", "tier2", "tier3"}:
            raise ValueError("primary_source_qualification.allowed_reliability_tiers must contain tier0/tier1/tier2/tier3")
        allowed_types = {str(item).strip() for item in data["source_independence"]["allowed_source_types"] if str(item).strip()}
        tier_mapping = qualification["allowed_tiers_by_source_type"]
        if not isinstance(tier_mapping, dict) or set(tier_mapping) != allowed_types:
            raise ValueError("primary_source_qualification tier mapping must cover every controlled source type exactly")
        for source_type, tiers in tier_mapping.items():
            normalized_tiers = {str(item).strip().casefold() for item in tiers if str(item).strip()}
            if not normalized_tiers or not normalized_tiers.issubset(allowed_tiers):
                raise ValueError(f"Invalid reliability-tier mapping for source type {source_type}")
        family_mapping = qualification["eligible_source_types_by_goal_family"]
        if not isinstance(family_mapping, dict) or set(family_mapping) != configured:
            raise ValueError("primary_source_qualification family mapping must cover every goal family exactly")
        for family, source_types in family_mapping.items():
            normalized_types = {str(item).strip() for item in source_types if str(item).strip()}
            if not normalized_types.issubset(allowed_types):
                raise ValueError(f"Unknown primary-eligible source type for {family}")
        verification_statuses = {str(item).strip().casefold() for item in qualification["countable_verification_statuses"] if str(item).strip()}
        relation_types = {str(item).strip() for item in qualification["countable_relation_types"] if str(item).strip()}
        if not verification_statuses or not relation_types:
            raise ValueError("primary_source_qualification countable statuses and relation types cannot be empty")
        if not relation_types.issubset({str(item).strip() for item in data["source_independence"]["allowed_relation_types"]}):
            raise ValueError("primary_source_qualification relation types must be controlled relation types")
        for key in ("require_declaration_match_derived", "require_existing_local_file_for_tier0"):
            if not isinstance(qualification[key], bool):
                raise ValueError(f"primary_source_qualification.{key} must be true or false")
    if int(data["policy_version"]) >= 8:
        claim_policy = data.get("critical_claim_evidence")
        if not isinstance(claim_policy, dict):
            raise ValueError("Policy version 8+ requires critical_claim_evidence")
        claim_keys = {
            "claim_hash_algorithm",
            "minimum_evidence_bindings_per_claim",
            "require_unique_claim_id",
            "require_unique_claim_hash",
            "require_binding_record_in_task_audit",
            "require_binding_owned_by_task",
            "require_binding_countable",
            "require_nonempty_evidence_fields",
            "require_claim_sources_equal_binding_sources",
            "disallowed_evidence_fields",
        }
        missing_claim_keys = sorted(claim_keys - set(claim_policy))
        if missing_claim_keys:
            raise ValueError(f"critical_claim_evidence missing keys: {missing_claim_keys}")
        if str(claim_policy["claim_hash_algorithm"]).casefold() != "sha256":
            raise ValueError("critical_claim_evidence.claim_hash_algorithm must be sha256")
        if not isinstance(claim_policy["minimum_evidence_bindings_per_claim"], int) or claim_policy["minimum_evidence_bindings_per_claim"] < 2:
            raise ValueError("critical_claim_evidence.minimum_evidence_bindings_per_claim must be an integer >= 2")
        for key in claim_keys - {"claim_hash_algorithm", "minimum_evidence_bindings_per_claim", "disallowed_evidence_fields"}:
            if not isinstance(claim_policy[key], bool):
                raise ValueError(f"critical_claim_evidence.{key} must be true or false")
        disallowed_fields = {str(item).strip().casefold() for item in claim_policy["disallowed_evidence_fields"] if str(item).strip()}
        if not disallowed_fields:
            raise ValueError("critical_claim_evidence.disallowed_evidence_fields cannot be empty")
    return data


@lru_cache(maxsize=None)
def _load_policy_cached(path_text: str) -> dict:
    path = Path(path_text)
    return validate_policy(yaml.safe_load(path.read_text(encoding="utf-8-sig")), path)


def load_policy(path: Path | str | None = None) -> dict:
    selected = Path(path) if path is not None else POLICY_PATH
    return _load_policy_cached(str(selected.resolve()))


def clear_policy_cache() -> None:
    _load_policy_cached.cache_clear()


def policy_sha256(path: Path | str | None = None) -> str:
    selected = Path(path) if path is not None else POLICY_PATH
    return hashlib.sha256(selected.read_bytes()).hexdigest()


def policy_manifest_fields(snapshot_path: Path, frozen_at: str) -> dict[str, object]:
    policy = load_policy(snapshot_path)
    return {
        MANIFEST_VERSION_FIELD: int(policy["policy_version"]),
        MANIFEST_SHA256_FIELD: policy_sha256(snapshot_path),
        MANIFEST_SNAPSHOT_FIELD: POLICY_SNAPSHOT_RELATIVE_PATH.as_posix(),
        MANIFEST_FROZEN_AT_FIELD: frozen_at,
    }


def freeze_policy_dict(project_dir: Path, policy: dict, frozen_at: str, *, overwrite: bool = False) -> dict[str, object]:
    """Freeze an explicit policy dict (e.g. template + project overrides) into
    the read-only project snapshot.  Used by upgrade_collection_policy.py when
    a project supplies generator_overrides (CHANGELOG v1.2.6)."""
    project_root = project_dir.resolve()
    destination = project_root / POLICY_SNAPSHOT_RELATIVE_PATH
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Project quantity-policy snapshot already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.chmod(stat.S_IWRITE | stat.S_IREAD)
    validate_policy(policy, destination)
    destination.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    destination.chmod(stat.S_IREAD)
    clear_policy_cache()
    return policy_manifest_fields(destination, frozen_at)


def freeze_current_policy(project_dir: Path, frozen_at: str, *, overwrite: bool = False) -> dict[str, object]:
    project_root = project_dir.resolve()
    destination = project_root / POLICY_SNAPSHOT_RELATIVE_PATH
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Project quantity-policy snapshot already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.chmod(stat.S_IWRITE | stat.S_IREAD)
    shutil.copyfile(POLICY_PATH, destination)
    destination.chmod(stat.S_IREAD)
    clear_policy_cache()
    return policy_manifest_fields(destination, frozen_at)


def archive_project_policy_snapshot(project_dir: Path, manifest: dict) -> dict[str, object] | None:
    project_root = project_dir.resolve()
    snapshot_value = str(manifest.get(MANIFEST_SNAPSHOT_FIELD, "")).strip()
    if not snapshot_value:
        return None
    relative = Path(snapshot_value)
    if relative.is_absolute():
        raise ValueError("Cannot archive an absolute quantity-policy snapshot path")
    source = (project_root / relative).resolve()
    if not source.is_relative_to(project_root):
        raise ValueError("Cannot archive a quantity-policy snapshot outside the project directory")
    if not source.exists():
        return None

    actual_hash = policy_sha256(source)
    version_text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(manifest.get(MANIFEST_VERSION_FIELD, "unknown"))) or "unknown"
    archive_relative = Path("policy_snapshot") / "archive" / f"v{version_text}_{actual_hash[:12]}.yaml"
    destination = (project_root / archive_relative).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if policy_sha256(destination) != actual_hash:
            raise ValueError(f"Existing policy archive has conflicting content: {archive_relative.as_posix()}")
    else:
        shutil.copyfile(source, destination)
    destination.chmod(stat.S_IREAD)
    return {
        "archive_path": archive_relative.as_posix(),
        "archive_sha256": actual_hash,
        "archive_version": manifest.get(MANIFEST_VERSION_FIELD),
    }


def load_project_policy(project_dir: Path, manifest: dict | None = None) -> dict:
    project_root = project_dir.resolve()
    if manifest is None:
        manifest_path = project_root / "project_manifest.json"
        if not manifest_path.exists():
            raise ValueError("project_manifest.json is required before loading the frozen quantity policy")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read project_manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("project_manifest.json must contain a JSON object")

    missing = [
        field
        for field in (MANIFEST_VERSION_FIELD, MANIFEST_SHA256_FIELD, MANIFEST_SNAPSHOT_FIELD, MANIFEST_FROZEN_AT_FIELD)
        if str(manifest.get(field, "")).strip() == ""
    ]
    if missing:
        raise ValueError(
            "Project has no complete frozen quantity-policy identity "
            f"({', '.join(missing)}). Run upgrade_collection_policy.py with explicit human confirmation."
        )

    relative = Path(str(manifest[MANIFEST_SNAPSHOT_FIELD]))
    if relative.is_absolute():
        raise ValueError("Quantity-policy snapshot path must be project-relative")
    snapshot = (project_root / relative).resolve()
    if not snapshot.is_relative_to(project_root):
        raise ValueError("Quantity-policy snapshot must remain inside the project directory")
    if not snapshot.exists():
        raise ValueError(f"Frozen quantity-policy snapshot does not exist: {relative.as_posix()}")
    if snapshot.stat().st_mode & stat.S_IWUSR:
        raise ValueError("Frozen quantity-policy snapshot is writable; restore it through the explicit upgrade workflow")

    expected_hash = str(manifest[MANIFEST_SHA256_FIELD]).strip().lower()
    actual_hash = policy_sha256(snapshot)
    if actual_hash != expected_hash:
        raise ValueError("Frozen quantity-policy snapshot hash does not match project_manifest.json")
    policy = load_policy(snapshot)
    try:
        expected_version = int(manifest[MANIFEST_VERSION_FIELD])
    except (TypeError, ValueError) as exc:
        raise ValueError("collection_quantity_policy_version must be an integer") from exc
    if int(policy["policy_version"]) != expected_version:
        raise ValueError("Frozen quantity-policy version does not match project_manifest.json")
    return policy


def market_goal_families(policy: dict | None = None) -> set[str]:
    return set((policy or load_policy())["market_goal_families"])


def model_goal_families(policy: dict | None = None) -> set[str]:
    return set((policy or load_policy())["model_goal_families"])


def minimum_exact_models_per_market(policy: dict | None = None) -> int:
    return int((policy or load_policy())["minimum_exact_models_per_market"])


def coverage_requirement(family: str, policy: dict | None = None) -> str:
    selected = policy or load_policy()
    return str(selected["families"][family].get("coverage_requirement") or selected["default_coverage_requirement"])


def round_floor(family: str, round_number: str, policy: dict | None = None) -> dict[str, int]:
    selected = policy or load_policy()
    return dict(selected["families"][family]["rounds"][str(round_number)])
