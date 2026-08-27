from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from energy_research_agent.domain.enums import (
    EnterpriseComplexity,
    RunStatus,
    SourceLevel,
    VerificationStatus,
)
from energy_research_agent.domain.models import (
    Claim,
    DataFreeze,
    Entity,
    FrozenResearchBundle,
    Product,
    RunManifest,
    Source,
)
from energy_research_agent.research.deep_retry import revalidate_product_state
from energy_research_agent.research.normalizer import NormalizedEvidence
from energy_research_agent.validation.formal_publication import (
    ProductPublicationIntegrityValidator,
)
from energy_research_agent.automation.orchestration import OrchestratingExecutor


def _bundle(*, product_status: VerificationStatus | None, with_claim: bool = False) -> FrozenResearchBundle:
    entity = Entity(
        entity_id="ENT-1",
        canonical_name="样本新能源企业",
        verification_status=VerificationStatus.VERIFIED,
    )
    source = Source(
        source_id="SOURCE-A",
        canonical_url="https://example.com/products/model-a",
        source_domain="example.com",
        source_level=SourceLevel.SOURCE_A,
        grading_reason="official product page",
    )
    products = [] if product_status is None else [Product(
        product_id="PROD-1",
        entity_id=entity.entity_id,
        name="Model A 储能系统",
        source_ids=[source.source_id],
        verification_status=product_status,
    )]
    claims = []
    if with_claim:
        claims.append(Claim(
            claim_id="CLAIM-PRODUCT-1",
            entity_id=entity.entity_id,
            field_name="product_family",
            value="储能系统",
            value_type="string",
            qualifier="exact",
            source_id=source.source_id,
            raw_text="产品包括储能系统",
            context_text="样本新能源企业产品包括储能系统",
            verification_status=VerificationStatus.VERIFIED,
            confidence=0.95,
        ))
    return FrozenResearchBundle(
        freeze=DataFreeze(
            freeze_id="FREEZE-1",
            run_id="RUN-1",
            evidence_version=1,
            included_record_ids={},
            record_hashes={},
            root_hash="0" * 64,
            validation_report_id="VAL-1",
        ),
        run_manifest=RunManifest(
            run_id="RUN-1",
            request_id="REQ-1",
            status=RunStatus.RUNNING,
            canonical_entity_id=entity.entity_id,
            complexity=EnterpriseComplexity.ENTERPRISE_NORMAL,
            config_hash="test",
            code_version="test",
            model_gateway={"mode": "fixture"},
        ),
        entities=[entity],
        sources=[source],
        claims=claims,
        products=products,
    )


class ProductPublicationIntegrityTests(unittest.TestCase):
    def test_post_retry_revalidation_promotes_text_supported_product_without_image(self) -> None:
        bundle = _bundle(product_status=VerificationStatus.UNVERIFIED)
        evidence = NormalizedEvidence()
        evidence.entities = list(bundle.entities)
        evidence.sources = list(bundle.sources)
        evidence.products = list(bundle.products)

        detection = revalidate_product_state(evidence, require_archived_images=True)

        self.assertEqual(evidence.products[0].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(detection.verified_product_count, 1)
        self.assertEqual(detection.product_count, 0)
        self.assertFalse(detection.has_physical_products)

    def test_formal_gate_blocks_strong_product_record_left_unverified(self) -> None:
        assessment = ProductPublicationIntegrityValidator().assess(
            _bundle(product_status=VerificationStatus.UNVERIFIED)
        )
        self.assertEqual(assessment.status, "BLOCKED")
        self.assertEqual(assessment.strong_source_products, 1)
        self.assertEqual(assessment.verified_products, 0)

    def test_formal_gate_blocks_verified_product_claim_without_product_object(self) -> None:
        assessment = ProductPublicationIntegrityValidator().assess(
            _bundle(product_status=None, with_claim=True)
        )
        self.assertEqual(assessment.status, "BLOCKED")
        self.assertEqual(assessment.verified_product_claims, 1)
        self.assertEqual(assessment.verified_products, 0)

    def test_formal_gate_accepts_verified_product_and_service_only_enterprise(self) -> None:
        product = ProductPublicationIntegrityValidator().assess(
            _bundle(product_status=VerificationStatus.VERIFIED)
        )
        service = ProductPublicationIntegrityValidator().assess(
            _bundle(product_status=None, with_claim=False)
        )
        self.assertEqual(product.status, "PASS")
        self.assertEqual(service.status, "PASS")

    def test_automation_repair_reads_product_integrity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            quality_dir = run_dir / "outputs" / "02_research_quality"
            quality_dir.mkdir(parents=True)
            (quality_dir / "formal_publication_eligibility.json").write_text(
                json.dumps({
                    "status": "BLOCKED",
                    "diagnostics": [
                        "product evidence exists but publishable VERIFIED product records are zero"
                    ],
                    "product_integrity": {"status": "BLOCKED"},
                }),
                encoding="utf-8",
            )

            codes, messages = OrchestratingExecutor._publication_qa_failures(run_dir)
            requirements = OrchestratingExecutor._publication_repair_requirements(
                codes, messages,
            )

            self.assertIn("product_publication_integrity", codes)
            self.assertIn("产品目录规范化与状态核验", requirements)
            self.assertIn("不得用图片缺失", requirements)


if __name__ == "__main__":
    unittest.main()
