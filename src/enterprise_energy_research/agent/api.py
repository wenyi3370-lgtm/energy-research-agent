"""Agent HTTP surface (§48-§50).

Additive endpoints on the existing FastAPI app: mission parse preview,
unified human approval, start/continue, status with agent trace. Business
language only for end users; technical trace is a separate debug payload.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .models import (
    ApprovalStatus,
    GoalStatus,
    MissionApproval,
    MissionStatus,
)
from .orchestrator import AgentOutcome, ResearchOrchestratorAgent
from .tools.enterprise_research import EnterpriseResearchSkill
from .tools.overseas_market_research import OverseasMarketResearchAdapter

logger = logging.getLogger(__name__)


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_request: str = Field(min_length=1)
    # Portal tab the request came from ("enterprise" | "market"). Never
    # overrides the parse; only produces a mismatch hint for the UI.
    track: str = ""


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool = True
    message: str = ""


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_request: str = Field(min_length=1)


class GoalEditItem(BaseModel):
    """One row of the desired final goal list (pre-approval framework edit)."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = ""  # empty -> a newly added custom goal
    goal_name: str = Field(min_length=1)
    goal_description: str = ""


class GoalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals: list[GoalEditItem] = Field(min_length=1)


class DeepResearchRequest(BaseModel):
    """Deep research on a finished mission: follow-up requirements + repair."""

    model_config = ConfigDict(extra="forbid")

    raw_request: str = ""  # optional; empty means repair-only


def _mission_preview(outcome: AgentOutcome) -> dict[str, Any]:
    """Business-language mission preview for the approval screen (§27/§48/§49)."""
    goals = outcome.goals
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for goal in goals:
        kind = {
            "CORE_ENTERPRISE": "企业研究",
            "CUSTOM_ENTERPRISE": "专项研究",
            "CUSTOM": "专项研究",
            "MARKET": "市场研究",
            "POLICY": "市场研究·政策",
            "CHANNEL": "市场研究·渠道",
            "COMPETITION": "市场研究·竞争",
            "CUSTOMER": "市场研究·客户",
            "PRODUCT": "企业研究·产品",
            "ENGINEERING": "企业研究·工程",
            "ECONOMICS": "市场研究·经济性",
            "STRATEGY": "跨域研究",
        }.get(goal.goal_class.value, "专项研究")
        by_kind.setdefault(kind, []).append({"id": goal.goal_id, "name": goal.goal_name})
    return {
        "mission_id": outcome.mission.mission_id,
        "raw_request": outcome.mission.raw_request,
        "research_mode": outcome.mission.mode.value,
        "primary_subject": outcome.mission.primary_subject,
        "geographies": outcome.mission.geographies,
        "goal_groups": by_kind,
        "approval_status": outcome.mission.approval_status.value,
        "status": outcome.mission.status.value,
        "parse_mode": outcome.mission.parse_mode,
    }


_FIELD_TO_FAMILIES: dict[str, list[str]] | None = None


def _field_to_families() -> dict[str, list[str]]:
    """Inverse extraction contract: field_name -> goal families (§20/§70).

    Built once from the repo's own GOAL_CONTRACTS registry (the deterministic
    contract the extractor and planner already share); never a heuristic.
    """
    global _FIELD_TO_FAMILIES
    if _FIELD_TO_FAMILIES is None:
        from enterprise_energy_research.research.contracts import GOAL_CONTRACTS

        mapping: dict[str, set[str]] = {}
        for family, contract in GOAL_CONTRACTS.items():
            for field in contract.expected_fields:
                mapping.setdefault(field, set()).add(family)
        _FIELD_TO_FAMILIES = {field: sorted(families) for field, families in mapping.items()}
    return _FIELD_TO_FAMILIES


