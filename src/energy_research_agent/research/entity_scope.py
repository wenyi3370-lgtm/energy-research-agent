"""Canonical-enterprise scope for research analysis and formal publication.

Search recall may discover customers, suppliers, competitors and adjacent
new-energy companies.  Those records remain valuable internal evidence, but
they must never become the target enterprise's revenue, capacity, products or
factories.  This module gives every downstream consumer one deterministic
boundary instead of relying on list order or narrative prompts.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import FrozenResearchBundle

FORWARD_GROUP_RELATIONS = {"ParentCompany", "Owns", "Subsidiary", "SUBSIDIARY"}
REVERSE_GROUP_RELATIONS = {"CONTROLLED_BY", "OWNED_BY"}
IDENTITY_FIELDS = {"canonical_company_name", "registered_name", "aliases", "former_names"}


def normalized_entity_name(value: object) -> str:
    text = re.sub(r"[\s\-—_（）()·,，.。]+", "", str(value or "")).casefold()
    for suffix in ("有限责任公司", "股份有限公司", "有限公司", "集团公司", "集团"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def entity_name_matches(entity: object, target_name: object) -> bool:
    """Match a resolved candidate to a normalized entity after consolidation.

    Resolver candidates are created from per-page temporary records, while
    normalization can choose another record as the merged primary.  Match on
    all declared identity names and allow a conservative legal-name/brand
    containment (for example ``星星充电`` and
    ``万帮星星充电科技有限公司``).
    """
    target = normalized_entity_name(target_name)
    if not target:
        return False
    names = {
        normalized_entity_name(getattr(entity, "canonical_name", None)),
        normalized_entity_name(getattr(entity, "registered_name", None)),
        *(normalized_entity_name(value) for value in getattr(entity, "aliases", []) or []),
        *(normalized_entity_name(value) for value in getattr(entity, "former_names", []) or []),
    } - {""}
    if target in names:
        return True
    return any(
        min(len(target), len(name)) >= 4
        and (target in name or name in target)
        for name in names
    )


def rebind_target_alias_entities(evidence: object, canonical_id: str, target_name: str) -> str:
    """Collapse only identities that explicitly name/alias the target.

    Competitors, customers, suppliers and policy issuers remain separate.
    This function is intentionally narrower than a generic fuzzy entity
    merger: an entity is rebound only when ``entity_name_matches`` proves a
    legal-name/brand/declared-alias match to the requested enterprise.
    """
    entities = list(getattr(evidence, "entities", []))
    canonical = next((item for item in entities if item.entity_id == canonical_id), None)
    if canonical is None:
        canonical = next((item for item in entities if entity_name_matches(item, target_name)), None)
    if canonical is None:
        raise ValueError(f"canonical enterprise cannot be rebound: {target_name}")
    canonical_names = list(dict.fromkeys(
        value for value in [
            target_name, canonical.canonical_name, canonical.registered_name,
            *canonical.aliases, *canonical.former_names,
        ] if value
    ))
    target_ids = {
        item.entity_id for item in entities
        if any(entity_name_matches(item, name) for name in canonical_names)
    }
    target_ids.add(canonical.entity_id)
    if len(target_ids) == 1:
        return canonical.entity_id

    matched = [item for item in entities if item.entity_id in target_ids]
    aliases = list(dict.fromkeys(
        value
        for item in matched
        for value in [item.canonical_name, item.registered_name, *item.aliases]
        if value and value not in {canonical.canonical_name, canonical.registered_name}
    ))
    former_names = list(dict.fromkeys(
        value for item in matched for value in item.former_names if value
    ))
    supporting = list(dict.fromkeys(
        claim_id for item in matched for claim_id in item.supporting_claim_ids
    ))
    merged = canonical.model_copy(update={
        "aliases": list(dict.fromkeys([*canonical.aliases, *aliases])),
        "former_names": list(dict.fromkeys([*canonical.former_names, *former_names])),
        "official_website": canonical.official_website or next(
            (item.official_website for item in matched if item.official_website), None
        ),
        "registration_region": canonical.registration_region or next(
            (item.registration_region for item in matched if item.registration_region), None
        ),
        "supporting_claim_ids": supporting,
    })
    canonical_id = merged.entity_id
    remap = {entity_id: canonical_id for entity_id in target_ids}
    setattr(evidence, "entities", [
        merged if item.entity_id == canonical_id else item.model_copy(update={
            "parent_entity_id": remap.get(item.parent_entity_id, item.parent_entity_id),
            "actual_controller_entity_id": remap.get(
                item.actual_controller_entity_id, item.actual_controller_entity_id
            ),
        })
        for item in entities if item.entity_id not in target_ids or item.entity_id == canonical_id
    ])
    for attr, field in (
        ("claims", "entity_id"), ("products", "entity_id"),
        ("images", "entity_id"), ("gaps", "entity_id"),
        ("energy_profiles", "entity_id"), ("factories", "operator_entity_id"),
    ):
        rows = list(getattr(evidence, attr, []))
        setattr(evidence, attr, [
            item.model_copy(update={field: remap.get(getattr(item, field), getattr(item, field))})
            for item in rows
        ])
    setattr(evidence, "solutions", [
        item.model_copy(update={
            "target_ids": list(dict.fromkeys(remap.get(value, value) for value in item.target_ids))
        })
        for item in list(getattr(evidence, "solutions", []))
    ])
    deduped_edges: dict[tuple[str, str, str], object] = {}
    for edge in list(getattr(evidence, "edges", [])):
        updated = edge.model_copy(update={
            "from_id": remap.get(edge.from_id, edge.from_id),
            "to_id": remap.get(edge.to_id, edge.to_id),
        })
        # Identity aliases collapsing onto themselves do not represent a
        # business relationship and must not survive as self loops.
        if updated.from_id == updated.to_id:
            continue
        key = (updated.from_id, updated.relation, updated.to_id)
        previous = deduped_edges.get(key)
        if previous is None:
            deduped_edges[key] = updated
        else:
            deduped_edges[key] = previous.model_copy(update={
                "claim_ids": list(dict.fromkeys([*previous.claim_ids, *updated.claim_ids]))
            })
    setattr(evidence, "edges", list(deduped_edges.values()))
    return canonical_id


def canonical_entity(bundle: FrozenResearchBundle):
    canonical_id = bundle.run_manifest.canonical_entity_id
    if not canonical_id:
        return None
    return next((entity for entity in bundle.entities if entity.entity_id == canonical_id), None)


def allowed_publication_entity_ids(bundle: FrozenResearchBundle) -> set[str]:
    """Canonical entity plus verified, explicitly connected group members."""
    canonical = canonical_entity(bundle)
    if canonical is None:
        return set()
    allowed = {canonical.entity_id}
    verified_edges = [
        edge for edge in bundle.edges
        if edge.verification_status == VerificationStatus.VERIFIED
    ]
    changed = True
    while changed:
        changed = False
        for entity in bundle.entities:
            if (
                entity.verification_status == VerificationStatus.VERIFIED
                and entity.parent_entity_id in allowed
                and entity.entity_id not in allowed
            ):
                allowed.add(entity.entity_id)
                changed = True
        for edge in verified_edges:
            candidate = None
            if edge.relation in FORWARD_GROUP_RELATIONS and edge.from_id in allowed:
                candidate = edge.to_id
            elif edge.relation in REVERSE_GROUP_RELATIONS and edge.to_id in allowed:
                candidate = edge.from_id
            if candidate and candidate not in allowed:
                entity = next((item for item in bundle.entities if item.entity_id == candidate), None)
                if entity is not None and entity.verification_status == VerificationStatus.VERIFIED:
                    allowed.add(candidate)
                    changed = True
    return allowed


def target_claims(bundle: FrozenResearchBundle, claims: list | None = None) -> list:
    canonical = canonical_entity(bundle)
    if canonical is None:
        return []
    return [claim for claim in (claims if claims is not None else bundle.claims) if claim.entity_id == canonical.entity_id]


def scoped_products(bundle: FrozenResearchBundle) -> list:
    allowed = allowed_publication_entity_ids(bundle)
    return [product for product in bundle.products if product.entity_id in allowed]


def scoped_factories(bundle: FrozenResearchBundle) -> list:
    allowed = allowed_publication_entity_ids(bundle)
    return [factory for factory in bundle.factories if factory.operator_entity_id in allowed]


def publication_identity_errors(bundle: FrozenResearchBundle) -> list[str]:
    """Fail closed when the canonical subject is absent, unverified or mismatched."""
    entity = canonical_entity(bundle)
    if entity is None:
        return ["canonical enterprise is missing from the frozen entity graph"]
    errors: list[str] = []
    if entity.verification_status != VerificationStatus.VERIFIED:
        errors.append(f"canonical enterprise {entity.canonical_name} is not VERIFIED")
    accepted_names = {
        normalized_entity_name(entity.canonical_name),
        normalized_entity_name(entity.registered_name),
        *(normalized_entity_name(value) for value in entity.aliases),
        *(normalized_entity_name(value) for value in entity.former_names),
    } - {""}
    identity = [
        claim for claim in bundle.claims
        if claim.entity_id == entity.entity_id
        and claim.verification_status == VerificationStatus.VERIFIED
        and claim.field_name in IDENTITY_FIELDS
        and claim.value not in (None, "", [])
    ]
    if not identity:
        errors.append("canonical enterprise has no verified identity claim")
    elif not any(normalized_entity_name(claim.value) in accepted_names for claim in identity):
        errors.append("verified identity claim does not match the canonical enterprise name or aliases")

    if entity.official_website:
        website_host = (urlparse(str(entity.official_website)).hostname or "").lower().removeprefix("www.")
        sources = {source.source_id: source for source in bundle.sources}
        supporting_hosts = {
            (source.source_domain or "").lower().removeprefix("www.")
            for claim in identity
            if (source := sources.get(claim.source_id)) is not None
        }
        website_claim_hosts = {
            (urlparse(str(claim.value)).hostname or "").lower().removeprefix("www.")
            for claim in bundle.claims
            if claim.entity_id == entity.entity_id
            and claim.verification_status == VerificationStatus.VERIFIED
            and claim.field_name == "official_website"
        }
        if website_host and website_host not in supporting_hosts | website_claim_hosts:
            errors.append(
                f"official website host {website_host} is not supported by canonical identity evidence"
            )
    return errors
