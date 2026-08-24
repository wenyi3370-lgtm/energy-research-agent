"""情报采集器：anysearch + kimi-webbridge 双适配器 → DeepSeek 抽取。

复用现有搜索适配器与 LLM gateway，不重复造轮子。查询集覆盖用户六大
监测领域（政策/项目/竞品/技术/市场/产业），每次查询的命中页面经
LLM 抽取为 :class:`RawIntelligenceItem`。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from ...adapters.base import SearchAdapter
from ...domain.ids import new_sortable_id
from ...gateway.base import ModelGateway, StructuredRequest
from ...research.executor import SearchExecutor
from ...domain.models import StrictModel
from pydantic import ConfigDict, Field, model_validator

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

    # This is an external model-response boundary.  DeepSeek may emit
    # harmless extra keys, null strings, date-only values in datetime slots,
    # or numeric values inside ``numbers``.  Normalize those transport quirks
    # here; the downstream RawIntelligenceItem remains strict.
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

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

    @model_validator(mode="before")
    @classmethod
    def normalize_model_response(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        string_fields = {
            "category", "title", "fact", "impact_company", "source", "source_name",
            "source_url", "published_at", "original_published_at", "original_source_name",
            "original_source_url", "discovery_url", "publication_time_evidence", "updated_at",
            "update_time_evidence", "event_at", "event_time_evidence", "topic", "event_key",
            "source_type", "search_layer", "content_hash", "update_facts", "company", "entity",
        }
        for field in string_fields:
            if payload.get(field) is None:
                payload[field] = ""
            elif field in payload and not isinstance(payload[field], str):
                payload[field] = str(payload[field])
        iso_value = payload.get("published_at_iso")
        if not iso_value or (isinstance(iso_value, str) and ":" not in iso_value):
            payload["published_at_iso"] = None
        numbers = payload.get("numbers")
        if numbers is None:
            payload["numbers"] = []
        elif isinstance(numbers, list):
            payload["numbers"] = [str(item) for item in numbers if item is not None]
        else:
            payload["numbers"] = [str(numbers)]
        return payload


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
        self.extraction_attempt_count = 0
        self.extraction_success_count = 0

    def collect(
        self,
        current_time: datetime | None = None,
        update_targets: list[RawIntelligenceItem] | None = None,
    ) -> list[Any]:
        from ...domain.models import ResearchPlan, ResearchQuery
        from ...domain.enums import SourceLevel

        current_time = normalize_current_time(current_time)
        self.extraction_failures = []
        self.extraction_attempt_count = 0
        self.extraction_success_count = 0
        primary_start = current_time - timedelta(hours=24)
        recovery_start = current_time - timedelta(hours=72)
        update_start = current_time - timedelta(days=7)
        query_specs: list[tuple[str, str, str, str]] = []
        for index, (query, topic) in enumerate(self.queries):
            query_specs.append((
                f"IQ-P-{index:03d}", topic, "PRIMARY",
                _window_query(query, primary_start, current_time),
            ))
            query_specs.append((
                f"IQ-R-{index:03d}", topic, "RECOVERY",
                _window_query(query, recovery_start, current_time),
            ))
        for index, target in enumerate((update_targets or [])[:12]):
            target_text = " ".join(part for part in (target.entity, target.title, target.topic) if part)
            query_specs.append((
                f"IQ-U-{index:03d}", target.topic or target.category, "UPDATE",
                _window_query(f"{target_text} 最新进展 更新 新增事实", update_start, current_time),
            ))
        # SearchExecutor accounts for every returned discovery hit against a
        # single plan-level page budget.  A fixed value of 100 was lower than
        # the normal 12-query PRIMARY+RECOVERY demand (120), and adding UPDATE
        # checks can raise the bounded maximum to 168.  Size the budget from
        # the exact query plan so later layers are never deterministically
        # blocked while the run remains strictly bounded.
        planned_page_budget = sum(_result_limit(layer) for _, _, layer, _ in query_specs)
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
                    # AnySearch discovers real result URLs.  Kimi is used only
                    # as a target-page fallback during hydration; sending a
                    # broad query directly to Kimi returns a Bing result page.
                    adapter_preference="anysearch",
                    max_results=_result_limit(layer),
                    requires_browser=False,
                    collection_round={"PRIMARY": "R1", "RECOVERY": "R2", "UPDATE": "R3"}[layer],
                    round_goal={"PRIMARY": "coverage", "RECOVERY": "depth", "UPDATE": "triangulation"}[layer],
                    high_priority=True,
                )
                for query_id, topic, layer, query in query_specs
            ],
            budget={
                "max_queries": max(40, len(query_specs)),
                "max_pages": planned_page_budget,
            },
            completion_contract=[],
        )
        envelopes = SearchExecutor(self.adapters).execute(plan)
        items: list[Any] = []
        seen_urls: set[str] = set()
        for envelope in envelopes:
            if envelope.status in ("blocked", "error"):
                self.extraction_failures.append(f"{envelope.query_id}: {envelope.diagnostics[:1]}")
                continue
            for hit_index, hit in enumerate(envelope.hits):
                if not hit.final_url or not hit.text or self.gateway is None:
                    continue
                canonical_url = _canonical_url(hit.final_url)
                if (
                    not canonical_url
                    or canonical_url in seen_urls
                    or _is_search_result_page(canonical_url)
                    or _is_listing_root_page(canonical_url)
                ):
                    continue
                seen_urls.add(canonical_url)
                hydrated = self._hydrate_hit(envelope.query_id, hit_index, hit)
                if hydrated is None:
                    continue
                final_url, final_title, final_text, retrieved_at = hydrated
                self.extraction_attempt_count += 1
                extracted = self._extract(
                    final_url, final_title, final_text,
                    current_time=current_time,
                    primary_start=primary_start,
                    recovery_start=recovery_start,
                    update_start=update_start,
                    search_layer=_layer_from_query_id(envelope.query_id),
                    topic=envelope.topic or "",
                    crawl_at=_parse_crawl_at(retrieved_at, current_time),
                    content_hash=content_sha256(final_text),
                )
                if extracted is not None:
                    items.append(extracted)
                    self.extraction_success_count += 1
        logger.info(
            "intelligence collect: %d envelopes, %d hydrated attempts, %d items, %d failures",
            len(envelopes), self.extraction_attempt_count, len(items), len(self.extraction_failures),
        )
        return items

    def _hydrate_hit(self, query_id: str, hit_index: int, hit: Any) -> tuple[str, str, str, str] | None:
        """Open a discovery hit as a real page before factual extraction."""
        from ...adapters.base import SearchRequest

        is_snippet = bool(getattr(hit, "metadata", {}).get("snippet"))
        if not is_snippet:
            return hit.final_url, hit.title or "", hit.text or "", hit.retrieved_at
        diagnostics: list[str] = []
        for adapter_name in ("anysearch", "kimi_webbridge"):
            adapter = self.adapters.get(adapter_name)
            if adapter is None:
                continue
            request = SearchRequest(
                query_id=f"{query_id}-FULL-{hit_index:02d}", query="", entity_id="intel",
                purpose="daily intelligence target-page hydration", max_results=1,
                requires_browser=adapter_name == "kimi_webbridge",
                metadata={"url": hit.final_url},
            )
            result = adapter.search(request)
            if result.status not in ("blocked", "error"):
                full = next((item for item in result.hits if item.final_url and item.text), None)
                if full is not None and not _is_search_result_page(full.final_url):
                    return (
                        full.final_url, full.title or hit.title or "", full.text or "",
                        full.retrieved_at or hit.retrieved_at,
                    )
            diagnostics.extend(result.diagnostics[:1])
        self.extraction_failures.append(
            f"{query_id} {hit.final_url}: target-page hydration failed: {diagnostics[:2]}"
        )
        return None

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
            "整页最多选择一条最重要且与上述领域直接相关的情报。只输出一个扁平 JSON 对象，"
            "禁止输出数组、intelligence_items 等包装字段；若页面只是聚合列表或没有直接相关事实，"
            "fact 留空。\n"
            "规则：只输出网页中明确存在的事实，禁止编造数字；category 必须是"
            "「政策监管」「重大项目」「竞争对手」「技术与产品」「市场与价格」「产业与资本」之一；"
            "fact 用 1-2 句包含关键数字的客观描述；impact_company 描述对储能/V2G"
            "设备制造企业的影响（若无明显影响留空）；source_name 填媒体/机构名。\n"
            f"REPORT_CUTOFF_TIME={current_time.isoformat()}；当前搜索层={search_layer}；"
            f"24小时主搜起点={primary_start.isoformat()}；72小时恢复起点={recovery_start.isoformat()}；"
            f"7天更新检查起点={update_start.isoformat()}。\n"
            "必须分别抽取 published_at、updated_at（如有）、event_at（如能确定）；不得把事件时间当发布时间。"
            "published_at 始终填写当前页面自身的发布时间；若当前页面未显示则留空。"
            "发布时间原文写入 publication_time_evidence，更新时间证据写入 update_time_evidence，"
            "事件时间证据写入 event_time_evidence；无法确认的字段留空，禁止推测。"
            "判断当前页面是否为政府/企业/招投标/媒体原始发布页，写入 is_original_source。"
            "若为转载，另行提供 original_source_name、original_source_url、original_published_at；"
            "找不到原始来源则这些字段留空。转载/二次传播本身可以作为情报来源，不得仅因转载而丢弃。"
            "不得用搜索摘要时间或抓取时间冒充 published_at。"
            "source_type 必须从 official_latest、company_official、government_tender、"
            "authoritative_media、industry_media、repost、unknown 中选择。"
            "event_key 用简短稳定短语概括实体+政策/项目/产品/订单标识，便于跨来源识别同一事件。"
            "company 填企业主体，entity 填企业/机构/项目主体，topic 填政策/项目/价格/产品等主题。"
            "旧文或历史事件只有确有新政策文件、项目规模、中标价格、产品参数、合作方、订单金额、"
            "项目进度、官方解释或监管要求，"
            "才设置 is_substantive_update=true，并在 update_facts 写明新增事实和 updated_at 精确时间；"
            "若只是已有新闻的重复报道，设置 is_duplicate_report=true；若是旧文重发、重编辑或只改标题，"
            "设置 is_republished_old=true。两者均不得视为实质更新，但当前页面若在时效窗口内，"
            "仍可作为最新传播信息进入候选。"
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
            detail = str(exc)[:480]
            self.extraction_failures.append(f"{url}: {detail}")
            logger.warning("intelligence extraction failed for %s: %s", url, detail)
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


def _result_limit(layer: str) -> int:
    return 6 if layer == "PRIMARY" else 4


def _parse_crawl_at(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback.tzinfo)
    return parsed.astimezone(fallback.tzinfo)


def _window_query(query: str, start: datetime, end: datetime) -> str:
    """Use search-engine date operators instead of ambiguous clock prose."""
    exclusive_end = (end + timedelta(days=1)).date()
    return (
        f"{query} 最新 发布 公告 after:{start.date().isoformat()} "
        f"before:{exclusive_end.isoformat()}"
    )


def _canonical_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def _is_search_result_page(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    return (
        host in {"bing.com", "www.bing.com", "google.com", "www.google.com"}
        and parsed.path.rstrip("/") in {"/search", ""}
    )


def _is_listing_root_page(value: str) -> bool:
    """Daily facts require an article/detail URL, not a multi-story homepage."""
    parsed = urlparse(value)
    return parsed.path.rstrip("/") == ""
