from __future__ import annotations

import argparse
import json
from pathlib import Path

from collection_quantity_policy import load_project_policy
from collection_record_registry import content_sha256, resolve_record_ref


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute the policy-v5 canonical SHA256 for one collection record reference.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--record-ref", required=True, help="Project-relative CSV reference, for example 01_Market_Scan.csv#2")
    args = parser.parse_args()
    project_root = Path(args.project_dir).expanduser().resolve()
    policy = load_project_policy(project_root)
    registry_policy = policy.get("record_registry")
    if not registry_policy:
        parser.error("The project's frozen policy does not define record_registry")
    row, error = resolve_record_ref(project_root, args.record_ref)
    if error or row is None:
        parser.error(error or "Unable to resolve record reference")
    excluded_fields = {str(item).strip().casefold() for item in registry_policy["excluded_hash_fields"]}
    excluded_prefixes = tuple(str(item).strip().casefold() for item in registry_policy["excluded_hash_field_prefixes"])
    digest, payload = content_sha256(row, excluded_fields, excluded_prefixes)
    print(json.dumps({"record_ref": args.record_ref, "content_sha256": digest, "canonical_payload": payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
