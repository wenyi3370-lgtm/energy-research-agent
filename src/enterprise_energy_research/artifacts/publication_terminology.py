"""Publication-language boundary for internal schemas and management output."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel


FIELD_LABELS: dict[str, str] = {
    "field": "项目", "value": "信息", "name": "名称", "brand": "品牌",
    "model": "型号", "category": "产品族", "series": "系列",
    "description": "业务说明", "parameters": "核心参数",
    "address": "地区", "processes": "主要工艺", "status": "运营状态",
    "relation": "关系类型", "from": "主体", "to": "关联方",
    "opportunity": "合作方向", "solution": "价值主张", "priority": "优先级",
    "next_step": "下一步行动", "strategic_rationale": "战略理由",
    "target_scenario": "切入场景", "our_value_proposition": "我方价值",
    "key_prerequisites": "关键前提", "go_no_go_gate": "Go / No-Go Gate",
    "electricity_consumption": "年度用电量",
    "energy_consumption": "综合能源消费量",
    "transformer_capacity": "配电变压器容量",
    "load_curve": "典型日/全年负荷曲线",
    "roof_area": "可利用屋面面积",
    "operating_schedule": "生产班次与运行时段",
    "subsidiaries": "核心经营主体与股权关系",
    "revenue": "营业收入及分业务收入",
    "profit": "归母净利润",
    "gross_margin": "毛利率",
    "rnd_expense": "研发投入",
    "rnd_expense_ratio": "研发费用率",
    "product_parameters": "核心产品技术参数",
    "production_capacity": "生产能力",
    "factory_capacity": "工厂产能",
    "battery_production_capacity": "电池制造产能",
    "product_catalog_scope": "产品目录覆盖范围",
    "catalog_items": "目录中的产品",
    "enumerated": "是否完成逐项列举",
    "official_product_centers": "官方产品中心",
    "product_family": "产品族",
    "product_name": "产品名称",
    "parameter_name": "技术参数项目",
    "process": "主要工艺",
    "factory_name": "生产基地",
    "factory_address": "基地地区",
    "production_lines": "生产线",
    "output": "产量",
    "annual_output": "年度产量",
    "core_business": "核心业务",
    "business_segment": "业务板块",
    "business_segments": "业务板块",
    "industry_position": "行业位置",
    "canonical_company_name": "企业名称",
    "registered_name": "注册名称",
    "registration_region": "注册地区",
    "official_website": "官方网站",
    "aliases": "企业别名",
    "risk": "关键风险",
}

REASON_LABELS: dict[str, str] = {
    "requires_site_due_diligence": "公开资料无法直接核验，需通过现场尽调获取",
    "SEARCH_FAILED": "本轮公开信息检索未取得可独立核验的信息",
    "NORMALIZED_NOT_VERIFIED": "已完成结构化整理，但仍缺少独立来源核验",
    "missing": "当前公开资料未披露",
    "conflicting": "不同来源的口径或数值存在冲突",
    "stale": "现有公开资料已过有效期",
    "unverifiable": "现有资料无法独立核验",
    "NOT_SEARCHED": "本轮尚未进入该项公开信息检索",
    "SEARCHED_NOT_FOUND": "已完成公开检索但未发现可核验披露",
    "PUBLIC_EVIDENCE_GAP": "公开资料不足以支持可靠判断",
}

SOURCE_TYPE_LABELS: dict[str, str] = {
    "SOURCE_A": "一级来源（企业官网、年报、政府或监管机构）",
    "SOURCE_B": "二级来源（权威行业机构或专业数据库）",
    "SOURCE_C": "三级来源（主流媒体或行业媒体）",
    "SOURCE_D": "辅助来源（其他公开资料）",
}

TABLE_HEADER_LABELS = FIELD_LABELS


def field_label(value: str) -> str:
    return FIELD_LABELS.get(value, "其他公开披露事项")


def reason_label(value: str) -> str:
    return REASON_LABELS.get(value, "需进一步获取资料并完成独立核验")


def source_type_label(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else str(value)
    return SOURCE_TYPE_LABELS.get(raw, "其他公开来源")


def translate_table_row(row: dict[str, Any]) -> dict[str, Any]:
    """Translate schema headers before renderers see a table."""
    return {FIELD_LABELS.get(str(key), field_label(str(key))): value for key, value in row.items()}


@dataclass(frozen=True)
class PublicationNumber:
    raw_value: Any
    display_value: str
    display_unit: str


class PublicationNumberFormatter:
    """Convert storage-scale raw values into executive-readable business units."""

    CURRENCY_UNITS = {
        "元": ((Decimal("100000000"), "亿元"), (Decimal("10000"), "万元")),
        "CNY": ((Decimal("100000000"), "亿元"), (Decimal("10000"), "万元")),
        "人民币": ((Decimal("100000000"), "亿元"), (Decimal("10000"), "万元")),
    }

    def format(self, value: Any, unit: str | None = None, *, decimals: int = 2) -> PublicationNumber:
        raw_unit = (unit or "").strip()
        if isinstance(value, (dict, list, tuple, set, bool)):
            return PublicationNumber(value, self._format_composite(value), raw_unit)
        try:
            number = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError):
            return PublicationNumber(value, self._format_composite(value), raw_unit)
        for divisor, display_unit in self.CURRENCY_UNITS.get(raw_unit, ()):
            if abs(number) >= divisor:
                return PublicationNumber(value, f"{number / divisor:,.{decimals}f}", display_unit)
        if abs(number) >= Decimal("100000000") and raw_unit in {"", "人次", "件"}:
            return PublicationNumber(value, f"{number / Decimal('100000000'):,.{decimals}f}", "亿" + raw_unit)
        if abs(number) >= Decimal("10000") and raw_unit in {"", "人", "台", "件"}:
            return PublicationNumber(value, f"{number / Decimal('10000'):,.{decimals}f}", "万" + raw_unit)
        if number == number.to_integral():
            display = f"{number:,.0f}"
        else:
            display = f"{number:,.{decimals}f}".rstrip("0").rstrip(".")
        return PublicationNumber(value, display, raw_unit)

    def _format_composite(self, value: Any) -> str:
        """Render structured evidence as business prose, never Python/JSON."""
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, dict):
            parts: list[str] = []
            for key, item in value.items():
                label = field_label(str(key))
                if isinstance(item, (list, tuple, set)) and item and all(self._is_url(entry) for entry in item):
                    rendered = f"已核验 {len(item)} 个公开页面"
                else:
                    rendered = self._format_composite(item)
                parts.append(f"{label}为{rendered}")
            return "；".join(parts) if parts else "未披露具体内容"
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            if not items:
                return "未披露具体内容"
            if all(self._is_url(item) for item in items):
                return f"已核验 {len(items)} 个公开页面"
            return "、".join(self._format_composite(item) for item in items[:8])
        if self._is_url(value):
            return "已核验公开页面"
        return str(value)

    @staticmethod
    def _is_url(value: Any) -> bool:
        return isinstance(value, str) and value.strip().casefold().startswith(("http://", "https://"))


class PublicationKPI(BaseModel):
    """A number prepared for publication without losing its stored value."""

    metric: str
    period: str
    raw_value: Any
    display_value: str
    display_unit: str
    context: str


def publication_kpi(
    metric: str, period: str, value: Any, unit: str | None, context: str,
) -> PublicationKPI:
    formatted = PublicationNumberFormatter().format(value, unit)
    return PublicationKPI(
        metric=metric, period=period, raw_value=formatted.raw_value,
        display_value=formatted.display_value, display_unit=formatted.display_unit,
        context=context,
    )
