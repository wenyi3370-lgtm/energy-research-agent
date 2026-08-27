"""Agent control-plane policies.

Loads config/agent.yaml and exposes the bounds the orchestrator and recovery
ledger must respect. Policies are data; the orchestrator is logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from energy_research_agent.domain.enums import ValueClass
from energy_research_agent.settings import load_yaml


CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agent.yaml"

DEFAULTS: dict = {
    "agent": {
        "enabled": True,
        "max_agent_iterations": 30,
        "max_recovery_rounds_per_goal": 10,
        "deep_recovery_rounds": 5,
        "require_structured_output": True,
        "parallel_recovery_rounds": 4,
    },
    "routing": {
        "allow_dynamic_custom_goal": True,
        "allow_multi_skill_goal": True,
    },
    "approval": {
        "unified_mission_approval": True,
    },
    "evidence": {
        "unified_store": True,
        "value_class_mapping": {
            "observed": "OBSERVED",
            "derived": "DERIVED",
            "modeled_estimate": "MODEL_ESTIMATE",
            "simulated": "SIMULATED",
            "scenario_assumption": "ASSUMPTION",
            "pending_verification": "TO_BE_CONFIRMED",
        },
    },
    "publication": {
        "single_artifact_owner": True,
    },
}

# Failure classes that prove a round did NOT actually execute (§24): the
# adapter was unavailable, nothing hit the network, or auth was missing.
NON_EXECUTED_FAILURES = frozenset({
    "ADAPTER_FAILURE",
    "AUTH_REQUIRED",
})


@dataclass(frozen=True)
class AgentPolicies:
    enabled: bool
    max_agent_iterations: int
    max_recovery_rounds_per_goal: int
    require_structured_output: bool
    allow_dynamic_custom_goal: bool
    allow_multi_skill_goal: bool
    unified_mission_approval: bool
    unified_store: bool
    single_artifact_owner: bool
    value_class_mapping: dict[str, ValueClass] = field(default_factory=dict)
    parallel_recovery_rounds: int = 4
    deep_recovery_rounds: int = 5

    @classmethod
    def load(cls, path: Path | None = None) -> "AgentPolicies":
        raw = dict(DEFAULTS)
        config_path = path or CONFIG_PATH
        if config_path.is_file():
            loaded = load_yaml(config_path) or {}
            for section, values in loaded.items():
                if isinstance(values, dict) and isinstance(raw.get(section), dict):
                    raw[section].update(values)
        mapping = {
            key: ValueClass(value)
            for key, value in raw["evidence"]["value_class_mapping"].items()
        }
        agent = raw["agent"]
        routing = raw["routing"]
        approval = raw["approval"]
        evidence = raw["evidence"]
        publication = raw["publication"]
        return cls(
            enabled=bool(agent["enabled"]),
            max_agent_iterations=int(agent["max_agent_iterations"]),
            max_recovery_rounds_per_goal=int(agent["max_recovery_rounds_per_goal"]),
            deep_recovery_rounds=max(1, int(agent.get("deep_recovery_rounds", 5))),
            require_structured_output=bool(agent["require_structured_output"]),
            parallel_recovery_rounds=max(1, int(agent.get("parallel_recovery_rounds", 4))),
            allow_dynamic_custom_goal=bool(routing["allow_dynamic_custom_goal"]),
            allow_multi_skill_goal=bool(routing["allow_multi_skill_goal"]),
            unified_mission_approval=bool(approval["unified_mission_approval"]),
            unified_store=bool(evidence["unified_store"]),
            single_artifact_owner=bool(publication["single_artifact_owner"]),
            value_class_mapping=mapping,
        )

    def map_value_class(self, ledger_value: str) -> ValueClass:
        return self.value_class_mapping.get(ledger_value, ValueClass.TO_BE_CONFIRMED)
