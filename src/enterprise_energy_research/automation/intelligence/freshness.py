"""三层 Freshness Gate：24h 主搜、72h 恢复、7d 实质更新检查。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import RawIntelligenceItem

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
PRIMARY_WINDOW = timedelta(hours=24)
RECOVERY_WINDOW = timedelta(hours=72)
UPDATE_WINDOW = timedelta(days=7)

SOURCE_PRIORITY = {
    "official_latest": 1,
    "company_official": 2,
    "government_tender": 3,
    "authoritative_media": 4,
    "industry_media": 5,
    "repost": 6,
    "unknown": 9,
    "": 9,
}


@dataclass(frozen=True)
class FreshnessGateResult:
    accepted: list[RawIntelligenceItem]
    rejected: list[str]
    evaluated: list[RawIntelligenceItem]


def current_intelligence_time() -> datetime:
    """Return the actual run time in the deployment's business timezone."""
    return datetime.now(LOCAL_TIMEZONE)


def normalize_current_time(value: datetime | None = None) -> datetime:
    value = value or current_intelligence_time()
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE)
    return value.astimezone(LOCAL_TIMEZONE)


def parse_exact_publication_time(value: str) -> datetime | None:
    """Parse a timestamp only when year, date, hour and minute are explicit."""
    text = (value or "").strip()
    if not text or not re.search(r"\d{1,2}\s*[:时]\s*\d{1,2}", text):
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", " ")
        .replace("/", "-")
        .replace("时", ":")
        .replace("分", ":")
        .replace("秒", "")
        .strip()
    )
    match = re.search(
        r"(\d{4})-(\d{1,2})-(\d{1,2})[ T]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?"
        r"(?:\s*(Z|[+-]\d{2}:?\d{2}))?",
        normalized,
    )
    if not match:
        return None
    offset = match.group(7) or ""
    if offset == "Z":
        offset = "+00:00"
    elif offset and ":" not in offset:
        offset = f"{offset[:3]}:{offset[3:]}"
    try:
        timestamp = (
            f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}T"
            f"{int(match.group(4)):02d}:{int(match.group(5)):02d}:"
            f"{int(match.group(6) or 0):02d}{offset}"
        )
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def parse_event_date(value: str) -> date | None:
    """Event dates may be date-only; never invent an unknown clock time."""
    exact = parse_exact_publication_time(value)
    if exact is not None:
        return exact.date()
    normalized = (
        (value or "").replace("年", "-").replace("月", "-").replace("日", "")
        .replace("/", "-")
    )
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    english = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})\b",
        value or "",
        re.IGNORECASE,
    )
    if not english:
        return None
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    try:
        return date(
            int(english.group(3)), months[english.group(1)[:3].lower()], int(english.group(2))
        )
    except ValueError:
        return None


def parse_publication_time(
    value: str,
    evidence: str,
    reference: datetime,
) -> tuple[datetime | None, str, bool]:
    """Return a conservative timestamp, precision and corroboration flag.

    Many authoritative sources publish only a calendar date.  A confirmed
    date is usable when the *whole possible day* is inside the 72-hour gate;
    it is never promoted to an invented exact clock time and remains LOW
    confidence in publication output.
    """
    exact = parse_exact_publication_time(value)
    evidence_exact = parse_exact_publication_time(evidence)
    value_date = parse_event_date(value)
    evidence_date = parse_event_date(evidence)

    if value_date and evidence_date and value_date != evidence_date:
        return None, "UNKNOWN", False
    if exact is not None and evidence_exact is not None:
        if abs((exact - evidence_exact).total_seconds()) <= 60:
            return exact, "EXACT", True
        return None, "UNKNOWN", False
    if evidence_exact is not None and (value_date is None or value_date == evidence_exact.date()):
        return evidence_exact, "EXACT", True
    if exact is not None:
        if evidence_date is not None and evidence_date == exact.date():
            midnight = datetime.combine(exact.date(), datetime.min.time(), tzinfo=reference.tzinfo)
            return midnight, "DATE_ONLY", True
        return exact, "EXACT", False
    confirmed_date = value_date or evidence_date
    if confirmed_date is not None:
        midnight = datetime.combine(confirmed_date, datetime.min.time(), tzinfo=reference.tzinfo)
        return midnight, "DATE_ONLY", bool(value_date and evidence_date)
    return None, "UNKNOWN", False


