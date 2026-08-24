from __future__ import annotations

import re
from pathlib import Path

from enterprise_energy_research.settings import load_yaml

from .models import QueryPriority, RecallQuerySpec, SearchPass, SourceLane


DEFAULT_TOPICS = Path(__file__).resolve().parents[4] / "config" / "intelligence_search_topics.yaml"


class QueryExpander:
    """Build a finite intent/lane/language matrix from configured aliases."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_TOPICS
        payload = load_yaml(self.path) if self.path.is_file() else {}
        self.topics: dict[str, dict] = dict(payload.get("topics", {}))

    def topic_for(self, query: str, fallback: str = "industry_capital") -> str:
        normalized = query.casefold()
        scored: list[tuple[int, str]] = []
        for topic, config in self.topics.items():
            matches = [str(alias) for alias in config.get("aliases", []) if str(alias).casefold() in normalized]
            if matches:
                scored.append((max(len(item) for item in matches), topic))
        return max(scored, default=(0, fallback))[1]

    def daily_specs(
        self,
        seeds: list[tuple[str, str]],
        *,
        primary_start: str,
        recovery_start: str,
        end_exclusive: str,
    ) -> list[RecallQuerySpec]:
        specs: list[RecallQuerySpec] = []
        for index, (seed, fallback_topic) in enumerate(seeds):
            topic = self.topic_for(seed, fallback_topic if fallback_topic in self.topics else "industry_capital")
            config = self.topics.get(topic, {})
            priority = QueryPriority(str(config.get("priority", "P1")))
            lanes = list(config.get("source_lanes", ["media_discovery"]))
            seed_lane = SourceLane(str(lanes[0]))
            specs.append(RecallQuerySpec(
                query_id=f"RQ-P-{index:03d}-00", topic=topic,
                query=self._window(seed, primary_start, end_exclusive),
                search_pass=SearchPass.PRIMARY, source_lane=seed_lane,
                language="zh-CN", priority=priority, desired_results=6,
                seed_query=True, query_variant="seed",
            ))
            specs.append(RecallQuerySpec(
                query_id=f"RQ-R-{index:03d}", topic=topic,
                query=self._window(seed, recovery_start, end_exclusive),
                search_pass=SearchPass.RECOVERY, source_lane=SourceLane.MEDIA_DISCOVERY,
                language="zh-CN", priority=priority, desired_results=4,
                seed_query=True, query_variant="recovery",
            ))
            intents = list(config.get("intents", []))[: max(0, int(config.get("max_variants", 3)) - 1)]
            aliases = [str(item) for item in config.get("aliases", [])]
            for variant_index, intent in enumerate(intents, start=1):
                language = str(intent.get("language", "zh-CN"))
                alias = self._alias_for_language(aliases, language) or seed
                suffix = str(intent.get("suffix", "")).strip()
                query = f"{alias} {suffix}".strip()
                specs.append(RecallQuerySpec(
                    query_id=f"RQ-P-{index:03d}-{variant_index:02d}", topic=topic,
                    query=self._window(query, primary_start, end_exclusive),
                    search_pass=SearchPass.PRIMARY,
                    source_lane=SourceLane(str(intent.get("lane", "media_discovery"))),
                    language=language, priority=priority, desired_results=4,
                    seed_query=False, query_variant=f"intent_{variant_index}",
                ))
        return self._dedupe(specs)

    def enterprise_specs(self, canonical_name: str, topics: list[str]) -> list[RecallQuerySpec]:
        lane_by_topic = {
            "subsidiaries": SourceLane.CORPORATE_OFFICIAL,
            "factories": SourceLane.GOVERNMENT_REGULATORY,
            "products": SourceLane.TECHNICAL_DOCUMENT,
            "product_models": SourceLane.TECHNICAL_DOCUMENT,
            "customers": SourceLane.CUSTOMER_PARTNER,
            "financials": SourceLane.FINANCIAL_DISCLOSURE,
            "energy_projects": SourceLane.GOVERNMENT_REGULATORY,
        }
        specs: list[RecallQuerySpec] = []
        for index, topic in enumerate(dict.fromkeys(topics)):
            lane = lane_by_topic.get(topic, SourceLane.MEDIA_DISCOVERY)
            suffix = {
                SourceLane.CORPORATE_OFFICIAL: "官网 子公司 名录 曾用名",
                SourceLane.GOVERNMENT_REGULATORY: "政府 环评 项目 基地 文件编号",
                SourceLane.TECHNICAL_DOCUMENT: "产品 型号 datasheet PDF 手册",
                SourceLane.CUSTOMER_PARTNER: "客户 供应商 合作伙伴 项目披露",
                SourceLane.FINANCIAL_DISCLOSURE: "年报 公告 交易所",
                SourceLane.MEDIA_DISCOVERY: "最新 项目 产品 业务",
            }[lane]
            specs.append(RecallQuerySpec(
                query_id=f"RQ-E-{index:03d}", topic=topic,
                query=f'"{canonical_name}" {suffix}', search_pass=SearchPass.ENTERPRISE_SEED,
                source_lane=lane, language="zh-CN", priority=QueryPriority.P1,
                desired_results=4, seed_query=False, query_variant="source_lane",
            ))
        return specs

    @staticmethod
    def _window(query: str, start: str, end_exclusive: str) -> str:
        return f"{query} 最新 发布 公告 after:{start} before:{end_exclusive}"

    @staticmethod
    def _alias_for_language(aliases: list[str], language: str) -> str:
        if language.lower().startswith("en"):
            candidates = [item for item in aliases if re.search(r"[A-Za-z]", item) and not re.search(r"[\u4e00-\u9fff]", item)]
            return max(candidates, key=len, default="")
        return next((item for item in aliases if re.search(r"[\u4e00-\u9fff]", item)), "")

    @staticmethod
    def _dedupe(specs: list[RecallQuerySpec]) -> list[RecallQuerySpec]:
        seen: set[tuple[str, str, str]] = set()
        unique: list[RecallQuerySpec] = []
        for spec in specs:
            key = (" ".join(spec.query.casefold().split()), spec.search_pass.value, spec.source_lane.value)
            if key in seen:
                continue
            seen.add(key)
            unique.append(spec)
        return unique
