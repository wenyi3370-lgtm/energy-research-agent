"""VisualOpportunityPlanner: research dataset -> visual proposals.

P0 third round: figures are planned from the Structured Research Dataset
(the ResearchAnalysis layer), not improvised at the last moment of the
narrative.  The planner only PROPOSES — the Visual Router still owns the
final visual-type decision with its anti-chart-abuse rules.  Every
proposal answers one real research question ("营业收入变化如何？",
"收入结构是否发生变化？", "生产基地集中在哪些地区？").

No data -> no proposal: callers receive an empty list and the QA layer
records ``missing_visual_data`` instead of drawing a fake chart.
"""

from __future__ import annotations

from typing import Any

from energy_research_agent.analysis.financials import parse_number
from energy_research_agent.domain.enums import VerificationStatus
from energy_research_agent.domain.models import FrozenResearchBundle
from energy_research_agent.research.research_analysis import ResearchAnalysis, ResearchMetric

from .visual_router import VisualDatum, VisualProposal, VisualStage


# Administrative centroids are a transparent fallback when an official source
# names a region but does not disclose exact site coordinates.  They are used
# only for distribution maps and are explicitly labelled as approximate.
REGION_CENTROIDS: tuple[tuple[tuple[str, ...], float, float], ...] = (
    (("福建", "宁德"), 119.30, 26.08), (("广东", "肇庆", "佛山"), 113.27, 23.13),
    (("江苏", "溧阳"), 119.48, 31.42), (("上海",), 121.47, 31.23),
    (("四川", "宜宾"), 104.07, 30.67), (("湖北", "宜昌"), 111.29, 30.69),
    (("江西", "宜春"), 115.86, 28.68), (("贵州", "贵阳"), 106.63, 26.65),
    (("河南", "洛阳"), 112.45, 34.62), (("山东",), 117.00, 36.65),
    (("青海", "西宁"), 101.78, 36.62), (("德国", "图林根", "erfurt"), 11.03, 50.98),
    (("匈牙利", "德布勒森", "debrecen"), 21.63, 47.53),
    (("印度尼西亚", "印尼", "indonesia"), 106.85, -6.21),
    (("西班牙", "zaragoza"), -0.89, 41.65), (("美国", "usa"), -98.58, 39.83),
)


