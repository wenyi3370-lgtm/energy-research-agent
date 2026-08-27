"""Three-dimensional routing for user requirements and recovery searches.

Every goal is classified independently along:

* ``goal_domain``: what business question is being answered;
* ``subject_role``: whose facts the query is expected to discover;
* ``evidence_use``: where those facts may be consumed in publication.

This keeps target-enterprise metrics, competitors, ecosystem parties and
policy context auditable without forcing them into one undifferentiated pool.
The mapping is deliberately data-driven so new Goal Families can be added
without branching the workflow in multiple places.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RequirementRoute:
    goal_domain: str
    subject_role: str
    evidence_lane: str
    evidence_use: str

    def model_updates(self) -> dict[str, str]:
        return asdict(self)


DOMAIN_TOPICS: dict[str, set[str]] = {
    "identity_governance": {
        "company_identity", "ownership_structure", "organization", "subsidiaries",
    },
    "manufacturing_footprint": {
        "factories", "locations", "capacity", "production_lines",
    },
    "product_technology": {
        "products", "product_series", "product_models", "product_parameters",
        "technology", "patents", "certifications",
    },
    "financial_performance": {
        "financials", "revenue", "profit", "employees", "strategic_trajectory",
        "business_drivers",
    },
    "commercial_channels": {
        "sales_channels", "customers", "customer_market_proof",
    },
    "supply_chain": {"suppliers"},
    "competitive_intelligence": {"industry_position", "competitive_position"},
    "policy_regulation": {"policy_regulation"},
    "energy_operations": {
        "energy_consumption", "energy_equipment", "electricity_load", "natural_gas",
        "compressed_air", "heat", "waste_heat", "roof_area", "renewable_energy",
        "energy_projects", "carbon_projects",
    },
    "cooperation_opportunity": {
        "cooperation_timing", "EPC_opportunities", "energy_saving_opportunities",
        "storage_opportunities", "V2G_opportunities", "overseas_opportunities",
    },
    "risk": {"enterprise_risks", "risks"},
    "visual_evidence": {"image_evidence"},
    "custom_supplement": {"custom_requirement"},
}

TOPIC_DOMAIN = {
    topic: domain for domain, topics in DOMAIN_TOPICS.items() for topic in topics
}

GROUP_TOPICS = {"ownership_structure", "organization", "subsidiaries"}
COMPETITOR_TOPICS = {"competitive_position"}
ECOSYSTEM_TOPICS = {"sales_channels", "customers", "customer_market_proof", "suppliers"}
POLICY_TOPICS = {"policy_regulation"}


def route_for_topic(topic: str) -> RequirementRoute:
    domain = TOPIC_DOMAIN.get(topic, "general_enterprise_research")
    if topic in COMPETITOR_TOPICS:
        return RequirementRoute(domain, "competitor", "comparison", "comparison_context")
    if topic in POLICY_TOPICS:
        return RequirementRoute(domain, "public_authority", "policy_context", "policy_context")
    if topic in ECOSYSTEM_TOPICS:
        return RequirementRoute(domain, "ecosystem_party", "ecosystem", "relationship_context")
    if topic in GROUP_TOPICS:
        return RequirementRoute(domain, "group_member", "enterprise_group", "target_context")
    if topic == "image_evidence":
        return RequirementRoute(domain, "target_enterprise", "target", "visual_support")
    if topic == "custom_requirement":
        return RequirementRoute(domain, "target_enterprise", "target", "target_context")
    return RequirementRoute(domain, "target_enterprise", "target", "target_fact")


def routing_manifest(topics: list[str]) -> list[dict[str, str]]:
    return [
        {"topic": topic, **route_for_topic(topic).model_updates()}
        for topic in dict.fromkeys(topics)
    ]
