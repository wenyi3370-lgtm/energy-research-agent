"""CompanyProfileBuilder / GroupProfile / PublishableEntityEvaluator (P0-5/6/7/8).

The formal report body describes a company; it never dumps research-system
metadata (entity_type / verification_status / entity_id / claim_id /
source_level / freeze_id / schema_version). A CompanyProfile is built from
verified claims, edges, factories and products; every field comes from
evidence or stays empty.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import (
    Claim,
    EnterpriseEdge,
    Entity,
    Factory,
    Product,
)


class CompanyProfile(BaseModel):
    entity_id: str
    company_name: str
    registered_name: str | None = None
    founded_date: str | None = None
    headquarters: str | None = None
    registration_region: str | None = None
    official_website: str | None = None
    parent_company: str | None = None
    actual_controller: str | None = None
    ownership_summary: str | None = None
    core_business: str | None = None
    business_segments: list[str] = Field(default_factory=list)
    revenue: object | None = None
    profit: object | None = None
    employee_count: object | None = None
    subsidiaries: list[str] = Field(default_factory=list)
    factories: list[str] = Field(default_factory=list)
    product_families: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)

    @property
    def substantive_fact_count(self) -> int:
        """Number of non-empty substantive business facts (P0-7 gate input)."""
        candidates = (
            self.registered_name, self.headquarters, self.parent_company,
            self.actual_controller, self.ownership_summary, self.core_business,
            self.revenue, self.profit, self.employee_count, self.founded_date,
        )
        return (
            sum(1 for value in candidates if value not in (None, "", []))
            + (1 if self.business_segments else 0)
            + (1 if self.subsidiaries else 0)
            + (1 if self.factories else 0)
            + (1 if self.product_families else 0)
        )


class GroupProfile(BaseModel):
    """Group companies render as a group, never as a flat list of "company" rows."""

    group_id: str
    group_name: str
    registered_name: str | None = None
    headquarters: str | None = None
    actual_controller: str | None = None
    core_business: str | None = None
    business_segments: list[str] = Field(default_factory=list)
    tier1_subsidiaries: list[dict] = Field(default_factory=list)  # {name, entity_id, business}
    production_entities: list[dict] = Field(default_factory=list)  # {name, entity_id}
    factories: list[dict] = Field(default_factory=list)  # {name, address, operator}
    product_families: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)


class CompanyProfileBuilder:
    """Build a publishable CompanyProfile from verified evidence only."""

    @staticmethod
    def _verified(claims: list[Claim], entity_id: str) -> dict[str, Claim]:
        result: dict[str, Claim] = {}
        for claim in claims:
            if claim.entity_id != entity_id or claim.verification_status != VerificationStatus.VERIFIED:
                continue
            current = result.get(claim.field_name)
            if current is None or claim.confidence > current.confidence:
                result[claim.field_name] = claim
        return result

    def build(
        self,
        entity: Entity,
        claims: list[Claim],
        edges: list[EnterpriseEdge],
        factories: list[Factory],
        products: list[Product],
        entities: list[Entity] | None = None,
    ) -> CompanyProfile:
        verified = self._verified(claims, entity.entity_id)
        entity_names = {item.entity_id: item.canonical_name for item in (entities or [])}

        def value(field: str):
            claim = verified.get(field)
            return claim.value if claim else None

        def multi(field: str) -> list[str]:
            return sorted({
                str(claim.value) for claim in claims
                if claim.entity_id == entity.entity_id
                and claim.field_name == field
                and claim.verification_status == VerificationStatus.VERIFIED
                and claim.value not in (None, "", [])
            })

        child_ids = [
            edge.to_id for edge in edges
            if edge.from_id == entity.entity_id
            and edge.relation == "Subsidiary"
            and edge.verification_status == VerificationStatus.VERIFIED
        ]
        subsidiary_names = sorted({
            entity_names.get(child_id, child_id) for child_id in child_ids
        })
        factory_names = [
            factory.name for factory in factories
            if factory.operator_entity_id == entity.entity_id and factory.name
        ]
        product_families = sorted({
            product.name for product in products
            if product.entity_id == entity.entity_id
            and product.verification_status == VerificationStatus.VERIFIED
        })
        return CompanyProfile(
            entity_id=entity.entity_id,
            company_name=entity.canonical_name,
            registered_name=entity.registered_name,
            founded_date=str(value("founded_date")) if value("founded_date") is not None else None,
            headquarters=str(value("headquarters")) if value("headquarters") is not None else None,
            registration_region=entity.registration_region,
            official_website=str(entity.official_website) if entity.official_website else None,
            parent_company=str(value("parent_company")) if value("parent_company") is not None else None,
            actual_controller=str(value("actual_controller")) if value("actual_controller") is not None else None,
            ownership_summary=str(value("ownership_structure")) if value("ownership_structure") is not None else None,
            core_business=str(value("core_business")) if value("core_business") is not None else None,
            business_segments=multi("business_segment"),
            revenue=value("revenue"),
            profit=value("profit"),
            employee_count=value("employee_count"),
            subsidiaries=subsidiary_names,
            factories=sorted(factory_names),
            product_families=product_families,
            supporting_claim_ids=[claim.claim_id for claim in verified.values()],
            supporting_source_ids=sorted({claim.source_id for claim in verified.values()}),
        )


class GroupProfileBuilder:
    """Build a GroupProfile from verified evidence only (no LLM guessing)."""

    def build(
        self,
        group: Entity,
        entities: list[Entity],
        claims: list[Claim],
        edges: list[EnterpriseEdge],
        factories: list[Factory],
        products: list[Product],
    ) -> GroupProfile:
        names = {item.entity_id: item.canonical_name for item in entities}
        profile = CompanyProfileBuilder().build(group, claims, edges, factories, products, entities=entities)
        tier1 = [
            {
                "name": names.get(edge.to_id, edge.to_id),
                "entity_id": edge.to_id,
                "business": self._business_of(edge.to_id, claims),
            }
            for edge in edges
            if edge.from_id == group.entity_id
            and edge.relation == "Subsidiary"
            and edge.verification_status == VerificationStatus.VERIFIED
        ]
        production: dict[tuple[str, str], dict] = {}
        for factory in factories:
            if factory.operator_entity_id == group.entity_id:
                continue
            key = (factory.operator_entity_id, names.get(factory.operator_entity_id, factory.operator_entity_id))
            production.setdefault(key, {"name": key[1], "entity_id": key[0]})
        factory_rows = [
            {
                "name": factory.name or "未命名生产基地",
                "address": factory.address,
                "operator": names.get(factory.operator_entity_id, factory.operator_entity_id),
            }
            for factory in factories
        ]
        return GroupProfile(
            group_id=group.entity_id,
            group_name=group.canonical_name,
            registered_name=group.registered_name,
            headquarters=profile.headquarters,
            actual_controller=profile.actual_controller,
            core_business=profile.core_business,
            business_segments=profile.business_segments,
            tier1_subsidiaries=tier1,
            production_entities=sorted(production.values(), key=lambda item: str(item["name"])),
            factories=factory_rows,
            product_families=profile.product_families,
            supporting_claim_ids=profile.supporting_claim_ids,
        )

    @staticmethod
    def _business_of(entity_id: str, claims: list[Claim]) -> str | None:
        for claim in claims:
            if claim.entity_id == entity_id and claim.field_name == "core_business" \
                    and claim.verification_status == VerificationStatus.VERIFIED:
                return str(claim.value)
        return None


SUBSTANTIVE_CATEGORIES = (
    "registered_name", "headquarters", "ownership", "core_business",
    "business_segment", "financial", "factory", "product", "technology",
)


class PublishableEntityEvaluator:
    """P0-7: an entity enters the formal body only with a verified identity
    AND at least 2 substantive fact categories. Everything else stays in the
    evidence store / appendix."""

    def evaluate(
        self,
        entity: Entity,
        claims: list[Claim],
        edges: list[EnterpriseEdge],
        factories: list[Factory],
        products: list[Product],
    ) -> tuple[bool, list[str]]:
        profile = CompanyProfileBuilder().build(entity, claims, edges, factories, products)
        verified = [
            claim for claim in claims
            if claim.entity_id == entity.entity_id and claim.verification_status == VerificationStatus.VERIFIED
        ]
        verified_identity = bool(
            [claim for claim in verified if claim.field_name in {"canonical_company_name", "registered_name"}]
        )
        categories: set[str] = set()
        if profile.registered_name:
            categories.add("registered_name")
        if profile.headquarters or profile.registration_region:
            categories.add("headquarters")
        if profile.parent_company or profile.actual_controller or profile.ownership_summary:
            categories.add("ownership")
        if profile.core_business:
            categories.add("core_business")
        if profile.business_segments:
            categories.add("business_segment")
        if profile.revenue is not None or profile.profit is not None or profile.employee_count is not None:
            categories.add("financial")
        if profile.factories or any(factory.operator_entity_id == entity.entity_id for factory in factories):
            categories.add("factory")
        if profile.product_families:
            categories.add("product")
        if any(claim.field_name in {"technology", "patent", "certification"} for claim in verified):
            categories.add("technology")
        publishable = verified_identity and len(categories) >= 2
        reasons: list[str] = []
        if not verified_identity:
            reasons.append("no verified identity evidence")
        if len(categories) < 2:
            reasons.append(f"only {len(categories)} substantive fact category(ies): {sorted(categories) or 'none'}")
        return publishable, reasons
