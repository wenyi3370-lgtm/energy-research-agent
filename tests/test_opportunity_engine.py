"""P0-20 regression: opportunities come from an extensible evidence-driven
registry — no evidence, no opportunity; no fixed EPC/ZERO_CARBON/... menu.
"""

from __future__ import annotations

import unittest

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, EnergyProfile, Entity
from enterprise_energy_research.research.opportunity_registry import (
    EvidenceOpportunityEngine, OpportunityRegistry,
)


def verified_claim(field: str, value, entity_id: str) -> Claim:
    return Claim(
        claim_id=new_sortable_id("CLAIM"), entity_id=entity_id, field_name=field,
        value=value, value_type="string", qualifier="exact", source_id="S1",
        raw_text=str(value), context_text=f"{field}={value}",
        verification_status=VerificationStatus.VERIFIED, confidence=0.95,
    )


class OpportunityEngineTests(unittest.TestCase):
    def test_no_evidence_generates_no_opportunities(self) -> None:
        entity = Entity(entity_id="E1", canonical_name="ACME科技有限公司")
        solutions = EvidenceOpportunityEngine().generate([entity], [], [])
        self.assertEqual(solutions, [])

    def test_roof_evidence_generates_pv_epc_opportunity(self) -> None:
        entity = Entity(entity_id="E1", canonical_name="ACME科技有限公司")
        claims = [
            verified_claim("canonical_company_name", "ACME科技有限公司", "E1"),
            verified_claim("roof_area", 12000, "E1"),
        ]
        profile = EnergyProfile(
            energy_profile_id="EP1", entity_id="E1", roof={"area": 12000, "unit": "m2"},
            field_status={},
        )
        solutions = EvidenceOpportunityEngine().generate([entity], [profile], claims)
        self.assertTrue(any(solution.engine == "PV_EPC" for solution in solutions))
        pv = next(solution for solution in solutions if solution.engine == "PV_EPC")
        self.assertTrue(pv.claim_ids)

    def test_opportunity_registry_is_extensible(self) -> None:
        registry = OpportunityRegistry()
        self.assertIn("PV_EPC", registry.codes())
        self.assertIn("V2G", registry.codes())
        self.assertIn("OVERSEAS", registry.codes())
        self.assertIsNotNone(registry.get("MICROGRID"))

    def test_evidence_supported_solution_requires_claims(self) -> None:
        entity = Entity(entity_id="E1", canonical_name="ACME科技有限公司")
        claims = [verified_claim("load_curve", "双峰", "E1")]
        profile = EnergyProfile(energy_profile_id="EP1", entity_id="E1", load_shape={"x": 1}, field_status={})
        solutions = EvidenceOpportunityEngine().generate([entity], [profile], claims)
        storage = [solution for solution in solutions if solution.engine == "STORAGE"]
        self.assertTrue(storage)
        for solution in solutions:
            if solution.statement_type.value == "EVIDENCE_SUPPORTED":
                self.assertTrue(solution.claim_ids)


if __name__ == "__main__":
    unittest.main()
