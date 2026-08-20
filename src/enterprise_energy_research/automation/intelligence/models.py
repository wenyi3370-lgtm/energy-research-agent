"""每日战略情报：V2G & 储能董事长日报（models）。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

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
    source_name: str = ""
    source_url: str = ""
    published_at: str = ""  # 原始发布时间 YYYY-MM-DD 或原文
    numbers: list[str] = Field(default_factory=list)  # 提取到的关键数字/单位
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
    updated_at: datetime = Field(default_factory=datetime.now)
    breaking_count: int = Field(default=0, ge=0)

    def render_text(self) -> str:
        """按用户固定格式渲染为飞书正文（无 markdown，使用 emoji/分隔符排版）。"""
        lines: list[str] = []
        lines.append(f"# V2G & 储能每日情报｜{self.brief_date:%Y.%m.%d}")
        lines.append("")
        lines.append("【今日判断】")
        lines.append(self.judgment or "今日暂无明显改变行业格局的重大事件，值得持续关注以下条目。")
        lines.append("")
        for index, item in enumerate(self.items, start=1):
            marker = "🟥" if item.is_breaking else "🟦"
            lines.append(f"{marker} {index}【{item.category}｜{item.display_score()}】{item.title}")
            lines.append(f"事实：{item.fact}")
            if item.insight:
                lines.append(f"判断：{item.insight}")
            if item.impact_company:
                lines.append(f"对公司：{item.impact_company}")
            if item.source_url:
                lines.append(f"查看原文：{item.source_url}")
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
