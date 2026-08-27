from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from energy_research_agent.domain.models import CompanyCandidate, CompanyResolution, ExtractedEvidenceBatch


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
        stats: dict[str, dict[str, object]] = defaultdict(lambda: {
            "exact": False,
            "contains": False,
            "official": False,
            "region": False,
            "domains": set(),
            "publishers": set(),
            "authority": 0,
            "non_snippet": 0,
            "claims": 0,
        })
        target = self._normalize_name(raw_name)
        for batch in batches:
            domain = urlparse(str(batch.source_url)).netloc.lower().removeprefix("www.")
            source_kind = batch.source_kind.casefold()
            authority = self._authority_score(source_kind, domain, batch.is_search_snippet)
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
                item_stats = stats[entity.entity_key]
                item_stats["exact"] = bool(item_stats["exact"]) or exact
                item_stats["contains"] = bool(item_stats["contains"]) or contains
                item_stats["official"] = bool(item_stats["official"]) or official_domain
                item_stats["region"] = bool(item_stats["region"]) or bool(entity.registration_region)
                item_stats["authority"] = max(int(item_stats["authority"]), authority)
                item_stats["non_snippet"] = int(item_stats["non_snippet"]) + int(not batch.is_search_snippet)
                item_stats["claims"] = int(item_stats["claims"]) + sum(
                    claim.entity_key == entity.entity_key for claim in batch.claims
                )
                if domain:
                    item_stats["domains"].add(domain)  # type: ignore[union-attr]
                if batch.publisher:
                    item_stats["publishers"].add(batch.publisher.casefold())  # type: ignore[union-attr]
                existing = candidates.get(entity.entity_key)
                candidate = CompanyCandidate(
                    candidate_id=entity.entity_key,
                    canonical_name=entity.canonical_name,
                    registered_name=entity.canonical_name,
                    aliases=entity.aliases,
                    official_website=entity.official_website,
                    registration_region=entity.registration_region,
                    score=0.0,
                    ambiguity_reasons=[] if exact else ["Input is an alias or partial match"],
                )
                if not existing or (official_domain and not existing.official_website):
                    candidates[entity.entity_key] = candidate

        scored: list[CompanyCandidate] = []
        for candidate_id, candidate in candidates.items():
            item_stats = stats[candidate_id]
            independent_origins = max(
                len(item_stats["domains"]),  # type: ignore[arg-type]
                len(item_stats["publishers"]),  # type: ignore[arg-type]
            )
            score = (
                (0.56 if item_stats["exact"] else 0.34 if item_stats["contains"] else 0.0)
                + (0.10 if item_stats["official"] else 0.0)
                + (0.04 if item_stats["region"] else 0.0)
                + (0.03 * int(item_stats["authority"]))
                + min(0.10, 0.025 * independent_origins)
                + (0.025 if int(item_stats["claims"]) > 0 else 0.0)
                + (0.015 if int(item_stats["non_snippet"]) > 0 else 0.0)
            )
            scored.append(candidate.model_copy(update={"score": min(1.0, score)}))

        ranked = sorted(
            scored,
            key=lambda item: (
                -item.score,
                -int(bool(stats[item.candidate_id]["exact"])),
                -int(stats[item.candidate_id]["authority"]),
                -len(stats[item.candidate_id]["domains"]),  # type: ignore[arg-type]
                item.canonical_name,
                item.candidate_id,
            ),
        )
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
        meets_threshold = top.score >= self.minimum_confidence and margin >= self.uniqueness_margin
        return CompanyResolution(
            raw_company_name=raw_name,
            candidates=ranked,
            selected_candidate_id=top.candidate_id,
            confidence=top.score,
            status="RESOLVED",
            rationale=(
                f"Automatic credibility adjudication selected {top.canonical_name} "
                f"(score={top.score:.2f}, margin={margin:.2f}, "
                f"thresholds_met={str(meets_threshold).lower()}); alternatives are retained in ranked order."
            ),
        )

    @staticmethod
    def _authority_score(source_kind: str, domain: str, is_search_snippet: bool) -> int:
        """Return a stable 0..4 source-authority tier for identity support."""
        if is_search_snippet:
            return 0
        if source_kind in {
            "government", "sasac", "annual_report", "official_manual",
            "official_announcement", "official_company",
        } or domain.endswith(".gov.cn"):
            return 4
        if source_kind in {
            "industry_association", "university", "research_institute", "certification_body",
        }:
            return 3
        if source_kind in {"commercial_database", "channel", "recruitment"}:
            return 2
        return 1
