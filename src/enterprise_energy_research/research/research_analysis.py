"""ResearchAnalysisEngine: objective enterprise research analysis.

P0 third-round architecture: this layer answers "what is the enterprise
REALLY like" from the frozen evidence, before any decision synthesis runs:

    Evidence -> PublicationRelevanceFilter -> ResearchAnalysis
        -> DecisionSynthesis -> PublicationNarrative -> Word/HTML

Every statement here is produced by deterministic analytical rules over
real verified claim values (YoY, CAGR, margin, growth-vs-revenue,
region distribution, product-family structure).  When the required data
is absent, the engine writes NOTHING for that question — it never pads
a missing series with template prose.

The output carries two voices:
  * objective research voice (企业经营事实, e.g. "2025 年公司实现营业收入…")
  * consulting analysis voice (e.g. "从合作基础看，… 但具体能源项目仍需…")
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from enterprise_energy_research.analysis.financials import parse_number
from enterprise_energy_research.artifacts.publication_terminology import (
    PublicationNumberFormatter,
    field_label,
)
from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Claim, FrozenResearchBundle, Product
from enterprise_energy_research.research.publication_relevance import (
    PublicationRelevanceFilter,
)

# Metric families the engine understands; unknown fields are ignored.
FLOW_METRICS = {
    "revenue": "营业收入",
    "profit": "归母净利润",
    "net_profit": "归母净利润",
    "rnd_expense": "研发投入",
    "operating_cash_flow": "经营活动现金流",
    "employee_count": "员工人数",
    "capacity": "产能",
    "production_capacity": "产能",
    "battery_production_capacity": "电池产能",
    "storage_capacity": "储能规模",
    "pv_capacity": "光伏装机容量",
    "battery_sales_volume": "动力电池销量",
    "total_assets": "总资产",
    "gross_profit": "毛利润",
}
PP_METRICS = {
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "rnd_expense_ratio": "研发费用率",
    "market_share": "市场份额",
    "renewable_share": "可再生能源占比",
    "green_electricity_usage_ratio": "绿电使用比例",
}
SEGMENT_FIELDS = {
    "battery_revenue": "动力电池业务",
    "storage_revenue": "储能业务",
    "material_revenue": "电池材料及回收业务",
    "energy_business_revenue": "电池矿产资源业务",
    "domestic_revenue": "境内",
    "overseas_revenue": "境外",
    "segment_revenue": "分业务",
}

YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# Storage-unit scale factors: every series point is normalized to the base
# unit (元) so 千元/万元/亿元 claims can never produce a false -100% trend.
UNIT_SCALE = {"元": 1.0, "千元": 1e3, "万元": 1e4, "亿元": 1e8}

# Factory site dedupe: same physical site often appears as
# "福建省宁德市…" vs "福建宁德…" across pages.
PROVINCE_RE = re.compile(r"([\u4e00-\u9fff]{2,10}?(?:省|自治区|特别行政区))")
CITY_RE = re.compile(r"([\u4e00-\u9fff]{2,10}?(?:市|州|地区))")
OVERSEAS_RE = re.compile(r"(德国|匈牙利|印尼|印度尼西亚|泰国|越南|美国|西班牙|墨西哥|日本|韩国|波兰|荷兰|比利时)")


class ResearchMetric(BaseModel):
    """One claim-bound number with full context (the ONLY carrier of facts)."""

    label: str
    field_name: str
    value: float
    value_display: str
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    period_from_text: bool = False


class ResearchTrend(BaseModel):
    trend_id: str
    label: str
    field_name: str
    points: list[ResearchMetric] = Field(default_factory=list)
    span: str = ""
    yoy_pct: float | None = None
    cagr_pct: float | None = None
    statement: str = ""
    consulting_note: str = ""
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)

    @property
    def year_count(self) -> int:
        return len(self.points)


class ResearchComparison(BaseModel):
    comparison_id: str
    label: str
    dimension_label: str = ""
    rows: list[ResearchMetric] = Field(default_factory=list)
    statement: str = ""
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class ResearchInsight(BaseModel):
    insight_id: str
    topic: str
    title: str
    findings: list[str] = Field(default_factory=list)
    consulting_note: str = ""
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class ResearchKpi(BaseModel):
    """A dashboard-ready KPI with metric/value/unit/period/source."""

    label: str
    value: str
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class ResearchAnalysis(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    entity_name: str
    metrics: list[ResearchMetric] = Field(default_factory=list)
    trends: list[ResearchTrend] = Field(default_factory=list)
    comparisons: list[ResearchComparison] = Field(default_factory=list)
    insights: list[ResearchInsight] = Field(default_factory=list)
    kpis: list[ResearchKpi] = Field(default_factory=list)
    key_product_ids: list[str] = Field(default_factory=list)
    region_distribution: dict[str, int] = Field(default_factory=dict)
    overseas_factory_count: int = 0
    domestic_factory_count: int = 0
    own_energy_metrics: list[ResearchMetric] = Field(default_factory=list)
    energy_product_metrics: list[ResearchMetric] = Field(default_factory=list)
    zero_carbon_metrics: list[ResearchMetric] = Field(default_factory=list)
    zero_carbon_goals: list[str] = Field(default_factory=list)
    factory_site_count: int = 0
    filtered_claim_count: int = 0
    junk_claim_count: int = 0

    def trend(self, field_name: str) -> ResearchTrend | None:
        return next((item for item in self.trends if item.field_name == field_name), None)


# Fields whose natural unit is NOT currency (capacity etc.): a wrong "元"
# unit from extraction must never leak into the display.
NON_CURRENCY_FIELDS = {
    "capacity", "production_capacity", "battery_production_capacity",
    "storage_capacity", "pv_capacity", "storage_power", "battery_sales_volume",
}


class ResearchAnalysisEngine:
    """Deterministic objective analysis of one frozen research bundle."""

    def analyze(self, bundle: FrozenResearchBundle) -> ResearchAnalysis:
        entity = self._canonical_entity(bundle)
        if entity is None:
            raise ValueError("Frozen bundle contains no enterprise entity")
        body_claims, report = PublicationRelevanceFilter().filter(bundle)
        analysis = ResearchAnalysis(
            run_id=bundle.run_manifest.run_id,
            entity_name=entity.canonical_name,
            filtered_claim_count=len(body_claims),
            junk_claim_count=len(report.internal),
        )
        by_field: dict[str, list[Claim]] = defaultdict(list)
        for claim in body_claims:
            by_field[claim.field_name].append(claim)

        self._financial_trends(analysis, by_field)
        self._margin_derivations(analysis, by_field)
        self._segment_comparison(analysis, by_field)
        self._product_families(analysis, bundle, by_field)
        self._factory_regions(analysis, bundle)
        self._energy_split(analysis, by_field)
        self._kpis(analysis, bundle, by_field)
        self._insights(analysis, bundle, by_field)
        return analysis

    # ── deterministic derivation ──────────────────────────────────────────
    def _financial_trends(self, analysis: ResearchAnalysis, by_field: dict[str, list[Claim]]) -> None:
        for field_name, label in FLOW_METRICS.items():
            points = self._series(field_name, label, by_field.get(field_name, []))
            if not points:
                continue
            analysis.metrics.extend(points)
            if len(points) < 2:
                continue
            first, last = points[0], points[-1]
            span = f"{first.period}—{last.period}" if first.period and last.period else ""
            yoy = self._pct_delta(first, last)
            cagr = self._cagr(first, last) if len(points) >= 3 else None
            statement = self._trend_statement(label, points, yoy, cagr)
            consulting = self._trend_consulting_note(label, points, yoy, cagr)
            analysis.trends.append(ResearchTrend(
                trend_id=f"TREND-{field_name}", label=label, field_name=field_name,
                points=points, span=span, yoy_pct=yoy, cagr_pct=cagr,
                statement=statement, consulting_note=consulting,
                source_ids=self._uniq(source_id for point in points for source_id in point.source_ids),
                claim_ids=self._uniq(claim_id for point in points for claim_id in point.claim_ids),
            ))

    def _margin_derivations(self, analysis: ResearchAnalysis, by_field: dict[str, list[Claim]]) -> None:
        revenue = {point.period: point for point in self._series("revenue", "营业收入", by_field.get("revenue", []))}
        profit = {point.period: point for point in self._series("profit", "归母净利润", by_field.get("profit", []))}
        shared = sorted(set(revenue) & set(profit))
        if not shared:
            return
        period = shared[-1]
        rev, prof = revenue[period], profit[period]
        if not rev.value:
            return
        margin = round(prof.value / rev.value * 100, 2)
        insight = ResearchInsight(
            insight_id="INS-NET-MARGIN", topic="financial", title="盈利能力",
            findings=[f"{period} 年按公开披露口径计算的净利率约为 {margin}%，"
                      f"即归母净利润 {prof.value_display}{prof.unit or ''} "
                      f"对应营业收入 {rev.value_display}{rev.unit or ''}。"],
            consulting_note="净利率水平反映盈利质量，是判断对方持续投入研发与联合项目能力的重要参考。",
            source_ids=self._uniq([*rev.source_ids, *prof.source_ids]),
            claim_ids=self._uniq([*rev.claim_ids, *prof.claim_ids]),
        )
        analysis.insights.append(insight)
        # profit growth vs revenue growth over the same window
        if len(shared) >= 2 and revenue[shared[0]].value:
            rev_growth = (rev.value / revenue[shared[0]].value - 1) * 100
            prof_growth = (prof.value / profit[shared[0]].value - 1) * 100 if profit[shared[0]].value else None
            if prof_growth is not None and rev_growth is not None:
                verdict = "利润端增速高于收入端，盈利能力持续改善" if prof_growth > rev_growth else "收入端增速高于利润端，需关注成本与费用变化"
                analysis.insights.append(ResearchInsight(
                    insight_id="INS-GROWTH-STRUCTURE", topic="financial", title="收入与利润增速结构",
                    findings=[f"{shared[0]} 至 {period} 年，营业收入累计增长 {rev_growth:+.1f}%，归母净利润累计增长 {prof_growth:+.1f}%，{verdict}。"],
                    source_ids=self._uniq([*rev.source_ids, *prof.source_ids]),
                    claim_ids=self._uniq([*rev.claim_ids, *prof.claim_ids]),
                ))

    def _segment_comparison(self, analysis: ResearchAnalysis, by_field: dict[str, list[Claim]]) -> None:
        rows: list[ResearchMetric] = []
        for field_name, label in SEGMENT_FIELDS.items():
            claims = by_field.get(field_name, [])
            if not claims:
                continue
            best = self._best(claims)
            value = parse_number(best.value)
            if value is None:
                continue
            formatted = PublicationNumberFormatter().format(best.value, best.unit)
            rows.append(ResearchMetric(
                label=label, field_name=field_name, value=value,
                value_display=formatted.display_value,
                unit=formatted.display_unit, period=self._period_of(best),
                scope=best.scope, source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))
        if len(rows) < 2:
            return
        total = sum(row.value for row in rows)
        if total <= 0:
            return
        breakdown = "、".join(f"{row.label} {round(row.value / total * 100, 1)}%" for row in rows)
        top = max(rows, key=lambda row: row.value)
        analysis.comparisons.append(ResearchComparison(
            comparison_id="CMP-SEGMENTS", label="业务收入构成", dimension_label="业务板块",
            rows=rows,
            statement=f"分业务收入构成中，{top.label}占比最高。按公开披露口径，{breakdown}。",
            source_ids=self._uniq(source_id for row in rows for source_id in row.source_ids),
            claim_ids=self._uniq(claim_id for row in rows for claim_id in row.claim_ids),
        ))

    def _product_families(self, analysis: ResearchAnalysis, bundle: FrozenResearchBundle, by_field: dict[str, list[Claim]]) -> None:
        products = [item for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED]
        if not products:
            return
        families: dict[str, list[Product]] = defaultdict(list)
        for product in products:
            families[product.category or "未分类"].append(product)
        parameterized = sum(bool(item.parameters) for item in products)
        rows = [
            ResearchMetric(
                label=family, field_name="product_family", value=float(len(items)), unit="项",
                value_display=str(len(items)),
                source_ids=self._uniq(source_id for item in items for source_id in item.source_ids),
                claim_ids=[],
            )
            for family, items in sorted(families.items(), key=lambda pair: -len(pair[1]))
        ]
        analysis.comparisons.append(ResearchComparison(
            comparison_id="CMP-FAMILIES", label="产品族分布", dimension_label="产品族",
            rows=rows,
            statement=f"已核验产品共 {len(products)} 项、覆盖 {len(families)} 个产品族，其中 {parameterized} 项具有公开参数。"
                      f"产品族重心为{'、'.join(row.label for row in rows[:4])}。",
            source_ids=self._uniq(source_id for row in rows for source_id in row.source_ids),
            claim_ids=self._uniq(claim_id for row in rows for claim_id in row.claim_ids),
        ))
        # Key products: prefer parameterized, then commercial models.
        ranked = sorted(products, key=lambda item: (-len(item.parameters), bool(item.model), item.name))
        analysis.key_product_ids = [item.product_id for item in ranked[:8]]

    def _factory_regions(self, analysis: ResearchAnalysis, bundle: FrozenResearchBundle) -> None:
        if not bundle.factories:
            return
        distribution: Counter[str] = Counter()
        sites: set[str] = set()
        for factory in bundle.factories:
            address = factory.address or ""
            overseas = OVERSEAS_RE.search(address)
            if overseas:
                site_key = f"overseas:{overseas.group(1)}"
                distribution[overseas.group(1)] += 1
                analysis.overseas_factory_count += 1
                sites.add(site_key)
                continue
            match = PROVINCE_RE.search(address)
            city_match = CITY_RE.search(address)
            site_key = f"{match.group(1) if match else ''}|{city_match.group(1) if city_match else address}"
            if match:
                distribution[match.group(1)] += 1
                analysis.domestic_factory_count += 1
                sites.add(site_key)
            else:
                distribution["地区待核验"] += 1
                sites.add(f"unknown:{address}")
        # Site-level counts are the honest metric: page records often repeat
        # the same physical base under near-identical names.
        analysis.factory_site_count = len(sites)
        analysis.region_distribution = dict(distribution.most_common())
        if analysis.region_distribution:
            top_regions = "、".join(f"{region} {count} 处" for region, count in list(analysis.region_distribution.items())[:5])
            analysis.insights.append(ResearchInsight(
                insight_id="INS-REGIONS", topic="manufacturing", title="生产基地地域分布",
                findings=[f"公开资料识别生产基地 {analysis.factory_site_count} 处（按地域去重口径），主要分布为{top_regions}。"
                          + (f"其中海外基地 {analysis.overseas_factory_count} 处，国内基地 {analysis.domestic_factory_count} 处。" if analysis.overseas_factory_count else "")],
                consulting_note="基地分布反映产能组织的区域重心与海外交付能力，可作为合作切入与复制路径的参考。",
            ))

    def _energy_split(self, analysis: ResearchAnalysis, by_field: dict[str, list[Claim]]) -> None:
        own_fields = {
            "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
            "peak_demand", "electricity_cost", "load_curve", "transformer_capacity",
            "roof_area", "carbon_intensity",
        }
        product_fields = {
            "pv_capacity", "storage_capacity", "storage_power", "energy_project",
            "project_name", "carbon_project",
        }
        for field_name in sorted(own_fields):
            claims = by_field.get(field_name, [])
            if not claims:
                continue
            best = self._best(claims)
            value = parse_number(best.value)
            if value is None:
                continue
            formatted = PublicationNumberFormatter().format(best.value, best.unit)
            analysis.own_energy_metrics.append(ResearchMetric(
                label=field_label(field_name), field_name=field_name, value=value,
                value_display=formatted.display_value,
                unit=formatted.display_unit, period=self._period_of(best), scope=best.scope,
                source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))
        for field_name in sorted(product_fields):
            claims = by_field.get(field_name, [])
            if not claims:
                continue
            best = self._best(claims)
            value = parse_number(best.value)
            if value is None:
                continue
            formatted = PublicationNumberFormatter().format(best.value, best.unit)
            analysis.energy_product_metrics.append(ResearchMetric(
                label=field_label(field_name), field_name=field_name, value=value,
                value_display=formatted.display_value,
                unit=formatted.display_unit, period=self._period_of(best), scope=best.scope,
                source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))
        # Zero-carbon facts: numeric metrics and goal statements, kept
        # separate from energy-product capability.
        zero_carbon_labels = {
            "green_electricity_usage_ratio": "绿电使用比例",
            "carbon_reduction": "碳减排量",
            "carbon_intensity": "碳排放强度",
        }
        for field_name in sorted(zero_carbon_labels):
            claims = by_field.get(field_name, [])
            if not claims:
                continue
            best = self._best(claims)
            value = parse_number(best.value)
            if value is None:
                continue
            formatted = PublicationNumberFormatter().format(best.value, best.unit)
            display_value = formatted.display_value
            # Percent values extracted as "26.60%" with unit "%" must not
            # render as "26.60%%".
            if str(display_value).endswith("%") and formatted.display_unit == "%":
                display_value = str(display_value)[:-1]
            analysis.zero_carbon_metrics.append(ResearchMetric(
                label=zero_carbon_labels[field_name], field_name=field_name, value=value,
                value_display=display_value,
                unit=formatted.display_unit, period=self._period_of(best), scope=best.scope,
                source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))
        for claim in by_field.get("carbon_neutrality_goal", []):
            text = str(claim.value).strip()
            if text and text not in analysis.zero_carbon_goals:
                analysis.zero_carbon_goals.append(text)
        if analysis.own_energy_metrics:
            analysis.insights.append(ResearchInsight(
                insight_id="INS-ENERGY-OWN", topic="energy", title="企业自身能源数据",
                findings=["公开披露可识别" + "、".join(item.label for item in analysis.own_energy_metrics) + "等企业自身能源语义数据。"],
            ))
        if analysis.energy_product_metrics:
            analysis.insights.append(ResearchInsight(
                insight_id="INS-ENERGY-CAPABILITY", topic="energy", title="能源产品与项目能力",
                findings=["公司披露" + "、".join(item.label for item in analysis.energy_product_metrics) + "等能源产品/项目能力。"],
                consulting_note="能源产品能力说明企业会做什么，与企业自身的用能规模是两类信息，应分别评估。",
            ))
        if analysis.zero_carbon_metrics or analysis.zero_carbon_goals:
            parts = [
                f"{item.label} {item.value_display}{item.unit or ''}" + (f"（{item.period}）" if item.period else "")
                for item in analysis.zero_carbon_metrics
            ]
            if analysis.zero_carbon_goals:
                parts.append(f"零碳目标：{'；'.join(analysis.zero_carbon_goals)}")
            analysis.insights.append(ResearchInsight(
                insight_id="INS-ZERO-CARBON", topic="energy", title="零碳与绿电",
                findings=["零碳方面，公开披露显示" + "；".join(parts) + "。"],
                consulting_note="绿电与零碳数据是能源合作（绿电采购、零碳工厂、储能配套）的真实事实基础。",
            ))

    def _kpis(self, analysis: ResearchAnalysis, bundle: FrozenResearchBundle, by_field: dict[str, list[Claim]]) -> None:
        kpi_specs = [
            ("revenue", "营业收入"), ("profit", "归母净利润"), ("employee_count", "员工人数"),
            ("rnd_expense", "研发投入"),
        ]
        for field_name, label in kpi_specs:
            claims = by_field.get(field_name, [])
            if not claims:
                continue
            best = self._best(claims)
            value = parse_number(best.value)
            if value is None:
                continue
            formatted = PublicationNumberFormatter().format(best.value, best.unit)
            analysis.kpis.append(ResearchKpi(
                label=label,
                value=formatted.display_value,
                unit=formatted.display_unit, period=self._period_of(best), scope=best.scope,
                source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))
        if bundle.products:
            analysis.kpis.append(ResearchKpi(label="已核验产品族",
                                             value=str(len({item.category or "未分类" for item in bundle.products if item.verification_status == VerificationStatus.VERIFIED})),
                                             unit="个"))
        if bundle.factories:
            analysis.kpis.append(ResearchKpi(label="已核验生产基地", value=str(analysis.factory_site_count or len(bundle.factories)), unit="处"))
        position = by_field.get("market_share") or by_field.get("industry_position")
        if position:
            best = self._best(position)
            analysis.kpis.append(ResearchKpi(
                label="市场地位", value=str(best.value), unit=None, period=self._period_of(best),
                scope=best.scope, source_ids=[best.source_id], claim_ids=[best.claim_id],
            ))

    def _insights(self, analysis: ResearchAnalysis, bundle: FrozenResearchBundle, by_field: dict[str, list[Claim]]) -> None:
        # Core business summary from identity evidence.
        business = []
        for field_name in ("core_business", "business_segment"):
            for claim in by_field.get(field_name, [])[:3]:
                text = str(claim.value).strip()
                if text and text not in business:
                    business.append(text)
        if business:
            analysis.insights.append(ResearchInsight(
                insight_id="INS-BUSINESS", topic="strategy", title="业务结构",
                findings=["公司已形成以" + "、".join(business[:3]) + "为核心的业务结构。"],
                source_ids=self._uniq(claim.source_id for claim in by_field.get("core_business", []) + by_field.get("business_segment", [])),
                claim_ids=self._uniq(claim.claim_id for claim in by_field.get("core_business", []) + by_field.get("business_segment", [])),
            ))
        # R&D insight.
        rnd_trend = analysis.trend("rnd_expense")
        if rnd_trend and rnd_trend.year_count >= 2:
            latest = rnd_trend.points[-1]
            analysis.insights.append(ResearchInsight(
                insight_id="INS-RND", topic="financial", title="研发投入",
                findings=[f"研发投入由 {rnd_trend.points[0].value_display}（{rnd_trend.points[0].period}）"
                          f"增至 {latest.value_display}（{latest.period}），研发投入保持较快增长。" if (rnd_trend.cagr_pct or 0) > 0
                          else f"最近披露的研发投入为 {latest.value_display}（{latest.period}）。"],
                consulting_note="持续研发投入是技术路线跟进与联合开发可行性的重要信号。",
                source_ids=rnd_trend.source_ids, claim_ids=rnd_trend.claim_ids,
            ))

    # ── helpers ────────────────────────────────────────────────────────────
    def _series(self, field_name: str, label: str, claims: list[Claim]) -> list[ResearchMetric]:
        by_period: dict[str, Claim] = {}
        today = date.today()
        for claim in claims:
            value = parse_number(claim.value)
            if value is None:
                continue
            # Annual series use FULL-YEAR claims only: a half-year report
            # (period_end 06-30) must never be averaged into an annual line.
            if claim.period_start and claim.period_end and (
                (claim.period_start.month, claim.period_start.day) != (1, 1)
                or (claim.period_end.month, claim.period_end.day) != (12, 31)
            ):
                continue
            # A full-year period that ends in the future is a mislabeled
            # claim (e.g. an H1 figure stamped as a full year) — never plot it.
            if claim.period_end and claim.period_end > today:
                continue
            period = self._period_of(claim) or self._year_from_text(claim)
            if not period:
                continue
            year = period[:4]
            # Text-derived years in the future are mislabeled claims too;
            # a current-year value without an explicit full-year period can
            # only be an interim figure (H1/Q) — never an annual point.
            if year.isdigit() and int(year) > today.year:
                continue
            if year == str(today.year) and not (claim.period_start and claim.period_end):
                continue
            existing = by_period.get(year)
            if existing is None or claim.confidence > existing.confidence:
                by_period[year] = claim
        points: list[ResearchMetric] = []
        fmt = PublicationNumberFormatter()
        for year in sorted(by_period):
            claim = by_period[year]
            raw_value = parse_number(claim.value)
            assert raw_value is not None
            if field_name in NON_CURRENCY_FIELDS:
                # Capacity/energy-power series keep their raw magnitude; a
                # wrong currency unit from extraction is dropped, not shown.
                unit = claim.unit if (claim.unit or "").strip() not in UNIT_SCALE else None
                value = raw_value
                value_display = fmt.format(raw_value, unit).display_value
            else:
                # Normalize the storage unit (千元/万元/亿元 -> 元) so annual
                # points are comparable across mixed-unit disclosures.
                value = raw_value * UNIT_SCALE.get((claim.unit or "").strip(), 1.0)
                formatted = fmt.format(value, "元")
                value_display = formatted.display_value
                unit = formatted.display_unit
            points.append(ResearchMetric(
                label=label, field_name=field_name, value=value,
                value_display=value_display,
                unit=unit, period=year, scope=claim.scope,
                source_ids=[claim.source_id], claim_ids=[claim.claim_id],
                period_from_text=not (claim.period_start or claim.period_end or claim.as_of_date),
            ))
        return points

    @staticmethod
    def _period_of(claim: Claim) -> str | None:
        if claim.period_start:
            return claim.period_start.strftime("%Y")
        if claim.period_end:
            return claim.period_end.strftime("%Y")
        if claim.as_of_date:
            return claim.as_of_date.strftime("%Y")
        return None

    @staticmethod
    def _year_from_text(claim: Claim) -> str | None:
        """Year mentioned in the source quote (traceable, never invented)."""
        text = f"{claim.raw_text} {claim.context_text}"
        years = YEAR_RE.findall(text)
        return years[-1] if years else None

    @staticmethod
    def _best(claims: list[Claim]) -> Claim:
        return max(claims, key=lambda item: item.confidence)

    @staticmethod
    def _uniq(values: Any) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if value))

    @staticmethod
    def _pct_delta(first: ResearchMetric, last: ResearchMetric) -> float | None:
        if not first.value:
            return None
        return round((last.value - first.value) / first.value * 100, 1)

    @staticmethod
    def _cagr(first: ResearchMetric, last: ResearchMetric) -> float | None:
        try:
            years = int(last.period or "") - int(first.period or "")
        except (TypeError, ValueError):
            return None
        if years <= 0 or not first.value or first.value <= 0 or last.value <= 0:
            return None
        return round(((last.value / first.value) ** (1 / years) - 1) * 100, 1)

    @staticmethod
    def _trend_statement(label: str, points: list[ResearchMetric], yoy: float | None, cagr: float | None) -> str:
        first, last = points[0], points[-1]
        span = f"{first.period}—{last.period} 年" if first.period and last.period else "最近可比年度"
        growth = f"，{span}复合增速 {cagr:+.1f}%" if cagr is not None else ""
        if len(points) >= 3:
            delta_text = f"，累计增长 {yoy:+.1f}%" if yoy is not None else ""
        else:
            delta_text = f"，较上期 {yoy:+.1f}%" if yoy is not None else ""
        return (
            f"{span}{label}由 {first.value_display}{first.unit or ''} 增至 {last.value_display}{last.unit or ''}"
            f"{growth}{delta_text}。"
        )

    @staticmethod
    def _trend_consulting_note(label: str, points: list[ResearchMetric], yoy: float | None, cagr: float | None) -> str:
        last = points[-1]
        if label in {"营业收入", "归母净利润"} and (yoy or 0) > 0:
            return f"从合作基础看，{label}保持增长说明公司具备跨业务线推进联合项目的资源基础；但具体能源项目仍需结合目标基地条件单独测算。"
        return f"{label}的最新公开披露为 {last.value_display}{last.unit or ''}（{last.period or '最新披露期'}）。"

    @staticmethod
    def _canonical_entity(bundle: FrozenResearchBundle):
        return next(
            (item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id),
            bundle.entities[0] if bundle.entities else None,
        )