def _read_run_claims(run_id: str, workdir: Path, limit: int = 3000) -> list[dict[str, Any]]:
    """Expose the run's claims as evidence rows for goal binding (§20).

    Claims carry ``field_name`` from the extraction contract; the orchestrator
    binds each row to goals whose ``required_evidence`` contains that field —
    deterministic, explicit, and audit-traced in goal.evidence_refs.
    """
    from enterprise_energy_research.evidence.store import EvidenceStore

    store = EvidenceStore(Path(workdir) / run_id / "evidence.sqlite3")
    try:
        claims = store.list(run_id, "claim")
    except Exception:
        return []
    field_to_families = _field_to_families()
    rows: list[dict[str, Any]] = []
    for claim in claims[:limit]:
        # §20 attribution chain (company-agnostic by construction):
        # 1) LLM-declared goal_family (extraction), 2) originating query topic
        # (locator._routing.topic, always present for pipeline claims),
        # 3) extraction-contract inverse lookup. Unresolved rows stay at
        # mission level and surface as gaps — never silently dropped.
        families: list[str] = []
        if claim.goal_family:
            families = [claim.goal_family]
        if not families:
            routing_topic = (claim.locator or {}).get("_routing", {}).get("topic")
            if routing_topic:
                families = [str(routing_topic)]
        if not families:
            families = list(field_to_families.get(claim.field_name, []))
        if not families:
            for field, mapped in field_to_families.items():
                if field in claim.field_name or claim.field_name in field:
                    families = mapped
                    break
        rows.append({
            "claim_id": claim.claim_id,
            "run_id": run_id,
            "field_name": claim.field_name,
            "goal_families": families,
            "raw_value": claim.value,
            "verification_status": claim.verification_status.value,
            "source_id": claim.source_id,
            "subject_role": "SUBJECT",
            "goal_id": "",  # bound via required_evidence contract
        })
    return rows


