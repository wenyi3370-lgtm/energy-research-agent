"""情报采集器：anysearch + kimi-webbridge 双适配器 → DeepSeek 抽取。

复用现有搜索适配器与 LLM gateway，不重复造轮子。查询集覆盖用户六大
监测领域（政策/项目/竞品/技术/市场/产业），每次查询的命中页面经
LLM 抽取为 :class:`RawIntelligenceItem`。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ...adapters.base import SearchAdapter
from ...domain.ids import new_sortable_id
from ...gateway.base import ModelGateway, StructuredRequest
from ...research.executor import SearchExecutor
from ...domain.models import StrictModel
from pydantic import Field

from .freshness import content_sha256, normalize_current_time
from .models import RawIntelligenceItem

logger = logging.getLogger("enterprise_energy_research.automation.intelligence")

DAILY_QUERIES = [
    ("V2G 车网互动 试点 政策", "policy"),
    ("车网互动 规模化 示范项目", "project"),
    ("储能 招标 中标 价格 MWh", "market"),
    ("工商业储能 项目 并网", "project"),
    ("虚拟电厂 聚合 运营", "project"),
    ("双向充电桩 V2G 产品", "technology"),
    ("构网型储能 招标", "market"),
    ("储能 新品 发布 液冷", "competitor"),
    ("储能 融资 并购 产能扩张", "capital"),
    ("充换电站 重卡 建设", "project"),
    ("峰谷电价 电力现货 辅助服务", "policy"),
    ("V2G 放电收益 商业模式", "market"),
]


class IntelligenceExtraction(StrictModel):
    """LLM 对单页的情报抽取输出（字段宽松，缺失由 collector 补全）。"""

    category: str = ""
    title: str = ""
    fact: str = ""
    impact_company: str = ""
    source: str = ""
    source_name: str = ""
    source_url: str = ""
    published_at: str = ""
    published_at_iso: datetime | None = None
    original_published_at: str = ""
    original_source_name: str = ""
    original_source_url: str = ""
    is_original_source: bool = False
    discovery_url: str = ""
    publication_time_evidence: str = ""
    updated_at: str = ""
    update_time_evidence: str = ""
    event_at: str = ""
    event_time_evidence: str = ""
    topic: str = ""
    event_key: str = ""
    source_type: str = ""
    search_layer: str = ""
    crawl_at: datetime | None = None
    content_hash: str = ""
    is_duplicate_report: bool = False
    is_republished_old: bool = False
    is_substantive_update: bool = False
    update_facts: str = ""
    numbers: list[str] = Field(default_factory=list)
    company: str = ""
    entity: str = ""


class IntelligenceCollector:
    """Run daily queries through the search adapters and extract items via LLM."""

    def __init__(
        self,
        adapters: dict[str, SearchAdapter],
        gateway: ModelGateway | None,
        queries: list[tuple[str, str]] | None = None,
    ) -> None:
        self.adapters = adapters
        self.gateway = gateway
        self.queries = queries or DAILY_QUERIES
        self.extraction_failures: list[str] = []

    def collect(
        self,
        current_time: datetime | None = None,
        update_targets: list[RawIntelligenceItem] | None = None,
    ) -> list[Any]:
        from ...domain.models import ResearchPlan, ResearchQuery
        from ...domain.enums import SourceLevel

        current_time = normalize_current_time(current_time)
        primary_start = current_time - timedelta(hours=24)
        recovery_start = current_time - timedelta(hours=72)
        update_start = current_time - timedelta(days=7)
        query_specs: list[tuple[str, str, str, str]] = []
        for index, (query, topic) in enumerate(self.queries):
            query_specs.append((
                f"IQ-P-{index:03d}", topic, "PRIMARY",
                f"{query} 发布时间 {primary_start:%Y-%m-%d %H:%M %z} 至 {current_time:%Y-%m-%d %H:%M %z}",
            ))
            query_specs.append((
                f"IQ-R-{index:03d}", topic, "RECOVERY",
                f"{query} 发布时间 {recovery_start:%Y-%m-%d %H:%M %z} 至 {current_time:%Y-%m-%d %H:%M %z}",
            ))
        for index, target in enumerate((update_targets or [])[:12]):
            target_text = " ".join(part for part in (target.entity, target.title, target.topic) if part)
            query_specs.append((
                f"IQ-U-{index:03d}", target.topic or target.category, "UPDATE",
                f"{target_text} 最新进展 更新 新增事实 {update_start:%Y-%m-%d %H:%M %z} 至 {current_time:%Y-%m-%d %H:%M %z}",
            ))
        plan = ResearchPlan(
            plan_id=new_sortable_id("IPLAN"),
            run_id="intelligence",
            complexity="UNKNOWN",
            queries=[
                ResearchQuery(
                    query_id=query_id,
                    entity_id="intel",
                    topic=topic,
                    query=query,
                    purpose=(
                        f"daily intelligence {layer}; REPORT_CUTOFF_TIME={current_time.isoformat()}; "
                        f"primary_start={primary_start.isoformat()}; recovery_start={recovery_start.isoformat()}; "
                        f"update_start={update_start.isoformat()}"
                    ),
                    preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                    adapter_preference="kimi_webbridge" if "产品" in query or "V2G" in query else "anysearch",
                    max_results=6 if layer == "PRIMARY" else 4,
                    requires_browser=False,
                    collection_round={"PRIMARY": "R1", "RECOVERY": "R2", "UPDATE": "R3"}[layer],
                    round_goal={"PRIMARY": "coverage", "RECOVERY": "depth", "UPDATE": "triangulation"}[layer],
                    high_priority=True,
                )
                for query_id, topic, layer, query in query_specs
            ],
            budget={"max_queries": max(40, len(query_specs)), "max_pages": 100},
            completion_contract=[],
        )
        envelopes = SearchExecutor(self.adapters).execute(plan)
        items: list[Any] = []
        failures: list[str] = []
        for envelope in envelopes:
            if envelope.status in ("blocked", "error"):
                failures.append(f"{envelope.query_id}: {envelope.diagnostics[:1]}")
                continue
            for hit in envelope.hits:
                if not hit.final_url or not hit.text or self.gateway is None:
                    continue
                extracted = self._extract(
                    hit.final_url, hit.title or "", hit.text,
                    current_time=current_time,
                    primary_start=primary_start,
                    recovery_start=recovery_start,
                    update_start=update_start,
                    search_layer=_layer_from_query_id(envelope.query_id),
                    topic=envelope.topic or "",
                    crawl_at=_parse_crawl_at(hit.retrieved_at, current_time),
                    content_hash=content_sha256(hit.text),
                )
                if extracted is not None:
                    items.append(extracted)
        self.extraction_failures = failures
        logger.info("intelligence collect: %d envelopes, %d items, %d failures", len(envelopes), len(items), len(failures))
        return items

    def _extract(
        self,
        url: str,
        title: str,
        text: str,
        *,
        current_time: datetime,
        primary_start: datetime,
        recovery_start: datetime,
        update_start: datetime,
        search_layer: str,
        topic: str,
        crawl_at: datetime,
        content_hash: str,
    ) -> IntelligenceExtraction | None:
        prompt = (
            "你是企业战略情报分析助手。从下面网页中抽取与 V2G、车网互动、储能、"
            "虚拟电厂、充换电、电力市场、双向充电设备相关的情报条目，输出 JSON 对象。\n"
            "规则：只输出网页中明确存在的事实，禁止编造数字；category 必须是"
            "「政策监管」「重大项目」「竞争对手」「技术与产品」「市场与价格」「产业与资本」之一；"
            "fact 用 1-2 句包含关键数字的客观描述；impact_company 描述对储能/V2G"
            "设备制造企业的影响（若无明显影响留空）；source_name 填媒体/机构名。\n"
            f"REPORT_CUTOFF_TIME={current_time.isoformat()}；当前搜索层={search_layer}；"
            f"24小时主搜起点={primary_start.isoformat()}；72小时恢复起点={recovery_start.isoformat()}；"
            f"7天更新检查起点={update_start.isoformat()}。\n"
            "必须分别抽取 published_at、updated_at（如有）、event_at（如能确定）；不得把事件时间当发布时间。"
            "发布时间原文写入 publication_time_evidence，更新时间证据写入 update_time_evidence，"
            "事件时间证据写入 event_time_evidence；无法确认的字段留空，禁止推测。"
            "判断当前页面是否为政府/企业/招投标/媒体原始发布页，写入 is_original_source。"
            "若为转载，必须提供 original_source_name、original_source_url、original_published_at；"
            "找不到原始来源则这些字段留空。不得用搜索摘要时间、抓取时间或转载时间代替原始时间。"
            "source_type 必须从 official_latest、company_official、government_tender、"
            "authoritative_media、industry_media、repost、unknown 中选择。"
            "event_key 用简短稳定短语概括实体+政策/项目/产品/订单标识，便于跨来源识别同一事件。"
            "company 填企业主体，entity 填企业/机构/项目主体，topic 填政策/项目/价格/产品等主题。"
            "旧文或历史事件只有确有新政策文件、项目规模、中标价格、产品参数、合作方、订单金额、"
            "项目进度、官方解释或监管要求，"
            "才设置 is_substantive_update=true，并在 update_facts 写明新增事实和 updated_at 精确时间；"
            "若只是已有新闻的重复报道，设置 is_duplicate_report=true；若是旧文重发、重编辑或只改标题，"
            "设置 is_republished_old=true。两者均不得视为实质更新。"
            "若 published_at 是今天但 event_at 更早，fact 必须使用“今日披露/最新公开信息显示”，"
            "不得描述为“今日发生”。\n\n"
            f"URL: {url}\nTITLE: {title}\nCONTENT:\n{text[:25000]}"
        )
        try:
            extracted = self.gateway.structured(StructuredRequest[IntelligenceExtraction](
                purpose="daily_intelligence_extraction",
                messages=[{"role": "user", "content": prompt}],
                response_model=IntelligenceExtraction,
                temperature=0.0,
                metadata={"query_id": "intel", "adapter": "intelligence"},
            ))
        except Exception as exc:  # noqa: BLE001 - one page must not sink the daily run
            logger.warning("intelligence extraction failed for %s: %s", url, str(exc)[:120])
            return None
        return self._complete(
            extracted, url, title, search_layer=search_layer, topic=topic,
            crawl_at=crawl_at, content_hash=content_hash,
        )

    @staticmethod
    def _complete(
        extracted: IntelligenceExtraction,
        url: str,
        title: str,
        *,
        search_layer: str,
        topic: str,
        crawl_at: datetime,
        content_hash: str,
    ) -> RawIntelligenceItem | None:
        """补全 LLM 稀疏输出：缺 title/来源用事实与页面信息兜底，绝不编造事实。"""
        if not extracted.fact.strip():
            return None
        if not extracted.title.strip():
            extracted.title = extracted.fact[:40].rstrip("。，；")
        if not extracted.source_url:
            extracted.source_url = url
        if not extracted.source_name:
            from urllib.parse import urlparse

            extracted.source_name = urlparse(url).netloc or "公开网络"
        if not extracted.source:
            extracted.source = extracted.source_name
        if not extracted.original_source_url and extracted.is_original_source:
            extracted.original_source_url = extracted.source_url
        if not extracted.original_source_name and extracted.is_original_source:
            extracted.original_source_name = extracted.source_name
        if not extracted.original_published_at and extracted.is_original_source:
            extracted.original_published_at = extracted.published_at
        if not extracted.category:
            extracted.category = "产业与资本"
        if not extracted.entity:
            extracted.entity = extracted.source_name
        if not extracted.company and extracted.entity:
            extracted.company = extracted.entity
        extracted.topic = extracted.topic or topic
        extracted.search_layer = search_layer
        extracted.crawl_at = crawl_at
        extracted.content_hash = content_hash
        if extracted.source_type not in {
            "official_latest", "company_official", "government_tender",
            "authoritative_media", "industry_media", "repost", "unknown", "",
        }:
            extracted.source_type = "unknown"
        return RawIntelligenceItem.model_validate(extracted.model_dump())


def _layer_from_query_id(query_id: str) -> str:
    if query_id.startswith("IQ-P-"):
        return "PRIMARY"
    if query_id.startswith("IQ-R-"):
        return "RECOVERY"
    return "UPDATE"


def _parse_crawl_at(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback.tzinfo)
    return parsed.astimezone(fallback.tzinfo)
