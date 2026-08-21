from __future__ import annotations

"""Recorded accuracy eval (P1-4).

Beyond raw record counts, every fixture carries GOLDEN labels
(expected_claims / entities / factories / products / parameters / conflicts /
sources). The deterministic kernel (normalize -> validate) is run against each
fixture and scored for:

- Evidence Precision / Recall      (golden claims found / extracted claims)
- Claim Accuracy                   (golden claim coverage)
- Entity Accuracy                  (golden entities found)
- Source Correctness               (golden source domains found)
- Catalog Recall / Parameter Recall
- Conflict Recall                  (golden conflict fields detected)
- Unsupported Claim Rate           (target: 0)

Fixtures cover: plain manufacturer, large group, listed company,
multi-subsidiary group, product/model-rich company, energy-rich company, and
a public-information-sparse company.
"""

import argparse
import json
from pathlib import Path

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.normalizer import EvidenceNormalizer


ROOT = Path(__file__).resolve().parents[1]


def _ratio(matched: int, expected: int) -> float:
    return round(matched / expected, 4) if expected else 1.0


def score_case(case: dict) -> dict:
    fixture = case["fixture"]
    batches = [
        ExtractedEvidenceBatch.model_validate(item)
        for item in json.loads((ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8"))
    ]
    golden = case.get("golden") or {}
    evidence = EvidenceNormalizer().normalize(batches)
    claims, conflicts = ClaimValidator().validate(evidence.claims, evidence.sources)

    def claim_key(claim) -> str:
        return f"{claim.field_name}={str(claim.value)}"

    extracted_keys = [claim_key(claim) for claim in claims]
    expected_claims = golden.get("expected_claims", [])
    matched_claims = [key for key in expected_claims if key in extracted_keys]
    matched_count = len(matched_claims)

    entity_names = {entity.canonical_name for entity in evidence.entities}
    expected_entities = golden.get("expected_entities", [])
    matched_entities = [name for name in expected_entities if name in entity_names]

    source_domains = {source.source_domain for source in evidence.sources}
    expected_sources = golden.get("expected_sources", [])
    matched_sources = [domain for domain in expected_sources if any(domain in item for item in source_domains)]

    product_names = {product.name for product in evidence.products}
    expected_products = golden.get("expected_products", [])
    matched_products = [name for name in expected_products if name in product_names]

    factory_names = {factory.name for factory in evidence.factories}
    expected_factories = golden.get("expected_factories", [])
    matched_factories = [name for name in expected_factories if name in factory_names]

    parameter_names = {parameter.name for product in evidence.products for parameter in product.parameters}
    expected_parameters = golden.get("expected_parameters", [])
    matched_parameters = [name for name in expected_parameters if name in parameter_names]

    conflict_fields = {conflict.field_name for conflict in conflicts}
    expected_conflicts = golden.get("expected_conflicts", [])
    matched_conflicts = [field for field in expected_conflicts if field in conflict_fields]

    # Unsupported Claim Rate: a string-valued claim whose raw quote does not
    # even contain its own value is not supported by the page text.
    unsupported = [
        claim for claim in claims
        if claim.verification_status == VerificationStatus.VERIFIED
        and isinstance(claim.value, str) and claim.value
        and claim.value not in claim.raw_text
    ]

    metrics = {
        "evidence_precision": _ratio(matched_count, len(extracted_keys)),
        "evidence_recall": _ratio(matched_count, len(expected_claims)),
        "claim_accuracy": _ratio(matched_count, len(expected_claims)),
        "entity_accuracy": _ratio(len(matched_entities), len(expected_entities)),
        "source_correctness": _ratio(len(matched_sources), len(expected_sources)),
        "catalog_recall": _ratio(len(matched_products), len(expected_products)),
        "parameter_recall": _ratio(len(matched_parameters), len(expected_parameters)),
        "conflict_recall": _ratio(len(matched_conflicts), len(expected_conflicts)),
        "unsupported_claim_rate": round(len(unsupported) / len(claims), 4) if claims else 0.0,
    }
    hard_metrics = {
        "evidence_recall": 1.0,
        "claim_accuracy": 1.0,
        "entity_accuracy": 1.0,
        "source_correctness": 1.0,
        "catalog_recall": 1.0,
        "parameter_recall": 1.0,
        "conflict_recall": 1.0,
        "unsupported_claim_rate": 0.0,
    }
    failures = [
        f"{key}={metrics[key]} (need {target})"
        for key, target in hard_metrics.items()
        if metrics[key] != target
    ]
    # Count floors (schema v1 compatibility) still apply.
    dumped = [item.model_dump(mode="json") for item in batches]
    counts = {
        kind: sum(len(batch.get(kind, [])) for batch in dumped)
        for kind in ("entities", "claims", "products", "images", "factories")
    }
    counts["sources"] = sum(
        max(1 if batch.get("source_url") else 0, len(batch.get("sources", [])))
        for batch in dumped
    )
    for key, threshold in case.items():
        if key.startswith("minimum_") and counts.get(key.removeprefix("minimum_"), 0) < threshold:
            failures.append(f"{key}={counts.get(key.removeprefix('minimum_'), 0)} below {threshold}")
    return {
        "fixture": fixture,
        "metrics": metrics,
        "matched_claims": matched_claims,
        "unsupported_claim_ids": [claim.claim_id for claim in unsupported],
        "status": "PASS" if not failures else "BLOCKED",
        "findings": failures,
    }


def evaluate() -> dict:
    contract = json.loads((ROOT / "evals" / "recorded_cases.json").read_text(encoding="utf-8"))
    results = [score_case(case) for case in contract["cases"]]
    return {
        "schema_version": "2.0",
        "layer": "L2_RECORDED_RESEARCH_ACCURACY",
        "status": "PASS" if all(row["status"] == "PASS" for row in results) else "BLOCKED",
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "evals" / "recorded_research_eval.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
