from __future__ import annotations

from energy_research_agent.domain.enums import ProductDashboardDecision, VerificationStatus
from typing import Any

from energy_research_agent.domain.models import Claim, ImageEvidence, Product, ProductDetection, Source


class ProductDetector:
    def detect(
        self,
        products: list[Product],
        images: list[ImageEvidence],
        sources: list[Source],
        claims: list[Claim] | None = None,
        *,
        require_archived_images: bool = False,
    ) -> tuple[list[Product], ProductDetection]:
        claims = claims or []
        source_levels = {source.source_id: source.source_level.value for source in sources}
        verified_images = {
            image.product_id: image.image_id
            for image in images
            if image.product_id
            and image.verification_status == VerificationStatus.VERIFIED
            and (not require_archived_images or bool(image.local_asset_ref))
        }
        qualifying: list[Product] = []
        updated: list[Product] = []
        for product in products:
            strong_source = any(source_levels.get(source_id) in {"SOURCE_A", "SOURCE_B"} for source_id in product.source_ids)
            has_identity = bool(product.name.strip() and product.entity_id)
            status = VerificationStatus.VERIFIED if strong_source and has_identity else VerificationStatus.UNVERIFIED
            item = product.model_copy(update={
                "verification_status": status,
                "image_id": product.image_id or verified_images.get(product.product_id),
            })
            updated.append(item)
            if status == VerificationStatus.VERIFIED and item.image_id:
                qualifying.append(item)
        verified_products = [item for item in updated if item.verification_status == VerificationStatus.VERIFIED]
        catalog_scope_verified, catalog_items = self._catalog_evidence(claims)
        matched, unresolved = self._match_catalog_items(catalog_items, verified_products)
        catalog_coverage_ratio = len(matched) / len(catalog_items) if catalog_items else 0.0
        model_level_count = sum(bool(item.model) for item in verified_products)
        parameterized_count = sum(bool(item.parameters) for item in verified_products)

        if not products:
            coverage_status = "NOT_ASSESSED"
            coverage_reason = "No physical products were discovered, so catalog coverage could not be assessed"
        elif not catalog_scope_verified:
            coverage_status = "PARTIAL"
            coverage_reason = "No verified declaration shows that every official product center and catalog page was enumerated"
        elif not catalog_items:
            coverage_status = "PARTIAL"
            coverage_reason = "The catalog scope was declared, but no catalog item inventory was captured"
        elif unresolved:
            coverage_status = "PARTIAL"
            coverage_reason = f"{len(unresolved)} catalog items have no matching verified product record"
        elif not any(item.model or item.parameters for item in verified_products):
            coverage_status = "PARTIAL"
            coverage_reason = "Only product families were captured; no model-level or parameter-level product record was verified"
        else:
            coverage_status = "COMPLETE"
            coverage_reason = "The verified official catalog scope is enumerated and all declared items map to product records"
        if qualifying:
            confidence = min(0.98, 0.75 + 0.03 * len(qualifying))
            decision = ProductDashboardDecision.GENERATE
            archive_label = " and archived verified images" if require_archived_images else ""
            reason = f"{len(qualifying)} physical products have traceable A/B-level evidence{archive_label}"
        else:
            confidence = 0.9 if not products else 0.55
            decision = ProductDashboardDecision.SKIP_PRODUCT_DASHBOARD
            reason = "No physical product met both the evidence and verified-image thresholds"
        return updated, ProductDetection(
            has_physical_products=bool(qualifying),
            product_confidence=confidence,
            product_count=len(qualifying),
            qualifying_product_ids=[item.product_id for item in qualifying],
            dashboard_decision=decision,
            reason=reason,
            coverage_status=coverage_status,
            catalog_scope_verified=catalog_scope_verified,
            catalog_item_count=len(catalog_items),
            matched_catalog_items=matched,
            unresolved_catalog_items=unresolved,
            catalog_coverage_ratio=catalog_coverage_ratio,
            verified_product_count=len(verified_products),
            model_level_product_count=model_level_count,
            parameterized_product_count=parameterized_count,
            coverage_reason=coverage_reason,
        )

    @staticmethod
    def _catalog_evidence(claims: list[Claim]) -> tuple[bool, list[str]]:
        verified = [item for item in claims if item.verification_status == VerificationStatus.VERIFIED]
        scope_verified = False
        catalog_items: list[str] = []
        for claim in verified:
            if claim.field_name == "product_catalog_scope" and isinstance(claim.value, dict):
                centers = claim.value.get("official_product_centers") or []
                scope_verified = scope_verified or bool(claim.value.get("enumerated") is True and centers)
                catalog_items.extend(ProductDetector._strings(claim.value.get("catalog_items")))
            elif claim.field_name in {"product_catalog_items", "product_portfolio", "products"}:
                catalog_items.extend(ProductDetector._strings(claim.value))
        deduped: list[str] = []
        seen: set[str] = set()
        for item in catalog_items:
            normalized = ProductDetector._normalize(item)
            if normalized and normalized not in seen:
                deduped.append(item.strip())
                seen.add(normalized)
        return scope_verified, deduped

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, (str, int, float))]
        return []

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = "".join(character.lower() for character in value if character.isalnum())
        for suffix in ("系列产品", "系列", "产品", "材料"):
            normalized = normalized.removesuffix(suffix)
        return normalized

    @classmethod
    def _match_catalog_items(cls, catalog_items: list[str], products: list[Product]) -> tuple[list[str], list[str]]:
        product_keys: list[str] = []
        for product in products:
            product_keys.extend(filter(None, (cls._normalize(product.name), cls._normalize(product.model or ""))))
        matched: list[str] = []
        unresolved: list[str] = []
        for item in catalog_items:
            expected = cls._normalize(item)
            is_match = any(expected == key or expected in key or key in expected for key in product_keys)
            (matched if is_match else unresolved).append(item)
        return matched, unresolved
