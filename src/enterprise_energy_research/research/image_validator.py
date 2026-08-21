from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Entity, ImageEvidence, Source
from enterprise_energy_research.research.image_semantics import ImageSemanticRouter
from enterprise_energy_research.research.vision import VisionVerifier, default_vision_verifier

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
    ) -> list[ImageEvidence]:
        entities_by_id = {entity.entity_id: entity for entity in entities}
        sources_by_id = {source.source_id: source for source in sources}
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
            context = " ".join(filter(None, [image.alt_text, image.surrounding_text, image.source_title])).lower()
            signals: list[str] = []
            semantic_score = 0.0
            if source and source.source_level.value == "SOURCE_A":
                signals.append("source_a")
                semantic_score += 0.2
            if entity:
                names = [entity.canonical_name, *entity.aliases]
                if any(name.lower() in context for name in names if name):
                    signals.append("entity_name_in_context")
                    semantic_score += 0.5
                if entity.official_website and source:
                    official = entity.official_website.host.lower().removeprefix("www.")
                    if source.source_domain == official or source.source_domain.endswith("." + official):
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
            target_entity_id = (
                image.product_id or image.factory_id or image.entity_id
                if target_entity_type not in {"editorial", "other"}
                else None
            )
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
    def _resolve_bytes(image: ImageEvidence) -> bytes | None:
        if not image.local_asset_ref:
            return None
        path = Path(image.local_asset_ref)
        if not path.is_absolute():
            return None
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def visual_verify(self, images: list[ImageEvidence]) -> list[ImageEvidence]:
        """Pixel-level verification AFTER archiving (local bytes exist).

        Called once ``ImageAssetArchiver`` has written local assets, because a
        vision verifier needs the actual image bytes.  Images without bytes or
        without a configured vision gateway keep ``visual_verified=False`` and
        ``verification_method`` unchanged — never silently promoted.
        """
        if self._vision is None:
            return list(images)
        verified: list[ImageEvidence] = []
        for image in images:
            if image.visual_verified:
                verified.append(image)
                continue
            image_bytes = self._resolve_bytes(image)
            verdict = None
            if image_bytes is not None:
                try:
                    verdict = self._vision(image, image_bytes)
                except Exception:
                    verdict = None
            if verdict is not None:
                signals = list(image.entity_match_signals)
                signals.append(f"vision_score:{verdict.score:.2f}")
                verified.append(image.model_copy(update={
                    "visual_verified": bool(verdict.verified),
                    "visual_description": verdict.description or image.visual_description,
                    "verification_method": "vision",
                    "semantic_score": max(image.semantic_score, min(1.0, verdict.score)),
                    "entity_match_signals": signals,
                }))
            else:
                verified.append(image)
        return verified
