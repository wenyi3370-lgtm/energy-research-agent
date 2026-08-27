# Live agent loop integration (local-only): real DeepSeek decisions + deterministic skills.
# Requires: ERA_DEEPSEEK_API_KEY in .env; run with the local proxy env if the
# Network routing is configured only through ERA_OUTBOUND_PROXY when required.
import os

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
if os.environ.get("AGENT_LIVE_PROXY"):
    os.environ["HTTPS_PROXY"] = os.environ["AGENT_LIVE_PROXY"]
    os.environ["HTTP_PROXY"] = os.environ["AGENT_LIVE_PROXY"]

import tempfile
from pathlib import Path

from energy_research_agent.agent.mission_store import MissionStore
from energy_research_agent.agent.models import (
    ApprovalStatus, MissionApproval, SkillName,
)
from energy_research_agent.agent.orchestrator import ResearchOrchestratorAgent
from energy_research_agent.agent.policies import AgentPolicies
from energy_research_agent.agent.tools.enterprise_research import EnterpriseResearchSkill
from energy_research_agent.automation.executor import SyntheticKernelExecutor
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.gateway import LiteLLMModelGateway
from energy_research_agent.settings import Settings
from energy_research_agent.domain.ids import new_sortable_id

tmp = Path(tempfile.mkdtemp(prefix="agent-live-"))
gateway = LiteLLMModelGateway(Settings())

# Enterprise skill: offline synthetic kernel executor (deterministic, fixture-based).
synthetic = SyntheticKernelExecutor()
ent_executor = lambda spec: {  # noqa: E731
    "status": "OK",
    "coverage_metrics": {"evidence_count": 12, "verified_claim_count": 8, "gap_count": 2},
    "quality_metrics": {"validation_status": "PASS"},
    "recovery_round": int(spec.get("recovery_round") or 0),
    "queries": list(spec.get("recovery_queries") or []),
}
skills = {
    SkillName.ENTERPRISE_RESEARCH: EnterpriseResearchSkill(ent_executor),
}

orchestrator = ResearchOrchestratorAgent(
    gateway=gateway,
    skills=skills,
    policies=AgentPolicies.load(),
    store=MissionStore(tmp / "store.sqlite3"),
    evidence_store=EvidenceStore(tmp / "evidence.sqlite3"),
    approval_cb=lambda mission, goals, routing: MissionApproval(
        approval_id=new_sortable_id("APPROVAL"),
        mission_id=mission.mission_id,
        decision=ApprovalStatus.APPROVED,
        scope_summary="live probe auto-approval (human-in-loop hook available in the API)",
    ),
)

outcome = orchestrator.run("调研阳光电源在西班牙户储市场的发展机会。")
print("mission:", outcome.mission.mission_id, "| mode:", outcome.mission.mode.value)
print("parse_mode:", outcome.mission.parse_mode, "| subject:", outcome.mission.primary_subject)
print("goals:", len(outcome.goals))
for goal in outcome.goals[:8]:
    print("  -", goal.goal_name, "|", goal.goal_class.value, "|", (goal.assigned_skill.value if goal.assigned_skill else "-"))
print("status:", outcome.status.value)
print("evaluations:", {e.goal_id: e.status.value for e in outcome.evaluations[:8]})
print("recovery_ledger:", outcome.recovery_ledger)
print("cost:", [c.model_dump() for c in outcome.cost_records])
