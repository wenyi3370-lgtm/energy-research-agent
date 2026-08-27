"""EvidenceExtractor 抽取一致性清洗 tests（无主引用记录丢弃，不沉船）。"""

import unittest

from energy_research_agent.adapters.base import SearchResultEnvelope
from energy_research_agent.domain.models import ExtractedEvidenceBatch
from energy_research_agent.research.extractor import EvidenceExtractor


class SanitizeTests(unittest.TestCase):
    def setUp(self):
        self.extractor = EvidenceExtractor()

    def _batch(self, url="https://example.com/a") -> ExtractedEvidenceBatch:
        return ExtractedEvidenceBatch.model_validate({
            "source_url": url, "source_kind": "official",
            "extraction_method": "model_structured",
            "entities": [{"entity_key": "catl", "canonical_name": "宁德时代"}],
        })

    @staticmethod
    def _result(query_id="IQ-1", company="宁德时代") -> SearchResultEnvelope:
        return SearchResultEnvelope(
            adapter="anysearch", query_id=query_id, status="ok",
            canonical_company_name=company,
        )

    def test_dangling_claim_dropped(self):
        batch = self._batch()
        batch.claims = [
            ExtractedClaimStub("catl", "revenue", "3620亿"),
            ExtractedClaimStub("global_largest_carbon_fiber_base", "note", "v"),
        ]
        clean = self.extractor._sanitize_batch(batch, self._result(), "https://example.com/a")
        self.assertIsNotNone(clean)
        self.assertEqual(len(clean.claims), 1)
        self.assertEqual(clean.claims[0].entity_key, "catl")
        self.assertTrue(any("dropped 1" in failure for failure in self.extractor.last_failures))

    def test_batch_kept_when_entities_remain(self):
        batch = self._batch()
        batch.claims = [ExtractedClaimStub("ghost", "f", "v")]
        clean = self.extractor._sanitize_batch(batch, self._result("IQ-2"), "https://example.com/a")
        self.assertIsNotNone(clean)  # 实体仍在 → batch 保留
        self.assertEqual(clean.claims, [])
        batch.entities = []
        self.assertIsNone(self.extractor._sanitize_batch(
            batch, self._result("IQ-2"), "https://example.com/a",
        ))

    def test_competitor_records_are_removed_at_subject_boundary(self):
        batch = ExtractedEvidenceBatch.model_validate({
            "source_url": "https://example.com/comparison",
            "source_kind": "ordinary_media",
            "extraction_method": "model_structured",
            "entities": [
                {"entity_key": "star", "canonical_name": "星星充电"},
                {"entity_key": "peer", "canonical_name": "优优绿能"},
            ],
            "claims": [
                {"entity_key": "star", "field_name": "industry_position", "value": "进入充电运营商前列", "value_type": "string", "raw_text": "星星充电进入前列", "context_text": "星星充电进入前列"},
                {"entity_key": "peer", "field_name": "revenue", "value": "10亿元", "value_type": "string", "raw_text": "优优绿能收入10亿元", "context_text": "优优绿能收入10亿元"},
            ],
            "factories": [{"factory_key": "peer_factory", "operator_entity_key": "peer", "name": "优优绿能工厂"}],
            "products": [{"product_key": "peer_product", "entity_key": "peer", "name": "充电模块"}],
        })

        clean = self.extractor._sanitize_batch(
            batch, self._result(company="星星充电"), "https://example.com/comparison",
        )

        self.assertIsNotNone(clean)
        self.assertEqual([item.entity_key for item in clean.entities], ["star"])
        self.assertEqual([item.entity_key for item in clean.claims], ["star"])
        self.assertEqual(clean.factories, [])
        self.assertEqual(clean.products, [])

    def test_page_without_target_enterprise_is_dropped(self):
        batch = ExtractedEvidenceBatch.model_validate({
            "source_url": "https://example.com/peer",
            "source_kind": "annual_report",
            "extraction_method": "model_structured",
            "entities": [{"entity_key": "peer", "canonical_name": "优优绿能"}],
        })
        clean = self.extractor._sanitize_batch(
            batch, self._result(company="星星充电"), "https://example.com/peer",
        )
        self.assertIsNone(clean)
        self.assertTrue(any("target enterprise absent" in item for item in self.extractor.last_failures))

    def test_verified_alias_is_accepted_without_admitting_unrelated_company(self):
        batch = ExtractedEvidenceBatch.model_validate({
            "source_url": "https://www.wbstar.com/about",
            "source_kind": "official_company",
            "extraction_method": "model_structured",
            "entities": [
                {"entity_key": "wanbang", "canonical_name": "万帮数字能源"},
                {"entity_key": "peer", "canonical_name": "优优绿能"},
            ],
            "claims": [
                {"entity_key": "wanbang", "field_name": "core_business", "value": "充电设备与运营", "value_type": "string", "raw_text": "主营充电设备与运营", "context_text": "主营充电设备与运营"},
                {"entity_key": "peer", "field_name": "revenue", "value": "10亿元", "value_type": "string", "raw_text": "优优绿能收入10亿元", "context_text": "优优绿能收入10亿元"},
            ],
        })
        result = self._result(company="星星充电").model_copy(update={
            "canonical_company_aliases": ["万帮数字能源", "万帮星星充电科技有限公司"],
        })

        clean = self.extractor._sanitize_batch(
            batch, result, "https://www.wbstar.com/about",
        )

        self.assertIsNotNone(clean)
        self.assertEqual([item.entity_key for item in clean.entities], ["wanbang"])
        self.assertEqual([item.entity_key for item in clean.claims], ["wanbang"])


def ExtractedClaimStub(entity_key, field_name, value):
    from energy_research_agent.domain.models import ExtractedClaim

    return ExtractedClaim(
        entity_key=entity_key, field_name=field_name, value=value,
        value_type="string", raw_text="r", context_text="c",
    )


if __name__ == "__main__":
    unittest.main()
