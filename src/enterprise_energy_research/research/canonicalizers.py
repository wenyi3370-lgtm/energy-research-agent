"""Canonicalizers (P0 refactor): normalization BEFORE Freeze.

UnitNormalizer fixes mechanical unit corruption (``kmkm`` → ``km``,
``%%`` → ``%``, ``次次`` → ``次``, ``年年`` → ``年``) and common aliases.
ProductCanonicalizer / FactoryCanonicalizer merge duplicate records of the
same real-world object and keep the union of their evidence ids, so the
frozen bundle has one canonical record per product/factory.
EntityResolver resolves a name (claim text, alias) to the canonical entity.

Everything here is deterministic and evidence-preserving: values and claim
ids are never invented; duplicates are merged, not dropped.
"""

from __future__ import annotations

import re
from typing import Any

from enterprise_energy_research.domain.models import Claim, Entity, Factory, ImageEvidence, Product

# Mechanical unit fixes: doubled suffixes are extraction artefacts.
_UNIT_FIXES: list[tuple[str, str]] = [
    ("kmkm", "km"), ("%%%%", "%%"), ("%%", "%"), ("次次", "次"),
    ("年年", "年"), ("度度", "度"), ("元元", "元"), ("瓦瓦", "瓦"),
    ("克克", "克"), ("吨吨", "吨"), ("升升", "升"), ("米米", "米"),
    ("小时时", "小时"), ("天天", "天"), ("月月", "月"),
]

_UNIT_ALIASES: dict[str, str] = {
    "kwh": "kWh", "KWH": "kWh", "千瓦时": "kWh", "兆瓦时": "MWh", "mwh": "MWh",
    "吉瓦时": "GWh", "gwh": "GWh", "兆瓦": "MW", "吉瓦": "GW", "千瓦": "kW",
    "万kwh": "万kWh", "万度": "万kWh", "万千瓦时": "万kWh", "度": "kWh",
    "万元": "万元", "亿元": "亿元", "元": "元", "％": "%", "百分比": "%",
}


class UnitNormalizer:
    """Fix mechanical unit corruption and unify common aliases."""

    def normalize(self, unit: str | None) -> str | None:
        if not unit:
            return unit
        cleaned = " ".join(str(unit).split()).strip()
        if not cleaned:
            return None
        changed = True
        while changed:
            changed = False
            for broken, fixed in _UNIT_FIXES:
                if broken in cleaned:
                    cleaned = cleaned.replace(broken, fixed)
                    changed = True
        # collapse segments like "kWh/kWh" that still repeat after fixing
        parts = [part for part in re.split(r"[/·\s]+", cleaned) if part]
        if len(parts) >= 2 and len(set(parts)) == 1 and cleaned:
            cleaned = parts[0]
        return _UNIT_ALIASES.get(cleaned, cleaned)

    def normalize_claim(self, claim: Claim) -> Claim:
        unit = self.normalize(claim.unit)
        if unit != claim.unit:
            claim = claim.model_copy(update={"unit": unit})
        return claim

    def normalize_claims(self, claims: list[Claim]) -> list[Claim]:
        return [self.normalize_claim(claim) for claim in claims]


def _name_key(name: str) -> str:
    """Case/space/punctuation-insensitive identity key for entity names."""
    return re.sub(r"[\s·\-—_()（）【】\[\].,，。、'\"“”]", "", str(name)).lower()


class ProductCanonicalizer:
    """Merge duplicate product records of the same real-world product.

    Returns ``(merged_products, rebind)`` where ``rebind`` maps every
    merged-away product id to its surviving canonical id, so edges and
    images keep pointing at real records (referential integrity).
    """

    def canonicalize(self, products: list[Product], images: list[ImageEvidence] | None = None) -> tuple[list[Product], dict[str, str]]:
        images = images or []
        merged: dict[str, Product] = {}
        rebind: dict[str, str] = {}  # merged-away product_id -> canonical product_id
        for product in products:
            key = _name_key(f"{product.name}|{product.model or ''}|{product.category or ''}")
            existing = merged.get(key)
            if existing is None:
                merged[key] = product.model_copy(deep=True)
            else:
                merged[key] = self._merge(existing, product)
                canonical_id = merged[key].product_id
                rebind[existing.product_id] = canonical_id
                rebind[product.product_id] = canonical_id
        for image in images:
            if image.product_id in rebind:
                image.product_id = rebind[image.product_id]
        return list(merged.values()), rebind

    @staticmethod
    def _merge(keep: Product, other: Product) -> Product:
        return keep.model_copy(update={
            "name": keep.name or other.name,
            "brand": keep.brand or other.brand,
            "model": keep.model or other.model,
            "category": keep.category or other.category,
            "series": keep.series or other.series,
            "description": keep.description or other.description,
            "parameters": keep.parameters or other.parameters,
            "applications": sorted(set(keep.applications + other.applications)),
            "customer_segment": keep.customer_segment or other.customer_segment,
            "commercial_status": keep.commercial_status or other.commercial_status,
            "image_id": keep.image_id or other.image_id,
            "source_ids": sorted(set(keep.source_ids + other.source_ids)),
            "verification_status": keep.verification_status,
        })


class FactoryCanonicalizer:
    """Merge duplicate factory records of the same physical site.

    Returns ``(merged_factories, rebind)`` so operators' edges can be
    remapped to the surviving canonical factory id (referential integrity).
    """

    def canonicalize(self, factories: list[Factory]) -> tuple[list[Factory], dict[str, str]]:
        merged: dict[str, Factory] = {}
        rebind: dict[str, str] = {}
        for factory in factories:
            key = _name_key(f"{factory.name or ''}|{factory.address or ''}")
            existing = merged.get(key)
            if existing is None:
                merged[key] = factory.model_copy(deep=True)
            else:
                merged[key] = FactoryCanonicalizer._merge(existing, factory)
                canonical_id = merged[key].factory_id
                rebind[existing.factory_id] = canonical_id
                rebind[factory.factory_id] = canonical_id
        return list(merged.values()), rebind

    @staticmethod
    def _merge(keep: Factory, other: Factory) -> Factory:
        return keep.model_copy(update={
            "name": keep.name or other.name,
            "address": keep.address or other.address,
            "latitude": keep.latitude if keep.latitude is not None else other.latitude,
            "longitude": keep.longitude if keep.longitude is not None else other.longitude,
            "processes": sorted(set(keep.processes + other.processes)),
            "operating_status": keep.operating_status or other.operating_status,
            "supporting_claim_ids": sorted(set(keep.supporting_claim_ids + other.supporting_claim_ids)),
        })


class EntityResolver:
    """Resolve names to canonical entities; reject ambiguous/unknown names."""

    def __init__(self, entities: list[Entity] | None = None) -> None:
        self._index: dict[str, str] = {}
        if entities:
            for entity in entities:
                for name in [entity.canonical_name, entity.registered_name, *entity.aliases]:
                    if name:
                        self._index[_name_key(name)] = entity.entity_id

    def resolve(self, name: str) -> str | None:
        key = _name_key(name)
        if not key:
            return None
        return self._index.get(key)
