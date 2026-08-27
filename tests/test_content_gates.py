"""P0-9 / P0-10 / P0-11 regression: chapters need substantive facts,
placeholder-dominated reports are blocked, and the core readiness gate stops
empty formal publication.
"""

from __future__ import annotations

import unittest

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import Claim, Entity, Source
from energy_research_agent.research.content_contract import (
    CHAPTER_CONTRACTS, CoreResearchReadinessGate, PlaceholderContentGate,
    chapter_substantive_facts, placeholder_ratio,
)


def verified_claim(field: str, value, entity_id: str, source_id: str) -> Claim:
    return Claim(
        claim_id=new_sortable_id("CLAIM"), entity_id=entity_id, field_name=field,
        value=value, value_type="string", qualifier="exact", source_id=source_id,
        raw_text=str(value), context_text=f"{field}={value}",
        verification_status=VerificationStatus.VERIFIED, confidence=0.95,
    )


class ContentGateTests(unittest.TestCase):
    def test_placeholder_ratio_blocks_empty_report(self) -> None:
        body = [
            "实体类型：company", "核验状态：UNVERIFIED", "注册区域：待核验",
            "暂无公开信息", "待核验", "需要进一步尽调",
            "该企业主营储能装备制造，产品覆盖储能系统与综合能源服务。",
        ]
        gate = PlaceholderContentGate(body_paragraphs=body).assess()
        self.assertEqual(gate["status"], "RESEARCH_CONTENT_BLOCKED")
        self.assertGreater(gate["placeholder_paragraph_ratio"], 0.15)

    def test_empty_chapter_is_blocked_or_skipped(self) -> None:
        contract = CHAPTER_CONTRACTS["factories"]
        ok, message = contract.assess([])
        self.assertFalse(ok)
        self.assertEqual(contract.fallback_behavior, "skip")

    def test_chapter_has_substantive_content(self) -> None:
        contract = CHAPTER_CONTRACTS["factories"]
        ok, message = contract.assess(["成都基地；地址：成都市；工艺：机加工、装配"])
        self.assertTrue(ok)
        contract2 = CHAPTER_CONTRACTS["company_profile"]
        ok2, _ = contract2.assess([
            "ACME科技有限公司", "core_business=储能系统研发制造", "headquarters=深圳", "revenue=100亿元",
        ])
        self.assertTrue(ok2)

    def test_placeholder_ratio_helper(self) -> None:
        self.assertGreater(placeholder_ratio(["待核验", "正常内容"]), 0.4)
        self.assertEqual(placeholder_ratio(["正常内容一", "正常内容二"]), 0.0)

    def test_research_content_gate_blocks_empty_report(self) -> None:
        readiness = CoreResearchReadinessGate().assess(
            entities=[], claims=[], edges=[], factories=[], products=[],
            is_large_enterprise=True, minimum_substantive_claims=20,
        )
        self.assertEqual(readiness["status"], "RESEARCH_CONTENT_BLOCKED")
        self.assertFalse(readiness["verified_company_identity"])
        self.assertEqual(readiness["substantive_verified_claims"], 0)

    def test_research_content_gate_passes_rich_evidence(self) -> None:
        entity_id = new_sortable_id("ENT")
        source_id = new_sortable_id("source")
        entity = Entity(
            entity_id=entity_id, canonical_name="ACME科技有限公司",
            registered_name="ACME科技有限公司",
            verification_status=VerificationStatus.VERIFIED,
        )
        fields = (
            ["canonical_company_name", "ACME科技有限公司", "identity"],
            ["registered_name", "ACME科技有限公司", "identity"],
            ["core_business", "储能系统研发制造", "business"],
            ["business_segment", "储能板块", "business"],
            ["revenue", "100亿元", "financial"],
            ["profit", "10亿元", "financial"],
            ["employee_count", "5000", "financial"],
            ["factory_name", "成都基地", "factory"],
            ["capacity", "5GWh", "factory"],
            ["process", "机加工", "factory"],
            ["product_family", "储能柜", "product"],
            ["model", "ES-200", "product"],
            ["parameter_name", "容量", "product"],
            ["electricity_consumption", "8000万千瓦时", "energy"],
            ["roof_area", "12000", "energy"],
            ["project_name", "分布式光伏项目", "project"],
            ["pv_capacity", "1.2MW", "project"],
            ["export", "欧洲", "overseas"],
            ["industry_position", "国内前列", "position"],
            ["headquarters", "深圳", "identity"],
        )
        claims = [verified_claim(field, value, entity_id, source_id) for field, value, _kind in fields]
        readiness = CoreResearchReadinessGate().assess(
            entities=[entity], claims=claims, edges=[], factories=[], products=[],
            is_large_enterprise=True, minimum_substantive_claims=20,
        )
        self.assertEqual(readiness["status"], "PASS")
        self.assertTrue(readiness["verified_company_identity"])
        self.assertGreaterEqual(len(readiness["categories_covered"]), 3)


if __name__ == "__main__":
    unittest.main()
