from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from energy_research_agent.domain.enums import EnterpriseComplexity, RunStatus, ValidationStatus


class ResearchState(BaseModel):
    run_id: str
    request_id: str
    status: RunStatus = RunStatus.PREFLIGHT
    current_node: str = "PREFLIGHT"
    canonical_entity_id: str | None = None
    complexity: EnterpriseComplexity = EnterpriseComplexity.UNKNOWN
    evidence_version: int = 1
    freeze_id: str | None = None
    artifact_manifest_id: str | None = None
    validation_status: ValidationStatus | None = None
    active_gaps: list[str] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    budgets: dict[str, int] = Field(default_factory=dict)
    node_attempts: dict[str, int] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)

    def transition(self, node: str, *, status: RunStatus | None = None) -> None:
        self.current_node = node
        self.node_attempts[node] = self.node_attempts.get(node, 0) + 1
        if status is not None:
            self.status = status
        self.checkpoints.append({
            "node": node,
            "status": self.status.value,
            "attempt": self.node_attempts[node],
        })

