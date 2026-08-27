from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import Entity, ImageEvidence, Source
from energy_research_agent.research.image_semantics import ImageSemanticRouter
from energy_research_agent.research.vision import VisionVerifier, default_vision_verifier

# image_type → target_entity_type (P0 image system)
IMAGE_TYPE_TO_TARGET = {
    "logo": "logo",
    "headquarters": "headquarters",
    "factory": "factory",
    "workshop": "workshop",
    "office": "office",
    "production_line": "production_line",
    "product": "product",
    "product_application": "product",
    "equipment": "equipment",
    "certificate": "certificate",
    "project": "project",
    "location": "editorial",  # region maps / site diagrams carry no entity claim
    "other": "other",
}

# Default editorial priority per image type (vision may raise/lower it).
IMAGE_TYPE_PRIORITY = {
    "logo": 4,
    "product": 4,
    "product_application": 3,
    "headquarters": 3,
    "factory": 3,
    "workshop": 3,
    "production_line": 3,
    "equipment": 2,
    "certificate": 2,
    "project": 2,
    "office": 2,
    "location": 2,
    "other": 1,
}


class ImageValidator:
    """Technical + contextual validation; pixel-level trust comes from a vision verifier.

    ``visual_verified`` is ONLY set when ``vision_verifier`` returns a verdict
    over actual image bytes.  Context signals contribute to
    ``semantic_score`` and ``verification_status`` but never promote an image
    to visually verified.
    """

    def __init__(
        self,
        *,
        minimum_dimension: int = 240,
        minimum_area: int = 120_000,
        vision_verifier: VisionVerifier | None = None,
    ) -> None:
        self.minimum_dimension = minimum_dimension
        self.minimum_area = minimum_area
        self._vision = vision_verifier if vision_verifier is not None else default_vision_verifier()

    def validate(
        self,
        images: list[ImageEvidence],
        entities: list[Entity],
        sources: list[Source],
        claims: list | None = None,
    ) -> list[ImageEvidence]:
        entities_by_id = {entity.entity_id: entity for entity in entities}
        sources_by_id = {source.source_id: source for source in sources}
        # The entity record is not always hydrated with its verified website
        # (extraction may carry it only as a claim). Derive the official
        # domain set per entity from VERIFIED official_website claims so
        # official-site images can still earn the official_domain signal —
        # evidence-bound, never invented.
        official_domains_by_entity: dict[str, set[str]] = defaultdict(set)
        for claim in claims or []:
            if getattr(claim, "field_name", None) != "official_website":
                continue
            if getattr(claim, "verification_status", None) != VerificationStatus.VERIFIED:
                continue
            entity_id = getattr(claim, "entity_id", None)
            if not entity_id or not getattr(claim, "value", None):
                continue
            host = (urlparse(str(claim.value)).netloc or "").lower().removeprefix("www.")
            if host:
                official_domains_by_entity[entity_id].add(host)
        # Single-subject runs: images discovered before entity binding carry
        # no entity_id; they may still inherit the canonical entity's name
        # context and official domains — but only when exactly one entity
        # exists, never guessed among multiple subjects.
        # Subject of the investigation: the company entity backed by a
        # VERIFIED official-website claim wins; recovery rounds can merge a
        # duplicate "other"-typed record for the same name into the bundle,
        # so never trust plain list length to identify the subject.
        verified_site_entities = [
            entity for entity in entities
            if entity.entity_id in official_domains_by_entity
            and (entity.entity_type or "").lower() == "company"
        ]
        company_entities = [
            entity for entity in entities
            if (entity.entity_type or "").lower() == "company"
        ]
        primary_entity = (
            verified_site_entities[0] if verified_site_entities
            else company_entities[0] if company_entities
            else entities[0] if entities else None
        )
        canonical_entity = entities[0] if len(entities) == 1 else primary_entity
        phash_groups: dict[str, list[str]] = defaultdict(list)
        classified: list[ImageEvidence] = []
        for original_image in images:
            image = ImageSemanticRouter.classify(original_image) if original_image.image_type in {"other", "location"} else original_image
            phash_groups[image.phash].append(image.image_id)
            classified.append(image)
        validated: list[ImageEvidence] = []
        for image in classified:
            source = sources_by_id.get(image.source_id)
            entity = entities_by_id.get(image.entity_id) if image.entity_id else None
            # Context signals use the inherited canonical entity for
            # unbound images; structural binding (target_entity_id) stays
            # untouched and never claims an entity the image did not declare.
            signal_entity = entity or canonical_entity
            context = " ".join(filter(None, [image.alt_text, image.surrounding_text, image.source_title])).lower()
            signals: list[str] = []
            semantic_score = 0.0
            if source and source.source_level.value == "SOURCE_A":
                signals.append("source_a")
                semantic_score += 0.2
            if signal_entity:
                names = [signal_entity.canonical_name, *signal_entity.aliases]
                if any(name.lower() in context for name in names if name):
                    signals.append("entity_name_in_context")
                    semantic_score += 0.5
            if signal_entity and source:
                official_hosts = set(official_domains_by_entity.get(signal_entity.entity_id, ()))
                if signal_entity.official_website:
                    official_hosts.add(signal_entity.official_website.host.lower().removeprefix("www."))
                domain = (source.source_domain or "").lower().removeprefix("www.")
                if domain and any(domain == host or domain.endswith("." + host) for host in official_hosts):
                    signals.append("official_domain")
                    semantic_score += 0.3
            dimensions_ok = min(image.width, image.height) >= self.minimum_dimension and image.width * image.height >= self.minimum_area
            format_ok = image.mime_type.lower() in {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}
            duplicate_count = len(phash_groups[image.phash])
            if dimensions_ok and format_ok and ("official_domain" in signals or {"source_a", "entity_name_in_context"}.issubset(signals)):
                status = VerificationStatus.VERIFIED
                confidence = 0.92 if "official_domain" in signals else 0.82
            elif not dimensions_ok or not format_ok:
                status = VerificationStatus.REJECTED
                confidence = 0.0
                signals.append("invalid_dimensions_or_format")
            else:
                status = VerificationStatus.REVIEW_REQUIRED
                confidence = 0.45
            if duplicate_count > 1:
                signals.append(f"perceptual_duplicate_count:{duplicate_count}")

            # P0 image-system fields: entity binding is structural (declared
            # in evidence), semantic score is context-derived, visual trust is
            # vision-only.
            target_entity_type = IMAGE_TYPE_TO_TARGET.get(image.image_type, "other")
            if target_entity_type == "product":
                target_entity_id = image.product_id
            elif target_entity_type in {"factory", "production_line", "workshop"}:
                target_entity_id = image.factory_id
            elif target_entity_type in {"headquarters", "logo", "office"}:
                target_entity_id = image.entity_id
            else:
                target_entity_id = None
            # Single-subject close: a VERIFIED image whose finer target record
            # (product/factory) was never extracted stays bound to the
            # subject entity instead of dangling — but only when the page
            # was tied to that entity via official domain or name context.
            # Never applied to REJECTED/REVIEW_REQUIRED images. Prefer the
            # entity whose official domain actually matched the source page.
            if (
                target_entity_id is None
                and status == VerificationStatus.VERIFIED
                and primary_entity is not None
                and {"official_domain", "entity_name_in_context"} & set(signals)
            ):
                bound_entity = primary_entity
                source_domain = (
                    (source.source_domain or "").lower().removeprefix("www.")
                    if source else ""
                )
                if "official_domain" in signals and source_domain:
                    for entity in entities:
                        hosts = set(official_domains_by_entity.get(entity.entity_id, ()))
                        if entity.official_website:
                            hosts.add(
                                entity.official_website.host.lower().removeprefix("www.")
                            )
                        if any(
                            source_domain == host or source_domain.endswith("." + host)
                            for host in hosts
                        ):
                            bound_entity = entity
                            break
                target_entity_id = bound_entity.entity_id
                signals.append("target_bound_to_canonical_entity")
            priority = IMAGE_TYPE_PRIORITY.get(image.image_type, 3)
            verification_method = "none"
            visual_verified = False
            visual_description: str | None = None
            verdict = None
            if status == VerificationStatus.VERIFIED and self._vision is not None:
                image_bytes = self._resolve_bytes(image)
                try:
                    verdict = self._vision(image, image_bytes)
                except Exception:
                    verdict = None
            if verdict is not None:
                verification_method = "vision"
                visual_verified = bool(verdict.verified)
                visual_description = verdict.description
                signals.append(f"vision_score:{verdict.score:.2f}")
            elif status == VerificationStatus.VERIFIED:
                verification_method = "context"
                signals.append("no_vision_capability_or_failed")
            validated.append(image.model_copy(update={
                "verification_status": status,
                "confidence": confidence,
                "entity_match_signals": signals,
                "target_entity_type": target_entity_type,  # type: ignore[arg-type]
                "target_entity_id": target_entity_id,
                "semantic_score": min(1.0, semantic_score),
                "visual_verified": visual_verified,
                "visual_description": visual_description,
                "publication_priority": priority,
                "verification_method": verification_method,  # type: ignore[arg-type]
            }))
        return validated

    @staticmethod
    def _resolve_bytes(image: ImageEvidence, base_dir: Path | None = None) -> bytes | None:
        if not image.local_asset_ref:
            return None
        path = Path(image.local_asset_ref)
        if not path.is_absolute():
            # archiver stores refs relative to the run output directory
            if base_dir is None:
                return None
            path = base_dir / path
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def visual_verify(self, images: list[ImageEvidence], *, base_dir: Path | None = None) -> list[ImageEvidence]:
        """Pixel-level verification AFTER archiving (local bytes exist).

        Called once ``ImageAssetArchiver`` has written local assets, because a
        vision verifier needs the actual image bytes.  ``base_dir`` resolves
        archiver-relative ``local_asset_ref`` values.  Images without bytes or
        without a configured vision gateway keep ``visual_verified=False`` and
        ``verification_method`` unchanged — never silently promoted.
        """
        if self._vision is None:
            return list(images)
        def verify_one(image: ImageEvidence) -> ImageEvidence:
            if image.visual_verified:
                return image
            image_bytes = self._resolve_bytes(image, base_dir)
            verdict = None
            if image_bytes is not None:
                try:
                    verdict = self._vision(image, image_bytes)
                except Exception:
                    verdict = None
            if verdict is not None:
                signals = list(image.entity_match_signals)
                signals.append(f"vision_score:{verdict.score:.2f}")
                return image.model_copy(update={
                    "visual_verified": bool(verdict.verified),
                    "visual_description": verdict.description or image.visual_description,
                    "verification_method": "vision",
                    "semantic_score": max(image.semantic_score, min(1.0, verdict.score)),
                    "entity_match_signals": signals,
                })
            return image

        # Pixel checks are independent network calls.  Preserve input order
        # while bounding the wall time of a whole image batch.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(6, len(images) or 1)) as pool:
            return list(pool.map(verify_one, images))