def build_enterprise_executor(executor: Any, workdir: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Adapter: agent contract -> the mature enterprise research pipeline.

    Reuses OrchestratingExecutor.research_and_validate (or a compatible
    execute()) without re-implementing any research logic (§70).
    """

    def run_enterprise(spec: dict[str, Any]) -> dict[str, Any]:
        from enterprise_energy_research.automation.contracts import ResearchRequest as AutomationResearchRequest
        from enterprise_energy_research.automation.enums import ResearchType
        from enterprise_energy_research.domain.ids import new_sortable_id

        requirements = [str(item) for item in (spec.get("requirements") or []) if str(item).strip()]
        recovery_queries = [str(item) for item in (spec.get("recovery_queries") or []) if str(item).strip()]
        # The production pipeline consumes user requirements from
        # optional_scope.notes (automation/orchestration.py) and routes them
        # semantically via planner.requirement_intents/requirement_queries.
        notes_lines = requirements + [f"第{spec.get('recovery_round') or 0}轮补采：{query}" for query in recovery_queries]
        canonical = str(spec.get("canonical_subject") or "").strip()
        request = AutomationResearchRequest(
            task_id=spec.get("request_id") or new_sortable_id("AGENTTASK"),
            requested_by="energy-research-agent",
            company=canonical or None,
            research_type=ResearchType.COMPANY_PROFILE if canonical else ResearchType.MARKET_ENTRY,
            notes="\n".join(notes_lines) or None,
        )
        run_id = new_sortable_id("AGENTENT")
        try:
            if hasattr(executor, "research_and_validate"):
                outcome = executor.research_and_validate(
                    run_id, request, workdir,
                    recovery_only=int(spec.get("recovery_round") or 0) > 0,
                )
            elif hasattr(executor, "execute"):
                outcome = executor.execute(run_id, request)
            else:
                return {"status": "UNAVAILABLE", "failure_class": "ADAPTER_FAILURE", "diagnostics": ["no enterprise executor"]}
        except Exception as exc:  # executor boundary is normalized; keep the real reason for audit
            return {
                "status": "UNAVAILABLE",
                "failure_class": "ADAPTER_FAILURE",
                "diagnostics": [f"{type(exc).__name__}: {exc}"[:500]],
            }
        payload = outcome.model_dump() if hasattr(outcome, "model_dump") else dict(outcome)
        # Honest status mapping: the agent's recovery loop must see BLOCKED
        # validation as such, never as a success (§63 agent cannot self-declare).
        # Publication happens after synthesis via the publish callback; here we
        # only carry research + validation state.
        validation_status = payload.get("validation_status")
        status = "BLOCKED" if validation_status == "BLOCKED" else "OK"
        diagnostics = []
        if status == "BLOCKED":
            diagnostics.append(f"enterprise validation blocked: evidence={payload.get('evidence_count', 0)}")
        # Research-stage review reasons (saturation findings, adapter gaps,
        # hydration/extraction failures) must survive the skill boundary so
        # the mission review can show WHY evidence is thin instead of an
        # unexplained BLOCKED.
        diagnostics.extend(
            str(reason) for reason in (payload.get("review_reasons") or [])[:12]
        )
        # §20 evidence rows: expose the run's claims so the orchestrator can
        # bind them to goals deterministically (field_name -> required_evidence).
        evidence_rows = _read_run_claims(run_id, workdir)
        return {
            "status": status,
            "run_id": run_id,
            "coverage_metrics": {
                "evidence_count": payload.get("evidence_count", 0),
                "verified_claim_count": payload.get("verified_claim_count", 0),
                "gap_count": payload.get("gap_count", 0),
                "conflict_count": payload.get("conflict_count", 0),
            },
            "quality_metrics": {"validation_status": validation_status},
            "artifact_refs": [],
            "evidence_rows": evidence_rows,
            "gaps": [{"type": "coverage_gap"} for _ in range(int(payload.get("gap_count", 0)))],
            "recovery_round": int(spec.get("recovery_round") or 0),
            "queries": list(spec.get("recovery_queries") or []),
            "diagnostics": diagnostics,
        }

    return run_enterprise


def build_agent_orchestrator(executor: Any, workdir: Path) -> ResearchOrchestratorAgent:
    """Assemble the agent from environment config, fail-closed where needed."""
    from enterprise_energy_research.evidence.store import EvidenceStore
    from enterprise_energy_research.settings import Settings

    gateway = None
    try:
        settings = Settings()
        if settings.deepseek_api_key or settings.openai_api_key:
            from enterprise_energy_research.gateway import LiteLLMModelGateway

            gateway = LiteLLMModelGateway(settings)
    except Exception as exc:  # fail-closed: agent runs degraded, never crashes the app
        logger.warning("agent gateway unavailable, running degraded: %s", exc)

    from .models import SkillName
    from .mission_store import MissionStore
    from .publication import publish_unified

    workdir = Path(workdir)
    evidence_store = EvidenceStore(workdir / "agent_evidence.sqlite3")

    def _unified_publish(spec: dict[str, Any]) -> dict[str, Any]:
        """§37: one artifact owner after synthesis; market store merges in."""
        market_run_id = f"agent-{spec['mission_id']}"
        return publish_unified(
            workdir=workdir,
            enterprise_run_id=str(spec.get("enterprise_run_id") or ""),
            findings=list(spec.get("findings") or []),
            sub_artifact_refs=list(spec.get("sub_artifact_refs") or []),
            recovery_run_ids=list(spec.get("recovery_run_ids") or []),
            market_evidence_store=evidence_store,
            market_run_id=market_run_id,
        )

    skills = {
        SkillName.ENTERPRISE_RESEARCH: EnterpriseResearchSkill(
            build_enterprise_executor(executor, workdir),
            publish_cb=_unified_publish,
        ),
        SkillName.OVERSEAS_MARKET_RESEARCH: OverseasMarketResearchAdapter(),
    }
    return ResearchOrchestratorAgent(
        gateway=gateway,
        skills=skills,
        evidence_store=evidence_store,
        store=MissionStore(workdir / "agent_store.sqlite3"),
    )


def create_agent_router(
    orchestrator: ResearchOrchestratorAgent,
    notifier: Any | None = None,
) -> APIRouter:
    router = APIRouter()
    _run_lock = threading.Lock()
    _running: set[str] = set()

    def _run_in_background(
        mission_id: str,
        background: BackgroundTasks,
        runner: Callable[[str], AgentOutcome],
        *,
        label: str,
    ) -> None:
        if mission_id in _running:
            raise HTTPException(status_code=409, detail="mission already running")

        def _run() -> None:
            with _run_lock:
                _running.add(mission_id)
            try:
                outcome = runner(mission_id)
                if notifier is not None and hasattr(notifier, "send_text"):
                    try:
                        notifier.send_text(
                            f"{label}完成\n"
                            f"任务：{outcome.mission.primary_subject or outcome.mission.mission_id}\n"
                            f"状态：{outcome.status.value}\n"
                            f"交付物：{', '.join(outcome.mission.artifact_refs) or '（无，见任务详情）'}"
                        )
                    except Exception as exc:  # notification must never crash the run
                        logger.warning("agent feishu notify failed: %s", exc)
                    # 成果文件随消息送达（正文消息 + 文件消息），与主调查交付方式一致；
                    # artifact_refs 已是发布成功的交付物路径，逐个上传，失败仅告警。
                    adapter = getattr(notifier, "adapter", notifier)
                    send_file = getattr(adapter, "send_file", None) if adapter is not None else None
                    if send_file is not None:
                        for ref in outcome.mission.artifact_refs:
                            try:
                                path = Path(ref)
                                if not path.is_file():
                                    continue
                                delivery = send_file("", str(path), file_name=path.name)
                                if not delivery.delivered:
                                    logger.warning(
                                        "agent feishu file notify failed: %s", delivery.diagnostics
                                    )
                            except Exception as exc:  # per-file failure never blocks others
                                logger.warning("agent feishu file notify failed: %s", exc)
            except Exception as exc:  # background boundary: record, never kill the loop
                logger.exception("agent %s %s failed: %s", label, mission_id, exc)
                orchestrator.store.trace(mission_id, "failed", {"error": type(exc).__name__})
            finally:
                with _run_lock:
                    _running.discard(mission_id)

        background.add_task(_run)

    def _start_in_background(mission_id: str, background: BackgroundTasks) -> None:
        _run_in_background(
            mission_id, background,
            orchestrator.run_approved,
            label="Agent 研究任务",
        )

    @router.post("/parse")
    def parse_mission(payload: ParseRequest) -> dict:
        track = payload.track.strip().lower() if payload.track.strip().lower() in {"enterprise", "market"} else None
        outcome = orchestrator.parse_and_plan(payload.raw_request, track=track)
        preview = _mission_preview(outcome)
        preview["diagnostics"] = outcome.diagnostics
        return preview

    @router.post("/mission/{mission_id}/approve")
    def approve_mission(mission_id: str, payload: ApproveRequest, background: BackgroundTasks) -> dict:
        mission = orchestrator.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found")
        if mission.status == MissionStatus.CANCELLED:
            raise HTTPException(status_code=409, detail="任务已停止；如需继续研究请新建任务")
        approval = MissionApproval(
            approval_id=f"APPROVAL-{mission_id}",
            mission_id=mission_id,
            decision=ApprovalStatus.APPROVED if payload.approve else ApprovalStatus.REJECTED,
            scope_summary=f"{mission.mode.value} / {len(mission.goals)} goals / {mission.primary_subject}",
            message=payload.message or None,
        )
        orchestrator.store.record_approval(approval)
        if approval.decision == ApprovalStatus.APPROVED:
            mission.approval_status = ApprovalStatus.APPROVED
            mission.status = MissionStatus.APPROVED
            orchestrator.store.upsert_mission(mission)
            orchestrator.store.trace(mission_id, "approved", {"approval_id": approval.approval_id})
            _start_in_background(mission_id, background)
        else:
            mission.status = MissionStatus.BLOCKED
            orchestrator.store.upsert_mission(mission)
            orchestrator.store.trace(mission_id, "rejected", {"approval_id": approval.approval_id})
        return {"mission_id": mission_id, "approval": approval.decision.value}

    @router.post("/mission/{mission_id}/start")
    def start_mission(mission_id: str, background: BackgroundTasks) -> dict:
        mission = orchestrator.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found")
        if mission.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(status_code=409, detail="mission not approved; the agent cannot self-approve")
        _start_in_background(mission_id, background)
        return {"mission_id": mission_id, "status": "STARTED"}

    @router.post("/mission/{mission_id}/continue")
    def continue_mission(mission_id: str, payload: ContinueRequest) -> dict:
        outcome = orchestrator.continue_mission(mission_id, payload.raw_request)
        return _mission_preview(outcome)

    @router.post("/mission/{mission_id}/stop")
    def stop_mission(mission_id: str) -> dict:
        """停止调查：海外采集进程立即终止；企业管线在当前步骤完成后停止。"""
        try:
            return orchestrator.request_stop(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.post("/mission/{mission_id}/goals")
    def edit_goals(mission_id: str, payload: GoalEditRequest) -> dict:
        """开始研究前修改研究框架：改名/删除/新增目标（最终状态语义）。"""
        items = [item.model_dump() for item in payload.goals]
        if orchestrator.store.get_mission(mission_id) is None:
            raise HTTPException(status_code=404, detail="mission not found")
        try:
            outcome = orchestrator.update_goals(mission_id, items)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        preview = _mission_preview(outcome)
        preview["diagnostics"] = outcome.diagnostics
        return preview

    @router.post("/mission/{mission_id}/deep-research")
    def start_deep_research(mission_id: str, payload: DeepResearchRequest, background: BackgroundTasks) -> dict:
        """深度研究：锁定已完成的任务，补充新需求并修复未达标目标。"""
        mission = orchestrator.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found")
        if mission.status.value not in {"COMPLETED", "PARTIAL", "EXHAUSTED", "BLOCKED"}:
            raise HTTPException(
                status_code=409,
                detail=f"仅已产出成果的任务可深度研究；当前状态 {mission.status.value}",
            )
        _run_in_background(
            mission_id, background,
            lambda mid: orchestrator.deep_research(mid, payload.raw_request),
            label="Agent 深度研究",
        )
        return {
            "mission_id": mission_id,
            "status": "STARTED",
            "message": "深度研究已启动：解析补充需求 + 修复未达标目标，完成后自动重新发布交付物",
        }

    @router.get("/mission/{mission_id}")
    def mission_detail(mission_id: str) -> dict:
        mission = orchestrator.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found")
        return {
            "mission": mission.model_dump(mode="json"),
            "trace": orchestrator.store.trace_for(mission_id),
            "approval": (
                orchestrator.store.latest_approval(mission_id).model_dump(mode="json")
                if orchestrator.store.latest_approval(mission_id) else None
            ),
        }

    @router.get("/mission/{mission_id}/debug")
    def mission_debug(mission_id: str) -> dict:
        """§50 advanced debug view: metrics, skill runs, recovery, trace."""
        mission = orchestrator.store.get_mission(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found")
        skill_runs = orchestrator.store.skill_runs_for(mission_id)
        return {
            "mission_id": mission_id,
            "mode": mission.mode.value,
            "subject": mission.primary_subject,
            "status": mission.status.value,
            "metrics": orchestrator.store.metrics_for(mission_id),
            "goals": [
                {
                    "goal_id": goal.goal_id,
                    "name": goal.goal_name,
                    "goal_class": goal.goal_class.value,
                    "skill": goal.assigned_skill.value if goal.assigned_skill else None,
                    "status": goal.status.value,
                    "recovery_rounds": goal.recovery_rounds,
                    "routing_reason": goal.routing_reason,
                }
                for goal in mission.goals
            ],
            "skill_runs": [
                {
                    "skill_name": item["skill_name"],
                    "status": (item["payload"] or {}).get("status"),
                    "failure_class": (item["payload"] or {}).get("failure_class"),
                    "coverage": (item["payload"] or {}).get("coverage_metrics"),
                    "attempts": len((item["payload"] or {}).get("attempts", [])),
                    "completed_at": item["completed_at"],
                }
                for item in skill_runs
            ],
            "recovery_ledger": {
                goal.goal_id: goal.recovery_rounds for goal in mission.goals if goal.recovery_rounds
            },
            "trace": orchestrator.store.trace_for(mission_id, limit=1000),
        }

    @router.get("/missions")
    def list_missions(limit: int = 50, status: str = "", query: str = "") -> dict:
        """任务列表；支持按状态过滤（逗号分隔）与自然语言名称模糊查找。"""
        pool = orchestrator.store.list_missions(limit=500)
        wanted = {part.strip().upper() for part in status.split(",") if part.strip()}
        needle = query.strip().casefold()
        missions = []
        for mission in pool:
            if wanted and mission.status.value not in wanted:
                continue
            if needle and not any(
                needle in text.casefold()
                for text in (mission.primary_subject, mission.raw_request, mission.mission_id)
                if text
            ):
                continue
            missions.append(mission)
        return {
            "missions": [
                {
                    "mission_id": mission.mission_id,
                    "mode": mission.mode.value,
                    "primary_subject": mission.primary_subject,
                    "status": mission.status.value,
                    "created_at": mission.created_at.isoformat(),
                    "updated_at": mission.updated_at.isoformat(),
                    "goal_summary": {
                        "total": len(mission.goals),
                        "satisfied": sum(1 for g in mission.goals if g.status == GoalStatus.SATISFIED),
                        "exhausted": sum(1 for g in mission.goals if g.status == GoalStatus.EXHAUSTED),
                        "blocked": sum(1 for g in mission.goals if g.status == GoalStatus.BLOCKED),
                        "partial": sum(1 for g in mission.goals if g.status == GoalStatus.PARTIAL),
                    },
                    "artifact_count": len(mission.artifact_refs),
                }
                for mission in missions[:limit]
            ]
        }

    @router.get("/health")
    def agent_health(request: Request) -> dict:
        return {
            "agent_enabled": getattr(request.app.state, "agent_enabled", False),
            "gateway": orchestrator.gateway is not None,
            "skills": sorted(skill.value for skill in orchestrator.skills),
            "policies": {
                "max_recovery_rounds_per_goal": orchestrator.policies.max_recovery_rounds_per_goal,
                "max_agent_iterations": orchestrator.policies.max_agent_iterations,
                "unified_mission_approval": orchestrator.policies.unified_mission_approval,
            },
        }

    return router
