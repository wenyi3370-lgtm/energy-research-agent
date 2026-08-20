"""情报评分与去重（用户权重：政策30/相关性30/商业价值20/行业10/新鲜度10）。"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .models import IntelligenceItem, RawIntelligenceItem

# 与"本公司业务"（储能/V2G 设备、系统、电力交易）相关度关键词
_RELEVANCE_KEYWORDS = [
    "V2G", "车网互动", "双向充电", "储能", "电池", "PCS", "EMS", "BMS",
    "虚拟电厂", "聚合", "充换电", "充电桩", "光储充", "峰谷", "现货", "辅助服务",
    "构网型", "液冷", "电芯", "兆瓦", "MWh", "MW", "Wh", "招标", "中标",
]

# 行业影响信号词
_INDUSTRY_SIGNALS = ["规模", "首", "试点", "示范", "标准", "规则", "价格", "降价", "并购", "产能"]


def _freshness(published_at: str, today: date) -> float:
    match = re.search(r"(\d{4})[-年.](\d{1,2})[-月.](\d{1,2})", published_at)
    if not match:
        return 7.0  # 未注明日期，给中间分
    try:
        published = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return 7.0
    days = (today - published).days
    if days <= 1:
        return 10.0
    if days <= 3:
        return 8.0
    if days <= 7:
        return 6.0
    return 3.0


def _relevance(text: str) -> float:
    """业务相关性：领域基准 4 分 + 每个命中关键词 +2（上限 10）。"""
    hits = sum(1 for keyword in _RELEVANCE_KEYWORDS if keyword.lower() in text.lower())
    return min(10.0, 4.0 + hits * 2.0)


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


def score_item(item: RawIntelligenceItem, today: date | None = None) -> IntelligenceItem:
    """按用户权重计算 Strategic Intelligence Score (0-100)。"""
    today = today or date.today()
    text = f"{item.title} {item.fact} {item.entity}"
    scores = {
        "政策/监管影响": _policy_weight(item.category),
        "与本公司业务相关性": _relevance(text),
        "潜在商业价值": _business_value(item.category, item.fact),
        "行业影响程度": _industry_impact(item.category, text),
        "信息新鲜度": _freshness(item.published_at, today),
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
    """同类信息合并：同实体+同类别只保留评分最高者。"""
    seen: dict[tuple[str, str], IntelligenceItem] = {}
    for item in items:
        key = (item.category, (item.entity or item.title)[:12])
        if key not in seen or item.score > seen[key].score:
            seen[key] = item
    return sorted(seen.values(), key=lambda item: item.score, reverse=True)


def select_top(items: list[IntelligenceItem], *, maximum: int = 5, floor: float = 70.0) -> list[IntelligenceItem]:
    """宁缺毋滥：默认只保留 >=80 分；当日不足时允许 70-79 分补位。"""
    strong = [item for item in items if item.score >= 80]
    if len(strong) >= 3:
        return strong[:maximum]
    return [item for item in items if item.score >= floor][:maximum]
