from __future__ import annotations

import argparse
import json

from critical_claim_evidence import claim_sha256, normalize_claim_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute the normalized SHA256 for a critical-claim statement.")
    parser.add_argument("claim_text", help="Exact critical-claim statement to hash")
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "claim_text": args.claim_text,
                "normalized_claim_text": normalize_claim_text(args.claim_text),
                "claim_sha256": claim_sha256(args.claim_text),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
