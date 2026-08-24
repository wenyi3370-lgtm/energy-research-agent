"""每日战略情报：V2G & 储能董事长日报（models）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from ...domain.models import StrictModel

INTELLIGENCE_CATEGORIES = ("政策监管", "重大项目", "竞争对手", "技术与产品", "市场与价格", "产业与资本")
CATEGORY_CODES = {
    "政策监管": "policy", "重大项目": "project", "竞争对手": "competitor",
    "技术与产品": "technology", "市场与价格": "market", "产业与资本": "capital",
}


class RawIntelligenceItem(StrictModel):
    """LLM 从网页抽取的一条原始情报（严格对齐用户六类监测领域）。"""

    category: str  # 政策监管|重大项目|竞争对手|技术与产品|市场与价格|产业与资本
    title: str = Field(min_length=2)
    fact: str = Field(min_length=5)
    impact_company: str = ""
    source: str = ""  # 对外字段；与 source_name 保持一致
    source_name: str = ""
    source_url: str = ""
    published_at: str = ""  # 当前来源页面显示的发布时间原文
    published_at_iso: datetime | None = None
    publication_time_precision: Literal["EXACT", "DATE_ONLY", "UNKNOWN"] = "UNKNOWN"
    original_published_at: str = ""  # 转载/更新文章对应的原始发布时间
    original_source_name: str = ""
    original_source_url: str = ""
    is_original_source: bool = False
    discovery_url: str = ""  # 搜索命中页；source_url 保留当前来源页面
    publication_time_evidence: str = ""  # 原文中的发布时间文本/元数据片段
    updated_at: str = ""  # 页面明确标注的更新时间
    updated_at_iso: datetime | None = None
    update_time_evidence: str = ""
    event_at: str = ""  # 事件发生时间；未知时必须留空
    event_at_iso: datetime | None = None
    event_date: date | None = None
    event_time_evidence: str = ""
    first_seen_at: datetime | None = None
    crawl_at: datetime | None = None
    topic: str = ""
    content_hash: str = ""  # 抓取页面正文 SHA-256
    event_key: str = ""  # 跨来源/跨日报事件匹配键
    search_layer: Literal["PRIMARY", "RECOVERY", "UPDATE", ""] = ""
    source_type: Literal[
        "official_latest", "company_official", "government_tender",
        "authoritative_media", "industry_media", "repost", "unknown", "",
    ] = ""
    source_priority: int = Field(default=99, ge=1, le=99)
    freshness_status: Literal["NEW", "UPDATED", "OLD", ""] = ""
    freshness_reason: str = ""
    confidence_level: Literal["HIGH", "MEDIUM", "LOW"] = "HIGH"
    disclosure_label: str = ""
    is_duplicate_report: bool = False
    is_republished_old: bool = False
    is_substantive_update: bool = False
    update_facts: str = ""  # 新增项目/价格/参数/订单/细则/合作等事实
    numbers: list[str] = Field(default_factory=list)  # 提取到的关键数字/单位
    company: str = ""  # 涉及企业；无企业主体时可与 entity 同为空
    entity: str = ""  # 涉及企业/机构/项目名

    @property
    def category_code(self) -> str:
        return CATEGORY_CODES.get(self.category, "other")


class IntelligenceItem(RawIntelligenceItem):
    """评分后的情报条目。"""

    score: float = Field(default=0.0, ge=0.0, le=100.0)
    score_reasons: list[str] = Field(default_factory=list)
    insight: str = ""  # LLM/规则生成的行业意义
    is_breaking: bool = False  # score >= 90 重大情报

    def display_score(self) -> str:
        if self.score >= 90:
            return "高重要性"
        if self.score >= 80:
            return "高重要性"
        if self.score >= 70:
            return "中重要性"
        return "低重要性"


class DailyBrief(StrictModel):
    """《V2G & 储能每日情报》成品。"""

    brief_date: date
    judgment: str = ""  # 今日判断（30-50字）
    items: list[IntelligenceItem] = Field(default_factory=list)
    watch_list: list[str] = Field(default_factory=list)  # 今日建议关注 1-3 项
    sources: list[str] = Field(default_factory=list)  # 信息源去重
    updated_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo("Asia/Shanghai")))
    window_start: datetime | None = None
    window_end: datetime | None = None
    report_cutoff_time: datetime | None = None
    primary_window_start: datetime | None = None
    recovery_window_start: datetime | None = None
    update_window_start: datetime | None = None
    candidate_count: int = Field(default=0, ge=0)
    freshness_rejected_count: int = Field(default=0, ge=0)
    freshness_rejection_reasons: list[str] = Field(default_factory=list)
    collection_status: Literal["OK", "DEGRADED", "FAILED"] = "OK"
    # Technical collection success is intentionally independent from bounded
    # Internet coverage.  ``OK`` must never be rendered as "all found".
    coverage_complete: bool = False
    recall_status: str = "PARTIAL_SOURCE_COVERAGE"
    recall_metrics: dict[str, Any] = Field(default_factory=dict)
    extraction_attempt_count: int = Field(default=0, ge=0)
    extraction_failure_count: int = Field(default=0, ge=0)
    collection_failure_reasons: list[str] = Field(default_factory=list)
    breaking_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def collection_status_is_not_coverage(self) -> "DailyBrief":
        if self.coverage_complete:
            raise ValueError("bounded daily recall cannot claim complete Internet coverage")
        return self

    @model_validator(mode="after")
    def enforce_publication_window(self) -> "DailyBrief":
        cutoff = self.report_cutoff_time or self.window_end
        if cutoff is None:
            return self  # backward-compatible loading of briefs created before this gate
        if self.window_start is not None and cutoff < self.window_start:
            raise ValueError("window_end must not precede window_start")
        for item in self.items:
            if not (item.source or item.source_name).strip() or not item.source_url.strip():
                raise ValueError(f"brief item lacks a confirmed source: {item.title}")
            if not item.topic.strip() or not (item.company or item.entity).strip():
                raise ValueError(f"brief item lacks topic/company/entity: {item.title}")
            if item.first_seen_at is None or item.crawl_at is None:
                raise ValueError(f"brief item lacks first_seen_at/crawl_at: {item.title}")
            if len(item.content_hash) != 64:
                raise ValueError(f"brief item lacks a SHA-256 content_hash: {item.title}")
            if item.freshness_status not in ("NEW", "UPDATED"):
                raise ValueError(f"brief item is not NEW/UPDATED: {item.title}")
            if item.freshness_status == "NEW":
                published = _aware(item.published_at_iso, cutoff)
                if published is not None and not cutoff - timedelta(hours=72) <= published <= cutoff:
                    raise ValueError(f"NEW item falls outside the 72-hour window: {item.title}")
                if published is None:
                    crawled = _aware(item.crawl_at, cutoff)
                    if (
                        item.confidence_level != "LOW"
                        or crawled is None
                        or not cutoff - timedelta(hours=72) <= crawled <= cutoff
                    ):
                        raise ValueError(
                            f"NEW item without a verified publication time lacks a recent LOW-confidence crawl: {item.title}"
                        )
            if item.freshness_status == "UPDATED":
                updated = _aware(item.updated_at_iso, cutoff)
                if (
                    updated is None
                    or not cutoff - timedelta(days=7) <= updated <= cutoff
                    or not item.is_substantive_update
                    or not item.update_facts.strip()
                ):
                    raise ValueError(f"UPDATED item lacks a valid 7-day substantive update: {item.title}")
        return self

    def render_text(self) -> str:
        """按用户固定格式渲染为飞书正文（无 markdown，使用 emoji/分隔符排版）。"""
        lines: list[str] = []
        lines.append(f"# V2G & 储能每日情报｜{self.brief_date:%Y.%m.%d}")
        cutoff = self.report_cutoff_time or self.window_end or self.updated_at
        lines.append(f"情报截止：{cutoff:%H:%M}｜24小时主搜｜72小时恢复｜7天更新检查")
        lines.append("")
        lines.append("【今日判断】")
        lines.append(self.judgment or "截至当前时间，未发现符合 NEW/UPDATED 标准的V2G及储能重大新增信息。")
        lines.append("")
        for index, item in enumerate(self.items, start=1):
            marker = "🟥" if item.is_breaking else "🟦"
            sequence = _circled_number(index)
            effective_at = item.updated_at_iso if item.freshness_status == "UPDATED" else item.published_at_iso
            precision = (
                "EXACT" if item.freshness_status == "UPDATED"
                else item.publication_time_precision
            )
            age = _age_label(effective_at, cutoff, precision=precision)
            category = _display_category(item.category)
            status = "最新进展" if item.freshness_status == "UPDATED" else "NEW"
            lines.append(f"{marker} {sequence}【{category}｜{item.display_score()}｜{age}】【{status}】{item.title}")
            if item.disclosure_label:
                lines.append(f"时效说明：{item.disclosure_label}")
            lines.append(f"事实：{item.fact}")
            if item.insight:
                lines.append(f"判断：{item.insight}")
            if item.impact_company:
                lines.append(f"对公司：{item.impact_company}")
            if item.source_url:
                lines.append(f"来源：{item.source or item.source_name}｜查看原文：{item.source_url}")
            lines.append("")
        if self.watch_list:
            lines.append("今日建议关注")
            for watch in self.watch_list:
                lines.append(f"· {watch}")
            lines.append("")
        lines.append("信息源")
        lines.append("来源：" + "｜".join(self.sources[:6]) if self.sources else "来源：公开网络")
        lines.append(f"更新时间：{self.updated_at:%H:%M}")
        return "\n".join(lines)

    def render_breaking(self, item: IntelligenceItem) -> str:
        """重大情报即时快讯（150-250字）。"""
        reported_at = item.published_at or f"{self.updated_at:%H:%M}"
        link = f"\n查看原文：{item.source_url}" if item.source_url else ""
        return (
            f"# 【V2G/储能重大情报｜高优先级】\n"
            f"事件：{item.fact}\n"
            f"核心变化：{item.insight or '待核验'}\n"
            f"对公司影响：{item.impact_company or '需进一步评估'}\n"
            f"建议：跟踪{item.entity or '相关主体'}后续进展并评估对自身业务的影响。\n"
            f"来源：{item.source_name or '公开网络'}｜时间：{reported_at}{link}"
        )


def _circled_number(index: int) -> str:
    values = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    return values[index - 1] if 1 <= index <= len(values) else str(index)


def _display_category(category: str) -> str:
    return {
        "政策监管": "政策",
        "重大项目": "项目",
        "竞争对手": "竞品",
        "技术与产品": "产品",
        "市场与价格": "市场",
        "产业与资本": "产业",
    }.get(category, category)


def _age_label(
    published_at: datetime | None,
    current_time: datetime,
    *,
    precision: str = "EXACT",
) -> str:
    if published_at is None:
        return "时间未核验"
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=current_time.tzinfo)
    if precision == "DATE_ONLY":
        day_delta = (current_time.date() - published_at.date()).days
        if day_delta == 0:
            return "今日发布"
        if day_delta == 1:
            return "昨日发布"
        return f"{published_at:%m月%d日}发布"
    elapsed = max(0, int((current_time - published_at).total_seconds()))
    if published_at.date() == current_time.date():
        minutes = elapsed // 60
        return f"{minutes}分钟前" if minutes < 60 else f"{minutes // 60}小时前"
    if (current_time.date() - published_at.date()).days == 1:
        return f"昨日{published_at:%H:%M}"
    return f"{elapsed // 3600}小时前"


def _aware(value: datetime | None, reference: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=reference.tzinfo)
    return value.astimezone(reference.tzinfo)
