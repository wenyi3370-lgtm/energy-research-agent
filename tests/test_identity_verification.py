"""P0-1 / P0-6 / P0-7 regression: identity evidence, verification semantics,
CompanyProfile substance, publishable-entity gating and the publisher body
never dumping internal research metadata.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.domain.enums import RunStatus, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim, CompanyCandidate, CompanyResolution, Entity, ExtractedEvidenceBatch,
    RunManifest, Source,
)
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.entity_mapper import EntityMapper
from enterprise_energy_research.research.identity_evidence import (
    IdentityEvidenceContract, IdentityEvidenceSynthesizer,
)
from enterprise_energy_research.research.normalizer import EvidenceNormalizer
from enterprise_energy_research.research.profiles import (
    CompanyProfile, CompanyProfileBuilder, PublishableEntityEvaluator,
)
from enterprise_energy_research.research.resolver import CompanyResolver
from enterprise_energy_research.settings import load_yaml

ROOT = Path(__file__).resolve().parents[1]


def official_batch(**overrides) -> ExtractedEvidenceBatch:
    payload = {
        "source_url": "https://www.acme-corp.com/about",
        "source_title": "ACME 公司简介",
        "publisher": "ACME 公司",
        "source_kind": "official_company",
        "extraction_method": "model_structured",
        "retrieval_adapter": "anysearch",
        "is_search_snippet": False,
        "entities": [{
            "entity_key": "acme",
            "canonical_name": "ACME科技有限公司",
            "entity_type": "company",
            "aliases": ["ACME"],
            "official_website": "https://www.acme-corp.com",
            "registration_region": "中国广东省深圳市",
            "registered_name": "ACME科技有限公司",
            "headquarters": "广东省深圳市南山区",
            "founded_date": "2010年",
            "parent_company": "ACME控股集团有限公司",
            "actual_controller": "公开披露的实际控制人",
        }],
        "claims": [
            {
                "entity_key": "acme", "field_name": "canonical_company_name",
                "value": "ACME科技有限公司", "value_type": "string",
                "raw_text": "公司全称：ACME科技有限公司", "context_text": "ACME科技有限公司是一家储能装备企业。",
                "qualifier": "exact",
            },
            {
                "entity_key": "acme", "field_name": "core_business",
                "value": "储能系统研发制造与综合能源服务", "value_type": "string",
                "raw_text": "主营业务为储能系统研发制造与综合能源服务",
                "context_text": "公司主营业务为储能系统研发制造与综合能源服务。", "qualifier": "exact",
            },
        ],
        "factories": [], "products": [], "images": [],
    }
    payload.update(overrides)
    return ExtractedEvidenceBatch.model_validate(payload)


def normalized(batches) -> tuple:
    evidence = EvidenceNormalizer().normalize(batches)
    evidence.claims, evidence.conflicts = ClaimValidator().validate(evidence.claims, evidence.sources)
    evidence.entities, evidence.edges = EntityMapper().apply_evidence(
        evidence.entities, evidence.edges, evidence.claims,
    )
    return evidence.entities, evidence.claims


class IdentityVerificationTests(unittest.TestCase):
    def test_brand_candidate_maps_to_legal_name_after_entity_merge(self) -> None:
        batch = ExtractedEvidenceBatch.model_validate({
            "source_url": "https://www.starcharge.com/about",
            "source_title": "星星充电公司介绍",
            "source_kind": "official_company",
            "extraction_method": "model_structured",
            "entities": [{
                "entity_key": "star", "canonical_name": "星星充电",
                "registered_name": "万帮星星充电科技有限公司",
                "aliases": ["StarCharge"],
            }],
        })
        evidence = EvidenceNormalizer().normalize([batch])
        # Entity consolidation may retain the legal name as its primary while
        # the resolver's winning candidate is the public brand.
        legal = evidence.entities[0].model_copy(update={
            "canonical_name": "万帮星星充电科技有限公司",
            "aliases": ["星星充电", "StarCharge"],
        })
        resolution = CompanyResolution(
            raw_company_name="星星充电",
            candidates=[CompanyCandidate(
                candidate_id="star", canonical_name="星星充电", score=0.95,
            )],
            selected_candidate_id="star", confidence=0.95,
            status="RESOLVED", rationale="test",
        )

        claims = IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], [legal], evidence.sources,
        )

        self.assertTrue(claims)
        self.assertTrue(all(item.entity_id == legal.entity_id for item in claims))

    def test_official_company_page_creates_identity_claims(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        self.assertEqual(resolution.status, "RESOLVED")
        entities, claims = normalized([batch])
        identity_claims = IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], entities, EvidenceNormalizer().normalize([batch]).sources,
        )
        fields = {claim.field_name for claim in identity_claims}
        self.assertIn("canonical_company_name", fields)
        self.assertIn("registered_name", fields)
        self.assertIn("official_website", fields)
        for claim in identity_claims:
            self.assertTrue(claim.source_id)
            self.assertTrue(claim.claim_id)

    def test_resolved_entity_becomes_verified_when_identity_evidence_exists(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims.extend(IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        ))
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        self.assertEqual(evidence.entities[0].verification_status, VerificationStatus.VERIFIED)

    def test_entity_cannot_be_verified_without_identity_evidence(self) -> None:
        # Social-media page: source level D, no identity claim may verify the entity.
        batch = official_batch(
            source_kind="social_media",
            source_url="https://www.weibo.com/post/1",
            claims=[{
                "entity_key": "acme", "field_name": "revenue",
                "value": "100亿元", "value_type": "string",
                "raw_text": "年收入100亿元", "context_text": "该公司年收入100亿元。",
                "qualifier": "exact",
            }],
        )
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        self.assertEqual(evidence.entities[0].verification_status, VerificationStatus.UNVERIFIED)

    def test_registered_name_has_supporting_claim(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        evidence = EvidenceNormalizer().normalize([batch])
        claims = IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        )
        registered = [claim for claim in claims if claim.field_name == "registered_name"]
        self.assertTrue(registered)
        self.assertEqual(registered[0].value, "ACME科技有限公司")

    def test_official_website_has_provenance(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        evidence = EvidenceNormalizer().normalize([batch])
        claims = IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        )
        website_claims = [claim for claim in claims if claim.field_name == "official_website"]
        self.assertTrue(website_claims)
        self.assertEqual(str(website_claims[0].value), "https://www.acme-corp.com")
        self.assertEqual(website_claims[0].source_id, evidence.sources[0].source_id)
        self.assertIn(str(evidence.sources[0].canonical_url), website_claims[0].context_text)

    def test_resolution_and_verification_semantics_are_consistent(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        self.assertEqual(resolution.status, "RESOLVED")
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims.extend(IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        ))
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        contract = IdentityEvidenceContract(entity_id=evidence.entities[0].entity_id)
        contract.check(evidence.entities[0], evidence.claims)
        self.assertTrue(contract.verified_identity)
        self.assertFalse(contract.violations)

    def test_official_company_page_produces_verified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "recorded-fixture"},
            ))
            state, _, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                "ACME", [official_batch()], output_dir=Path(temp) / "out",
            )
            self.assertIn(state.status, (RunStatus.PASS, RunStatus.PASS_WITH_WARNINGS))
            entities = store.list(run_id, "entity")
            self.assertEqual(entities[0].verification_status, VerificationStatus.VERIFIED)

    def test_resolved_entity_not_left_unverified_when_supported(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        self.assertEqual(resolution.status, "RESOLVED")
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims.extend(IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        ))
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        self.assertNotEqual(evidence.entities[0].verification_status, VerificationStatus.UNVERIFIED)


class ProfileAndPublishableTests(unittest.TestCase):
    def test_company_profile_not_internal_metadata(self) -> None:
        batch = official_batch()
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        profile = CompanyProfileBuilder().build(
            evidence.entities[0], evidence.claims, evidence.edges,
            evidence.factories, evidence.products,
        )
        for field_name in ("entity_type", "verification_status", "claim_id", "source_level", "freeze_id", "schema_version"):
            self.assertNotIn(field_name, profile.model_fields)
        dumped = profile.model_dump_json()
        self.assertNotIn("UNVERIFIED", dumped)
        self.assertNotIn("实体类型", dumped)

    def test_company_profile_contains_substantive_business_facts(self) -> None:
        batch = official_batch()
        resolution = CompanyResolver().resolve("ACME", [batch])
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims.extend(IdentityEvidenceSynthesizer().synthesize(
            resolution, [batch], evidence.entities, evidence.sources,
        ))
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        profile = CompanyProfileBuilder().build(
            evidence.entities[0], evidence.claims, evidence.edges,
            evidence.factories, evidence.products,
        )
        self.assertEqual(profile.company_name, "ACME科技有限公司")
        self.assertEqual(profile.registered_name, "ACME科技有限公司")
        self.assertEqual(profile.headquarters, "广东省深圳市南山区")
        self.assertEqual(profile.core_business, "储能系统研发制造与综合能源服务")
        self.assertGreaterEqual(profile.substantive_fact_count, 3)

    def test_empty_entity_not_published(self) -> None:
        entity = Entity(
            entity_id=new_sortable_id("ENT"), canonical_name="空壳公司",
            verification_status=VerificationStatus.UNVERIFIED,
        )
        evaluator = PublishableEntityEvaluator()
        publishable, reasons = evaluator.evaluate(entity, [], [], [], [])
        self.assertFalse(publishable)
        self.assertTrue(reasons)

    def test_unverified_entity_not_dumped_into_body(self) -> None:
        batch = official_batch()
        evidence = EvidenceNormalizer().normalize([batch])
        evidence.claims, _ = ClaimValidator().validate(evidence.claims, evidence.sources)
        evidence.entities, _ = EntityMapper().apply_evidence(
            evidence.entities, evidence.edges, evidence.claims,
        )
        empty = Entity(
            entity_id=new_sortable_id("ENT"), canonical_name="无证据企业",
            verification_status=VerificationStatus.UNVERIFIED,
        )
        evaluator = PublishableEntityEvaluator()
        publishable, _ = evaluator.evaluate(
            empty, evidence.claims, evidence.edges, evidence.factories, evidence.products,
        )
        self.assertFalse(publishable)

    def test_word_body_contains_no_internal_metadata(self) -> None:
        from enterprise_energy_research.artifacts.word import FrozenWordPublisher
        from enterprise_energy_research.domain.enums import ArtifactType
        from enterprise_energy_research.evidence.freeze import FreezeService
        with tempfile.TemporaryDirectory() as temp:
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "recorded-fixture"},
            ))
            state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                "ACME", [official_batch()], output_dir=Path(temp) / "freeze",
            )
            self.assertIsNotNone(state.freeze_id)
            bundle = FreezeService(store).load_bundle(state.freeze_id)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published")
            from docx import Document
            document = Document(target)
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            self.assertNotIn("实体类型", text)
            self.assertNotIn("核验状态", text)
            self.assertNotIn("注册区域：", text)
            self.assertIn("ACME科技有限公司", text)
            self.assertIn("储能系统研发制造与综合能源服务", text)


if __name__ == "__main__":
    unittest.main()
