# HYBRID live end-to-end probe: real DeepSeek decisions + real AnySearch
# searches (market side via the vendored CLI adapter) + real enterprise
# pipeline + cross-domain synthesis + unified publication (§37/§38/§59).
# Local-only diagnostic; requires ERA_DEEPSEEK_API_KEY + network.
import csv
import os
import sys
import tempfile
from pathlib import Path

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
if os.environ.get("AGENT_LIVE_PROXY"):
    os.environ["HTTPS_PROXY"] = os.environ["AGENT_LIVE_PROXY"]
    os.environ["HTTP_PROXY"] = os.environ["AGENT_LIVE_PROXY"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from energy_research_agent.agent.mission_store import MissionStore  # noqa: E402
from energy_research_agent.agent.models import (  # noqa: E402
    ApprovalStatus, MissionApproval, SkillName,
)
from energy_research_agent.agent.orchestrator import ResearchOrchestratorAgent  # noqa: E402
from energy_research_agent.agent.policies import AgentPolicies  # noqa: E402
from energy_research_agent.agent.publication import publish_unified  # noqa: E402
from energy_research_agent.agent.tools.enterprise_research import EnterpriseResearchSkill  # noqa: E402
from energy_research_agent.agent.tools.overseas_market_research import OverseasMarketResearchAdapter  # noqa: E402
from energy_research_agent.adapters.anysearch import AnySearchCliAdapter  # noqa: E402
from energy_research_agent.adapters.base import SearchRequest  # noqa: E402
from energy_research_agent.automation.orchestration import OrchestratingExecutor  # noqa: E402
from energy_research_agent.domain.ids import new_sortable_id  # noqa: E402
from energy_research_agent.evidence.store import EvidenceStore  # noqa: E402
from energy_research_agent.gateway import LiteLLMModelGateway  # noqa: E402
from energy_research_agent.settings import Settings  # noqa: E402


def make_market_runner(adapter: AnySearchCliAdapter, project_dir: Path):
    """Real searches; writes source ledger rows bound to the mission's goals."""

    def runner(spec: dict) -> dict:
        project_dir.mkdir(parents=True, exist_ok=True)
        # Simulate the post-approval state the adapter requires: the unified
        # mission approval (approval_cb above) corresponds to an approved
        # record in the skill's own approval gate (§27 double gate).
        approval = project_dir / "00_Research_Approval.csv"
        if not approval.is_file():
            approval.write_text(
                "approval_id,outline_version,outline_path,scope_summary,reviewer,approval_status,approval_date,approval_message,scope_change_requires_reapproval,notes\n"
                "A-HYBRID,v1,outline.md,HYBRID live probe,human,approved,2026-08-25,unified mission approval,yes,\n",
                encoding="utf-8-sig",
            )
        ledger = project_dir / "00_Source_Ledger.csv"
        existing = []
        if ledger.is_file():
            with ledger.open("r", encoding="utf-8-sig", newline="") as handle:
                existing = list(csv.DictReader(handle))
        goal_specs = spec.get("goal_specs") or []
        queries = spec.get("recovery_queries") or []
        rows = list(existing)
        seen_urls = {row.get("source_url") for row in rows}
        search_terms = queries or [
            f"{goal.get('geography') or ''} residential energy storage {goal.get('name', '')}"
            for goal in goal_specs
        ]
        for term in search_terms[:8]:
            envelope = adapter.search(SearchRequest(
                query_id=new_sortable_id("Q"),
                query=term,
                entity_id="market",
                purpose="market research",
                max_results=4,
            ))
            for hit in envelope.hits[:4]:
                url = str(hit.final_url or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                rows.append({
                    "source_id": new_sortable_id("SRC"),
                    "stage": "1",
                    "evidence_item": term[:80],
                    "value_class": "observed",
                    "source_type": "web",
                    "source_title": str(hit.title or "")[:200],
                    "publisher": "",
                    "source_url": url,
                    "root_domain": url.split("/")[2] if "//" in url else "",
                    "country": spec.get("geographies") or "",
                    "reliability_tier": "B",
                    "raw_value": "",
                    "unit": "",
                    "verification_status": "verified",
                    "goal_id": (goal_specs[0].get("goal_id") if goal_specs else ""),
                    "subject_role": "MARKET_CONTEXT",
                })
        fieldnames = sorted({key for row in rows for key in row})
        with ledger.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return {"status": "OK", "strategy": "real AnySearch market collection", "recovery_queries": queries}

    return runner


def main() -> int:
    # Persistent probe location: the automation data volume survives container
    # recreation (unlike /tmp). Kept under /data/automation_work in-container;
    # falls back to a temp dir when running on the host.
    probe_base = Path(os.environ.get("AGENT_PROBE_DIR") or "/data/automation_work/agent_probes")
    probe_base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="agent-hybrid-", dir=probe_base))
    gateway = LiteLLMModelGateway(Settings())
    anysearch = AnySearchCliAdapter()
    # Production budgets (config/research_budgets.yaml) are used as-is:
    # evidence quantity is part of quality (PERFORMANCE_POLICY.md §2).
    executor = OrchestratingExecutor.from_environment(gateway=gateway)
    project_dir = tmp / "market"

    def market_runner(spec: dict) -> dict:
        return make_market_runner(anysearch, project_dir)(spec)

    def unified_publish(spec: dict) -> dict:
        return publish_unified(
            workdir=tmp,
            enterprise_run_id=spec["enterprise_run_id"],
            findings=list(spec.get("findings") or []),
            sub_artifact_refs=list(spec.get("sub_artifact_refs") or []),
            market_evidence_store=EvidenceStore(tmp / "agent_evidence.sqlite3"),
            market_run_id=f"agent-{spec['mission_id']}",
        )

    def ent_run(spec: dict) -> dict:
        from energy_research_agent.agent.api import build_enterprise_executor
        fn = build_enterprise_executor(executor, tmp)
        return fn(spec)

    skills = {
        SkillName.ENTERPRISE_RESEARCH: EnterpriseResearchSkill(ent_run, publish_cb=unified_publish),
        SkillName.OVERSEAS_MARKET_RESEARCH: OverseasMarketResearchAdapter(
            skill_root=ROOT / "vendor" / "skills" / "overseas-energy-market-research",
            runner=market_runner,
        ),
    }
    orchestrator = ResearchOrchestratorAgent(
        gateway=gateway,
        skills=skills,
        policies=AgentPolicies(
            enabled=True,
            max_agent_iterations=4,
            max_recovery_rounds_per_goal=1,
            require_structured_output=True,
            allow_dynamic_custom_goal=True,
            allow_multi_skill_goal=True,
            unified_mission_approval=True,
            unified_store=True,
            single_artifact_owner=True,
            value_class_mapping={"observed": "OBSERVED"},
        ),
        store=MissionStore(tmp / "agent_store.sqlite3"),
        evidence_store=EvidenceStore(tmp / "agent_evidence.sqlite3"),
        approval_cb=lambda mission, goals, routing: MissionApproval(
            approval_id=new_sortable_id("APPROVAL"),
            mission_id=mission.mission_id,
            decision=ApprovalStatus.APPROVED,
            scope_summary="hybrid live probe",
        ),
    )
    outcome = orchestrator.run("调研宁德时代在德国户储市场的发展机会。")
    print("=" * 60)
    print("mode:", outcome.mission.mode.value, "| parse_mode:", outcome.mission.parse_mode)
    print("status:", outcome.status.value)
    print("goals:", len(outcome.goals))
    print("findings:", len(outcome.synthesis_findings))
    for f in outcome.synthesis_findings[:4]:
        print("  -", f.finding_type, "|", f.statement[:80], "| refs:", len(f.enterprise_evidence_refs) + len(f.market_evidence_refs))
    print("artifact_refs:", outcome.mission.artifact_refs[:4])
    print("metrics:", {k: outcome.metrics.get(k) for k in ("goal_completion_rate", "valid_evidence_yield", "recovery_success_rate", "citation_traceability")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
