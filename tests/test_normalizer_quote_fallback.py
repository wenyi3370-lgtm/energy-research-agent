"""normalizer 空引文三级兜底 tests（raw_text → value → field_name，绝不为空）。"""

import unittest

from enterprise_energy_research.research.normalizer import EvidenceNormalizer
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch


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


if __name__ == "__main__":
    unittest.main()