def content_sha256(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_event_key(item: RawIntelligenceItem) -> str:
    if item.event_key.strip():
        return item.event_key.strip().lower()
    entity = _normal_text(item.entity or "unknown")
    topic = _normal_text(item.topic or item.category)
    title = _normal_text(item.title)
    return content_sha256(f"{entity}|{topic}|{title}")[:24]


def are_same_event(left: RawIntelligenceItem, right: RawIntelligenceItem) -> bool:
    """Conservative cross-source event match for history and source selection."""
    left_urls = {_canonical_url(left.source_url), _canonical_url(left.original_source_url)} - {""}
    right_urls = {_canonical_url(right.source_url), _canonical_url(right.original_source_url)} - {""}
    if left_urls & right_urls:
        return True
    if left.content_hash and left.content_hash == right.content_hash:
        return True
    if left.event_key and right.event_key and left.event_key == right.event_key:
        return True
    if _normal_text(left.entity) != _normal_text(right.entity):
        return False
    left_topic = _normal_text(left.topic or left.category)
    right_topic = _normal_text(right.topic or right.category)
    if left_topic != right_topic:
        return False
    title_ratio = SequenceMatcher(None, _normal_text(left.title), _normal_text(right.title)).ratio()
    fact_ratio = SequenceMatcher(None, _normal_text(left.fact), _normal_text(right.fact)).ratio()
    return title_ratio >= 0.72 or fact_ratio >= 0.68


def apply_freshness_gate(
    items: list[RawIntelligenceItem],
    history: list[RawIntelligenceItem] | None = None,
    current_time: datetime | None = None,
) -> FreshnessGateResult:
    """Classify every candidate as NEW, UPDATED or OLD and return publishable items."""
    cutoff = normalize_current_time(current_time)
    historical = [_prepare_history(item, cutoff) for item in (history or [])]
    accepted: list[RawIntelligenceItem] = []
    evaluated: list[RawIntelligenceItem] = []
    rejected: list[str] = []

    for raw in items:
        item, reason = _classify(raw, historical, cutoff)
        evaluated.append(item)
        if item.freshness_status in ("NEW", "UPDATED"):
            accepted.append(item)
        else:
            rejected.append(f"{item.title}: {reason}")
    return FreshnessGateResult(accepted=accepted, rejected=rejected, evaluated=evaluated)


def filter_last_24_hours(
    items: list[RawIntelligenceItem], current_time: datetime | None = None
) -> tuple[list[RawIntelligenceItem], list[str]]:
    """Backward-compatible strict 24h view; the daily service uses the full gate."""
    cutoff = normalize_current_time(current_time)
    result = apply_freshness_gate(items, current_time=cutoff)
    accepted: list[RawIntelligenceItem] = []
    rejected = list(result.rejected)
    for item in result.accepted:
        effective = item.updated_at_iso if item.freshness_status == "UPDATED" else item.published_at_iso
        if effective is not None and cutoff - PRIMARY_WINDOW <= effective <= cutoff:
            accepted.append(item)
        else:
            rejected.append(f"{item.title}: original/effective publication time exceeds 24 hours")
    return accepted, rejected


def _classify(
    raw: RawIntelligenceItem,
    history: list[RawIntelligenceItem],
    cutoff: datetime,
) -> tuple[RawIntelligenceItem, str]:
    crawl_at = _aware(raw.crawl_at, cutoff) or cutoff
    source_name = (raw.source or raw.source_name).strip()
    source_url = raw.source_url.strip()
    original_name = (raw.original_source_name or (source_name if raw.is_original_source else "")).strip()
    original_url = (raw.original_source_url or (source_url if raw.is_original_source else "")).strip()
    published_raw = raw.original_published_at or raw.published_at
    published, publication_precision, publication_corroborated = parse_publication_time(
        published_raw, raw.publication_time_evidence, cutoff
    )

    updated = parse_exact_publication_time(raw.updated_at)
    update_evidence = parse_exact_publication_time(raw.update_time_evidence)
    if update_evidence is not None and updated is not None:
        if abs((updated - update_evidence).total_seconds()) > 60:
            updated = None

    event_exact = parse_exact_publication_time(raw.event_at)
    event_date = parse_event_date(raw.event_at)
    content_hash = raw.content_hash or content_sha256(
        f"{raw.title}\n{raw.fact}\n{raw.update_facts}"
    )
    source_type = raw.source_type or ("repost" if not raw.is_original_source else "unknown")
    priority = SOURCE_PRIORITY.get(source_type, 9)
    provisional = raw.model_copy(update={
        "company": raw.company or raw.entity,
        "source": source_name,
        "source_name": source_name,
        "source_url": original_url or source_url,
        "original_source_name": original_name,
        "original_source_url": original_url,
        "published_at_iso": published,
        "publication_time_precision": publication_precision,
        "updated_at_iso": updated,
        "event_at_iso": event_exact,
        "event_date": event_date,
        "crawl_at": crawl_at,
        "content_hash": content_hash,
        "source_type": source_type,
        "source_priority": priority,
    })
    provisional = provisional.model_copy(update={"event_key": canonical_event_key(provisional)})
    matched = next((candidate for candidate in history if are_same_event(provisional, candidate)), None)
    first_seen = (_aware(matched.first_seen_at, cutoff) if matched is not None else crawl_at) or crawl_at
    confidence = "HIGH" if publication_precision == "EXACT" and publication_corroborated else "LOW"
    common = {
        "first_seen_at": first_seen,
        "confidence_level": confidence,
        "disclosure_label": _disclosure_label(event_date, published, cutoff),
    }

    if not source_url or not source_name:
        reason = "source name or source URL is unconfirmed"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
            "confidence_level": "LOW",
        }), reason
    if not raw.is_original_source:
        reason = "repost/secondary propagation is not new information"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
        }), reason
    if (raw.is_duplicate_report or raw.is_republished_old) and (
        not raw.is_substantive_update or matched is None
    ):
        reason = "duplicate report or republished old article is not a verified historical update"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
        }), reason
    if not original_url or not original_name:
        reason = "original source is unconfirmed"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
            "confidence_level": "LOW",
        }), reason

    if matched is not None:
        if not raw.is_substantive_update or not raw.update_facts.strip():
            reason = "event was previously discovered/sent and has no substantive new facts"
            return provisional.model_copy(update={
                **common, "freshness_status": "OLD", "freshness_reason": reason,
            }), reason
        if updated is None or not cutoff - UPDATE_WINDOW <= updated <= cutoff:
            reason = "substantive update lacks a verified update time within 7 days"
            return provisional.model_copy(update={
                **common, "freshness_status": "OLD", "freshness_reason": reason,
            }), reason
        if _update_already_known(provisional, history):
            reason = "update facts/content were already discovered or sent"
            return provisional.model_copy(update={
                **common, "freshness_status": "OLD", "freshness_reason": reason,
            }), reason
        reason = "previously known event contains verified substantive new facts"
        return provisional.model_copy(update={
            **common,
            "freshness_status": "UPDATED",
            "freshness_reason": reason,
            "confidence_level": confidence,
            "disclosure_label": _updated_disclosure_label(event_date, updated, cutoff),
        }), reason

    if published is None:
        reason = "publication date cannot be verified; confidence lowered"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
            "confidence_level": "LOW",
        }), reason
    if published > cutoff:
        reason = "publication time is later than REPORT_CUTOFF_TIME"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
        }), reason
    if published < cutoff - RECOVERY_WINDOW:
        reason = "first-seen publication is older than the 72-hour recovery window"
        return provisional.model_copy(update={
            **common, "freshness_status": "OLD", "freshness_reason": reason,
        }), reason
    reason = (
        "first discovery, original publication date within 72 hours at LOW confidence"
        if confidence == "LOW"
        else "first discovery, original publication within 72 hours, not previously sent"
    )
    return provisional.model_copy(update={
        **common, "freshness_status": "NEW", "freshness_reason": reason,
    }), reason


