from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import RunSequence, new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim,
    ConflictGroup,
    DataGap,
    EnergyProfile,
    EnterpriseEdge,
    Entity,
    ExtractedEvidenceBatch,
    Factory,
    ImageEvidence,
    Product,
    Retrieval,
    Source,
)

from .source_grader import SourceGrader


@dataclass
class NormalizedEvidence:
    entities: list[Entity] = field(default_factory=list)
    factories: list[Factory] = field(default_factory=list)
    edges: list[EnterpriseEdge] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    retrievals: list[Retrieval] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    conflicts: list[ConflictGroup] = field(default_factory=list)
    gaps: list[DataGap] = field(default_factory=list)
    images: list[ImageEvidence] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    energy_profiles: list[EnergyProfile] = field(default_factory=list)


class EvidenceNormalizer:
    def __init__(self, grader: SourceGrader | None = None) -> None:
        self.grader = grader or SourceGrader()

    def normalize(
        self,
        batches: list[ExtractedEvidenceBatch],
        *,
        official_domains: set[str] | None = None,
        query_ids: list[str] | None = None,
    ) -> NormalizedEvidence:
        sequence = RunSequence()
        output = NormalizedEvidence()
        declared_entity_keys = {item.entity_key for batch in batches for item in batch.entities}
        declared_factory_keys = {item.factory_key for batch in batches for item in batch.factories}
        declared_product_keys = {item.product_key for batch in batches for item in batch.products}
        entity_ids = {key: new_sortable_id("ENT") for key in declared_entity_keys}
        factory_ids = {key: new_sortable_id("FAC") for key in declared_factory_keys}
        product_ids = {key: new_sortable_id("PROD") for key in declared_product_keys}
        seen_entities: set[str] = set()
        seen_factories: set[str] = set()
        seen_products: set[str] = set()
        edge_keys: set[tuple[str, str, str]] = set()

        for batch_index, batch in enumerate(batches):
            source_id = sequence.next("source")
            url = str(batch.source_url)
            source_level, grading_reason = self.grader.grade(
                url, batch.source_kind, official_domains=official_domains, is_search_snippet=batch.is_search_snippet,
            )
            domain = urlparse(url).netloc.lower().removeprefix("www.")
            output.sources.append(Source(
                source_id=source_id,
                canonical_url=batch.source_url,
                source_title=batch.source_title,
                source_domain=domain,
                publisher=batch.publisher,
                source_level=source_level,
                publication_date=batch.publication_date,
                content_type="text/html",
                grading_reason=grading_reason,
            ))
            output.retrievals.append(Retrieval(
                retrieval_id=sequence.next("retrieval"),
                source_id=source_id,
                adapter="fixture" if batch.extraction_method == "recorded_fixture" else batch.retrieval_adapter,
                requested_url=batch.source_url,
                final_url=batch.source_url,
                status_code=200,
                query_id=(query_ids[batch_index] if query_ids and batch_index < len(query_ids) else None),
                diagnostics={"extraction_method": batch.extraction_method},
            ))

            for extracted in batch.entities:
                entity_id = entity_ids[extracted.entity_key]
                if extracted.entity_key not in seen_entities:
                    output.entities.append(Entity(
                        entity_id=entity_id,
                        canonical_name=extracted.canonical_name,
                        entity_type=extracted.entity_type,
                        registered_name=extracted.canonical_name,
                        aliases=extracted.aliases,
                        official_website=extracted.official_website,
                        registration_region=extracted.registration_region,
                    ))
                    seen_entities.add(extracted.entity_key)

            for extracted in batch.factories:
                if extracted.operator_entity_key not in declared_entity_keys:
                    raise ValueError(f"Factory {extracted.factory_key} references undeclared entity {extracted.operator_entity_key}")
                operator_id = entity_ids[extracted.operator_entity_key]
                factory_id = factory_ids[extracted.factory_key]
                if extracted.factory_key not in seen_factories:
                    output.factories.append(Factory(
                        factory_id=factory_id,
                        operator_entity_id=operator_id,
                        name=extracted.name,
                        address=extracted.address,
                        processes=extracted.processes,
                    ))
                    seen_factories.add(extracted.factory_key)
                self._edge(output, edge_keys, operator_id, "OperatesFactory", factory_id, [])

            for extracted in batch.products:
                if extracted.entity_key not in declared_entity_keys:
                    raise ValueError(f"Product {extracted.product_key} references undeclared entity {extracted.entity_key}")
                owner_id = entity_ids[extracted.entity_key]
                product_id = product_ids[extracted.product_key]
                if extracted.product_key not in seen_products:
                    output.products.append(Product(
                        product_id=product_id,
                        entity_id=owner_id,
                        name=extracted.name,
                        brand=extracted.brand,
                        model=extracted.model,
                        category=extracted.category,
                        description=extracted.description,
                        parameters=extracted.parameters,
                        source_ids=[source_id],
                    ))
                    seen_products.add(extracted.product_key)
                self._edge(output, edge_keys, owner_id, "ProducesProduct", product_id, [])

            for extracted in batch.claims:
                if extracted.entity_key not in declared_entity_keys:
                    raise ValueError(f"Claim {extracted.field_name} references undeclared entity {extracted.entity_key}")
                entity_id = entity_ids[extracted.entity_key]
                # LLM extraction may leave empty quotes; fall back to the
                # extracted value (and then the field name) so one blank
                # quote never sinks a run. Non-empty quotes pass through
                # unchanged (no fabrication).
                if extracted.raw_text:
                    raw_text = extracted.raw_text
                elif extracted.value not in (None, ""):
                    raw_text = str(extracted.value)
                else:
                    raw_text = extracted.field_name
                context_text = extracted.context_text or raw_text
                output.claims.append(Claim(
                    claim_id=sequence.next("claim"),
                    entity_id=entity_id,
                    field_name=extracted.field_name,
                    value=extracted.value,
                    value_type=extracted.value_type,
                    unit=extracted.unit,
                    currency=extracted.currency,
                    as_of_date=extracted.as_of_date,
                    scope=extracted.scope,
                    qualifier=extracted.qualifier,
                    source_id=source_id,
                    raw_text=raw_text,
                    context_text=context_text,
                    locator=extracted.locator,
                    confidence=0.0,
                    notes="search snippet discovery-only" if batch.is_search_snippet else None,
                ))

            for extracted in batch.images:
                if extracted.entity_key and extracted.entity_key not in declared_entity_keys:
                    raise ValueError(f"Image {extracted.image_key} references undeclared entity {extracted.entity_key}")
                if extracted.factory_key and extracted.factory_key not in declared_factory_keys:
                    raise ValueError(f"Image {extracted.image_key} references undeclared factory {extracted.factory_key}")
                if extracted.product_key and extracted.product_key not in declared_product_keys:
                    raise ValueError(f"Image {extracted.image_key} references undeclared product {extracted.product_key}")
                output.images.append(ImageEvidence(
                    image_id=sequence.next("image"),
                    entity_id=entity_ids.get(extracted.entity_key) if extracted.entity_key else None,
                    factory_id=factory_ids.get(extracted.factory_key) if extracted.factory_key else None,
                    product_id=product_ids.get(extracted.product_key) if extracted.product_key else None,
                    source_url=extracted.source_url,
                    source_page_url=batch.source_url,
                    source_id=source_id,
                    source_domain=domain,
                    source_title=batch.source_title,
                    image_type=extracted.image_type,
                    sha256=extracted.sha256,
                    phash=extracted.phash,
                    width=extracted.width,
                    height=extracted.height,
                    mime_type=extracted.mime_type,
                    alt_text=extracted.alt_text,
                    surrounding_text=extracted.surrounding_text,
                    confidence=0.0,
                ))

            for extracted in batch.entities:
                if extracted.parent_entity_key:
                    if extracted.parent_entity_key not in declared_entity_keys:
                        raise ValueError(f"Entity {extracted.entity_key} references undeclared parent {extracted.parent_entity_key}")
                    child_id = entity_ids[extracted.entity_key]
                    parent_id = entity_ids[extracted.parent_entity_key]
                    self._edge(output, edge_keys, parent_id, "Subsidiary", child_id, [])
        return output

    @staticmethod
    def _edge(
        output: NormalizedEvidence,
        seen: set[tuple[str, str, str]],
        from_id: str,
        relation: str,
        to_id: str,
        claim_ids: list[str],
    ) -> None:
        key = (from_id, relation, to_id)
        if key in seen:
            return
        seen.add(key)
        output.edges.append(EnterpriseEdge(
            edge_id=new_sortable_id("EDGE"), from_id=from_id, relation=relation,
            to_id=to_id, confidence=0.5, claim_ids=claim_ids,
        ))
