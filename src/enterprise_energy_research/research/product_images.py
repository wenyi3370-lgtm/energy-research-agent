"""ProductImageResolver: bind verified product photos to product records.

A product photo often arrives AFTER product extraction (image discovery
runs on pages opened later in the pipeline), so ``Product.image_id`` may
still be None at freeze time.  This resolver rebuilds the relationship at
Narrative stage from the frozen evidence itself — it never creates new
evidence and never invents a binding:

Priority:
  1. ``product.image_id`` already set by extraction;
  2. a VERIFIED image whose ``product_id`` equals the product;
  3. a VERIFIED image from an official source whose alt/surrounding/page
     text names the product (normalized name match);
  4. no photo (renderers show a text-only card, never a fake image).
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
        ]
        by_product = {
            image.product_id: image for image in verified_images if image.product_id
        }
        official_images = [
            image for image in verified_images
            if image.source_domain and self._is_official_domain(image.source_domain, bundle)
        ]
        products = [
            product for product in bundle.products
            if product.verification_status == VerificationStatus.VERIFIED
        ]
        resolved: dict[str, str] = {}
        for product in products:
            if product.image_id:
                resolved[product.product_id] = product.image_id
                continue
            bound = by_product.get(product.product_id)
            if bound is not None:
                resolved[product.product_id] = bound.image_id
                continue
            matched = self._match_by_name(product.name, official_images)
            if matched is not None:
                resolved[product.product_id] = matched.image_id
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
