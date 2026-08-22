"""Canonical, evidence-bound opportunity assessment and prioritization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field, model_validator

from enterprise_energy_research.domain.models import FrozenResearchBundle, Solution


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

    @model_validator(mode="after")
    def evidence_and_gate_required(self) -> "OpportunityAssessment":
        if not self.supporting_claim_ids or not self.supporting_source_ids:
            raise ValueError("opportunity assessment requires evidence lineage")
        if not all((self.strategic_rationale, self.target_scenario, self.entry_point, self.go_no_go_gate)):
            raise ValueError("opportunity must explain why, where, how and its gate")
        return self


class OpportunityAssessmentEngine:
    """Deduplicate before analysis, merge evidence, then score and rank."""

    def assess(self, bundle: FrozenResearchBundle) -> list[OpportunityAssessment]:
        claims = {claim.claim_id: claim for claim in bundle.claims}
        grouped: dict[str, list[Solution]] = defaultdict(list)
        for solution in bundle.solutions:
            if not solution.claim_ids:
                continue
            grouped[opportunity_canonical_key(solution)].append(solution)
        assessments: list[OpportunityAssessment] = []
        for index, (canonical_key, solutions) in enumerate(grouped.items(), start=1):
            primary = sorted(solutions, key=lambda item: self._priority_score(item.priority), reverse=True)[0]
            claim_ids = list(dict.fromkeys(claim_id for solution in solutions for claim_id in solution.claim_ids if claim_id in claims))
            source_ids = list(dict.fromkeys(claims[claim_id].source_id for claim_id in claim_ids))
            if not claim_ids or not source_ids:
                continue
            evidence_strength = min(5, max(1, 1 + len(source_ids) + (1 if len(claim_ids) >= 3 else 0)))
            feasibility = self._feasibility(primary)
            strategic_fit = 5 if primary.priority == "A" else 4 if primary.priority == "B" else 3
            commercial = max(1, min(5, round((strategic_fit + feasibility + evidence_strength) / 3)))
            priority = self._priority(strategic_fit, feasibility, evidence_strength, commercial)
            prerequisites = list(dict.fromkeys(
                requirement for solution in solutions for requirement in solution.data_requirements
            )) or ["目标场景原始数据", "技术与商务责任边界"]
            risks = list(dict.fromkeys(risk for solution in solutions for risk in solution.risks))
            target_scenario = self._target_scenario(primary)
            entry = self._entry_point(primary)
            assessments.append(OpportunityAssessment(
                opportunity_id=f"OA-{index:03d}", canonical_key=canonical_key,
                opportunity_name=primary.opportunity,
                target_scenario=target_scenario,
                strategic_rationale=(
                    f"该方向由 {len(claim_ids)} 条已核验事实和 {len(source_ids)} 个来源共同触发，"
                    "其成立前提是已披露能力能够映射到明确场景，并通过现场数据验证项目价值。"
                ),
                evidence_basis=primary.proposed_solution,
                supporting_claim_ids=claim_ids, supporting_source_ids=source_ids,
                target_need=self._target_need(primary),
                our_value_proposition=(
                    "提供场景诊断、数据边界梳理、技术适配与预可研，把公开能力转化为可审计的项目判断。"
                ),
                entry_point=entry,
                strategic_fit=strategic_fit,
                implementation_feasibility=feasibility,
                evidence_strength=evidence_strength,
                commercial_potential=commercial,
                priority=priority,
                key_prerequisites=prerequisites,
                key_risks=risks or ["数据口径不一致", "责任边界未确认"],
                first_30_day_action=f"由联合项目组对接{entry}，确认场景、资料清单和一处优先验证对象。",
                day_60_action="完成资料清洗、现场核验、技术适配与初步价值测算，并形成问题闭环清单。",
                day_90_milestone="提交预可研结论和 Go / No-Go 评审材料，决定进入方案设计、继续补数或停止。",
                owner="联合项目组",
                success_kpi="关键资料齐套率 100%，完成一处场景预可研并形成书面决策结论",
                go_no_go_gate=(
                    "关键数据完整、技术接口可行、责任主体明确且价值测算通过敏感性检验后方可 Go；"
                    "任何一项不满足则 No-Go 或返回补数。"
                ),
                confidence=min(0.95, 0.45 + evidence_strength * 0.08 + feasibility * 0.03),
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

