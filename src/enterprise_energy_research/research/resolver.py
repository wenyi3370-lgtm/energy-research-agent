from __future__ import annotations

from urllib.parse import urlparse

from enterprise_energy_research.domain.models import CompanyCandidate, CompanyResolution, ExtractedEvidenceBatch


class CompanyResolver:
    def __init__(self, *, minimum_confidence: float = 0.75, uniqueness_margin: float = 0.12) -> None:
        self.minimum_confidence = minimum_confidence
        self.uniqueness_margin = uniqueness_margin

    @staticmethod
    def _normalize_name(value: str) -> str:
        suffixes = ("有限责任公司", "股份有限公司", "有限公司", "集团公司", "集团")
        value = "".join(value.lower().split())
        for suffix in suffixes:
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value

    def resolve(self, raw_name: str, batches: list[ExtractedEvidenceBatch]) -> CompanyResolution:
        candidates: dict[str, CompanyCandidate] = {}
        target = self._normalize_name(raw_name)
        for batch in batches:
            for entity in batch.entities:
                normalized = self._normalize_name(entity.canonical_name)
                aliases = [self._normalize_name(alias) for alias in entity.aliases]
                exact = normalized == target or target in aliases
                contains = bool(
                    target and (
                        target in normalized
                        or normalized in target
                        or any(target in alias or alias in target for alias in aliases)
                    )
                )
                official_domain = bool(entity.official_website and urlparse(str(entity.official_website)).netloc)
                score = min(1.0, (0.65 if exact else 0.40 if contains else 0.0) + (0.20 if official_domain else 0.0) + (0.10 if entity.registration_region else 0.0))
                existing = candidates.get(entity.entity_key)
                candidate = CompanyCandidate(
                    candidate_id=entity.entity_key,
                    canonical_name=entity.canonical_name,
                    registered_name=entity.canonical_name,
                    aliases=entity.aliases,
                    official_website=entity.official_website,
                    registration_region=entity.registration_region,
                    score=score,
                    ambiguity_reasons=[] if exact else ["Input is an alias or partial match"],
                )
                if not existing or candidate.score > existing.score:
                    candidates[entity.entity_key] = candidate
        ranked = sorted(candidates.values(), key=lambda item: (-item.score, item.canonical_name))
        if not ranked:
            return CompanyResolution(
                raw_company_name=raw_name,
                candidates=[],
                confidence=0.0,
                status="BLOCKED",
                rationale="No company candidates were extracted from approved adapter results",
            )
        top = ranked[0]
        margin = top.score - (ranked[1].score if len(ranked) > 1 else 0.0)
        if top.score >= self.minimum_confidence and margin >= self.uniqueness_margin:
            return CompanyResolution(
                raw_company_name=raw_name,
                candidates=ranked,
                selected_candidate_id=top.candidate_id,
                confidence=top.score,
                status="RESOLVED",
                rationale=f"Top candidate passed confidence and uniqueness thresholds (margin={margin:.2f})",
            )
        return CompanyResolution(
            raw_company_name=raw_name,
            candidates=ranked,
            confidence=top.score,
            status="HUMAN_REVIEW",
            rationale=f"Candidate ambiguity remains (top={top.score:.2f}, margin={margin:.2f})",
        )
