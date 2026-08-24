"""ChapterContentContract / Placeholder Content Gate / CoreResearchReadinessGate
(P0-9 / P0-10 / P0-11).

Chapters declare required evidence and minimum substantive facts. A chapter
without content is blocked or skipped — it is never padded with placeholder
paragraphs. The whole formal report is blocked when placeholder text exceeds
15% of the body (or 50% within one core chapter), and when core research
readiness is not met.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import (
    Claim,
    EnergyProfile,
    Entity,
    Factory,
    Product,
)

PLACEHOLDER_TOKENS = (
    "待核验", "未披露", "未形成", "待补充", "证据不足", "暂无",
    "需尽调", "公开资料不足", "待确认", "尚未取得", "未检索到",
)


class ChapterContentContract(BaseModel):
    chapter_key: str
    title: str
    required_evidence: list[str] = Field(default_factory=list)
    minimum_substantive_facts: int = 1
    fallback_behavior: str = "skip"  # skip | short_notice | block_report

    def assess(self, facts: list[str]) -> tuple[bool, str]:
        """Return (has_substantive_content, message)."""
        if not facts:
            return False, "no substantive facts present"
        if len(facts) < self.minimum_substantive_facts:
            return False, (
                f"only {len(facts)} substantive fact(s); minimum is "
                f"{self.minimum_substantive_facts}"
            )
        return True, f"{len(facts)} substantive fact(s)"


CHAPTER_CONTRACTS: dict[str, ChapterContentContract] = {
    "company_profile": ChapterContentContract(
        chapter_key="company_profile",
        title="企业概况",
        required_evidence=["verified_identity", "substantive_facts"],
        minimum_substantive_facts=3,
        fallback_behavior="block_report",
    ),
    "factories": ChapterContentContract(
        chapter_key="factories",
        title="生产基地",
        required_evidence=["verified_factory"],
        minimum_substantive_facts=1,
        fallback_behavior="skip",
    ),
    "products": ChapterContentContract(
        chapter_key="products",
        title="产品目录",
        required_evidence=["verified_product"],
        minimum_substantive_facts=1,
        fallback_behavior="skip",
    ),
    "financials": ChapterContentContract(
        chapter_key="financials",
        title="财务与经营数据",
        required_evidence=["financial_claim"],
        minimum_substantive_facts=1,
        fallback_behavior="skip",
    ),
    "energy": ChapterContentContract(
        chapter_key="energy",
        title="能源画像",
        required_evidence=["energy_evidence"],
        minimum_substantive_facts=1,
        fallback_behavior="skip",
    ),
    "cooperation": ChapterContentContract(
        chapter_key="cooperation",
        title="合作机会",
        required_evidence=["evidence_supported_opportunity"],
        minimum_substantive_facts=1,
        fallback_behavior="skip",
    ),
}


def placeholder_ratio(paragraphs: list[str]) -> float:
    """Share of body paragraphs dominated by placeholder tokens (P0-10)."""
    if not paragraphs:
        return 0.0
    hits = 0
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        if any(token in paragraph for token in PLACEHOLDER_TOKENS):
            hits += 1
    return hits / len(paragraphs)


class PlaceholderContentGate(BaseModel):
    body_paragraphs: list[str] = Field(default_factory=list)
    chapter_paragraphs: dict[str, list[str]] = Field(default_factory=dict)
    overall_limit: float = 0.15
    chapter_limit: float = 0.50

    def assess(self) -> dict:
        overall = placeholder_ratio(self.body_paragraphs)
        blocked_chapters: list[str] = []
        for chapter, paragraphs in self.chapter_paragraphs.items():
            if placeholder_ratio(paragraphs) > self.chapter_limit:
                blocked_chapters.append(chapter)
        blocked = overall > self.overall_limit or bool(blocked_chapters)
        return {
            "placeholder_paragraph_ratio": round(overall, 4),
            "status": "RESEARCH_CONTENT_BLOCKED" if overall > self.overall_limit else (
                "CHAPTER_CONTENT_BLOCKED" if blocked_chapters else "PASS"
            ),
            "blocked_chapters": blocked_chapters,
            "blocked": blocked,
        }


def chapter_substantive_facts(chapter_key: str, *, entities, claims, edges, factories, products, energy_profiles) -> list[str]:
    """Collect substantive fact strings for one chapter contract (P0-9)."""
    from enterprise_energy_research.research.profiles import PublishableEntityEvaluator

    verified_claims = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
    facts: list[str] = []
    if chapter_key == "company_profile":
        evaluator = PublishableEntityEvaluator()
        for entity in entities:
            publishable, _ = evaluator.evaluate(entity, claims, edges, factories, products)
            if publishable:
                facts.append(entity.canonical_name)
        for claim in verified_claims:
            if claim.field_name in {
                "core_business", "business_segment", "revenue", "profit",
                "employee_count", "headquarters", "founded_date", "actual_controller",
            } and claim.value not in (None, "", []):
                facts.append(f"{claim.field_name}={claim.value}")
    elif chapter_key == "factories":
        for factory in factories:
            detail = [
                factory.name, factory.address,
                "、".join(factory.processes) if factory.processes else "",
            ]
            if len([item for item in detail if item]) >= 2:
                facts.append("；".join(item for item in detail if item))
    elif chapter_key == "products":
        for product in products:
            if product.verification_status == VerificationStatus.VERIFIED:
                facts.append(product.name)
    elif chapter_key == "financials":
        for claim in verified_claims:
            if claim.field_name in {
                "revenue", "profit", "total_assets", "investment", "employee_count",
            } and claim.value not in (None, "", []):
                facts.append(f"{claim.field_name}={claim.value}")
    elif chapter_key == "energy":
        for claim in verified_claims:
            if claim.field_name in {
                "energy_consumption", "electricity_consumption", "energy_equipment",
                "roof_area", "transformer_capacity", "energy_project", "pv_capacity",
            } and claim.value not in (None, "", []):
                facts.append(f"{claim.field_name}={claim.value}")
        for profile in energy_profiles:
            if profile.processes or profile.electricity_equipment or profile.roof:
                facts.append(profile.energy_profile_id)
    elif chapter_key == "cooperation":
        facts.extend(
            f"{claim.field_name}={claim.value}"
            for claim in verified_claims
            if claim.field_name.endswith(("_project", "_opportunity")) and claim.value not in (None, "", [])
        )
    return facts


class CoreResearchReadinessGate(BaseModel):
    """P0-11: formal Word/HTML publication requires real research content."""

    def assess(
        self,
        *,
        entities: list[Entity],
        claims: list[Claim],
        edges,
        factories: list[Factory],
        products: list[Product],
        is_large_enterprise: bool = True,
        minimum_substantive_claims: int = 20,
        canonical_entity_id: str | None = None,
    ) -> dict:
        from enterprise_energy_research.research.profiles import PublishableEntityEvaluator
        from enterprise_energy_research.research.entity_scope import normalized_entity_name

        scoped_claims = [
            claim for claim in claims
            if canonical_entity_id is None or claim.entity_id == canonical_entity_id
        ]
        verified_claims = [claim for claim in scoped_claims if claim.verification_status == VerificationStatus.VERIFIED]
        evaluator = PublishableEntityEvaluator()
        if canonical_entity_id is None:
            verified_identity = any(
                evaluator.evaluate(entity, claims, edges, factories, products)[0]
                for entity in entities
            )
        else:
            canonical = next((entity for entity in entities if entity.entity_id == canonical_entity_id), None)
            names = ({normalized_entity_name(canonical.canonical_name),
                      normalized_entity_name(canonical.registered_name),
                      *(normalized_entity_name(item) for item in canonical.aliases)} - {""}) if canonical else set()
            verified_identity = bool(canonical and canonical.verification_status == VerificationStatus.VERIFIED and any(
                claim.field_name in {"canonical_company_name", "registered_name", "aliases"}
                and normalized_entity_name(claim.value) in names
                for claim in verified_claims
            ))
        substantive = [
            claim for claim in verified_claims
            if claim.field_name in {
                "canonical_company_name", "registered_name", "core_business",
                "business_segment", "revenue", "profit", "gross_profit",
                "total_assets", "total_liabilities", "employee_count",
                "factory_name", "capacity", "process", "product_family",
                "model", "parameter_name", "technology", "certification",
                "customer_name", "supplier_name", "electricity_consumption",
                "energy_consumption", "roof_area", "project_name",
                "pv_capacity", "storage_power", "headquarters", "founded_date",
                "actual_controller", "parent_company", "ownership_structure",
                "investment", "export", "industry_position",
            } and claim.value not in (None, "", [])
        ]
        categories_covered: set[str] = set()
        for claim in substantive:
            if claim.field_name in {"core_business", "business_segment"}:
                categories_covered.add("business")
            elif claim.field_name in {
                "revenue", "profit", "gross_profit", "total_assets",
                "total_liabilities", "employee_count", "investment",
            }:
                categories_covered.add("financial")
            elif claim.field_name in {"factory_name", "capacity", "process", "subsidiary_name"}:
                categories_covered.add("factory/subsidiary")
            elif claim.field_name in {
                "product_family", "model", "parameter_name", "series",
            }:
                categories_covered.add("product")
        readiness = {
            "verified_company_identity": verified_identity,
            "substantive_verified_claims": len(substantive),
            "minimum_substantive_claims": minimum_substantive_claims,
            "categories_covered": sorted(categories_covered),
            "required_categories": ["business", "financial", "factory/subsidiary", "product"],
            "status": "PASS",
            "diagnostics": [],
        }
        if not verified_identity:
            readiness["status"] = "RESEARCH_CONTENT_BLOCKED"
            readiness["diagnostics"].append("no verified company identity")
        if is_large_enterprise and len(substantive) < minimum_substantive_claims:
            readiness["status"] = "RESEARCH_CONTENT_BLOCKED"
            readiness["diagnostics"].append(
                f"substantive verified claims {len(substantive)} < {minimum_substantive_claims}"
            )
        if len(categories_covered) < 3:
            readiness["status"] = "RESEARCH_CONTENT_BLOCKED"
            readiness["diagnostics"].append(
                f"category coverage {len(categories_covered)}/4 < 3"
            )
        return readiness
