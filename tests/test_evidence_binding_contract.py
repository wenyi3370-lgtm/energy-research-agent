"""Evidence binding contract locks (§20).

Guarantees, company-agnostic by construction:
1. Every core goal's required_evidence family has an extraction contract, and
   every contract field resolves back to its family (no silent dead ends).
2. The attribution chain (LLM goal_family -> query topic -> contract inverse)
   binds claims to goals deterministically; unresolved rows stay visible.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.agent.api import _field_to_families, _read_run_claims
from enterprise_energy_research.agent.goal_planner import CORE_ENTERPRISE_GOALS
from enterprise_energy_research.agent.mission_parser import MissionParseResult
from enterprise_energy_research.agent.orchestrator import ResearchOrchestratorAgent
from enterprise_energy_research.agent.policies import AgentPolicies
from enterprise_energy_research.domain.enums import RunStatus, SourceLevel, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim,
    Entity,
    RunManifest,
    Source,
    utc_now,
)
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.research.contracts import GOAL_CONTRACTS


class TestBindingContractCompleteness(unittest.TestCase):
    """§20 lock: every required family has a contract; every contract field
    resolves back to its family — the structural guarantee that switching
    companies cannot break matching."""

    def test_core_required_families_have_contracts(self):
        required = {
            field
            for spec in CORE_ENTERPRISE_GOALS
            for field in spec.required_evidence
        }
        for family in sorted(required):
            with self.subTest(family=family):
                self.assertIn(family, GOAL_CONTRACTS, f"missing contract for {family}")
                self.assertTrue(
                    GOAL_CONTRACTS[family].expected_fields,
                    f"contract {family} must declare expected fields",
                )

    def test_every_contract_field_resolves_back(self):
        inverse = _field_to_families()
        for family, contract in GOAL_CONTRACTS.items():
            for field in contract.expected_fields:
                resolved = inverse.get(field, [])
                self.assertIn(
                    family, resolved,
                    f"field {field} of contract {family} must resolve back to {family}",
                )

    def test_mapping_is_company_agnostic(self):
        """The inverse map never contains a company name — matching cannot
        depend on which enterprise is being researched."""
        for field in _field_to_families():
            self.assertNotIn("阳光", field)
            self.assertNotIn("公司", field)


class TestAttributionChain(unittest.TestCase):
    """LLM goal_family -> query topic -> contract inverse; unresolved stays
    mission-level (never silently dropped)."""

    def _mission_and_store(self) -> tuple[Path, str]:
        store_dir = Path(tempfile.mkdtemp(prefix="bind-chain-"))
        run_id = new_sortable_id("RUN")
        run_dir = store_dir / run_id
        run_dir.mkdir(parents=True)
        store = EvidenceStore(run_dir / "evidence.sqlite3")
        store.create_run(RunManifest(run_id=run_id, request_id="r", config_hash="t", code_version="t", model_gateway={}))
        store.add(run_id, 1, "entity", Entity(entity_id="E", canonical_name="示例公司"))
        store.add(run_id, 1, "source", Source(
            source_id="S", canonical_url="https://example.com/a",
            source_domain="example.com", source_level=SourceLevel.SOURCE_A, grading_reason="t",
        ))
        return store_dir, run_id

    def _claim(self, field: str, value: str, **extra) -> Claim:
        return Claim(
            claim_id=new_sortable_id("CLAIM"),
            entity_id="E",
            field_name=field,
            value=value,
            value_type="string",
            source_id="S",
            raw_text="raw",
            context_text="context",
            retrieved_at=utc_now(),
            confidence=0.8,
            verification_status=VerificationStatus.VERIFIED,
            **extra,
        )

    def test_llm_family_binds(self):
        store_dir, run_id = self._mission_and_store()
        store = EvidenceStore(store_dir / run_id / "evidence.sqlite3")
        store.add(run_id, 1, "claim", self._claim("founded_date", "2011", goal_family="company_identity"))
        rows = _read_run_claims(run_id, store_dir)
        self.assertEqual(rows[0]["goal_families"], ["company_identity"])

    def test_query_topic_fallback_binds(self):
        store_dir, run_id = self._mission_and_store()
        store = EvidenceStore(store_dir / run_id / "evidence.sqlite3")
        store.add(run_id, 1, "claim", self._claim(
            "production_capacity", "10GWh",
            locator={"_routing": {"topic": "capacity"}},
        ))
        rows = _read_run_claims(run_id, store_dir)
        self.assertIn("capacity", rows[0]["goal_families"])

    def test_contract_inverse_fallback_binds(self):
        store_dir, run_id = self._mission_and_store()
        store = EvidenceStore(store_dir / run_id / "evidence.sqlite3")
        store.add(run_id, 1, "claim", self._claim("official_website", "https://x.com"))
        rows = _read_run_claims(run_id, store_dir)
        self.assertIn("company_identity", rows[0]["goal_families"])

    def test_unresolved_stays_mission_level(self):
        store_dir, run_id = self._mission_and_store()
        store = EvidenceStore(store_dir / run_id / "evidence.sqlite3")
        store.add(run_id, 1, "claim", self._claim("completely_unknown_field_xyz", "v"))
        rows = _read_run_claims(run_id, store_dir)
        self.assertEqual(rows[0]["goal_families"], [], "unresolved rows stay visible, never forced")


if __name__ == "__main__":
    unittest.main()
