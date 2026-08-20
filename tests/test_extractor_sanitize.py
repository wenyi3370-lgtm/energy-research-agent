"""EvidenceExtractor 抽取一致性清洗 tests（无主引用记录丢弃，不沉船）。"""

import unittest

from enterprise_energy_research.domain.models import ExtractedEvidenceBatch
from enterprise_energy_research.research.extractor import EvidenceExtractor


class SanitizeTests(unittest.TestCase):
    def setUp(self):
        self.extractor = EvidenceExtractor()

    def _batch(self, url="https://example.com/a") -> ExtractedEvidenceBatch:
        return ExtractedEvidenceBatch.model_validate({
            "source_url": url, "source_kind": "official",
            "extraction_method": "model_structured",
            "entities": [{"entity_key": "catl", "canonical_name": "宁德时代"}],
        })

    def test_dangling_claim_dropped(self):
        batch = self._batch()
        batch.claims = [
            ExtractedClaimStub("catl", "revenue", "3620亿"),
            ExtractedClaimStub("global_largest_carbon_fiber_base", "note", "v"),
        ]
        clean = self.extractor._sanitize_batch(batch, "IQ-1", "https://example.com/a")
        self.assertIsNotNone(clean)
        self.assertEqual(len(clean.claims), 1)
        self.assertEqual(clean.claims[0].entity_key, "catl")
        self.assertTrue(any("dropped 1" in failure for failure in self.extractor.last_failures))

    def test_batch_kept_when_entities_remain(self):
        batch = self._batch()
        batch.claims = [ExtractedClaimStub("ghost", "f", "v")]
        clean = self.extractor._sanitize_batch(batch, "IQ-2", "https://example.com/a")
        self.assertIsNotNone(clean)  # 实体仍在 → batch 保留
        self.assertEqual(clean.claims, [])
        batch.entities = []
        self.assertIsNone(self.extractor._sanitize_batch(batch, "IQ-2", "https://example.com/a"))


def ExtractedClaimStub(entity_key, field_name, value):
    from enterprise_energy_research.domain.models import ExtractedClaim

    return ExtractedClaim(
        entity_key=entity_key, field_name=field_name, value=value,
        value_type="string", raw_text="r", context_text="c",
    )


if __name__ == "__main__":
    unittest.main()
