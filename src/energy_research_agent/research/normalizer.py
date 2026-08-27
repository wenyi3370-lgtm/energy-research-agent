from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import logging
from typing import Any
from urllib.parse import urlparse

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.ids import RunSequence, new_sortable_id
from energy_research_agent.domain.models import (
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
    Solution,
    Source,
)

from .canonicalizers import FactoryCanonicalizer, ProductCanonicalizer, UnitNormalizer
from .entity_scope import normalized_entity_name
from .field_registry import CanonicalFieldRegistry
from .source_grader import SourceGrader


logger = logging.getLogger(__name__)


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
    solutions: list[Solution] = field(default_factory=list)


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
                query_id=(
                    query_ids[batch_index]
                    if query_ids and batch_index < len(query_ids)
                    else batch.origin_query_id
                ),
                diagnostics={
                    "extraction_method": batch.extraction_method,
                    "origin_topic": batch.origin_topic,
                    "goal_domain": batch.goal_domain,
                    "subject_role": batch.subject_role,
                    "evidence_lane": batch.evidence_lane,
                    "evidence_use": batch.evidence_use,
                },
            ))

            for extracted in batch.entities:
                entity_id = entity_ids[extracted.entity_key]
                if extracted.entity_key not in seen_entities:
                    output.entities.append(Entity(
                        entity_id=entity_id,
                        canonical_name=extracted.canonical_name,
                        entity_type=extracted.entity_type,
                        # registered_name is only the page-stated registered
                        # name; a bare canonical name is never promoted into a
                        # fabricated legal name.
                        registered_name=extracted.registered_name,
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
                        series=extracted.series,
                        description=extracted.description,
                        parameters=extracted.parameters,
                        applications=extracted.applications,
                        customer_segment=extracted.customer_segment,
                        commercial_status=extracted.commercial_status,
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
                # CanonicalFieldRegistry (P0-4): raw field name -> canonical
                # field; the raw name is preserved for audit.
                raw_field_name = extracted.field_name
                canonical_field = CanonicalFieldRegistry.canonicalize(raw_field_name)
                output.claims.append(Claim(
                    claim_id=sequence.next("claim"),
                    entity_id=entity_id,
                    field_name=canonical_field,
                    raw_field_name=raw_field_name,
                    value=extracted.value,
                    value_type=extracted.value_type,
                    unit=extracted.unit,
                    currency=extracted.currency,
                    as_of_date=extracted.as_of_date,
                    period_start=extracted.period_start,
                    period_end=extracted.period_end,
                    scope=extracted.scope,
                    qualifier=extracted.qualifier,
                    source_id=source_id,
                    raw_text=raw_text,
                    context_text=context_text,
                    goal_family=extracted.goal_family,
                    locator={
                        **extracted.locator,
                        "_routing": {
                            "origin_query_id": batch.origin_query_id,
                            "topic": batch.origin_topic,
                            "goal_domain": batch.goal_domain,
                            "subject_role": batch.subject_role,
                            "evidence_lane": batch.evidence_lane,
                            "evidence_use": batch.evidence_use,
                            "requirement_text": batch.requirement_text,
                        },
                    },
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
                        # Parent linkage is optional extraction metadata.  A model
                        # can legitimately identify a brand/subsidiary on one page
                        # while naming a parent key that was not emitted as a full
                        # entity record.  Keep the independently usable entity and
                        # evidence, but omit the dangling edge and retain an
                        # auditable gap instead of aborting the whole research run.
                        detail = {
                            "record_type": "entity_parent",
                            "entity_key": extracted.entity_key,
                            "missing_parent_entity_key": extracted.parent_entity_key,
                            "action": "edge_omitted",
                        }
                        output.retrievals[-1].diagnostics.setdefault(
                            "dropped_references", []
                        ).append(detail)
                        output.gaps.append(DataGap(
                            gap_id=new_sortable_id("GAP"),
                            entity_id=entity_ids[extracted.entity_key],
                            field_name="parent_entity_relationship",
                            importance="major",
                            reason="EXTRACTED_NOT_NORMALIZED",
                            attempted_query_ids=(
                                [query_ids[batch_index]]
                                if query_ids and batch_index < len(query_ids)
                                else []
                            ),
                            next_action=(
                                "补充检索并声明父实体 "
                                f"{extracted.parent_entity_key}，再核验其与 "
                                f"{extracted.entity_key} 的关系"
                            ),
                        ))
                        logger.warning(
                            "omitted dangling parent edge entity=%s parent=%s source=%s",
                            extracted.entity_key,
                            extracted.parent_entity_key,
                            url,
                        )
                        continue
                    child_id = entity_ids[extracted.entity_key]
                    parent_id = entity_ids[extracted.parent_entity_key]
                    self._edge(output, edge_keys, parent_id, "Subsidiary", child_id, [])
        self._bind_factory_claim_lineage(output)
        self._canonicalize(output)
        return self._consolidate_duplicate_entities(output)

    # Factories are extracted as structured records while the same pages also
    # emit claim rows stating their address/city/province facts.  Value-matching
    # those claims back onto the factory record restores the evidence lineage
    # that downstream chapters need (no claim is invented here).
    FACTORY_LINEAGE_FIELDS = {
        "address", "factory_city", "factory_province", "factory_name",
        "headquarters", "operating_status",
    }

    @classmethod
    def _bind_factory_claim_lineage(cls, output: NormalizedEvidence) -> None:
        claims_by_entity: dict[str, list[Any]] = defaultdict(list)
        for claim in output.claims:
            if claim.field_name in cls.FACTORY_LINEAGE_FIELDS and claim.value not in (None, "", []):
                claims_by_entity[claim.entity_id].append(claim)
        updated: list[Factory] = []
        for factory in output.factories:
            matched: list[str] = []
            for claim in claims_by_entity.get(factory.operator_entity_id, ()):
                value = str(claim.value).strip()
                if not value:
                    continue
                if factory.address and factory.address.strip() and (
                    value == factory.address.strip() or value in factory.address
                ):
                    matched.append(claim.claim_id)
                elif factory.name and value == factory.name.strip():
                    matched.append(claim.claim_id)
            if matched:
                factory = factory.model_copy(update={
                    "supporting_claim_ids": list(dict.fromkeys(
                        [*factory.supporting_claim_ids, *matched]
                    )),
                })
            updated.append(factory)
        output.factories = updated

    @staticmethod
    def _consolidate_duplicate_entities(output: NormalizedEvidence) -> NormalizedEvidence:
        """Merge model-varying entity keys that resolve to the same company.

        LLM batches frequently emit ``star_charge``, ``starcharge`` and
        ``xingxing_charging`` for the same page-stated enterprise. Stable
        evidence IDs must follow the normalized enterprise name, not those
        per-call temporary keys.
        """
        groups: dict[str, list[Entity]] = {}
        for entity in output.entities:
            key = normalized_entity_name(entity.registered_name or entity.canonical_name)
            groups.setdefault(key or entity.entity_id, []).append(entity)

        remap: dict[str, str] = {}
        merged: list[Entity] = []
        for entities in groups.values():
            primary = max(
                entities,
                key=lambda item: (
                    bool(item.registered_name), bool(item.official_website),
                    len(item.aliases), -output.entities.index(item),
                ),
            )
            aliases: list[str] = []
            for entity in entities:
                remap[entity.entity_id] = primary.entity_id
                aliases.extend(entity.aliases)
                if entity.canonical_name != primary.canonical_name:
                    aliases.append(entity.canonical_name)
            merged.append(primary.model_copy(update={
                "registered_name": primary.registered_name or next(
                    (item.registered_name for item in entities if item.registered_name), None
                ),
                "official_website": primary.official_website or next(
                    (item.official_website for item in entities if item.official_website), None
                ),
                "registration_region": primary.registration_region or next(
                    (item.registration_region for item in entities if item.registration_region), None
                ),
                "aliases": list(dict.fromkeys(alias for alias in aliases if alias)),
            }))

        output.entities = [
            entity.model_copy(update={
                "parent_entity_id": remap.get(entity.parent_entity_id, entity.parent_entity_id),
            })
            for entity in merged
        ]
        output.claims = [
            item.model_copy(update={"entity_id": remap.get(item.entity_id, item.entity_id)})
            for item in output.claims
        ]
        output.factories = [
            item.model_copy(update={
                "operator_entity_id": remap.get(item.operator_entity_id, item.operator_entity_id),
            })
            for item in output.factories
        ]
        output.products = [
            item.model_copy(update={"entity_id": remap.get(item.entity_id, item.entity_id)})
            for item in output.products
        ]
        output.images = [
            item.model_copy(update={
                "entity_id": remap.get(item.entity_id, item.entity_id) if item.entity_id else None,
            })
            for item in output.images
        ]
        output.gaps = [
            item.model_copy(update={
                "entity_id": remap.get(item.entity_id, item.entity_id) if item.entity_id else None,
            })
            for item in output.gaps
        ]
        deduped_edges: dict[tuple[str, str, str], EnterpriseEdge] = {}
        for edge in output.edges:
            updated = edge.model_copy(update={
                "from_id": remap.get(edge.from_id, edge.from_id),
                "to_id": remap.get(edge.to_id, edge.to_id),
            })
            key = (updated.from_id, updated.relation, updated.to_id)
            if key in deduped_edges:
                previous = deduped_edges[key]
                deduped_edges[key] = previous.model_copy(update={
                    "claim_ids": list(dict.fromkeys([*previous.claim_ids, *updated.claim_ids])),
                })
            else:
                deduped_edges[key] = updated
        output.edges = list(deduped_edges.values())
        return output

    @staticmethod
    def _canonicalize(output: NormalizedEvidence) -> None:
        """P0: normalization must complete BEFORE Freeze (units, products, factories)."""
        output.claims = UnitNormalizer().normalize_claims(output.claims)
        output.products, product_rebind = ProductCanonicalizer().canonicalize(output.products, output.images)
        output.factories, factory_rebind = FactoryCanonicalizer().canonicalize(output.factories)
        # Merged-away ids must not leave dangling edges: remap to the
        # surviving canonical records (referential integrity at freeze).
        for edge in output.edges:
            if edge.relation == "ProducesProduct" and edge.to_id in product_rebind:
                edge.to_id = product_rebind[edge.to_id]
            if edge.relation == "OperatesFactory" and edge.to_id in factory_rebind:
                edge.to_id = factory_rebind[edge.to_id]

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
