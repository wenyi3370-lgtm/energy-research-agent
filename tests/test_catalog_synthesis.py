"""P0-17 / P0-18 / P1-3 regression: catalog traversal states, claim-bound
synthesis, verified claims reaching the publisher, and high-value claim
utilization.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, Product
from enterprise_energy_research.research.catalog import CatalogInventory, CatalogItem, CatalogTraverser
from enterprise_energy_research.research.claim_utilization import ClaimUtilizationAuditor, high_value_claim_ids
from enterprise_energy_research.research.synthesis import ResearchSynthesizer, SynthesisFinding


def verified_claim(field: str, value, entity_id: str, source_id: str) -> Claim:
    return Claim(
        claim_id=new_sortable_id("CLAIM"), entity_id=entity_id, field_name=field,
        value=value, value_type="string", qualifier="exact", source_id=source_id,
        raw_text=str(value), context_text=f"{field}={value}",
        verification_status=VerificationStatus.VERIFIED, confidence=0.95,
    )


class CatalogTests(unittest.TestCase):
    def test_catalog_items_advance_discovered_to_published(self) -> None:
        inventory = CatalogInventory()
        traverser = CatalogTraverser()
        traverser.discover(inventory, [
            {"name": "储能柜系列", "level": "family", "url": "https://www.acme-corp.com/p/family"},
            {"name": "ES-200", "level": "model", "url": "https://www.acme-corp.com/p/es200"},
        ])
        counts = inventory.by_state()
        self.assertEqual(counts["DISCOVERED"], 0)
        self.assertEqual(counts["VISITED"], 2)
        traverser.mark_extracted(
            inventory, ["储能柜系列", "ES-200"],
            product_id_by_name={"ES-200": "PROD-1"},
        )
        product = Product(
            product_id="PROD-1", entity_id="E1", name="ES-200", model="ES-200",
            verification_status=VerificationStatus.VERIFIED, source_ids=["S1"],
        )
        traverser.reconcile(inventory, [product])
        self.assertEqual(inventory.by_state()["VERIFIED"], 1)
        coverage = inventory.coverage()
        self.assertEqual(coverage, 1.0)

    def test_catalog_item_cannot_move_backwards(self) -> None:
        item = CatalogItem(item_id="C1", name="X", state="VERIFIED")
        with self.assertRaises(ValueError):
            item.transition("DISCOVERED")


class SynthesisTests(unittest.TestCase):
    def test_synthesis_is_claim_bound(self) -> None:
        with self.assertRaises(ValueError):
            SynthesisFinding(
                finding="无证据事实", supporting_claim_ids=[],
                supporting_source_ids=[], statement_type="EVIDENCE_SYNTHESIS",
            )
        source_id, entity_id = "S1", "E1"
        claims = [
            verified_claim("canonical_company_name", "ACME科技有限公司", entity_id, source_id),
            verified_claim("core_business", "储能系统研发制造", entity_id, source_id),
        ]
        from enterprise_energy_research.domain.models import Entity
        entity = Entity(entity_id=entity_id, canonical_name="ACME科技有限公司")
        synthesis = ResearchSynthesizer().synthesize(
            run_id="RUN-1", entity=entity, entities=[entity], claims=claims,
            sources=[], edges=[], factories=[], products=[],
            energy_profiles=[], gaps=[], solutions=[],
        )
        self.assertTrue(synthesis.findings)
        for finding in synthesis.findings:
            self.assertTrue(finding.supporting_claim_ids, finding.finding)
            self.assertTrue(finding.supporting_source_ids)

    def test_synthesis_summaries_have_substance(self) -> None:
        from enterprise_energy_research.domain.models import Entity
        source_id, entity_id = "S1", "E1"
        claims = [
            verified_claim("canonical_company_name", "ACME科技有限公司", entity_id, source_id),
            verified_claim("core_business", "储能系统研发制造", entity_id, source_id),
            verified_claim("revenue", "100亿元", entity_id, source_id),
            verified_claim("employee_count", "5000", entity_id, source_id),
        ]
        entity = Entity(entity_id=entity_id, canonical_name="ACME科技有限公司")
        synthesis = ResearchSynthesizer().synthesize(
            run_id="RUN-1", entity=entity, entities=[entity], claims=claims,
            sources=[], edges=[], factories=[], products=[],
            energy_profiles=[], gaps=[], solutions=[],
        )
        self.assertIn("储能系统研发制造", synthesis.executive_summary[1])
        self.assertEqual(synthesis.company_profile.revenue, "100亿元")


class ClaimUtilizationTests(unittest.TestCase):
    def test_high_value_claim_not_dropped(self) -> None:
        entity_id, source_id = "E1", "S1"
        claims = [
            verified_claim("canonical_company_name", "ACME科技有限公司", entity_id, source_id),
            verified_claim("revenue", "100亿元", entity_id, source_id),
            verified_claim("core_business", "储能", entity_id, source_id),
        ]
        high_value = high_value_claim_ids(claims)
        self.assertEqual(len(high_value), 3)
        audit = ClaimUtilizationAuditor().audit(
            claims, synthesis_claim_ids=[], artifact_claim_ids=[], table_claim_ids=[],
        )
        self.assertEqual(audit.unused_high_value_claims, sorted(high_value))
        self.assertFalse(audit.meets_target())

    def test_high_value_utilization_meets_target_when_used(self) -> None:
        entity_id, source_id = "E1", "S1"
        claims = [
            verified_claim("canonical_company_name", "ACME科技有限公司", entity_id, source_id),
            verified_claim("revenue", "100亿元", entity_id, source_id),
        ]
        audit = ClaimUtilizationAuditor().audit(
            claims, synthesis_claim_ids=[claims[0].claim_id, claims[1].claim_id],
            artifact_claim_ids=[], table_claim_ids=[],
        )
        self.assertEqual(audit.utilization_ratio, 1.0)
        self.assertTrue(audit.meets_target())
        with tempfile.TemporaryDirectory() as temp:
            path = audit.write(Path(temp))
            self.assertTrue(path.is_file())


class VerifiedClaimReachesPublisherTests(unittest.TestCase):
    def test_verified_claim_reaches_publisher(self) -> None:
        from enterprise_energy_research.artifacts.word import FrozenWordPublisher
        from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
        from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
        from enterprise_energy_research.evidence.freeze import FreezeService
        from enterprise_energy_research.evidence.store import EvidenceStore
        from enterprise_energy_research.graph.phase3_runner import Phase3Runner
        from enterprise_energy_research.graph.state import ResearchState
        from enterprise_energy_research.settings import load_yaml
        import json
        ROOT = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
            company = raw[0]["entities"][0]["canonical_name"]
            run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "recorded-fixture"},
            ))
            state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                company,
                [ExtractedEvidenceBatch.model_validate(item) for item in raw],
                output_dir=Path(temp) / "freeze",
            )
            self.assertIsNotNone(state.freeze_id)
            bundle = FreezeService(store).load_bundle(state.freeze_id)
            verified = [claim for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED]
            self.assertTrue(verified)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            result = FrozenWordPublisher().publish(bundle, binding, Path(temp) / "report.docx")
            self.assertEqual(result.status, "published")
            used = set(result.used_claim_ids)
            self.assertTrue([claim.claim_id for claim in verified if claim.claim_id in used])


if __name__ == "__main__":
    unittest.main()
