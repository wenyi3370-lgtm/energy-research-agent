from __future__ import annotations

from collections import defaultdict

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Entity, ImageEvidence, Source
from enterprise_energy_research.research.image_semantics import ImageSemanticRouter


class ImageValidator:
    def __init__(self, *, minimum_dimension: int = 240, minimum_area: int = 120_000) -> None:
        self.minimum_dimension = minimum_dimension
        self.minimum_area = minimum_area

    def validate(
        self,
        images: list[ImageEvidence],
        entities: list[Entity],
        sources: list[Source],
    ) -> list[ImageEvidence]:
        entities_by_id = {entity.entity_id: entity for entity in entities}
        sources_by_id = {source.source_id: source for source in sources}
        phash_groups: dict[str, list[str]] = defaultdict(list)
        for original_image in images:
            image = ImageSemanticRouter.classify(original_image) if original_image.image_type == "other" else original_image
            phash_groups[image.phash].append(image.image_id)
        validated: list[ImageEvidence] = []
        for image in images:
            source = sources_by_id.get(image.source_id)
            entity = entities_by_id.get(image.entity_id) if image.entity_id else None
            context = " ".join(filter(None, [image.alt_text, image.surrounding_text, image.source_title])).lower()
            signals: list[str] = []
            if source and source.source_level.value == "SOURCE_A":
                signals.append("source_a")
            if entity:
                names = [entity.canonical_name, *entity.aliases]
                if any(name.lower() in context for name in names if name):
                    signals.append("entity_name_in_context")
                if entity.official_website and source:
                    official = entity.official_website.host.lower().removeprefix("www.")
                    if source.source_domain == official or source.source_domain.endswith("." + official):
                        signals.append("official_domain")
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
            validated.append(image.model_copy(update={
                "verification_status": status,
                "confidence": confidence,
                "entity_match_signals": signals,
            }))
        return validated
