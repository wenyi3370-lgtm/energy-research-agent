"""IdentityEvidenceContract (P0-1).

The company-resolution deadlock: CompanyResolver can RESOLVE a company from
an official page, but EntityMapper only marks an Entity VERIFIED when a
VERIFIED ``canonical_company_name``/``registered_name`` Claim exists — and
nothing produced such Claims. This module closes that loop:

1. ``IdentityEvidenceSynthesizer`` turns page-level identity evidence
   (ExtractedEntity records) into provenance-bound identity Claims. Values
   are taken ONLY from what the page produced; nothing is invented (a bare
   "宁德时代" never becomes a fabricated registered name).
2. ``IdentityEvidenceContract`` audits the invariant: every identity field
   populated on a formally published Entity must have a supporting Claim
   with source_id/provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim,
    CompanyResolution,
    Entity,
    ExtractedEntity,
    ExtractedEvidenceBatch,
    Source,
)
from pydantic import HttpUrl

from .contracts import IDENTITY_FIELDS

OFFICIAL_SOURCE_KINDS = {
    "government", "sasac", "annual_report", "official_manual",
    "official_announcement", "official_company",
}

# ExtractedEntity field name -> canonical Claim field name.
ENTITY_FIELD_TO_CLAIM_FIELD = {
    "registered_name": "registered_name",
    "official_website": "official_website",
    "registration_region": "registration_region",
    "headquarters": "headquarters",
    "founded_date": "founded_date",
    "parent_company": "parent_company",
    "actual_controller": "actual_controller",
    "registration_identifier": "registration_identifier",
}


@dataclass
class IdentityEvidenceContract:
    """Audit result for one Entity's identity evidence coverage."""

    entity_id: str
    verified_identity: bool = False
    covered_fields: list[str] = field(default_factory=list)
    uncovered_fields: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def check(self, entity: Entity, claims: list[Claim]) -> "IdentityEvidenceContract":
        claims_by_field: dict[str, list[Claim]] = {}
        for claim in claims:
            if claim.entity_id != entity.entity_id:
                continue
            claims_by_field.setdefault(claim.field_name, []).append(claim)
        self.covered_fields = [
            name for name in IDENTITY_FIELDS
            if any(claim.value not in (None, "", []) for claim in claims_by_field.get(name, []))
        ]
        self.uncovered_fields = [name for name in IDENTITY_FIELDS if name not in self.covered_fields]
        verified_identity_claims = [
            claim for name in ("canonical_company_name", "registered_name")
            for claim in claims_by_field.get(name, [])
            if claim.verification_status == VerificationStatus.VERIFIED and claim.value not in (None, "")
        ]
        self.verified_identity = bool(verified_identity_claims)
        # Field-with-value-without-Claim is the production bug this contract
        # exists to prevent. A canonical_company_name Claim with the same
        # value also supports registered_name (normalizer fallback).
        name_claim_values = {str(claim.value) for claim in claims_by_field.get("canonical_company_name", [])}
        for name in ("registered_name", "official_website", "registration_region"):
            value = getattr(entity, name, None)
            if value in (None, ""):
                continue
            supported = any(claim.value not in (None, "") for claim in claims_by_field.get(name, []))
            if not supported and name == "registered_name" and str(value) in name_claim_values:
                supported = True
            if not supported:
                self.violations.append(
                    f"{entity.entity_id}.{name} has a value without a supporting identity Claim"
                )
        return self


def _norm_name(value: str) -> str:
    suffixes = ("有限责任公司", "股份有限公司", "有限公司", "集团公司", "集团")
    folded = "".join(value.lower().split())
    for suffix in suffixes:
        if folded.endswith(suffix):
            folded = folded[: -len(suffix)]
    return folded


