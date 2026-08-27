from __future__ import annotations

from dataclasses import dataclass, field

from .models import QueryPriority, RecallQuerySpec, SearchPass


@dataclass(frozen=True)
class RecallBudgetPolicy:
    """Single source of truth for bounded recall allocation."""

    total_result_slots: int = 168
    frontier_reserve: int = 12
    minimum_by_pass: dict[SearchPass, int] = field(default_factory=lambda: {
        SearchPass.PRIMARY: 3,
        SearchPass.RECOVERY: 2,
        SearchPass.UPDATE: 2,
        SearchPass.SOURCE_PATROL: 1,
        SearchPass.FRONTIER: 2,
        SearchPass.ENTERPRISE_SEED: 2,
        SearchPass.ENTERPRISE_FRONTIER: 2,
        SearchPass.ANOMALY: 1,
    })

    def __post_init__(self) -> None:
        if self.total_result_slots <= 0:
            raise ValueError("total_result_slots must be positive")
        if not 0 <= self.frontier_reserve < self.total_result_slots:
            raise ValueError("frontier_reserve must be within the total budget")


@dataclass
class BudgetAllocation:
    planned: list[RecallQuerySpec]
    deferred: list[RecallQuerySpec]
    used_slots: int
    remaining_slots: int
    reserved_frontier_slots: int


class DailyRecallBudgetPlanner:
    """Priority allocation with explicit recovery/update/frontier reserves."""

    def __init__(self, policy: RecallBudgetPolicy | None = None) -> None:
        self.policy = policy or RecallBudgetPolicy()

    def allocate(self, specs: list[RecallQuerySpec]) -> BudgetAllocation:
        # Frontier is executed after entity/event mining.  Its reserve cannot
        # be consumed by broad PRIMARY variants in the initial pass.
        available = self.policy.total_result_slots - self.policy.frontier_reserve
        planned: list[RecallQuerySpec] = []
        deferred: list[RecallQuerySpec] = []

        ordered = sorted(specs, key=self._allocation_key)
        for spec in ordered:
            minimum = self._minimum(spec)
            if minimum > available:
                deferred.append(spec.model_copy(update={
                    "requested_results": 0, "deferred": True,
                    "defer_reason": "lower priority deferred to protect recovery/update/frontier reserves",
                }))
                continue
            planned_spec = spec.model_copy(update={"requested_results": minimum})
            planned.append(planned_spec)
            available -= minimum

        # Fill toward desired depth only after every admitted query has its
        # minimum.  P0 receives depth first; no query can exceed its desire.
        for index in sorted(range(len(planned)), key=lambda i: self._depth_key(planned[i])):
            if available <= 0:
                break
            spec = planned[index]
            extra = min(available, max(0, spec.desired_results - spec.requested_results))
            if extra:
                planned[index] = spec.model_copy(update={
                    "requested_results": spec.requested_results + extra,
                })
                available -= extra

        used = sum(spec.requested_results for spec in planned)
        if used + self.policy.frontier_reserve > self.policy.total_result_slots:
            raise AssertionError("recall allocation exceeded its strict bound")
        return BudgetAllocation(
            planned=sorted(planned, key=lambda item: item.query_id),
            deferred=sorted(deferred, key=lambda item: item.query_id),
            used_slots=used,
            remaining_slots=self.policy.total_result_slots - used,
            reserved_frontier_slots=self.policy.frontier_reserve,
        )

    def allocate_frontier(
        self, specs: list[RecallQuerySpec], *, remaining_slots: int
    ) -> BudgetAllocation:
        available = max(0, min(remaining_slots, self.policy.total_result_slots))
        planned: list[RecallQuerySpec] = []
        deferred: list[RecallQuerySpec] = []
        for spec in sorted(specs, key=self._allocation_key):
            minimum = self._minimum(spec)
            if minimum > available:
                deferred.append(spec.model_copy(update={
                    "requested_results": 0, "deferred": True,
                    "defer_reason": "frontier result-slot budget exhausted",
                }))
                continue
            requested = min(spec.desired_results, available)
            planned.append(spec.model_copy(update={"requested_results": requested}))
            available -= requested
        used = sum(item.requested_results for item in planned)
        return BudgetAllocation(planned, deferred, used, available, 0)

    def _minimum(self, spec: RecallQuerySpec) -> int:
        base = self.policy.minimum_by_pass.get(spec.search_pass, 1)
        # P0 seed queries keep enough depth to remain useful.  Lower priority
        # variants are the first candidates for deferral.
        if spec.search_pass == SearchPass.PRIMARY and spec.seed_query and spec.priority == QueryPriority.P0:
            return max(base, 4)
        return min(base, spec.desired_results)

    @staticmethod
    def _allocation_key(spec: RecallQuerySpec) -> tuple[int, int, int, str]:
        pass_order = {
            SearchPass.UPDATE: 0,
            SearchPass.RECOVERY: 1,
            SearchPass.SOURCE_PATROL: 2,
            SearchPass.PRIMARY: 3,
            SearchPass.FRONTIER: 4,
            SearchPass.ENTERPRISE_SEED: 5,
            SearchPass.ENTERPRISE_FRONTIER: 6,
            SearchPass.ANOMALY: 7,
        }
        priority_order = {QueryPriority.P0: 0, QueryPriority.P1: 1, QueryPriority.P2: 2, QueryPriority.P3: 3}
        return (
            pass_order.get(spec.search_pass, 99),
            0 if spec.seed_query else 1,
            priority_order[spec.priority],
            spec.query_id,
        )

    @staticmethod
    def _depth_key(spec: RecallQuerySpec) -> tuple[int, int, int, str]:
        priority_order = {QueryPriority.P0: 0, QueryPriority.P1: 1, QueryPriority.P2: 2, QueryPriority.P3: 3}
        pass_order = {
            SearchPass.UPDATE: 0, SearchPass.RECOVERY: 1,
            SearchPass.SOURCE_PATROL: 2, SearchPass.PRIMARY: 3,
        }
        return (
            priority_order[spec.priority],
            0 if spec.seed_query else 1,
            pass_order.get(spec.search_pass, 9), spec.query_id,
        )