def _prepare_history(item: RawIntelligenceItem, cutoff: datetime) -> RawIntelligenceItem:
    published = item.published_at_iso or parse_exact_publication_time(
        item.original_published_at or item.published_at
    )
    updated = item.updated_at_iso or parse_exact_publication_time(item.updated_at)
    crawl = _aware(item.crawl_at, cutoff) or _aware(item.first_seen_at, cutoff) or updated or published
    content_hash = item.content_hash or content_sha256(
        f"{item.title}\n{item.fact}\n{item.update_facts}"
    )
    prepared = item.model_copy(update={
        "published_at_iso": published,
        "updated_at_iso": updated,
        "crawl_at": crawl,
        "first_seen_at": _aware(item.first_seen_at, cutoff) or crawl,
        "content_hash": content_hash,
    })
    return prepared.model_copy(update={"event_key": canonical_event_key(prepared)})


def _update_already_known(item: RawIntelligenceItem, history: list[RawIntelligenceItem]) -> bool:
    update_hash = content_sha256(item.update_facts)
    for old in history:
        if not are_same_event(item, old):
            continue
        if item.content_hash and item.content_hash == old.content_hash:
            return True
        if old.update_facts and content_sha256(old.update_facts) == update_hash:
            return True
    return False


def _disclosure_label(event_date: date | None, published: datetime | None, cutoff: datetime) -> str:
    if event_date is None:
        return "事件时间未确认，不作推测"
    if published is not None and event_date < published.date():
        if published.date() == cutoff.date():
            return f"今日披露；据今日发布的信息，该事件发生于{event_date:%Y年%m月%d日}"
        return f"最新公开信息显示，该事件发生于{event_date:%Y年%m月%d日}"
    return f"事件时间：{event_date:%Y年%m月%d日}"


def _updated_disclosure_label(event_date: date | None, updated: datetime, cutoff: datetime) -> str:
    prefix = "今日披露新的实质进展" if updated.date() == cutoff.date() else "最新公开信息披露实质进展"
    if event_date is None:
        return f"{prefix}；原事件时间未确认，不作推测"
    return f"{prefix}；原事件发生于{event_date:%Y年%m月%d日}"


def _normal_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").lower())


def _canonical_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except ValueError:
        return value.strip().lower()


def _aware(value: datetime | None, reference: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=reference.tzinfo)
    return value.astimezone(reference.tzinfo)
