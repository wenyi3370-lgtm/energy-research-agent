"""Shared fail-closed gate for every formal publication entry point."""

from __future__ import annotations

from pydantic import BaseModel, Field

from energy_research_agent.domain.enums import EnterpriseComplexity, VerificationStatus
from energy_research_agent.domain.models import FrozenResearchBundle
from energy_research_agent.research.content_contract import CoreResearchReadinessGate
from energy_research_agent.research.data_coverage import ResearchDataCoverageValidator
from energy_research_agent.research.entity_scope import (
    allowed_publication_entity_ids,
    canonical_entity,
    publication_identity_errors,
    scoped_factories,
    scoped_products,
    target_claims,
)


PRODUCT_FACT_FIELDS = {
    "product_family", "products", "product_portfolio", "product_catalog_items",
    "product_catalog_scope", "series", "model", "product_parameter",
    "product_parameters", "product_certification", "product_launch_date",
}


class ProductPublicationIntegrityAssessment(BaseModel):
    status: str = "PASS"
    product_records: int = 0
    verified_products: int = 0
    verified_product_claims: int = 0
    strong_source_products: int = 0
    diagnostics: list[str] = Field(default_factory=list)


class ProductPublicationIntegrityValidator:
    """Block silent loss between product evidence and publication objects.

    Product images are deliberately absent from this contract.  They have a
    separate acquisition/publication gate and must never determine whether a
    product supported by reliable textual evidence exists in the report.
    """

    def assess(self, bundle: FrozenResearchBundle) -> ProductPublicationIntegrityAssessment:
        allowed_ids = allowed_publication_entity_ids(bundle)
        products = scoped_products(bundle)
        verified_products = [
            product for product in products
            if product.verification_status == VerificationStatus.VERIFIED
        ]
        verified_product_claims = [
            claim for claim in bundle.claims
            if claim.entity_id in allowed_ids
            and claim.verification_status == VerificationStatus.VERIFIED
            and claim.value not in (None, "", [])
            and (
                claim.field_name in PRODUCT_FACT_FIELDS
                or claim.field_name.startswith("product_")
            )
        ]
        source_levels = {
            source.source_id: source.source_level.value for source in bundle.sources
        }
        strong_source_products = [
            product for product in products
            if any(source_levels.get(source_id) in {"SOURCE_A", "SOURCE_B"}
                   for source_id in product.source_ids)
        ]
        diagnostics: list[str] = []
        if (verified_product_claims or strong_source_products) and not verified_products:
            diagnostics.append(
                "product evidence exists but publishable VERIFIED product records are zero; "
                "re-run product normalization/status validation before freeze"
            )
        return ProductPublicationIntegrityAssessment(
            status="BLOCKED" if diagnostics else "PASS",
            product_records=len(products),
            verified_products=len(verified_products),
            verified_product_claims=len(verified_product_claims),
            strong_source_products=len(strong_source_products),
            diagnostics=diagnostics,
        )


class FormalPublicationAssessment(BaseModel):
    status: str = "PASS"
    diagnostics: list[str] = Field(default_factory=list)
    high_coverage_gaps: list[str] = Field(default_factory=list)
    readiness: dict = Field(default_factory=dict)
    product_integrity: dict = Field(default_factory=dict)


class FormalPublicationEligibilityValidator:
    """Identity, entity scope, data coverage and research-density gate."""

    def validate(self, bundle: FrozenResearchBundle) -> FormalPublicationAssessment:
        entity = canonical_entity(bundle)
        diagnostics = publication_identity_errors(bundle)
        if entity is None:
            return FormalPublicationAssessment(status="BLOCKED", diagnostics=diagnostics)

        claims = target_claims(bundle)
        products = scoped_products(bundle)
        factories = scoped_factories(bundle)
        complexity = bundle.run_manifest.complexity or EnterpriseComplexity.UNKNOWN
        has_stock_code = any(
            claim.field_name == "stock_code" and claim.value not in (None, "", [])
            for claim in claims
        )
        coverage = ResearchDataCoverageValidator().audit(
            entity_name=entity.canonical_name,
            claims=claims,
            products=products,
            factories=factories,
            images=bundle.images,
            complexity=complexity,
            has_stock_code=has_stock_code,
        )
        high_gaps = [gap.gap_code for gap in coverage.high_gaps]
        if high_gaps:
            diagnostics.append("unresolved high coverage gaps: " + ", ".join(high_gaps))

        readiness = CoreResearchReadinessGate().assess(
            entities=bundle.entities,
            claims=bundle.claims,
            edges=bundle.edges,
            factories=bundle.factories,
            products=bundle.products,
            is_large_enterprise=complexity == EnterpriseComplexity.GROUP_LARGE,
            canonical_entity_id=entity.entity_id,
        )
        if readiness["status"] != "PASS":
            diagnostics.extend(str(item) for item in readiness.get("diagnostics", []))
        product_integrity = ProductPublicationIntegrityValidator().assess(bundle)
        if product_integrity.status != "PASS":
            diagnostics.extend(product_integrity.diagnostics)
        return FormalPublicationAssessment(
            status="BLOCKED" if diagnostics else "PASS",
            diagnostics=list(dict.fromkeys(diagnostics)),
            high_coverage_gaps=high_gaps,
            readiness=readiness,
            product_integrity=product_integrity.model_dump(mode="json"),
        )