class VisualOpportunityPlanner:
    """Detect visualizable patterns in one ResearchAnalysis."""

    def __init__(self, bundle: FrozenResearchBundle, analysis: ResearchAnalysis) -> None:
        self.bundle = bundle
        self.analysis = analysis
        self._source_note_cache: dict[tuple[str, ...], str] = {}

    def _note(self, source_ids: list[str]) -> str:
        key = tuple(source_ids[:6])
        if key not in self._source_note_cache:
            names = {
                source.source_id: source.source_title or source.source_domain
                for source in self.bundle.sources
            }
            cited = [names[source_id] for source_id in source_ids if source_id in names]
            self._source_note_cache[key] = "数据来源：" + "、".join(cited[:5]) if cited else ""
        return self._source_note_cache[key]

    @staticmethod
    def _chart_value(value: float, unit: str | None) -> float:
        """Scale a raw stored value to its display magnitude (亿元/万元)."""
        if unit == "亿元":
            return round(value / 1e8, 2)
        if unit == "万元":
            return round(value / 1e4, 2)
        return value

    @staticmethod
    def _factory_point(factory: Any) -> tuple[float, float, str] | None:
        if factory.longitude is not None and factory.latitude is not None:
            return float(factory.longitude), float(factory.latitude), "official_coordinates"
        haystack = f"{factory.name or ''} {factory.address or ''}".lower()
        for keywords, longitude, latitude in REGION_CENTROIDS:
            if any(keyword.lower() in haystack for keyword in keywords):
                return longitude, latitude, "administrative_centroid"
        return None

    def _trend_proposal(self, chapter_id: str, index: int, title: str, thesis: str, points: list[ResearchMetric]) -> VisualProposal | None:
        if len(points) < 2:
            return None
        scaled_unit = points[-1].unit
        return VisualProposal(
            visual_id=f"v-{chapter_id}-{index:02d}", chapter_id=chapter_id,
            decision_question=f"{title}如何变化？", business_thesis=thesis,
            semantic_pattern="time_series", semantic_domain="financial",
            title=title,
            subtitle="、".join(f"{point.period}：{point.value_display}{point.unit or ''}" for point in points),
            data_binding=f"research:{points[0].field_name}",
            source_ids=list(dict.fromkeys(source_id for point in points for source_id in point.source_ids)),
            source_claim_ids=list(dict.fromkeys(claim_id for point in points for claim_id in point.claim_ids)),
            unit=scaled_unit, period=f"{points[0].period}—{points[-1].period}",
            transformation=(
                "直接映射冻结证据，未插值、未预测；图表数值按亿元折算显示，原始值保留于来源。"
                if scaled_unit == "亿元" else "直接映射冻结证据，未插值、未预测。"
            ),
            items=[
                VisualDatum(
                    label=f"{point.period}年",
                    value=self._chart_value(point.value, point.unit),
                    unit=point.unit, period=point.period,
                )
                for point in points
            ],
            source_note=self._note(list(dict.fromkeys(source_id for point in points for source_id in point.source_ids))),
            confidence="high",
        )

    def financial_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        trends = {trend.field_name: trend for trend in self.analysis.trends}

        # Revenue + profit answer one executive question and therefore share a
        # genuine two-axis figure when at least three common periods exist.
        revenue = trends.get("revenue")
        profit = trends.get("net_profit") or trends.get("profit")
        if revenue is not None and profit is not None:
            rev_by_period = {point.period: point for point in revenue.points}
            profit_by_period = {point.period: point for point in profit.points}
            periods = sorted(set(rev_by_period) & set(profit_by_period))
            if len(periods) >= 3:
                selected = [rev_by_period[p] for p in periods] + [profit_by_period[p] for p in periods]
                proposals.append(VisualProposal(
                    visual_id="v-operations-revenue-profit", chapter_id="operations",
                    decision_question="收入规模与盈利能力是否同步变化？",
                    business_thesis=f"营业收入与净利润形成 {len(periods)} 个共同年度的可比序列。",
                    semantic_pattern="dual_metric_time_series", semantic_domain="financial",
                    title="营业收入与净利润变化", data_binding="research:revenue+net_profit",
                    source_ids=list(dict.fromkeys(s for point in selected for s in point.source_ids)),
                    source_claim_ids=list(dict.fromkeys(c for point in selected for c in point.claim_ids)),
                    period=f"{periods[0]}—{periods[-1]}",
                    transformation="两组数值均直接映射冻结证据；按各自披露单位显示，未插值、未预测。",
                    items=[VisualDatum(label=f"{p}年", value=self._chart_value(rev_by_period[p].value, rev_by_period[p].unit), unit=rev_by_period[p].unit, period=p, series="营业收入") for p in periods]
                    + [VisualDatum(label=f"{p}年", value=self._chart_value(profit_by_period[p].value, profit_by_period[p].unit), unit=profit_by_period[p].unit, period=p, series="净利润") for p in periods],
                    source_note=self._note(list(dict.fromkeys(s for point in selected for s in point.source_ids))),
                    confidence="high",
                ))

        # A dashboard chapter exposes at most three visuals. Prefer the fields
        # explicitly required by the publication contract.
        for field_name in ("gross_margin", "rnd_expense", "operating_cash_flow"):
            if len(proposals) >= 3:
                break
            trend = trends.get(field_name)
            if trend is None or len(trend.points) < 3:
                continue
            proposal = self._trend_proposal(
                "operations", len(proposals) + 1, f"{trend.label}趋势",
                f"{trend.label}形成 {len(trend.points)} 个真实年度的可比序列。", trend.points,
            )
            if proposal is not None:
                proposals.append(proposal)

        if len(proposals) < 3 and sum(item.semantic_pattern == "time_series" for item in proposals) < 2:
            fallback_trend = revenue or profit
            if fallback_trend is not None and len(fallback_trend.points) >= 3:
                proposal = self._trend_proposal(
                    "operations", len(proposals) + 1, f"{fallback_trend.label}趋势",
                    f"{fallback_trend.label}形成 {len(fallback_trend.points)} 个真实年度的可比序列。",
                    fallback_trend.points,
                )
                if proposal is not None:
                    proposals.append(proposal)

        # Segment structure is retained only when the trend set leaves room.
        comparison = next((item for item in self.analysis.comparisons if item.comparison_id == "CMP-SEGMENTS"), None)
        if len(proposals) < 3 and comparison is not None and len(comparison.rows) >= 2:
            proposals.append(VisualProposal(
                visual_id="v-operations-segments", chapter_id="operations",
                decision_question="收入结构是否发生变化？", business_thesis=comparison.statement,
                semantic_pattern="category_comparison", semantic_domain="financial",
                title="分业务收入构成",
                data_binding="research:segments",
                source_ids=comparison.source_ids, source_claim_ids=comparison.claim_ids,
                unit=comparison.rows[0].unit, period=comparison.rows[0].period,
                transformation="直接映射冻结证据；图表数值按亿元折算显示，原始值保留于来源。",
                items=[VisualDatum(
                    label=row.label,
                    value=self._chart_value(row.value, row.unit),
                    unit=row.unit, period=row.period,
                ) for row in comparison.rows],
                source_note=self._note(comparison.source_ids),
            ))
        return proposals[:3]

    def product_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        comparison = next((item for item in self.analysis.comparisons if item.comparison_id == "CMP-FAMILIES"), None)
        if comparison is not None and len(comparison.rows) >= 2:
            proposals.append(VisualProposal(
                visual_id="v-products-families", chapter_id="products",
                decision_question="产品组合的重心在哪几个产品族？", business_thesis=comparison.statement,
                semantic_pattern="part_to_whole", semantic_domain="product",
                title="产品族分布",
                data_binding="research:product_families",
                source_ids=comparison.source_ids, source_claim_ids=comparison.claim_ids,
                items=[VisualDatum(label=row.label, value=row.value, weight=row.value, unit="项") for row in comparison.rows],
                source_note=self._note(comparison.source_ids),
            ))
        # Key-product parameter matrix -> structured table (mixed units: never
        # a fake bar/radar).
        products = [
            product for product in self.bundle.products
            if product.product_id in self.analysis.key_product_ids
            and product.parameters
        ]
        if len(products) >= 2:
            parameter_names: list[str] = []
            for product in products:
                for parameter in product.parameters:
                    if parameter.name not in parameter_names:
                        parameter_names.append(parameter.name)
            if len(parameter_names) >= 2:
                items = []
                for product in products:
                    values = {parameter.name: parameter for parameter in product.parameters}
                    for name in parameter_names[:8]:
                        parameter = values.get(name)
                        if parameter is None:
                            continue
                        items.append(VisualDatum(
                            label=f"{product.name}｜{name}",
                            value=str(parameter.value or ""),
                            unit=parameter.unit, series=product.name, note=name,
                        ))
                if items:
                    proposals.append(VisualProposal(
                        visual_id="v-products-params", chapter_id="products",
                        decision_question="主要产品路线有什么差异？", business_thesis="重点产品参数矩阵（真实披露参数，未作评分）。",
                        semantic_pattern="none", semantic_domain="product",
                        title="重点产品参数对比",
                        data_binding="research:product_parameters",
                        source_ids=list(dict.fromkeys(source_id for product in products for source_id in product.source_ids)),
                        source_claim_ids=[],
                        items=items,
                        source_note=self._note(list(dict.fromkeys(source_id for product in products for source_id in product.source_ids))),
                    ))

        # Product × application matrix: binary cells reflect disclosed
        # applications, not invented scores. It complements the parameter table.
        scenario_products = [
            product for product in self.bundle.products
            if product.product_id in self.analysis.key_product_ids and product.applications
        ][:8]
        applications: list[str] = []
        for product in scenario_products:
            for application in product.applications:
                if application not in applications:
                    applications.append(application)
        applications = applications[:8]
        if len(scenario_products) >= 2 and len(applications) >= 2:
            items = [
                VisualDatum(label=f"{product.name}｜{application}", x=app_index, y=product_index, value=1 if application in product.applications else 0)
                for product_index, product in enumerate(scenario_products)
                for app_index, application in enumerate(applications)
            ]
            proposals.append(VisualProposal(
                visual_id="v-products-scenarios", chapter_id="products",
                decision_question="重点产品分别覆盖哪些应用场景？",
                business_thesis="产品—应用场景矩阵仅标记官网或正式材料已披露的适用关系。",
                semantic_pattern="matrix_heatmap", semantic_domain="product",
                title="重点产品—应用场景矩阵", data_binding="research:product_applications",
                source_ids=list(dict.fromkeys(source_id for product in scenario_products for source_id in product.source_ids)),
                source_claim_ids=[], transformation="披露适用关系记为 1，未披露记为 0；不把空白解释为不适用。",
                items=items,
                axes={
                    "x_labels": {index: value for index, value in enumerate(applications)},
                    "y_labels": {index: product.name for index, product in enumerate(scenario_products)},
                },
                source_note=self._note(list(dict.fromkeys(source_id for product in scenario_products for source_id in product.source_ids))),
            ))
        return proposals[:3]

    def factory_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        claim_sources = {claim.claim_id: claim.source_id for claim in self.bundle.claims}
        mapped = []
        approximate = False
        for factory in self.bundle.factories:
            point = self._factory_point(factory)
            if point is None:
                continue
            longitude, latitude, method = point
            approximate = approximate or method == "administrative_centroid"
            mapped.append((factory, longitude, latitude))
        if mapped:
            source_ids = list(dict.fromkeys(
                claim_sources[claim_id]
                for factory, _, _ in mapped
                for claim_id in factory.supporting_claim_ids
                if claim_id in claim_sources
            ))
            if not source_ids:
                source_ids = [source.source_id for source in self.bundle.sources[:5]]
            proposals.append(VisualProposal(
                visual_id="v-factories-map", chapter_id="factories",
                decision_question="核心生产基地在全球如何布局？",
                business_thesis=f"已定位 {len(mapped)} 处公开披露基地，呈现国内集群与海外节点。",
                semantic_pattern="spatial_distribution", semantic_domain="manufacturing",
                title="全球生产基地布局", data_binding="research:factory_locations",
                source_ids=source_ids,
                source_claim_ids=list(dict.fromkeys(claim_id for factory, _, _ in mapped for claim_id in factory.supporting_claim_ids)),
                transformation=("精确坐标优先；未披露坐标的基地按公开地址所属行政区中心定位，不表示厂址边界。" if approximate else "使用公开披露坐标直接定位。"),
                items=[VisualDatum(label=factory.name or factory.address or factory.factory_id, x=longitude, y=latitude, value=1, weight=1, note=factory.address) for factory, longitude, latitude in mapped],
                source_note=self._note(source_ids) or "数据来源：公开披露基地地址（详见附录基地清单）。",
            ))
        distribution = self.analysis.region_distribution
        if len(distribution) >= 2:
            proposals.append(VisualProposal(
                visual_id="v-factories-regions", chapter_id="factories",
                decision_question="生产基地集中在哪些地区？", business_thesis="生产基地地域分布（按公开地址归类）。",
                semantic_pattern="category_comparison", semantic_domain="manufacturing",
                title="生产基地地域分布",
                data_binding="research:factory_regions",
                source_ids=[], source_claim_ids=[],
                items=[VisualDatum(label=region, value=count, unit="处") for region, count in distribution.items()],
                source_note="数据来源：公开披露基地地址（详见附录基地清单）。",
            ))
        # Domestic / overseas split -> part_to_whole treemap (real counts).
        classified_count = self.analysis.domestic_factory_count + self.analysis.overseas_factory_count
        if self.analysis.overseas_factory_count > 0 and classified_count == self.analysis.factory_site_count:
            proposals.append(VisualProposal(
                visual_id="v-factories-domestic-overseas", chapter_id="factories",
                decision_question="国内外基地如何分布？", business_thesis="国内与海外基地数量构成。",
                semantic_pattern="part_to_whole", semantic_domain="manufacturing",
                title="国内/海外基地构成",
                data_binding="research:factory_domestic_overseas",
                source_ids=[], source_claim_ids=[],
                items=[
                    VisualDatum(label="国内基地", weight=self.analysis.domestic_factory_count, value=self.analysis.domestic_factory_count, unit="处"),
                    VisualDatum(label="海外基地", weight=self.analysis.overseas_factory_count, value=self.analysis.overseas_factory_count, unit="处"),
                ],
                source_note="数据来源：公开披露基地地址（详见附录基地清单）。",
            ))
        # Capacity time series (real periods only).
        capacity_trend = self.analysis.trend("capacity")
        if capacity_trend is not None and len(capacity_trend.points) >= 2:
            proposal = self._trend_proposal(
                "factories", 1, "产能变化",
                f"已披露 {len(capacity_trend.points)} 个年度的产能数据。",
                capacity_trend.points,
            )
            if proposal is not None:
                proposal = proposal.model_copy(update={"semantic_domain": "manufacturing", "decision_question": "产能如何变化？"})
                proposals.append(proposal)
        return proposals[:3]

    def energy_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        own = self.analysis.own_energy_metrics
        if own:
            proposals.append(VisualProposal(
                visual_id="v-energy-own-kpis", chapter_id="energy_profile",
                decision_question="企业自身能源数据有多少？", business_thesis="企业自身能源语义数据（与产品能力分开）。",
                semantic_pattern="quantitative_facts", semantic_domain="energy",
                title="企业自身能源数据",
                data_binding="research:own_energy",
                source_ids=list(dict.fromkeys(source_id for item in own for source_id in item.source_ids)),
                source_claim_ids=list(dict.fromkeys(claim_id for item in own for claim_id in item.claim_ids)),
                items=[VisualDatum(label=item.label, value=item.value, unit=item.unit, period=item.period, note=item.scope) for item in own],
                source_note=self._note(list(dict.fromkeys(source_id for item in own for source_id in item.source_ids))),
            ))
        capability = self.analysis.energy_product_metrics
        if capability:
            proposals.append(VisualProposal(
                visual_id="v-energy-capability", chapter_id="energy_profile",
                decision_question="企业有哪些能源产品与项目能力？", business_thesis="能源产品/项目能力盘点。",
                semantic_pattern="quantitative_facts", semantic_domain="strategy",
                title="能源产品与项目能力",
                data_binding="research:energy_capability",
                source_ids=list(dict.fromkeys(source_id for item in capability for source_id in item.source_ids)),
                source_claim_ids=list(dict.fromkeys(claim_id for item in capability for claim_id in item.claim_ids)),
                items=[VisualDatum(label=item.label, value=item.value, unit=item.unit, period=item.period, note=item.scope) for item in capability],
                source_note=self._note(list(dict.fromkeys(source_id for item in capability for source_id in item.source_ids))),
            ))
        return proposals

    @staticmethod
    def opportunity_proposal(opportunities: list[Any]) -> VisualProposal | None:
        """Priority comparison TABLE (rule-derived scores never fake a radar)."""
        if not opportunities:
            return None
        items = [
            VisualDatum(
                label=f"{item.opportunity_name}（{item.priority}）",
                value=item.priority, note=item.target_scenario,
            )
            for item in opportunities
        ]
        return VisualProposal(
            visual_id="v-opportunities-priority", chapter_id="opportunities",
            decision_question="哪些合作机会最值得推进？", business_thesis="合作机会优先级比较（评分来自规则判断，仅用于排序）。",
            semantic_pattern="none", semantic_domain="strategy",
            title="合作机会优先级比较",
            data_binding="research:opportunity_priority",
            source_ids=list(dict.fromkeys(source_id for item in opportunities for source_id in item.supporting_source_ids)),
            source_claim_ids=list(dict.fromkeys(claim_id for item in opportunities for claim_id in item.supporting_claim_ids)),
            items=items,
            source_note="优先级依据：战略匹配、实施可行性、证据强度与商业潜力（规则评分）。",
        )

    @staticmethod
    def action_proposal(opportunities: list[Any]) -> VisualProposal | None:
        """30/60/90-day Gantt from the opportunity action plan."""
        if not opportunities:
            return None
        top = opportunities[0]
        stages = [
            VisualStage(id="s30", label=f"0—30 天：{top.first_30_day_action}", start="D0", end="D30", kind="backend"),
            VisualStage(id="s60", label=f"31—60 天：{top.day_60_action}", start="D31", end="D60", kind="backend"),
            VisualStage(id="s90", label=f"61—90 天：{top.day_90_milestone}", start="D61", end="D90", kind="backend"),
        ]
        return VisualProposal(
            visual_id="v-action-timeline", chapter_id="action_plan",
            decision_question="未来 90 天应完成什么？", business_thesis="90 天行动以一处场景的书面决策为终点。",
            semantic_pattern="implementation_roadmap", semantic_domain="strategy",
            title="90 天行动路线",
            data_binding="research:action_plan",
            source_ids=list(top.supporting_source_ids), source_claim_ids=list(top.supporting_claim_ids),
            stages=stages,
            source_note="行动安排基于公开事实与规则判断，须由双方书面确认后执行。",
        )
