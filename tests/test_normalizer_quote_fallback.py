"""normalizer 空引文三级兜底 tests（raw_text → value → field_name，绝不为空）。"""

import unittest

from energy_research_agent.research.normalizer import EvidenceNormalizer
from energy_research_agent.domain.models import ExtractedEvidenceBatch


class QuoteFallbackTests(unittest.TestCase):
    def _normalize(self, raw_text="", value=""):
        batch = ExtractedEvidenceBatch.model_validate({
            "source_url": "https://example.com/a", "source_kind": "official",
            "extraction_method": "model_structured",
            "entities": [{"entity_key": "e1", "canonical_name": "示例公司"}],
            "claims": [{"entity_key": "e1", "field_name": "revenue", "value": value,
                        "value_type": "string", "raw_text": raw_text, "context_text": ""}],
        })
        return EvidenceNormalizer().normalize([batch])

    def test_empty_value_falls_back_to_field_name(self):
        evidence = self._normalize("", "")
        claim = evidence.claims[0]
        self.assertEqual(claim.raw_text, "revenue")
        self.assertEqual(claim.context_text, "revenue")

    def test_value_falls_back_to_value(self):
        evidence = self._normalize("", "3620亿")
        claim = evidence.claims[0]
        self.assertEqual(claim.raw_text, "3620亿")

    def test_raw_text_unchanged(self):
        evidence = self._normalize("原文引用", "3620亿")
        self.assertEqual(evidence.claims[0].raw_text, "原文引用")

    def test_same_named_entities_from_multiple_pages_are_consolidated(self):
        batches = []
        for index, key in enumerate(("star_charge", "xingxing_charging"), start=1):
            batches.append(ExtractedEvidenceBatch.model_validate({
                "source_url": f"https://example.com/{index}",
                "source_kind": "official_company",
                "extraction_method": "model_structured",
                "entities": [{
                    "entity_key": key, "canonical_name": "星星充电",
                    "aliases": ["StarCharge"] if index == 2 else [],
                }],
                "claims": [{
                    "entity_key": key, "field_name": "industry_position",
                    "value": f"事实{index}", "value_type": "string",
                    "raw_text": f"星星充电事实{index}", "context_text": f"星星充电事实{index}",
                }],
                "products": [{
                    "product_key": f"product_{index}", "entity_key": key,
                    "name": f"产品{index}",
                }],
            }))

        evidence = EvidenceNormalizer().normalize(batches)

        self.assertEqual(len(evidence.entities), 1)
        entity_id = evidence.entities[0].entity_id
        self.assertTrue(all(item.entity_id == entity_id for item in evidence.claims))
        self.assertTrue(all(item.entity_id == entity_id for item in evidence.products))
        self.assertEqual({item.to_id for item in evidence.edges if item.relation == "ProducesProduct"}, {
            item.product_id for item in evidence.products
        })


if __name__ == "__main__":
    unittest.main()
