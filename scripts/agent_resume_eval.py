# Resume evaluation from already-collected evidence (§12/§20 continuation).
# Reuses an existing mission's evidence (no re-collection): bind claims to
# goals with the fixed contract chain, evaluate, run targeted recovery only
# for unresolved goals, synthesize cross-domain findings, and publish.
#
# Usage (in-container or host):
#   python scripts/agent_resume_eval.py --probe-dir /tmp/agent-hybrid-XXXX
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from energy_research_agent.agent.api import _read_run_claims  # noqa: E402
from energy_research_agent.agent.evals import compute_agent_metrics  # noqa: E402
from energy_research_agent.agent.mission_store import MissionStore  # noqa: E402
from energy_research_agent.agent.models import (  # noqa: E402
    ApprovalStatus, GoalStatus, MissionApproval, ResearchMode, SkillName,
)
from energy_research_agent.agent.orchestrator import ResearchOrchestratorAgent  # noqa: E402
from energy_research_agent.agent.policies import AgentPolicies  # noqa: E402
from energy_research_agent.agent.publication import publish_unified  # noqa: E402
from energy_research_agent.agent.synthesis import CrossDomainSynthesisEngine  # noqa: E402
from energy_research_agent.evidence.store import EvidenceStore  # noqa: E402
from energy_research_agent.gateway import LiteLLMModelGateway  # noqa: E402
from energy_research_agent.settings import Settings  # noqa: E402


