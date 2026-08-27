"""Agent control-plane state (§30).

References only: large objects (missions, goals, skill results, evidence) live
in the store / evidence plane; this state keeps ids, counters and status.
State names follow the target machine in §29.
"""

from __future__ import annotations

from typing import Any

from energy_research_agent.domain.enums import StrEnum

from .models import AgentStrictModel, GoalStatus, ResearchMode, SkillName


class AgentPhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    MISSION_PARSE = "MISSION_PARSE"
    IDENTITY = "IDENTITY"
    GOAL_PLAN = "GOAL_PLAN"
    ROUTING = "ROUTING"
    APPROVAL = "APPROVAL"
    EXECUTE_SKILLS = "EXECUTE_SKILLS"
    INGEST = "INGEST"
    GOAL_EVALUATION = "GOAL_EVALUATION"
    RECOVERY = "RECOVERY"
    SYNTHESIS = "SYNTHESIS"
    UNIFIED_VALIDATE = "UNIFIED_VALIDATE"
    FREEZE = "FREEZE"
    ARTIFACT_PLAN = "ARTIFACT_PLAN"
    PUBLISH = "PUBLISH"
    CROSS_VALIDATE = "CROSS_VALIDATE"
    PACKAGE = "PACKAGE"


class AgentState(AgentStrictModel):
    mission_id: str
    raw_request: str
    research_mode: ResearchMode = ResearchMode.ENTERPRISE
    phase: AgentPhase = AgentPhase.PREFLIGHT
    goal_ids: list[str] = []
    skill_assignments: dict[str, SkillName] = {}
    active_goal_ids: list[str] = []
    goal_status: dict[str, GoalStatus] = {}
    agent_iteration: int = 0
    recovery_rounds: dict[str, int] = {}
    approval_id: str | None = None
    skill_run_ids: list[str] = []
    evidence_version: int = 1
    active_gaps: list[dict[str, Any]] = []
    blocking_findings: list[str] = []
    checkpoints: list[dict[str, Any]] = []

    def transition(self, phase: AgentPhase) -> None:
        self.phase = phase
        self.checkpoints.append({"phase": phase.value, "iteration": self.agent_iteration})
