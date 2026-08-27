from __future__ import annotations

import argparse
from pathlib import Path

from _common import now_iso, read_json, write_json
from collection_quantity_policy import (
    MANIFEST_FROZEN_AT_FIELD,
    MANIFEST_SHA256_FIELD,
    MANIFEST_SNAPSHOT_FIELD,
    MANIFEST_VERSION_FIELD,
    POLICY_PATH,
    archive_project_policy_snapshot,
    freeze_current_policy,
    freeze_policy_dict,
    load_policy,
    load_project_policy,
    policy_sha256,
)


def _merge_overrides(template: dict, overrides_path: str) -> dict:
    """Deep-merge a project overrides YAML into the policy dict.

    The overrides file is read as the *generator_overrides* section (keys like
    market / created_date / domain_to_source_id / ...).  Top-level override
    keys replace template defaults; nested dicts (e.g. domain_to_source_id)
    are merged key-by-key so a project can add/remove individual hosts.
    """
    import yaml

    overrides_path = Path(overrides_path).expanduser().resolve()
    if not overrides_path.is_file():
        raise ValueError(f"overrides file not found: {overrides_path}")
    overrides = yaml.safe_load(overrides_path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(overrides, dict):
        raise ValueError(f"overrides file must contain a YAML mapping: {overrides_path}")

    merged = dict(template)
    default_ov = dict(template.get("generator_overrides") or {})
    merged_ov = dict(default_ov)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(default_ov.get(key), dict):
            merged_ov[key] = {**default_ov[key], **value}
        else:
            merged_ov[key] = value
    merged["generator_overrides"] = merged_ov
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upgrade a research project's frozen collection-quantity policy after explicit human approval."
    )
    parser.add_argument("--project-dir", required=True, help="Existing research project directory.")
    parser.add_argument(
        "--confirm-policy-upgrade",
        action="store_true",
        help="Required explicit confirmation that a human approved applying the current skill policy.",
    )
    parser.add_argument("--approved-by", required=True, help="Human approver name or accountable role.")
    parser.add_argument("--approval-note", default="", help="Optional reason, ticket, or approval reference.")
    parser.add_argument(
        "--overrides",
        default="",
        help="Optional YAML file with project-specific generator_overrides (market, created_date, "
        "domain_to_source_id, channel_brand_to_source_id, tech_keywords, review_theme_to_record). "
        "Merged into the frozen snapshot; see CHANGELOG v1.2.6.",
    )
    args = parser.parse_args()

    if not args.confirm_policy_upgrade:
        parser.error("--confirm-policy-upgrade is required; policy upgrades cannot happen implicitly")
    if not args.approved_by.strip():
        parser.error("--approved-by must identify the human approver or accountable role")

    project_dir = Path(args.project_dir).expanduser().resolve()
    manifest_path = project_dir / "project_manifest.json"
    if not manifest_path.exists():
        parser.error(f"project_manifest.json does not exist: {manifest_path}")
    manifest = read_json(manifest_path, {})
    if not isinstance(manifest, dict) or not manifest:
        parser.error("project_manifest.json must contain a nonempty JSON object")

    previous_validation_error = ""
    try:
        load_project_policy(project_dir, manifest)
    except ValueError as exc:
        previous_validation_error = str(exc)

    previous = {
        "version": manifest.get(MANIFEST_VERSION_FIELD),
        "sha256": manifest.get(MANIFEST_SHA256_FIELD),
        "snapshot_path": manifest.get(MANIFEST_SNAPSHOT_FIELD),
        "frozen_at": manifest.get(MANIFEST_FROZEN_AT_FIELD),
    }
    archive = archive_project_policy_snapshot(project_dir, manifest)
    if archive:
        previous.update(archive)
        previous["archive_trust_status"] = "forensic_unverified" if previous_validation_error else "verified"
    upgraded_at = now_iso()
    template_policy = load_policy(POLICY_PATH)
    if args.overrides:
        try:
            current_policy = _merge_overrides(template_policy, args.overrides)
        except ValueError as exc:
            parser.error(str(exc))
        new_fields = freeze_policy_dict(project_dir, current_policy, upgraded_at, overwrite=True)
        print(f"Project generator_overrides merged from: {Path(args.overrides).expanduser().resolve()}")
    else:
        current_policy = template_policy
        new_fields = freeze_current_policy(project_dir, upgraded_at, overwrite=True)

    history = manifest.get("collection_quantity_policy_upgrade_history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "upgraded_at": upgraded_at,
            "approved_by": args.approved_by.strip(),
            "approval_note": args.approval_note.strip(),
            "from": previous,
            "to": {
                "version": int(current_policy["policy_version"]),
                "sha256": policy_sha256(POLICY_PATH),
                "snapshot_path": new_fields[MANIFEST_SNAPSHOT_FIELD],
            },
            "previous_policy_validation_error": previous_validation_error,
        }
    )
    manifest.update(new_fields)
    manifest["collection_quantity_policy_upgrade_history"] = history
    write_json(manifest_path, manifest)

    print(f"Upgraded frozen collection quantity policy: {project_dir}")
    print(f"Policy version: {new_fields[MANIFEST_VERSION_FIELD]}")
    print(f"Policy SHA256: {new_fields[MANIFEST_SHA256_FIELD]}")
    print(f"Approved by: {args.approved_by.strip()}")
    if archive:
        print(f"Archived previous policy: {archive['archive_path']}")
    else:
        print("Archived previous policy: none (legacy project had no snapshot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
