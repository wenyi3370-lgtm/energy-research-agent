from __future__ import annotations

from enterprise_energy_research.domain.enums import EnterpriseComplexity
from enterprise_energy_research.domain.models import ComplexityDecision, Entity, EnterpriseEdge, Factory, Product


class EnterpriseComplexityClassifier:
    def __init__(self, rules: dict) -> None:
        self.rules = rules

    def classify(
        self,
        entity: Entity,
        entities: list[Entity],
        factories: list[Factory],
        edges: list[EnterpriseEdge],
        products: list[Product] | None = None,
    ) -> ComplexityDecision:
        signals: dict[str, int] = {}
        large_weights = self.rules.get("group_large", {}).get("signals", {})
        small_weights = self.rules.get("small_simple", {}).get("signals", {})
        children = {edge.to_id for edge in edges if edge.from_id == entity.entity_id and edge.relation in {"Owns", "Subsidiary"}}
        operated_factories = [item for item in factories if item.operator_entity_id == entity.entity_id or item.operator_entity_id in children]
        name = entity.canonical_name
        if "集团" in name:
            signals["group_in_canonical_name"] = int(large_weights.get("group_in_canonical_name", 2))
        if len(children) >= 2:
            signals["multiple_subsidiaries"] = int(large_weights.get("multiple_subsidiaries", 2))
        if len(operated_factories) >= 2:
            signals["multiple_factories"] = int(large_weights.get("multiple_factories", 2))
        if not children:
            signals["no_known_subsidiaries"] = int(small_weights.get("no_known_subsidiaries", -1))
        if len(operated_factories) <= 1:
            signals["single_factory"] = int(small_weights.get("single_factory", -1))
        owned_products = [item for item in (products or []) if item.entity_id == entity.entity_id]
        if operated_factories and (owned_products or any(item.processes for item in operated_factories)):
            # Workflow complexity only; this is not a legal enterprise-size conclusion.
            signals["manufacturing_footprint"] = 4
        score = sum(signals.values())
        large_threshold = int(self.rules.get("group_large", {}).get("minimum_score", 5))
        small_threshold = int(self.rules.get("small_simple", {}).get("maximum_score", -1))
        if score >= large_threshold:
            complexity = EnterpriseComplexity.GROUP_LARGE
        elif score <= small_threshold and entity.verification_status.value == "VERIFIED":
            complexity = EnterpriseComplexity.SMALL_SIMPLE
        elif entity.verification_status.value == "VERIFIED":
            complexity = EnterpriseComplexity.ENTERPRISE_NORMAL
        else:
            complexity = EnterpriseComplexity.UNKNOWN
        return ComplexityDecision(
            complexity=complexity,
            score=score,
            signals=signals,
            rationale=f"Workflow score {score}; this is not a legal enterprise-size classification.",
        )
