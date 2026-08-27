from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from energy_research_agent.domain.models import (
        ArtifactManifest,
        Claim,
        ConflictGroup,
        DataGap,
        DataFreeze,
        EnergyProfile,
        EnterpriseGraph,
        ImageEvidence,
        ResearchPlan,
        ResearchRequest,
        ValidationReport,
    )
    from energy_research_agent.agent.models import (
        GoalEvaluation,
        RecoveryPlan,
        ResearchGoal,
        ResearchMission,
        RoutingDecision,
        SkillRunResult,
    )

    targets = {
        "research-request.schema.json": ResearchRequest,
        "evidence.schema.json": Claim,
        "image.schema.json": ImageEvidence,
        "enterprise-graph.schema.json": EnterpriseGraph,
        "research-plan.schema.json": ResearchPlan,
        "conflict.schema.json": ConflictGroup,
        "data-gap.schema.json": DataGap,
        "energy-profile.schema.json": EnergyProfile,
        "data-freeze.schema.json": DataFreeze,
        "artifact-manifest.schema.json": ArtifactManifest,
        "validation-report.schema.json": ValidationReport,
        # Agent control-plane contracts (§54)
        "research-mission.schema.json": ResearchMission,
        "research-goal.schema.json": ResearchGoal,
        "routing-decision.schema.json": RoutingDecision,
        "skill-run-result.schema.json": SkillRunResult,
        "goal-evaluation.schema.json": GoalEvaluation,
        "recovery-plan.schema.json": RecoveryPlan,
    }
    output = root / "schemas"
    output.mkdir(exist_ok=True)
    for filename, model in targets.items():
        (output / filename).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
