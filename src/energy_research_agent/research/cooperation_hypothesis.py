"""Convert discovered opportunity candidates into falsifiable cooperation hypotheses."""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from energy_research_agent.domain.models import FrozenResearchBundle, Solution
from energy_research_agent.research.client_profile import ClientProfile, client_profile_from_manifest
from energy_research_agent.research.strategic_interpretation import StrategicInterpretation


class CooperationHypothesisStatus(str, Enum):
    PRIORITY_OPPORTUNITY = "PRIORITY_OPPORTUNITY"
    POTENTIAL_HYPOTHESIS = "POTENTIAL_HYPOTHESIS"
    REJECTED = "REJECTED"


class CooperationHypothesis(BaseModel):
    hypothesis_id: str
    candidate_solution_ids: list[str]
    opportunity_type: str
    opportunity_name: str
    status: CooperationHypothesisStatus
    target_problem: str
    why_now: str
    client_capability_match: list[str] = Field(default_factory=list)
    client_capability_statuses: list[str] = Field(default_factory=list)
    value_creation_logic: str
    target_department: str
    recommended_action: str
    evidence_claim_ids: list[str] = Field(default_factory=list)
    evidence_source_ids: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disconfirming_conditions: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def priority_contract(self) -> "CooperationHypothesis":
        if self.status == CooperationHypothesisStatus.PRIORITY_OPPORTUNITY:
            required = [self.target_problem, self.why_now, self.client_capability_match,
                        self.value_creation_logic, self.target_department,
                        self.evidence_claim_ids, self.disconfirming_conditions]
            if not all(required):
                raise ValueError("priority opportunity does not satisfy cooperation hypothesis contract")
            if "UNKNOWN_CLIENT_CAPABILITY" in self.client_capability_statuses:
                raise ValueError("unknown client capability cannot support priority opportunity")
        return self


