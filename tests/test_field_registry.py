"""P0-4 regression: CanonicalFieldRegistry normalizes alias field names into
one canonical field while preserving the exact raw name on the Claim.
"""

from __future__ import annotations

import unittest

from energy_research_agent.domain.models import ExtractedClaim, ExtractedEvidenceBatch
from energy_research_agent.research.field_registry import CanonicalFieldRegistry
from energy_research_agent.research.normalizer import EvidenceNormalizer
from energy_research_agent.research.claim_validator import ClaimValidator
from energy_research_agent.research.profiles import CompanyProfileBuilder


def _batch(field_name: str, value) -> ExtractedEvidenceBatch:
    return ExtractedEvidenceBatch.model_validate({
        "source_url": "https://www.acme-corp.com/about",
        "source_title": "ACME 简介",
        "publisher": "ACME",
        "source_kind": "official_company",
        "extraction_method": "model_structured",
        "retrieval_adapter": "anysearch",
        "is_search_snippet": False,
        "entities": [{
            "entity_key": "acme", "canonical_name": "ACME科技有限公司",
            "entity_type": "company", "official_website": "https://www.acme-corp.com",
        }],
        "claims": [{
            "entity_key": "acme", "field_name": field_name, "value": value,
            "value_type": "string", "raw_text": f"{field_name}: {value}",
            "context_text": f"页面披露 {field_name} 为 {value}", "qualifier": "exact",
        }],
        "factories": [], "products": [], "images": [],
    })


class FieldRegistryTests(unittest.TestCase):
    def test_field_alias_normalization(self) -> None:
        for alias in ("annual_revenue", "operating_revenue", "sales_revenue", "营业收入", "营收"):
            self.assertEqual(CanonicalFieldRegistry.canonicalize(alias), "revenue")
        for alias in ("employees", "staff_count", "employee_number", "员工人数", "人员规模"):
            self.assertEqual(CanonicalFieldRegistry.canonicalize(alias), "employee_count")
        for alias in ("annual_electricity", "power_consumption", "electricity_usage", "年用电量", "年度耗电量"):
            self.assertEqual(CanonicalFieldRegistry.canonicalize(alias), "electricity_consumption")
        for alias in ("rooftop_area", "factory_roof_area", "usable_roof_area", "屋顶面积", "厂房屋面面积"):
            self.assertEqual(CanonicalFieldRegistry.canonicalize(alias), "roof_area")

    def test_raw_field_name_is_preserved(self) -> None:
        batch = _batch("annual_revenue", "100亿元")
        evidence = EvidenceNormalizer().normalize([batch])
        claim = evidence.claims[0]
        self.assertEqual(claim.field_name, "revenue")
        self.assertEqual(claim.raw_field_name, "annual_revenue")

    def test_canonical_field_used_downstream(self) -> None:
        batch = _batch("营业收入", "80亿元")
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        from energy_research_agent.research.entity_mapper import EntityMapper
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        profile = CompanyProfileBuilder().build(
            evidence.entities[0], evidence.claims, evidence.edges,
            evidence.factories, evidence.products,
        )
        self.assertEqual(profile.revenue, "80亿元")

    def test_unknown_field_not_merged_into_wrong_family(self) -> None:
        self.assertEqual(CanonicalFieldRegistry.canonicalize("some_unknown_metric"), "some_unknown_metric")


if __name__ == "__main__":
    unittest.main()
