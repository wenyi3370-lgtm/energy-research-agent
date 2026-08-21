from __future__ import annotations

from urllib.parse import urlparse

from enterprise_energy_research.domain.enums import SourceLevel


GOVERNMENT_SUFFIXES = (".gov.cn", ".sasac.gov.cn")
AUTHORITATIVE_MEDIA = ("people.com.cn", "xinhuanet.com", "chinanews.com.cn", "cnstock.com")
RECRUITMENT_DOMAINS = ("zhaopin.com", "liepin.com", "51job.com", "boss.com")
SOCIAL_DOMAINS = ("xiaohongshu.com", "weibo.com", "zhihu.com", "douyin.com")

# Fixed vocabulary the extractor must choose source_kind from. Unknown kinds
# are normalized conservatively (never upgraded).
RECOGNIZED_SOURCE_KINDS = (
    "government", "sasac", "annual_report", "official_manual",
    "official_announcement", "official_company", "industry_association",
    "university", "research_institute", "certification_body", "recruitment",
    "commercial_database", "marketplace", "channel", "social_media",
    "forum", "ordinary_media",
)


def normalize_source_kind(value: str) -> str:
    """Map free-text source kinds onto the fixed vocabulary (never upgrade)."""
    folded = (value or "").strip().lower()
    if folded in RECOGNIZED_SOURCE_KINDS:
        return folded
    if any(token in folded for token in ("官网", "official", "company_site", "企业官网")):
        return "official_company"
    if any(token in folded for token in ("政府", "gov", "sasac", "国资委")):
        return "government"
    if any(token in folded for token in ("年报", "annual", "公告", "announcement", "说明书", "manual")):
        return "official_announcement"
    if any(token in folded for token in ("协会", "association")):
        return "industry_association"
    if any(token in folded for token in ("媒体", "新闻", "news", "media")):
        return "ordinary_media"
    if any(token in folded for token in ("招聘", "recruit", "job")):
        return "recruitment"
    if any(token in folded for token in ("数据库", "database", "查", "平台")):
        return "commercial_database"
    return "ordinary_media"


class SourceGrader:
    def grade(
        self,
        url: str,
        source_kind: str,
        *,
        official_domains: set[str] | None = None,
        is_search_snippet: bool = False,
    ) -> tuple[SourceLevel, str]:
        domain = urlparse(url).netloc.lower().split(":")[0]
        domain = domain.removeprefix("www.")
        official_domains = {item.lower().removeprefix("www.") for item in (official_domains or set())}
        if is_search_snippet:
            return SourceLevel.SOURCE_D, "search snippet is discovery-only"
        if source_kind in {"government", "sasac", "annual_report", "official_manual", "official_announcement"}:
            return SourceLevel.SOURCE_A, source_kind
        if domain in official_domains or source_kind == "official_company":
            return SourceLevel.SOURCE_A, "verified official company source"
        if any(domain.endswith(suffix) for suffix in GOVERNMENT_SUFFIXES):
            return SourceLevel.SOURCE_A, "government domain"
        if source_kind in {"industry_association", "university", "research_institute", "certification_body"}:
            return SourceLevel.SOURCE_B, source_kind
        if any(domain == item or domain.endswith("." + item) for item in AUTHORITATIVE_MEDIA):
            return SourceLevel.SOURCE_B, "recognized original-reporting media"
        if source_kind in {"recruitment", "commercial_database", "marketplace", "channel"} or any(
            domain == item or domain.endswith("." + item) for item in RECRUITMENT_DOMAINS
        ):
            return SourceLevel.SOURCE_C, source_kind
        if source_kind in {"social_media", "forum", "ordinary_media"} or any(
            domain == item or domain.endswith("." + item) for item in SOCIAL_DOMAINS
        ):
            return SourceLevel.SOURCE_D, source_kind
        return SourceLevel.SOURCE_D, "unclassified public source"

