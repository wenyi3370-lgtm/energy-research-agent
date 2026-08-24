from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from enterprise_energy_research.adapters.base import SearchAdapter, SearchResultEnvelope
from enterprise_energy_research.domain.enums import EnterpriseComplexity, SourceLevel
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ResearchPlan, ResearchQuery
from enterprise_energy_research.research.executor import SearchExecutor

from .budget import BudgetAllocation, DailyRecallBudgetPlanner, RecallBudgetPolicy
from .models import QueryPriority, RecallProfile, RecallQuerySpec, SearchPass, SourceLane
from .query_expander import QueryExpander
from .source_lanes import SourceRoster


class RecallEngine:
    """Shared planner/executor facade for both recall profiles."""

    def __init__(
        self,
        profile: RecallProfile,
        *,
        policy: RecallBudgetPolicy | None = None,
        expander: QueryExpander | None = None,
        roster: SourceRoster | None = None,
    ) -> None:
        self.profile = profile
        self.policy = policy or RecallBudgetPolicy()
        self.budget_planner = DailyRecallBudgetPlanner(self.policy)
        self.expander = expander or QueryExpander()
        self.roster = roster or SourceRoster()

    def plan_daily(
        self,
        seeds: list[tuple[str, str]],
        *,
        current_time: datetime,
        update_targets: Iterable[object] = (),
    ) -> BudgetAllocation:
        end_exclusive = (current_time + timedelta(days=1)).date().isoformat()
        specs = self.expander.daily_specs(
            seeds,
            primary_start=(current_time - timedelta(hours=24)).date().isoformat(),
            recovery_start=(current_time - timedelta(hours=72)).date().isoformat(),
            end_exclusive=end_exclusive,
        )
        specs.extend(self.roster.query_specs(
            start_date=(current_time - timedelta(hours=72)).date().isoformat(),
            end_date=end_exclusive,
        ))
        for index, target in enumerate(list(update_targets)[:12]):
            text = " ".join(str(getattr(target, field, "") or "") for field in ("entity", "title", "topic")).strip()
            if not text:
                continue
            specs.append(RecallQuerySpec(
                query_id=f"RQ-U-{index:03d}", topic=str(getattr(target, "topic", "update") or "update"),
                query=f"{text} 最新进展 更新 新增事实 after:{(current_time - timedelta(days=7)).date().isoformat()} before:{end_exclusive}",
                search_pass=SearchPass.UPDATE, source_lane=SourceLane.MEDIA_DISCOVERY,
                language="zh-CN", priority=QueryPriority.P0, desired_results=4,
                query_variant="historical_update",
            ))
        return self.budget_planner.allocate(specs)

    def plan_enterprise(self, canonical_name: str, topics: list[str], *, max_slots: int) -> BudgetAllocation:
        specs = self.expander.enterprise_specs(canonical_name, topics)
        policy = RecallBudgetPolicy(total_result_slots=max(1, max_slots), frontier_reserve=min(24, max(0, max_slots // 5)))
        return DailyRecallBudgetPlanner(policy).allocate(specs)

    def execute(
        self,
        specs: list[RecallQuerySpec],
        adapters: dict[str, SearchAdapter],
        *,
        run_id: str,
        canonical_name: str = "",
    ) -> list[SearchResultEnvelope]:
        if not specs:
            return []
        plan = self.to_research_plan(specs, run_id=run_id, canonical_name=canonical_name)
        return SearchExecutor(adapters).execute(plan)

    @staticmethod
    def to_research_plan(
        specs: list[RecallQuerySpec], *, run_id: str, canonical_name: str = ""
    ) -> ResearchPlan:
        queries: list[ResearchQuery] = []
        for spec in specs:
            round_name, round_goal = {
                SearchPass.PRIMARY: ("R1", "coverage"),
                SearchPass.SOURCE_PATROL: ("R1", "coverage"),
                SearchPass.ENTERPRISE_SEED: ("R1", "coverage"),
                SearchPass.FRONTIER: ("R2", "depth"),
                SearchPass.ENTERPRISE_FRONTIER: ("R2", "depth"),
                SearchPass.RECOVERY: ("R2", "depth"),
                SearchPass.UPDATE: ("R3", "triangulation"),
                SearchPass.ANOMALY: ("R3", "triangulation"),
            }[spec.search_pass]
            queries.append(ResearchQuery(
                query_id=spec.query_id, entity_id="intel" if not canonical_name else "PENDING-ENTITY",
                topic=spec.topic, query=spec.query,
                purpose=(f"{spec.search_pass.value} recall; lane={spec.source_lane.value}; "
                         f"language={spec.language}; priority={spec.priority.value}"),
                preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                adapter_preference="anysearch", max_results=max(1, spec.requested_results),
                collection_round=round_name, round_goal=round_goal,
                high_priority=spec.priority in {QueryPriority.P0, QueryPriority.P1},
                trigger="official_discovery" if spec.source_lane != SourceLane.MEDIA_DISCOVERY else "baseline",
                canonical_company_name=canonical_name or None,
            ))
        return ResearchPlan(
            plan_id=new_sortable_id("RECALL-PLAN"), run_id=run_id,
            complexity=EnterpriseComplexity.UNKNOWN, queries=queries,
            budget={"max_queries": len(queries), "max_pages": sum(spec.requested_results for spec in specs)},
            completion_contract=[], canonical_company_name=canonical_name or None,
        )
