from __future__ import annotations

from enterprise_energy_research.domain.enums import StatementType
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, EnergyProfile, Entity, Solution


class SolutionEngine:
    def generate(self, entities: list[Entity], profiles: list[EnergyProfile], claims: list[Claim]) -> list[Solution]:
        verified_claims = {claim.claim_id: claim for claim in claims if claim.verification_status.value == "VERIFIED"}
        claims_by_field: dict[str, list[str]] = {}
        for claim in verified_claims.values():
            claims_by_field.setdefault(claim.field_name, []).append(claim.claim_id)
        solutions: list[Solution] = []
        for profile in profiles:
            entity = next(item for item in entities if item.entity_id == profile.entity_id)
            evidence_ids = [claim_id for claim_id in profile.claim_ids if claim_id in verified_claims]
            missing_load = profile.field_status.get("load_curve") != "observed"
            if profile.roof:
                solutions.append(self._evidence_solution(
                    "EPC", entity.entity_id, "已核验屋面条件显示具备分布式光伏筛选机会",
                    "开展屋面结构、遮挡和并网条件评估",
                    evidence_ids, "核验屋面权属与并网容量", "B",
                ))
            else:
                solutions.append(self._inference_solution(
                    "EPC", entity.entity_id, "已有屋顶光伏运行证据，但新增项目须在取得屋面数据后再筛选",
                    "先完成屋面结构、权属、遮挡、变压器余量和并网条件勘察，再测算容量与收益",
                    "缺少可用于项目测算的屋面面积、结构与并网余量数据", "HOLD",
                ))
            zero_carbon_ids = [
                claim_id
                for field in (
                    "green_electricity_transaction_volume", "roof_pv_generation", "green_factory_count",
                    "energy_management_certified_sites", "energy_efficiency_signal", "waste_heat_recovery",
                    "sichuan_factory_efficiency_improvement", "sichuan_factory_unit_energy_reduction",
                )
                for claim_id in claims_by_field.get(field, [])
            ]
            solutions.append(self._evidence_solution(
                "ZERO_CARBON", entity.entity_id,
                "绿电交易、屋顶光伏、ISO 50001 与余热回收已形成基础，适合进一步建立可审计的园区级能源碳管理体系",
                "按厂区梳理计量点位、能源边界和碳排口径，建设统一数据底座并形成持续节能核证机制",
                zero_carbon_ids,
                "选取四川、内蒙古及杉金光电重点厂区开展计量与能源数据成熟度诊断", "A",
            ))
            solutions.append(self._inference_solution(
                "STORAGE_ODM", entity.entity_id,
                "现有公开证据支持其负极材料能力，但不足以证明具备储能系统整机 ODM 能力",
                "仅在明确终端需求、品牌责任、系统集成边界与认证责任后，再评估联合产品或供应链合作",
                "缺少负荷曲线、储能应用场景、整机制造与渠道责任证据，不能直接提出功率或容量方案", "HOLD" if missing_load else "B",
            ))
            overseas_ids = [
                claim_id
                for field in ("export", "planned_overseas_project", "planned_overseas_investment")
                for claim_id in claims_by_field.get(field, [])
            ]
            solutions.append(self._evidence_solution(
                "OVERSEAS", entity.entity_id,
                "韩国、日本销售与芬兰负极材料项目规划表明其具备海外业务信号，可进一步评估海外能源配套合作",
                "围绕目标市场准入、绿电与碳足迹要求、本地 EPC/运维资源及售后责任建立分阶段进入方案",
                overseas_ids,
                "核验芬兰项目最新状态，并梳理欧洲厂区能源负荷、许可和本地合作方", "B",
            ))
        return solutions

    @staticmethod
    def _evidence_solution(engine: str, target: str, opportunity: str, proposed: str, claims: list[str], next_step: str, priority: str) -> Solution:
        if not claims:
            return SolutionEngine._inference_solution(engine, target, opportunity, proposed, "Supporting field exists but lacks a verified claim binding", "HOLD")
        return Solution(
            solution_id=new_sortable_id("SOL"), engine=engine, target_ids=[target], opportunity=opportunity,
            proposed_solution=proposed, benefit_logic="项目价值取决于经核验的现场数据与可审计基线，不在公开信息不足时承诺收益",
            data_requirements=["现场勘察", "负荷与电价数据"], risks=["权属边界", "并网容量", "数据质量"],
            next_step=next_step, priority=priority, statement_type=StatementType.EVIDENCE_SUPPORTED,
            claim_ids=claims,
        )

    @staticmethod
    def _inference_solution(engine: str, target: str, opportunity: str, proposed: str, assumption: str, priority: str) -> Solution:
        return Solution(
            solution_id=new_sortable_id("SOL"), engine=engine, target_ids=[target], opportunity=opportunity,
            proposed_solution=proposed, benefit_logic="情景价值需经现场验证；当前不主张任何节省金额或收益率",
            data_requirements=["经核验的运营数据", "商务与责任边界"], risks=["证据不足", "范围不确定"],
            next_step="补齐关键数据并与企业完成联合验证", priority=priority,
            statement_type=StatementType.ANALYTICAL_INFERENCE, assumptions=[assumption],
        )
