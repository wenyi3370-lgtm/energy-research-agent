"""ProductImageResolver: bind verified product photos to product records.

A product photo often arrives AFTER product extraction (image discovery
runs on pages opened later in the pipeline), so ``Product.image_id`` may
still be None at freeze time.  This resolver rebuilds the relationship at
Narrative stage from the frozen evidence itself — it never creates new
evidence and never invents a binding:

Priority:
  1. ``product.image_id`` already set by extraction;
  2. a VERIFIED and pixel-verified image whose exact target/product ID equals
     the product;
  3. no photo. Name-only/context-only matches never enter formal publication.
"""

from __future__ import annotations

import re

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import FrozenResearchBundle

from .publication_relevance import IDENTITY_FIELDS  # noqa: F401  (kept for stable imports)

_NAME_NORMALIZE = re.compile(r"[^0-9a-zA-Z\u3400-\u9fff\u4e00-\u9fff]+")


def normalize_product_name(name: str) -> str:
    return _NAME_NORMALIZE.sub("", (name or "").lower())


class ProductImageResolver:
    """Rebuild product->image bindings from frozen evidence."""

    def resolve(self, bundle: FrozenResearchBundle) -> dict[str, str]:
        verified_images = [
            image for image in bundle.images
            if image.verification_status == VerificationStatus.VERIFIED
            and image.visual_verified
            and image.verification_method == "vision"
        ]
        by_product = {
            image.product_id: image
            for image in verified_images
            if image.target_entity_type == "product"
            and image.product_id is not None
            and image.target_entity_id == image.product_id
        }
        products = [
            product for product in bundle.products
            if product.verification_status == VerificationStatus.VERIFIED
        ]
        resolved: dict[str, str] = {}
        for product in products:
            direct = next((image for image in verified_images if image.image_id == product.image_id), None)
            if direct is not None and self._is_official_domain(direct.source_domain, bundle):
                resolved[product.product_id] = product.image_id
                continue
            bound = by_product.get(product.product_id)
            if bound is not None and self._is_official_domain(bound.source_domain, bundle):
                resolved[product.product_id] = bound.image_id
        return resolved

    @staticmethod
    def _is_official_domain(domain: str, bundle: FrozenResearchBundle) -> bool:
        for entity in bundle.entities:
            website = entity.official_website
            if website and website.host and (
                domain == website.host or domain.endswith("." + website.host)
            ):
                return True
        return False

    @staticmethod
    def _match_by_name(product_name: str, images: list) -> object | None:
        normalized = normalize_product_name(product_name)
        if not normalized or len(normalized) < 2:
            return None
        best = None
        best_len = 0
        for image in images:
            context = " ".join(filter(None, (
                image.alt_text or "", image.surrounding_text or "",
                image.source_title or "",
            )))
            folded = normalize_product_name(context)
            if normalized in folded and len(normalized) > best_len:
                best = image
                best_len = len(normalized)
        return best
