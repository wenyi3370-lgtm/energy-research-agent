"""Canonical, evidence-bound opportunity assessment and prioritization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field, model_validator

from enterprise_energy_research.domain.models import FrozenResearchBundle, Solution
from enterprise_energy_research.research.client_profile import client_profile_from_manifest
from enterprise_energy_research.research.cooperation_hypothesis import (
    CooperationHypothesisEngine, CooperationHypothesisStatus,
)
from enterprise_energy_research.research.strategic_interpretation import (
    StrategicInterpretation, StrategicInterpretationEngine,
)


SYNONYM_MAP = {
    "产品联合合作": "产品合作",
    "联合产品合作": "产品合作",
    "用户侧储能": "用户侧储能",
    "工商业储能": "用户侧储能",
    "分布式光伏epc": "分布式光伏",
    "光伏epc": "分布式光伏",
    "能源数字化管理": "能源数字化",
}


def canonicalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    text = re.sub(r"[\s\-_—–·,，。；;:：/\\()（）\[\]【】]+", "", text)
    return SYNONYM_MAP.get(text, text)


def opportunity_canonical_key(solution: Solution) -> str:
    payload = "|".join((
        canonicalize_text(solution.opportunity),
        canonicalize_text(solution.proposed_solution),
        canonicalize_text(solution.next_step),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class OpportunityAssessment(BaseModel):
    opportunity_id: str
    canonical_key: str
    opportunity_name: str
    target_scenario: str
    strategic_rationale: str
    evidence_basis: str
    supporting_claim_ids: list[str]
    supporting_source_ids: list[str]
    target_need: str
    our_value_proposition: str
    entry_point: str
    strategic_fit: int = Field(ge=1, le=5)
    implementation_feasibility: int = Field(ge=1, le=5)
    evidence_strength: int = Field(ge=1, le=5)
    commercial_potential: int = Field(ge=1, le=5)
    priority: str
    key_prerequisites: list[str]
    key_risks: list[str]
    first_30_day_action: str
    day_60_action: str
    day_90_milestone: str
    owner: str
    success_kpi: str
    go_no_go_gate: str
    confidence: float = Field(ge=0.0, le=1.0)
    hypothesis_status: str = "POTENTIAL_HYPOTHESIS"
    target_problem: str = ""
    why_now: str = ""
    client_name: str = ""
    client_capability_match: list[str] = Field(default_factory=list)
    client_capability_statuses: list[str] = Field(default_factory=list)
    value_creation_logic: str = ""
    target_department: str = ""
    recommended_action: str = ""
    counterevidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disconfirming_conditions: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_and_gate_required(self) -> "OpportunityAssessment":
        if not self.supporting_claim_ids or not self.supporting_source_ids:
            raise ValueError("opportunity assessment requires evidence lineage")
        if not all((self.strategic_rationale, self.target_scenario, self.entry_point, self.go_no_go_gate)):
            raise ValueError("opportunity must explain why, where, how and its gate")
        return self


class OpportunityAssessmentEngine:
    """Deduplicate before analysis, merge evidence, then score and rank."""

    def assess(
        self, bundle: FrozenResearchBundle,
        strategic: StrategicInterpretation | None = None,
    ) -> list[OpportunityAssessment]:
        strategic = strategic or StrategicInterpretationEngine().interpret(bundle)
        client = client_profile_from_manifest(bundle.run_manifest)
        hypotheses = CooperationHypothesisEngine().build(bundle, strategic, client)
        claims = {claim.claim_id: claim for claim in bundle.claims}
        solutions_by_id = {solution.solution_id: solution for solution in bundle.solutions}
        assessments: list[OpportunityAssessment] = []
        seen_keys: set[str] = set()
        for index, hypothesis in enumerate(hypotheses, start=1):
            solutions = [solutions_by_id[item] for item in hypothesis.candidate_solution_ids if item in solutions_by_id]
            if not solutions:
                continue
            primary = solutions[0]
            canonical_key = opportunity_canonical_key(primary)
            if canonical_key in seen_keys:
                continue
            seen_keys.add(canonical_key)
            claim_ids = list(dict.fromkeys(hypothesis.evidence_claim_ids))
            source_ids = list(dict.fromkeys(claims[claim_id].source_id for claim_id in claim_ids))
            if not claim_ids or not source_ids:
                continue
            evidence_strength = min(5, max(1, 1 + len(source_ids) + (1 if len(claim_ids) >= 3 else 0)))
            feasibility = self._feasibility(primary)
            strategic_fit = 5 if hypothesis.status == CooperationHypothesisStatus.PRIORITY_OPPORTUNITY else 3 if hypothesis.status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS else 1
            commercial = max(1, min(5, round((strategic_fit + feasibility + evidence_strength) / 3)))
            priority = self._priority(strategic_fit, feasibility, evidence_strength, commercial)
            if hypothesis.status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS:
                priority = "C"
            elif hypothesis.status == CooperationHypothesisStatus.REJECTED:
                priority = "HOLD"
            prerequisites = list(dict.fromkeys(
                requirement for solution in solutions for requirement in solution.data_requirements
            )) or ["对方业务部门确认的具体需求", "双方认可的计算口径和验证结果"]
            risks = list(dict.fromkeys(risk for solution in solutions for risk in solution.risks))
            target_scenario = self._target_scenario(primary)
            entry = self._entry_point(primary)
            assessments.append(OpportunityAssessment(
                opportunity_id=f"OA-{index:03d}", canonical_key=canonical_key,
                opportunity_name=primary.opportunity,
                target_scenario=target_scenario,
                strategic_rationale=f"业务事项：{hypothesis.target_problem} 近期变化：{hypothesis.why_now}",
                evidence_basis=primary.proposed_solution,
                supporting_claim_ids=claim_ids, supporting_source_ids=source_ids,
                target_need=hypothesis.target_problem,
                our_value_proposition=hypothesis.value_creation_logic,
                entry_point=hypothesis.target_department,
                strategic_fit=strategic_fit,
                implementation_feasibility=feasibility,
                evidence_strength=evidence_strength,
                commercial_potential=commercial,
                priority=priority,
                key_prerequisites=prerequisites,
                key_risks=risks,
                first_30_day_action=(
                    f"与{hypothesis.target_department}确认是否有与“{primary.opportunity}”相关的当前需求，"
                    "并确定一名业务负责人。"
                ),
                day_60_action=(
                    f"由{client.client_name}与对方围绕“{primary.opportunity}”选择一个具体课题，"
                    "明确技术指标、所需数据、双方分工和知识产权边界。"
                ),
                day_90_milestone=f"根据课题验证结果决定立项、缩小范围或结束“{primary.opportunity}”接洽。",
                owner=f"{client.client_name}与{hypothesis.target_department}",
                success_kpi="对方需求、课题指标、双方分工和下一步投入均有书面结论",
                go_no_go_gate="仅在对方确认需求、课题可量化且双方能够落实资源时立项；任一条件不满足则缩小范围或结束接洽。",
                confidence=hypothesis.confidence,
                hypothesis_status=hypothesis.status.value,
                target_problem=hypothesis.target_problem, why_now=hypothesis.why_now,
                client_name=client.client_name,
                client_capability_match=hypothesis.client_capability_match,
                client_capability_statuses=hypothesis.client_capability_statuses,
                value_creation_logic=hypothesis.value_creation_logic,
                target_department=hypothesis.target_department,
                recommended_action=hypothesis.recommended_action,
                counterevidence=hypothesis.counterevidence, assumptions=hypothesis.assumptions,
                disconfirming_conditions=hypothesis.disconfirming_conditions,
                rejection_reasons=hypothesis.rejection_reasons,
            ))
        assessments.sort(
            key=lambda item: (
                self._priority_score(item.priority), item.strategic_fit,
                item.evidence_strength, item.implementation_feasibility,
            ),
            reverse=True,
        )
        return assessments

    @staticmethod
    def _priority_score(value: str) -> int:
        return {"A": 4, "B": 3, "C": 2, "HOLD": 1}.get(value, 0)

    @staticmethod
    def _feasibility(solution: Solution) -> int:
        lower = " ".join(solution.data_requirements + solution.risks).casefold()
        if any(token in lower for token in ("负荷", "现场", "权属", "并网", "经济性")):
            return 2
        return 3 if solution.data_requirements else 4

    @staticmethod
    def _priority(strategic: int, feasibility: int, evidence: int, commercial: int) -> str:
        score = strategic * 0.3 + feasibility * 0.25 + evidence * 0.25 + commercial * 0.2
        if evidence <= 1 or feasibility <= 1:
            return "HOLD"
        if score >= 4.1:
            return "A"
        if score >= 3.0:
            return "B"
        return "C"

    @staticmethod
    def _target_scenario(solution: Solution) -> str:
        mapping = {
            "PV_EPC": "具备可利用屋面和明确并网边界的生产基地",
            "STORAGE": "存在峰谷价差、需量压力或可调负荷的生产基地",
            "ENERGY_EFFICIENCY": "能耗边界可计量、主要设备运行数据可取得的生产系统",
            "PRODUCT_COOPERATION": "双方产品接口明确、客户场景可联合验证的业务环节",
            "ZERO_CARBON_FACTORY": "具备能碳数据基础和明确减排目标的生产基地",
            "OVERSEAS": "目标市场准入、碳足迹与本地交付责任明确的海外项目",
        }
        return mapping.get(solution.engine, "与已核验能力直接相关且数据边界清晰的优先场景")

    @staticmethod
    def _entry_point(solution: Solution) -> str:
        if solution.engine in {"PV_EPC", "STORAGE", "ENERGY_EFFICIENCY", "ZERO_CARBON_FACTORY", "ENERGY_MANAGEMENT"}:
            return "能源管理、基建或工厂运营责任部门"
        if solution.engine in {"PRODUCT_COOPERATION", "JOINT_RND", "ODM"}:
            return "产品、研发与供应链责任部门"
        return "战略合作与目标业务责任部门"

    @staticmethod
    def _target_need(solution: Solution) -> str:
        if solution.engine in {"PV_EPC", "STORAGE", "ENERGY_EFFICIENCY", "ZERO_CARBON_FACTORY"}:
            return "在不夸大收益的前提下识别能源成本、韧性或减碳改善空间"
        if solution.engine in {"PRODUCT_COOPERATION", "JOINT_RND", "ODM"}:
            return "缩短技术适配与商业验证周期，明确产品接口和责任边界"
        return "把已披露能力转化为可验证、可决策的合作场景"
