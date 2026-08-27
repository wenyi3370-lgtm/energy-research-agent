"""Mission parsing: natural language -> ResearchMission intent.

Primary path is LLM structured output via ModelGateway. A deterministic
keyword fallback exists only as a fail-safe degradation path (it is tagged
``parse_mode=keyword_fallback`` and never claims completion quality).
"""

from __future__ import annotations

import re
from typing import Any

from energy_research_agent.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .models import (
    AgentStrictModel,
    ResearchMode,
)


class CustomGoalSpec(AgentStrictModel):
    """A user-specific research question discovered by semantic parsing (§10)."""

    name: str = ""
    description: str = ""
    subject_name: str = ""
    goal_class_hint: str = "CUSTOM"
    geographies: list[str] = []


class MarketGoalSpec(AgentStrictModel):
    """A market-side research question (§42 always carries geography + object)."""

    name: str = ""
    description: str = ""
    geography: str = ""
    market_object: str = ""
    goal_class_hint: str = "MARKET"


class MissionParseResult(AgentStrictModel):
    mode: ResearchMode
    primary_subject: str = ""
    geographies: list[str] = []
    industries: list[str] = []
    products: list[str] = []
    time_scope: str | None = None
    decision_question: str | None = None
    audience: str | None = None
    custom_goals: list[CustomGoalSpec] = []
    market_goals: list[MarketGoalSpec] = []
    continuation_hint: str | None = None
    parse_mode: str = "llm"
    notes: str = ""


_MARKET_TERMS = (
    "市场", "市场规模", "政策", "电价", "补贴", "认证", "准入", "渠道", "零售",
    "户储", "户用储能", "家用储能", "海外", "欧洲", "德国", "西班牙", "泰国",
    "东南亚", "美国", "英国", "意大利", "澳大利亚", "日本", "巴西", "非洲",
    "TAM", "SAM", "SOM", "经济性", "商业模式", "竞品", "竞争格局", "市场进入",
)
_ENTERPRISE_TERMS = (
    "公司", "企业", "集团", "主营业务", "生产基地", "工厂", "产能", "生产线",
    "财务", "营收", "净利润", "客户", "产品线", "技术", "战略", "股权",
)
_COUNTRY_WORDS = (
    "西班牙", "德国", "泰国", "欧洲", "东南亚", "美国", "英国", "意大利",
    "澳大利亚", "日本", "巴西", "非洲", "中东", "拉美", "印度", "越南",
)
_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:集团|公司|股份|能源|科技|电子|电气|电源|电池|储能))"
)
_LEADING_VERBS = ("调研", "调查", "研究", "了解", "分析", "评估", "查询", "查找")
_TRUNCATE_MARKERS = (
    "有没有", "是否", "针对", "进行", "相关", "怎么样", "以及", "及其", "属于",
)


def _clean_company_name(name: str) -> str:
    """Strip leading action verbs and truncate at semantic question markers."""
    for verb in _LEADING_VERBS:
        if name.startswith(verb):
            name = name[len(verb):]
            break
    for marker in _TRUNCATE_MARKERS:
        index = name.find(marker)
        if index > 0:
            name = name[:index]
            break
    return name.strip()


class MissionParser:
    """Parses a raw request into mission intent. Never drops the original text."""

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        self.gateway = gateway

    def parse(self, raw_request: str) -> MissionParseResult:
        if self.gateway is not None:
            try:
                return self._parse_llm(raw_request)
            except (GatewayError, ValueError):
                # Degraded path; explicit about what it is.
                fallback = self._parse_keywords(raw_request)
                fallback.notes = "LLM structured parse unavailable; keyword fallback used."
                return fallback
        return self._parse_keywords(raw_request)

    def _parse_llm(self, raw_request: str) -> MissionParseResult:
        request = StructuredRequest[MissionParseResult](
            purpose="agent.mission_parse",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是新能源产业研究 Agent 的需求解析器。从用户一句话中完整识别研究意图，"
                        "只输出给定的 JSON 结构，禁止输出任何其他字段，禁止直接开展研究或编造事实。\n"
                        "规则：1) 分隔符（逗号/顿号/分号/换行）不是语义边界，必须做完整语义解析；"
                        "2) 提到企业主体时，mode 为 ENTERPRISE；提到国家/区域+市场对象时 mode 为 MARKET；"
                        "两者都有则 mode=HYBRID；"
                        "3) 用户任何新问题都是合法专项目标（custom_goals），不要归入 OTHER；"
                        "4) 市场目标必须带 geography 与市场对象；"
                        "5) goal_class_hint 取值：CUSTOM/POLICY/COMPETITION/CHANNEL/CUSTOMER/PRODUCT/"
                        "ENGINEERING/ECONOMICS/MARKET/STRATEGY。\n"
                        'JSON 骨架（缺省值照抄）：\n'
                        '{"mode":"ENTERPRISE","primary_subject":"","geographies":[],"industries":[],'
                        '"products":[],"time_scope":null,"decision_question":null,"audience":null,'
                        '"custom_goals":[{"name":"","description":"","subject_name":"","goal_class_hint":"CUSTOM","geographies":[]}],'
                        '"market_goals":[{"name":"","description":"","geography":"","market_object":"","goal_class_hint":"MARKET"}],'
                        '"continuation_hint":null,"parse_mode":"llm","notes":""}'
                    ),
                },
                {"role": "user", "content": raw_request},
            ],
            response_model=MissionParseResult,
        )
        return self.gateway.structured(request)

    def _parse_keywords(self, raw_request: str) -> MissionParseResult:
        text = raw_request.strip()
        has_market = any(term in text for term in _MARKET_TERMS)
        match = _COMPANY_PATTERN.search(text)
        # A suffix match inside a market phrase ("西班牙户用储能市场") is not a
        # company. Exclude matches containing a country word or directly
        # followed by a market term; strong enterprise words always win.
        strong = any(term in text for term in _ENTERPRISE_TERMS)
        matched_name = _clean_company_name(match.group(1)) if match else ""
        market_next = bool(match) and text[match.end():match.end() + 2] in {
            "市场", "政策", "电价", "准入", "认证", "补贴", "渠道", "竞争",
        }
        contains_country = any(word in matched_name for word in _COUNTRY_WORDS)
        has_enterprise = strong or (bool(match) and not market_next and not contains_country)
        if has_market and has_enterprise:
            mode = ResearchMode.HYBRID
        elif has_market:
            mode = ResearchMode.MARKET
        else:
            mode = ResearchMode.ENTERPRISE

        geographies = [word for word in _COUNTRY_WORDS if word in text]
        primary_subject = matched_name if has_enterprise else ""

        custom_goals: list[CustomGoalSpec] = []
        market_goals: list[MarketGoalSpec] = []
        if mode in {ResearchMode.MARKET, ResearchMode.HYBRID}:
            for geo in geographies or [""]:
                market_goals.append(
                    MarketGoalSpec(
                        name=f"{geo or '目标'}市场调研",
                        description=text,
                        geography=geo,
                        market_object=text,
                        goal_class_hint="MARKET",
                    )
                )
        # Keyword fallback cannot reliably separate additive goals; record the
        # request as one open-set custom goal so it is never silently dropped.
        custom_goals.append(
            CustomGoalSpec(
                name="原始专项需求",
                description=text,
                subject_name=primary_subject,
                goal_class_hint="CUSTOM",
                geographies=geographies,
            )
        )
        return MissionParseResult(
            mode=mode,
            primary_subject=primary_subject,
            geographies=geographies,
            custom_goals=custom_goals,
            market_goals=market_goals,
            parse_mode="keyword_fallback",
        )
