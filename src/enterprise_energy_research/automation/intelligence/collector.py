"""情报采集器：anysearch + kimi-webbridge 双适配器 → DeepSeek 抽取。

复用现有搜索适配器与 LLM gateway，不重复造轮子。查询集覆盖用户六大
监测领域（政策/项目/竞品/技术/市场/产业），每次查询的命中页面经
LLM 抽取为 :class:`RawIntelligenceItem`。
"""

from __future__ import annotations

import logging
from typing import Any

from ...adapters.base import SearchAdapter, SearchRequest
from ...domain.ids import new_sortable_id
from ...gateway.base import ModelGateway, StructuredRequest
from ...research.executor import SearchExecutor
from ...domain.models import StrictModel
from pydantic import Field

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
    source_name: str = ""
    source_url: str = ""
    published_at: str = ""
    numbers: list[str] = Field(default_factory=list)
    entity: str = ""


class IntelligenceCollector:
    """Run daily queries through the search adapters and extract items via LLM."""

    def __init__(
        self,
        adapters: dict[str, SearchAdapter],
        gateway: ModelGateway | None,
        queries: list[str] | None = None,
    ) -> None:
        self.adapters = adapters
        self.gateway = gateway
        self.queries = queries or DAILY_QUERIES
        self.extraction_failures: list[str] = []

    def collect(self) -> list[Any]:
        from ...domain.models import ResearchPlan, ResearchQuery
        from ...domain.enums import SourceLevel

        plan = ResearchPlan(
            plan_id=new_sortable_id("IPLAN"),
            run_id="intelligence",
            complexity="UNKNOWN",
            queries=[
                ResearchQuery(
                    query_id=f"IQ-{index:03d}",
                    entity_id="intel",
                    topic=topic,
                    query=query,
                    purpose=f"daily intelligence: {query}",
                    preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                    adapter_preference="kimi_webbridge" if "产品" in query or "V2G" in query else "anysearch",
                    max_results=6,
                    requires_browser=False,
                    collection_round="R1",
                    round_goal="coverage",
                    high_priority=True,
                )
                for index, (query, topic) in enumerate(self.queries)
            ],
            budget={"max_queries": 40, "max_pages": 60},
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
                extracted = self._extract(hit.final_url, hit.title or "", hit.text)
                if extracted is not None:
                    items.append(extracted)
        self.extraction_failures = failures
        logger.info("intelligence collect: %d envelopes, %d items, %d failures", len(envelopes), len(items), len(failures))
        return items

    def _extract(self, url: str, title: str, text: str) -> IntelligenceExtraction | None:
        prompt = (
            "你是企业战略情报分析助手。从下面网页中抽取与 V2G、车网互动、储能、"
            "虚拟电厂、充换电、电力市场、双向充电设备相关的情报条目，输出 JSON 对象。\n"
            "规则：只输出网页中明确存在的事实，禁止编造数字；category 必须是"
            "「政策监管」「重大项目」「竞争对手」「技术与产品」「市场与价格」「产业与资本」之一；"
            "fact 用 1-2 句包含关键数字的客观描述；impact_company 描述对储能/V2G"
            "设备制造企业的影响（若无明显影响留空）；source_name 填媒体/机构名。\n\n"
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
        return self._complete(extracted, url, title)

    @staticmethod
    def _complete(extracted: IntelligenceExtraction, url: str, title: str) -> IntelligenceExtraction:
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
        if not extracted.category:
            extracted.category = "产业与资本"
        return extracted
