from __future__ import annotations

from enterprise_energy_research.domain.models import Claim, EnergyProfile, Entity, Solution

from enterprise_energy_research.research.opportunity_registry import EvidenceOpportunityEngine


class SolutionEngine:
    """Evidence-driven opportunity generation (P0-20).

    Replaces the previous fixed EPC / ZERO_CARBON / STORAGE_ODM / OVERSEAS
    menu: opportunities are produced only when supporting evidence exists,
    and skipped (never padded with HOLD content) otherwise.
    """

    def __init__(self) -> None:
        self.engine = EvidenceOpportunityEngine()

    def generate(self, entities: list[Entity], profiles: list[EnergyProfile], claims: list[Claim]) -> list[Solution]:
        return self.engine.generate(entities, profiles, claims)
