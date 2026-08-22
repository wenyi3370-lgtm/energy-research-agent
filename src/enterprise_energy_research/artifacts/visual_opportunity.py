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

from enterprise_energy_research.analysis.financials import parse_number
from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import FrozenResearchBundle
from enterprise_energy_research.research.research_analysis import ResearchAnalysis, ResearchMetric

from .visual_router import VisualDatum, VisualProposal, VisualStage


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

    def _trend_proposal(self, chapter_id: str, index: int, title: str, thesis: str, points: list[ResearchMetric]) -> VisualProposal | None:
        if len(points) < 2:
            return None
        return VisualProposal(
            visual_id=f"v-{chapter_id}-{index:02d}", chapter_id=chapter_id,
            decision_question=f"{title}如何变化？", business_thesis=thesis,
            semantic_pattern="time_series", semantic_domain="financial",
            title=title,
            subtitle="、".join(f"{point.period}：{point.value_display}{point.unit or ''}" for point in points),
            data_binding=f"research:{points[0].field_name}",
            source_ids=list(dict.fromkeys(source_id for point in points for source_id in point.source_ids)),
            source_claim_ids=list(dict.fromkeys(claim_id for point in points for claim_id in point.claim_ids)),
            unit=points[-1].unit, period=f"{points[0].period}—{points[-1].period}",
            transformation="直接映射冻结证据，未插值、未预测。",
            items=[
                VisualDatum(label=f"{point.period}年", value=point.value, unit=point.unit, period=point.period)
                for point in points
            ],
            source_note=self._note(list(dict.fromkeys(source_id for point in points for source_id in point.source_ids))),
            confidence="high",
        )

    def financial_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        index = 0
        for trend in self.analysis.trends:
            index += 1
            proposal = self._trend_proposal(
                "operations", index, f"{trend.label}趋势",
                f"{trend.label}形成 {len(trend.points)} 个真实年度的可比序列。",
                trend.points,
            )
            if proposal is not None:
                proposals.append(proposal)
        # Segment structure -> bar (real part-to-whole from disclosed numbers).
        comparison = next((item for item in self.analysis.comparisons if item.comparison_id == "CMP-SEGMENTS"), None)
        if comparison is not None and len(comparison.rows) >= 2:
            proposals.append(VisualProposal(
                visual_id="v-operations-segments", chapter_id="operations",
                decision_question="收入结构是否发生变化？", business_thesis=comparison.statement,
                semantic_pattern="category_comparison", semantic_domain="financial",
                title="分业务收入构成",
                data_binding="research:segments",
                source_ids=comparison.source_ids, source_claim_ids=comparison.claim_ids,
                unit=comparison.rows[0].unit, period=comparison.rows[0].period,
                items=[VisualDatum(label=row.label, value=row.value, unit=row.unit, period=row.period) for row in comparison.rows],
                source_note=self._note(comparison.source_ids),
            ))
        return proposals

    def product_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
        comparison = next((item for item in self.analysis.comparisons if item.comparison_id == "CMP-FAMILIES"), None)
        if comparison is not None and len(comparison.rows) >= 2:
            proposals.append(VisualProposal(
                visual_id="v-products-families", chapter_id="products",
                decision_question="产品组合的重心在哪几个产品族？", business_thesis=comparison.statement,
                semantic_pattern="category_comparison", semantic_domain="product",
                title="产品族分布",
                data_binding="research:product_families",
                source_ids=comparison.source_ids, source_claim_ids=comparison.claim_ids,
                items=[VisualDatum(label=row.label, value=row.value, unit="项") for row in comparison.rows],
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
        return proposals

    def factory_proposals(self) -> list[VisualProposal]:
        proposals: list[VisualProposal] = []
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
        if self.analysis.overseas_factory_count > 0:
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
        return proposals

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