def _merge_run_claims(probe: Path, src_run_id: str, dst_run_id: str) -> int:
    """Copy records from a recovery run into the accumulating enterprise run,
    deduplicated by record id (append-only store semantics)."""
    from energy_research_agent.evidence.store import EvidenceStore

    src = EvidenceStore(probe / src_run_id / "evidence.sqlite3")
    dst = EvidenceStore(probe / dst_run_id / "evidence.sqlite3")
    copied = 0
    for kind in ("entity", "source", "retrieval", "claim", "conflict", "gap"):
        try:
            records = src.list(src_run_id, kind)
        except Exception:
            continue
        for record in records:
            record_id = str(getattr(record, f"{kind}_id", "") or id(record))
            if dst.has_record(dst_run_id, kind, record_id):
                continue
            try:
                dst.add(dst_run_id, 1, kind, record)
                copied += 1
            except Exception:
                continue
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-dir", required=True)
    parser.add_argument("--gateway", action="store_true", default=False, help="use real LLM gateway")
    args = parser.parse_args()
    probe = Path(args.probe_dir)
    store = MissionStore(probe / "agent_store.sqlite3")
    missions = store.list_missions()
    if not missions:
        print("no mission found")
        return 1
    mission = missions[0]
    print("mission:", mission.mission_id, "| mode:", mission.mission_mode if hasattr(mission, "mission_mode") else mission.mode.value, "| status:", mission.status.value)

    # 1) locate the enterprise run with evidence (first OK skill run)
    enterprise_run_id = None
    for run in store.skill_runs_for(mission.mission_id):
        payload = run["payload"]
        if payload.get("skill_name") == "ENTERPRISE_RESEARCH" and payload.get("status") == "OK":
            exports = payload.get("evidence_exports") or []
            if exports:
                enterprise_run_id = exports[0].get("run_id")
                break
    if not enterprise_run_id:
        # older runs stored the summary payload with run_id at top level
        for run in store.skill_runs_for(mission.mission_id):
            if run["payload"].get("skill_name") == "ENTERPRISE_RESEARCH" and run["payload"].get("run_id"):
                enterprise_run_id = run["payload"].get("run_id")
                break
    if not enterprise_run_id:
        # Fallback: the run dirs survive on disk; pick the one with the most
        # claims (the accumulating main run).
        import glob as _glob

        def _claims(d: str) -> int:
            try:
                import sqlite3 as _sq

                conn = _sq.connect(str(Path(d) / "evidence.sqlite3"))
                return conn.execute("SELECT count(*) FROM evidence_records WHERE kind='claim'").fetchone()[0]
            except Exception:
                return 0

        candidates = _glob.glob(str(probe / "AGENTENT-*"))
        if candidates:
            enterprise_run_id = Path(max(candidates, key=_claims)).name
    if not enterprise_run_id:
        print("no enterprise run id found")
        return 1
    print("enterprise run:", enterprise_run_id)

    gateway = LiteLLMModelGateway(Settings()) if args.gateway else None
    rows = _read_run_claims(enterprise_run_id, probe)
    print("claims loaded:", len(rows))

    # 2) bind + evaluate (reuse the orchestrator's deterministic machinery)
    from energy_research_agent.agent.tools.enterprise_research import EnterpriseResearchSkill
    from energy_research_agent.agent.evaluator import GoalEvaluator
    from energy_research_agent.agent.recovery import RecoveryLedger, RecoveryPlanner
    from energy_research_agent.automation.orchestration import OrchestratingExecutor

    evaluator = GoalEvaluator(gateway)
    recovery_planner = RecoveryPlanner(gateway, max_rounds_per_goal=3)
    ledger = RecoveryLedger()
    required_by_goal = {g.goal_id: set(g.required_evidence) for g in mission.goals}
    evidence_by_goal: dict[str, list] = {}
    for row in rows:
        families = [str(f) for f in (row.get("goal_families") or [])]
        field = str(row.get("field_name") or "")
        for gid, fields in required_by_goal.items():
            if any(f in fields for f in families) or (field and field in fields):
                evidence_by_goal.setdefault(gid, []).append(row)
                break
    bound = sum(len(v) for v in evidence_by_goal.values())
    print("bound rows:", bound)

    evaluations = []
    executor = OrchestratingExecutor.from_environment(gateway=gateway)
    from energy_research_agent.agent.api import build_enterprise_executor

    ent_executor = build_enterprise_executor(executor, probe)
    for goal in mission.goals:
        # Resume semantics: this is a fresh evaluation pass over accumulated
        # evidence; previously spent rounds are not carried over as exhaustion.
        goal.recovery_rounds = 0
        evaluation = evaluator.evaluate(goal, evidence_by_goal.get(goal.goal_id, []), [])
        rounds = 0
        # Full recovery loop: config-driven cap (10), each round rotates a
        # distinct RECOVERY_STRATEGIES; goals stop the moment they satisfy.
        max_rounds = AgentPolicies.load().max_recovery_rounds_per_goal
        while evaluation.status == GoalStatus.PARTIAL and rounds < max_rounds:
            # §22 targeted recovery: real pipeline, recovery_only mode — only
            # this round's gap queries run (minutes, not the full plan).
            recovery = recovery_planner.plan(
                goal, evaluation, failed_round=rounds,
                previous_attempts=[], evidence_sample=evidence_by_goal.get(goal.goal_id, []),
            )
            if recovery.failure_class == __import__("energy_research_agent.agent.models", fromlist=["FailureClass"]).FailureClass.RECOVERY_EXHAUSTED or not recovery.new_queries:
                break
            print(f"  recovery {goal.goal_name} round {rounds + 1}: {recovery.new_queries[:2]}")
            payload = ent_executor({
                "canonical_subject": mission.primary_subject,
                "requirements": [],
                "recovery_queries": recovery.new_queries,
                "recovery_round": rounds + 1,
                "mission_id": mission.mission_id,
            })
            rec_run_id = payload.get("run_id")
            if not rec_run_id:
                print("    recovery run missing")
                break
            # Merge the new run's records into the accumulating enterprise run
            # so later evaluation and the unified freeze see everything.
            copied = _merge_run_claims(probe, rec_run_id, enterprise_run_id)
            print(f"    merged {copied} new records from {rec_run_id}")
            new_rows = _read_run_claims(enterprise_run_id, probe)
            evidence_by_goal = {}
            for row in new_rows:
                families = [str(f) for f in (row.get("goal_families") or [])]
                field = str(row.get("field_name") or "")
                for gid, fields in required_by_goal.items():
                    if any(f in fields for f in families) or (field and field in fields):
                        evidence_by_goal.setdefault(gid, []).append(row)
                        break
            evaluation = evaluator.evaluate(goal, evidence_by_goal.get(goal.goal_id, []), [])
            rounds += 1
        evaluations.append((goal.goal_id, evaluation.status.value, len(evidence_by_goal.get(goal.goal_id, []))))
    for gid, status, count in evaluations:
        print("  ", gid, status, "evidence:", count)

    # 3) synthesis (HYBRID only)
    findings = []
    if mission.mode == ResearchMode.HYBRID:
        market_rows = []
        try:
            market_store = EvidenceStore(probe / "agent_evidence.sqlite3")
            market_rows = [
                {
                    "claim_id": c.claim_id,
                    "verification_status": c.verification_status.value,
                    "goal_id": c.goal_id or "",
                    "field_name": c.field_name,
                }
                for c in market_store.list(f"agent-{mission.mission_id}", "claim")
            ]
        except Exception as exc:
            print("market store unavailable:", exc)
        findings = CrossDomainSynthesisEngine(gateway).synthesize(
            mission, mission.goals,
            [row for rows in evidence_by_goal.values() for row in rows],
            market_rows,
        )
        print("findings:", len(findings))

    # 4) unified publication
    published = publish_unified(
        workdir=probe,
        enterprise_run_id=enterprise_run_id,
        findings=findings,
        sub_artifact_refs=[],
        market_evidence_store=EvidenceStore(probe / "agent_evidence.sqlite3"),
        market_run_id=f"agent-{mission.mission_id}",
    )
    print("publish:", published["status"], "| freeze:", published.get("freeze_id"), "| artifacts:", len(published.get("artifacts", [])))
    print("publish diagnostics:", published.get("diagnostics"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
