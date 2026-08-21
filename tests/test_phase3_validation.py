from __future__ import annotations

import unittest
import hashlib
import io
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image

from enterprise_energy_research.domain.enums import SourceLevel, VerificationStatus
from enterprise_energy_research.domain.models import Claim, Entity, ImageEvidence, Product, ProductParameter, Source
from enterprise_energy_research.research.claim_validator import ClaimValidator
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
from enterprise_energy_research.research.product_detector import ProductDetector
from enterprise_energy_research.research.source_grader import SourceGrader


class Phase3ValidationTests(unittest.TestCase):
    def _source(self, source_id: str, level: SourceLevel, domain: str, publisher: str) -> Source:
        return Source(
            source_id=source_id,
            canonical_url=f"https://{domain}/report",
            source_domain=domain,
            publisher=publisher,
            source_level=level,
            grading_reason="test fixture",
        )

    def _claim(self, claim_id: str, source_id: str, value: object) -> Claim:
        return Claim(
            claim_id=claim_id,
            entity_id="ENT-1",
            field_name="revenue",
            value=value,
            value_type="number",
            unit="CNY million",
            as_of_date=date(2025, 12, 31),
            scope="consolidated",
            source_id=source_id,
            raw_text=f"Revenue {value}",
            context_text=f"2025 consolidated revenue {value}",
            confidence=0,
        )

    def test_search_snippet_is_always_source_d(self) -> None:
        level, reason = SourceGrader().grade(
            "https://example.gov.cn/result", "government", is_search_snippet=True,
        )
        self.assertEqual(level, SourceLevel.SOURCE_D)
        self.assertIn("discovery-only", reason)

    def test_two_independent_source_b_origins_can_corroborate(self) -> None:
        sources = [
            self._source("SOURCE-S001", SourceLevel.SOURCE_B, "one.example.com", "Publisher One"),
            self._source("SOURCE-S002", SourceLevel.SOURCE_B, "two.example.com", "Publisher Two"),
        ]
        claims, conflicts = ClaimValidator().validate([
            self._claim("CLAIM-000001", "SOURCE-S001", 100),
            self._claim("CLAIM-000002", "SOURCE-S002", 100),
        ], sources)
        self.assertEqual(conflicts, [])
        self.assertTrue(all(item.verification_status == VerificationStatus.VERIFIED for item in claims))

    def test_conflicting_core_field_selects_most_authoritative_claim(self) -> None:
        sources = [
            self._source("SOURCE-S001", SourceLevel.SOURCE_A, "official.example.com", "Company"),
            self._source("SOURCE-S002", SourceLevel.SOURCE_A, "filing.example.gov.cn", "Regulator"),
        ]
        claims, conflicts = ClaimValidator().validate([
            self._claim("CLAIM-000001", "SOURCE-S001", 100),
            self._claim("CLAIM-000002", "SOURCE-S002", 120),
        ], sources)
        self.assertEqual(len(conflicts), 1)
        conflict = conflicts[0]
        self.assertEqual(conflict.status.value, "RESOLVED")
        self.assertEqual(conflict.resolution, "select_authoritative")
        self.assertEqual(conflict.selected_claim_ids, ["CLAIM-000002"])
        self.assertEqual(claims[1].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(claims[0].verification_status, VerificationStatus.CONFLICTING)

    def test_official_contextual_image_is_verified_but_small_image_is_rejected(self) -> None:
        entity = Entity(
            entity_id="ENT-1",
            canonical_name="示例能源装备有限公司",
            official_website="https://company.example.com",
        )
        source = self._source("SOURCE-S001", SourceLevel.SOURCE_A, "company.example.com", "Company")
        base = dict(
            entity_id=entity.entity_id,
            source_page_url="https://company.example.com/products",
            source_id=source.source_id,
            source_domain=source.source_domain,
            image_type="product",
            sha256="a" * 64,
            phash="0123456789abcdef",
            mime_type="image/jpeg",
            alt_text="示例能源装备有限公司储能产品",
            confidence=0,
        )
        images = [
            ImageEvidence(
                image_id="IMAGE-I001", source_url="https://company.example.com/a.jpg",
                width=1200, height=800, **base,
            ),
            ImageEvidence(
                image_id="IMAGE-I002", source_url="https://company.example.com/tiny.jpg",
                width=100, height=100, **{**base, "phash": "fedcba9876543210"},
            ),
        ]
        verified = ImageValidator().validate(images, [entity], [source])
        self.assertEqual(verified[0].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(verified[1].verification_status, VerificationStatus.REJECTED)

    def test_verified_image_is_archived_only_after_binary_hash_and_decode_match(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (320, 260), "white").save(buffer, format="PNG")
        payload = buffer.getvalue()
        image = ImageEvidence(
            image_id="IMAGE-I001", entity_id="ENT-1", product_id="PROD-1",
            source_url="https://company.example.com/product.png",
            source_page_url="https://company.example.com/products",
            source_id="SOURCE-S001", source_domain="company.example.com",
            image_type="product", sha256=hashlib.sha256(payload).hexdigest(),
            phash="0123456789abcdef", width=320, height=260, mime_type="image/png",
            verification_status=VerificationStatus.VERIFIED, confidence=0.95,
        )
        archiver = ImageAssetArchiver(fetcher=lambda _url, _referer: (payload, "image/png"))
        with tempfile.TemporaryDirectory() as temp:
            result = archiver.archive([image], Path(temp))
            archived = result.images[0]
            self.assertEqual(result.coverage_ratio, 1.0)
            self.assertTrue(archived.local_asset_ref)
            self.assertTrue((Path(temp) / archived.local_asset_ref).is_file())

    def test_product_families_without_catalog_scope_are_partial(self) -> None:
        source = self._source("SOURCE-S001", SourceLevel.SOURCE_A, "company.example.com", "Company")
        products = [Product(
            product_id="PROD-1", entity_id="ENT-1", name="人造石墨负极材料",
            category="负极材料", source_ids=[source.source_id],
        )]
        _, detection = ProductDetector().detect(products, [], [source], [])
        self.assertEqual(detection.coverage_status, "PARTIAL")
        self.assertFalse(detection.catalog_scope_verified)

    def test_verified_enumerated_catalog_with_model_and_parameters_is_complete(self) -> None:
        source = self._source("SOURCE-S001", SourceLevel.SOURCE_A, "company.example.com", "Company")
        claim = Claim(
            claim_id="CLAIM-000001", entity_id="ENT-1", field_name="product_catalog_scope",
            value={
                "official_product_centers": ["https://company.example.com/products"],
                "enumerated": True,
                "catalog_items": ["EP5-H"],
            },
            value_type="object", source_id=source.source_id, raw_text="官网列示EP5-H",
            context_text="已枚举产品中心", confidence=0.95,
            verification_status=VerificationStatus.VERIFIED,
        )
        products = [Product(
            product_id="PROD-1", entity_id="ENT-1", name="人造石墨负极材料", model="EP5-H",
            category="负极材料", parameters=[ProductParameter(name="D50", value=6, unit="μm")],
            source_ids=[source.source_id],
        )]
        _, detection = ProductDetector().detect(products, [], [source], [claim])
        self.assertEqual(detection.coverage_status, "COMPLETE")
        self.assertEqual(detection.catalog_coverage_ratio, 1.0)
        self.assertEqual(detection.unresolved_catalog_items, [])


if __name__ == "__main__":
    unittest.main()