class IdentityEvidenceSynthesizer:
    """Derive identity Claims from page entity records (never from the input name alone)."""

    def synthesize(
        self,
        resolution: CompanyResolution,
        batches: list[ExtractedEvidenceBatch],
        entities: list[Entity],
        sources: list[Source],
    ) -> list[Claim]:
        selected_candidate = self._selected_candidate(resolution)
        if selected_candidate is None:
            return []
        selected = next(
            (entity for entity in entities if entity.canonical_name == selected_candidate.canonical_name),
            None,
        )
        if selected is None:
            return []
        claims: list[Claim] = []
        emitted: set[tuple[str, str]] = set()
        # Official/full pages first: snippet-derived entity records must not
        # shadow a real page's identity evidence (discovery-only ordering).
        ordered_batches = sorted(
            enumerate(batches),
            key=lambda row: (row[1].is_search_snippet, not self.is_official_page(row[1], selected)),
        )
        for index, batch in ordered_batches:
            source = sources[index] if index < len(sources) else None
            if source is None:
                continue
            for extracted in batch.entities:
                if _norm_name(extracted.canonical_name) != _norm_name(selected.canonical_name):
                    continue
                self._emit(claims, emitted, selected, extracted, source, batch)
        return claims

    @staticmethod
    def _selected_candidate(resolution: CompanyResolution):
        if not resolution.selected_candidate_id:
            return None
        return next(
            (candidate for candidate in resolution.candidates
             if candidate.candidate_id == resolution.selected_candidate_id),
            None,
        )

    def _emit(
        self,
        claims: list[Claim],
        emitted: set[tuple[str, str]],
        selected: Entity,
        extracted: ExtractedEntity,
        source: Source,
        batch: ExtractedEvidenceBatch,
    ) -> None:
        pairs: list[tuple[str, object]] = [("canonical_company_name", extracted.canonical_name)]
        for entity_field, claim_field in ENTITY_FIELD_TO_CLAIM_FIELD.items():
            value = getattr(extracted, entity_field, None)
            if value not in (None, "", []):
                pairs.append((claim_field, value))
        pairs.append(("aliases", extracted.aliases) if extracted.aliases else ("aliases", None))
        for field_name, value in pairs:
            if field_name == "aliases":
                for alias in extracted.aliases:
                    self._add(claims, emitted, selected, field_name, alias, source, batch)
                continue
            if value in (None, "", []):
                continue
            self._add(claims, emitted, selected, field_name, value, source, batch)

    @staticmethod
    def _add(
        claims: list[Claim],
        emitted: set[tuple[str, str]],
        selected: Entity,
        field_name: str,
        value: object,
        source: Source,
        batch: ExtractedEvidenceBatch,
    ) -> None:
        # HttpUrl and other non-JSON values must be stored as plain strings.
        if isinstance(value, HttpUrl):
            value = str(value).rstrip("/")
        key = (field_name, str(value))
        if key in emitted:
            return
        emitted.add(key)
        title = batch.source_title or ""
        claims.append(Claim(
            claim_id=new_sortable_id("CLAIM"),
            entity_id=selected.entity_id,
            field_name=field_name,
            value=value,
            value_type="string",
            qualifier="exact",
            source_id=source.source_id,
            raw_text=str(value),
            context_text=f"来源页面：{title or batch.publisher or source.source_domain}（{source.canonical_url}）",
            locator={"url": str(source.canonical_url), "origin": "page entity record"},
            verification_status=VerificationStatus.UNVERIFIED,
            confidence=0.0,
            notes=(
                "official page identity evidence" if batch.source_kind in OFFICIAL_SOURCE_KINDS
                else "identity evidence from page entity record (verification pending source level)"
            ),
        ))

    @staticmethod
    def is_official_page(batch: ExtractedEvidenceBatch, entity: Entity) -> bool:
        """True when the page is the company's own official source."""
        if batch.is_search_snippet:
            return False
        if batch.source_kind in OFFICIAL_SOURCE_KINDS:
            return True
        if entity.official_website:
            official_host = urlparse(str(entity.official_website)).netloc.lower().removeprefix("www.")
            page_host = urlparse(str(batch.source_url)).netloc.lower().removeprefix("www.")
            return bool(official_host and (page_host == official_host or page_host.endswith("." + official_host)))
        return False
