from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from energy_research_agent.domain.enums import RunStatus, SourceLevel, VerificationStatus
from energy_research_agent.domain.models import Claim, Entity, RunManifest, Source
from energy_research_agent.evidence.freeze import FreezeService
from energy_research_agent.evidence.store import EvidenceStore, EvidenceStoreError
from energy_research_agent.validation.core import CoreValidator


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "test.sqlite3")
        self.run = RunManifest(
            run_id="RUN-TEST",
            request_id="REQ-TEST",
            status=RunStatus.RUNNING,
            config_hash="a" * 64,
            code_version="test",
            model_gateway={"mode": "test"},
        )
        self.store.create_run(self.run)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_valid_evidence(self, source_level: SourceLevel = SourceLevel.SOURCE_A) -> None:
        self.store.add("RUN-TEST", 1, "entity", Entity(
            entity_id="ENT-TEST", canonical_name="测试企业", verification_status=VerificationStatus.VERIFIED,
        ))
        self.store.add("RUN-TEST", 1, "source", Source(
            source_id="SOURCE-S001",
            canonical_url="https://example.com/company",
            source_domain="example.com",
            source_level=source_level,
            grading_reason="official_company" if source_level == SourceLevel.SOURCE_A else "search snippet",
        ))
        self.store.add("RUN-TEST", 1, "claim", Claim(
            claim_id="CLAIM-000001",
            entity_id="ENT-TEST",
            field_name="canonical_company_name",
            value="测试企业",
            value_type="string",
            source_id="SOURCE-S001",
            raw_text="测试企业",
            context_text="企业名称：测试企业",
            verification_status=VerificationStatus.VERIFIED,
            confidence=1.0,
        ))

    def test_freeze_prevents_mutation_of_same_version(self) -> None:
        self.add_valid_evidence()
        report = CoreValidator(self.store).validate("RUN-TEST", 1)
        FreezeService(self.store).create("RUN-TEST", 1, report)
        with self.assertRaises(EvidenceStoreError):
            self.store.add("RUN-TEST", 1, "entity", Entity(entity_id="ENT-NEW", canonical_name="新企业"))

    def test_freeze_is_idempotent_for_unchanged_evidence(self) -> None:
        self.add_valid_evidence()
        service = FreezeService(self.store)
        first = service.create("RUN-TEST", 1, CoreValidator(self.store).validate("RUN-TEST", 1))
        second = service.create("RUN-TEST", 1, CoreValidator(self.store).validate("RUN-TEST", 1))
        self.assertEqual(second.freeze_id, first.freeze_id)
        self.assertEqual(second.root_hash, first.root_hash)

    def test_weak_verified_source_blocks(self) -> None:
        self.add_valid_evidence(SourceLevel.SOURCE_D)
        report = CoreValidator(self.store).validate("RUN-TEST", 1)
        self.assertEqual(report.status.value, "BLOCKED")
        self.assertIn("WEAK_SOURCE_MARKED_VERIFIED", {item.code for item in report.findings})

    def test_orphan_claim_blocks(self) -> None:
        self.store.add("RUN-TEST", 1, "entity", Entity(entity_id="ENT-TEST", canonical_name="测试企业"))
        self.store.add("RUN-TEST", 1, "claim", Claim(
            claim_id="CLAIM-ORPHAN",
            entity_id="ENT-TEST",
            field_name="revenue",
            value=100,
            value_type="number",
            source_id="SOURCE-MISSING",
            raw_text="营业收入100亿元",
            context_text="示例上下文：营业收入100亿元",
            confidence=0.5,
        ))
        with self.assertRaises(EvidenceStoreError):
            self.store.assert_referential_integrity("RUN-TEST", 1)


if __name__ == "__main__":
    unittest.main()
