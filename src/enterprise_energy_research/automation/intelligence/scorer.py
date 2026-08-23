"""情报评分与去重（用户权重：政策30/相关性30/商业价值20/行业10/新鲜度10）。"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .models import IntelligenceItem, RawIntelligenceItem
from .freshness import are_same_event, normalize_current_time, parse_exact_publication_time

# 与"本公司业务"（储能/V2G 设备、系统、电力交易）相关度关键词
_RELEVANCE_KEYWORDS = [
    "V2G", "车网互动", "双向充电", "储能", "电池", "PCS", "EMS", "BMS",
    "虚拟电厂", "聚合", "充换电", "充电桩", "光储充", "峰谷", "现货", "辅助服务",
    "构网型", "液冷", "电芯", "兆瓦", "MWh", "MW", "Wh", "招标", "中标",
]

# Hard scope gate. Generic project words such as MW/招标/中标 may improve the
# score only after an item has demonstrated an actual V2G/storage/electricity-
# flexibility link; otherwise ordinary PV/EPC procurements can become false
# positives merely because they contain a capacity and a tender amount.
_CORE_SCOPE_KEYWORDS = [
    "V2G", "车网互动", "双向充电", "储能", "虚拟电厂", "充换电", "充电桩",
    "光储充", "构网型", "储能电池", "电化学储能", "电芯", "PCS", "BMS", "EMS",
    "峰谷电价", "电力现货", "辅助服务", "需求响应", "源网荷储", "微电网",
]

# 行业影响信号词
_INDUSTRY_SIGNALS = ["规模", "首", "试点", "示范", "标准", "规则", "价格", "降价", "并购", "产能"]


def _freshness(item: RawIntelligenceItem, current_time: date | datetime) -> float:
    if isinstance(current_time, date) and not isinstance(current_time, datetime):
        current_time = datetime.combine(current_time, datetime.max.time()).replace(
            tzinfo=normalize_current_time().tzinfo
        )
    current_time = normalize_current_time(current_time)
    if item.freshness_status == "UPDATED":
        updated = item.updated_at_iso or parse_exact_publication_time(item.updated_at)
        if updated is None:
            return 0.0
        hours = (current_time - updated).total_seconds() / 3600
        return 9.0 if 0 <= hours <= 72 else (7.0 if 72 < hours <= 168 else 0.0)
    published = item.published_at_iso or parse_exact_publication_time(item.published_at)
    if published is None:
        return 0.0
    hours = (current_time - published).total_seconds() / 3600
    if 0 <= hours <= 24:
        return 10.0
    return 8.0 if 24 < hours <= 72 else 0.0


def _relevance(text: str) -> float:
    """业务相关性：领域基准 4 分 + 每个命中关键词 +2（上限 10）。"""
    hits = sum(1 for keyword in _RELEVANCE_KEYWORDS if keyword.lower() in text.lower())
    return min(10.0, 4.0 + hits * 2.0)


def _is_in_scope(item: RawIntelligenceItem) -> bool:
    text = f"{item.title} {item.fact} {item.impact_company} {item.topic}"
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in _CORE_SCOPE_KEYWORDS)


def _business_value(category: str, fact: str) -> float:
    """商业价值：重大项目/市场价/竞品动作价值高；纯政策文本次之。"""
    if any(k in fact for k in ("中标", "招标", "签约", "订单", "投资", "亿元", "GW", "GWh", "MWh")):
        return 9.0
    value_by_category = {"重大项目": 8.0, "市场与价格": 8.0, "竞争对手": 7.0,
                         "产业与资本": 6.0, "政策监管": 5.0, "技术与产品": 5.0}
    return value_by_category.get(category, 5.0)


def _industry_impact(category: str, text: str) -> float:
    hits = sum(1 for signal in _INDUSTRY_SIGNALS if signal in text)
    return min(10.0, 4.0 + hits * 1.5)


def score_item(item: RawIntelligenceItem, today: date | datetime | None = None) -> IntelligenceItem:
    """按用户权重计算 Strategic Intelligence Score (0-100)。"""
    today = today or normalize_current_time()
    text = f"{item.title} {item.fact} {item.company} {item.entity}"
    scores = {
        "政策/监管影响": _policy_weight(item.category),
        "与本公司业务相关性": _relevance(text),
        "潜在商业价值": _business_value(item.category, item.fact),
        "行业影响程度": _industry_impact(item.category, text),
        "信息新鲜度": _freshness(item, today),
    }
    weights = {"政策/监管影响": 0.30, "与本公司业务相关性": 0.30,
               "潜在商业价值": 0.20, "行业影响程度": 0.10, "信息新鲜度": 0.10}
    score = round(sum(value * weights[key] for key, value in scores.items()) * 10, 1)
    reasons = [f"{key} {value:.0f}/10" for key, value in scores.items()]
    return IntelligenceItem(
        **item.model_dump(),
        score=score,
        score_reasons=reasons,
        is_breaking=score >= 90,
    )


def _policy_weight(category: str) -> float:
    return 9.0 if category == "政策监管" else 5.0


def deduplicate(items: list[IntelligenceItem]) -> list[IntelligenceItem]:
    """同一事件只留最优来源；实质更新、来源权威性和最新版本优先。"""
    groups: list[list[IntelligenceItem]] = []
    for item in items:
        group = next((group for group in groups if are_same_event(item, group[0])), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    preferred = [min(group, key=_source_choice_key) for group in groups]
    return sorted(preferred, key=lambda item: item.score, reverse=True)


def _source_choice_key(item: IntelligenceItem) -> tuple[Any, ...]:
    effective = item.updated_at_iso if item.freshness_status == "UPDATED" else item.published_at_iso
    timestamp = effective.timestamp() if effective is not None else 0.0
    return (
        0 if item.freshness_status == "UPDATED" else 1,
        item.source_priority,
        -timestamp,
        -item.score,
    )


def select_top(items: list[IntelligenceItem], *, maximum: int = 5, floor: float = 70.0) -> list[IntelligenceItem]:
    """宁缺毋滥：默认只保留 >=80 分；当日不足时允许 70-79 分补位。"""
    in_scope = [item for item in items if _is_in_scope(item)]
    strong = [item for item in in_scope if item.score >= 80]
    if len(strong) >= 3:
        return strong[:maximum]
    return [item for item in in_scope if item.score >= floor][:maximum]