class CooperationHypothesisEngine:
    """Opportunity Registry is discovery only; this engine may reject it."""

    PROBLEM_FIELDS = {
        "risk", "regulatory_risk", "customer_concentration", "gross_margin",
        "profit", "carbon_emissions", "carbon_target", "energy_cost",
        "technology_route", "supply_chain", "order", "contract",
    }

    def build(
        self,
        bundle: FrozenResearchBundle,
        strategic: StrategicInterpretation,
        client: ClientProfile | None = None,
    ) -> list[CooperationHypothesis]:
        client = client or client_profile_from_manifest(bundle.run_manifest)
        claims = {claim.claim_id: claim for claim in bundle.claims}
        results: list[CooperationHypothesis] = []
        for solution in bundle.solutions:
            evidence = [claims[cid] for cid in solution.claim_ids if cid in claims]
            source_ids = list(dict.fromkeys(claim.source_id for claim in evidence))
            problem_claims = [claim for claim in evidence if claim.field_name in self.PROBLEM_FIELDS or "risk" in claim.field_name]
            capability_matches = client.capability_matches(solution.engine)
            supported_capabilities = [item for item in capability_matches if item.supports_formal_recommendation]
            why_now_lineage = [
                claim_id for item in [*strategic.trajectories, *strategic.priorities, *strategic.turning_points]
                for claim_id in item.lineage.claim_ids
            ]
            why_now_claims = [claims[cid] for cid in why_now_lineage if cid in claims]
            why_now = self._why_now(strategic)
            target_problem = self._target_problem(solution, problem_claims)
            value_logic = self._value_logic(solution)
            department = self._department(solution.engine)
            rejection: list[str] = []
            if not evidence:
                rejection.append("候选方向没有可追溯企业证据")
            if not problem_claims:
                rejection.append("现有资料只有产品、产能或场景信息，未显示对方提出具体合作需求")
            if not why_now_claims:
                rejection.append("缺少能够说明近期业务安排发生变化的公开依据")
            if not supported_capabilities:
                rejection.append("创新中心尚未确认可用于该方向的人员、技术或客户资源")
            if solution.engine in {"PRODUCT_COOPERATION", "CHANNEL", "STORAGE"} and not problem_claims:
                rejection.append("现有产品或客户信息不足以支持正式接洽")
            hard_failure = not evidence or not capability_matches
            contract_pass = bool(problem_claims and why_now_claims and supported_capabilities and value_logic and department)
            status = (
                CooperationHypothesisStatus.PRIORITY_OPPORTUNITY if contract_pass
                else CooperationHypothesisStatus.REJECTED if hard_failure
                else CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS
            )
            hypothesis_id = "CH-" + hashlib.sha256(
                f"{solution.engine}|{solution.opportunity}|{','.join(sorted(solution.claim_ids))}".encode("utf-8")
            ).hexdigest()[:12]
            results.append(CooperationHypothesis(
                hypothesis_id=hypothesis_id, candidate_solution_ids=[solution.solution_id],
                opportunity_type=solution.engine, opportunity_name=solution.opportunity, status=status,
                target_problem=target_problem, why_now=why_now,
                client_capability_match=[item.name for item in capability_matches],
                client_capability_statuses=[item.status.value for item in capability_matches] or ["UNKNOWN_CLIENT_CAPABILITY"],
                value_creation_logic=value_logic, target_department=department,
                recommended_action=self._recommended_action(status, solution, department),
                evidence_claim_ids=[claim.claim_id for claim in evidence], evidence_source_ids=source_ids,
                counterevidence=[risk for risk in solution.risks if risk],
                assumptions=list(solution.assumptions),
                disconfirming_conditions=self._disconfirming_conditions(solution),
                rejection_reasons=list(dict.fromkeys(rejection)),
                confidence=min(0.9, 0.35 + 0.1 * len(source_ids) + (0.2 if contract_pass else 0.0)),
            ))
        return sorted(results, key=lambda item: ({"PRIORITY_OPPORTUNITY": 3, "POTENTIAL_HYPOTHESIS": 2, "REJECTED": 1}[item.status.value], item.confidence), reverse=True)

    @staticmethod
    def _why_now(strategic: StrategicInterpretation) -> str:
        if strategic.turning_points:
            item = strategic.turning_points[-1]
            return f"{item.period} 年公司披露“{item.event}”。这一变化可能带来新的协同需求，仍需向相关业务部门确认。"
        if strategic.trajectories:
            return strategic.trajectories[0].direction
        if strategic.priorities:
            return f"企业已公开披露“{strategic.priorities[0].name}”这一战略优先事项。"
        return "公开资料尚未显示近期出现明确的合作需求。"

    @staticmethod
    def _target_problem(solution: Solution, problem_claims: list) -> str:
        if problem_claims:
            return "；".join(str(claim.value) for claim in problem_claims[:3])
        return f"公开资料尚未显示公司对“{solution.opportunity}”有明确需求。"

    @staticmethod
    def _value_logic(solution: Solution) -> str:
        value = solution.benefit_logic.strip() if solution.benefit_logic else ""
        if value != "价值取决于经核验的现场数据与可审计基线，公开信息不足时不承诺收益":
            return value
        # Translate the legacy catch-all sentence at the analysis boundary so
        # old frozen evidence can be republished without leaking the template.
        if solution.engine in {"JOINT_RND", "PRODUCT_COOPERATION", "ODM", "SUPPLY_CHAIN"}:
            return (
                "通过联合技术验证、产品适配或供应链协同缩短开发与导入周期；"
                "具体贡献需由双方在明确课题、指标和交付边界后确认"
            )
        if solution.engine == "OVERSEAS":
            return "通过市场准入、本地资源和交付协同降低海外项目落地难度，合作范围按目标市场逐项确定"
        if solution.engine == "CHANNEL":
            return "通过渠道覆盖和客户触达增加有效销售机会，合作前需明确客户归属、区域和分成规则"
        return (
            "通过降低用能成本、提高供能稳定性或减少碳排放形成项目价值；"
            "容量和收益须按具体基地的实际数据测算"
        )

    @staticmethod
    def _department(engine: str) -> str:
        if engine in {"PRODUCT_COOPERATION", "JOINT_RND", "ODM", "SUPPLY_CHAIN", "CHANNEL"}:
            return "产品、研发或供应链责任部门"
        if engine in {"PV_EPC", "STORAGE", "ENERGY_EFFICIENCY", "ZERO_CARBON_FACTORY", "ENERGY_MANAGEMENT", "ENERGY_DIGITALIZATION"}:
            return "能源、可持续发展或基地运营责任部门"
        if engine == "OVERSEAS":
            return "海外业务与战略责任部门"
        return "战略与目标业务责任部门"

    @staticmethod
    def _recommended_action(status: CooperationHypothesisStatus, solution: Solution, department: str) -> str:
        if status == CooperationHypothesisStatus.PRIORITY_OPPORTUNITY:
            return f"先与{department}确定一个具体课题，明确技术指标、双方分工和知识产权边界，再讨论立项。"
        if status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS:
            return f"先向{department}确认是否存在具体需求；未获得明确需求前不进入立项。"
        return "现有资料不足以支持主动接洽，出现新的企业需求或合作条件后再评估。"

    @staticmethod
    def _disconfirming_conditions(solution: Solution) -> list[str]:
        return list(dict.fromkeys([
            f"对方未将“{solution.opportunity}”列入当前工作重点",
            "双方技术路线或交付范围无法对齐",
            "创新中心现有资源无法承担所需的组织或验证工作",
            *[f"经核实存在以下限制：{risk}" for risk in solution.risks[:2]],
        ]))
