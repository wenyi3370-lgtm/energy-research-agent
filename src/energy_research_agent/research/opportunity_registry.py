"""Evidence-driven Opportunity Registry (P0-20).

No company is force-fed a fixed EPC / ZERO_CARBON / STORAGE_ODM / OVERSEAS
menu. Each opportunity type declares the evidence signals that justify it;
an opportunity is generated ONLY when those signals exist, otherwise it is
SKIPPED — placeholder HOLD chapters are not produced to fill space.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from energy_research_agent.domain.enums import StatementType, VerificationStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import Claim, EnergyProfile, Entity, Solution


@dataclass
class OpportunityDefinition:
    code: str
    title: str
    description_template: str
    # Claim field names or energy-profile signals that support this opportunity.
    signals: tuple[str, ...] = ()
    minimum_signals: int = 1
    priority: str = "B"
    next_step_template: str = "与目标企业完成联合验证并取得关键现场数据后推进"

    def matches(self, claim_fields: set[str], profile: EnergyProfile | None) -> tuple[bool, list[str]]:
        hits = [signal for signal in self.signals if signal in claim_fields]
        if profile is not None:
            if "roof" in self.signals and profile.roof:
                hits.append("roof")
            if "load_shape" in self.signals and profile.load_shape:
                hits.append("load_shape")
            if "electricity_equipment" in self.signals and profile.electricity_equipment:
                hits.append("electricity_equipment")
            if "gas_equipment" in self.signals and profile.gas_equipment:
                hits.append("gas_equipment")
        return len(hits) >= self.minimum_signals, list(dict.fromkeys(hits))


OPPORTUNITY_DEFINITIONS: tuple[OpportunityDefinition, ...] = (
    OpportunityDefinition(
        code="PV_EPC",
        title="分布式光伏 EPC",
        description_template="已核验屋面/光伏相关证据，具备分布式光伏 EPC 筛选条件",
        signals=("roof_area", "pv_capacity", "annual_generation", "roof"),
        minimum_signals=1,
        priority="B",
        next_step_template="核验屋面权属、遮挡、变压器余量与并网容量后再测算容量与收益",
    ),
    OpportunityDefinition(
        code="STORAGE",
        title="用户侧储能",
        description_template="已核验负荷/电价/需量相关证据，可评估储能削峰填谷价值",
        signals=("load_curve", "peak_valley_price", "demand_charge", "storage_power", "storage_capacity"),
        priority="B",
        next_step_template="取得负荷曲线与电价结构后测算储能功率、容量与经济性",
    ),
    OpportunityDefinition(
        code="V2G",
        title="V2G 车网互动",
        description_template="已核验充换电/双向充放电证据，可评估 V2G 试点",
        signals=("v2g", "bidirectional_charging", "charging_station"),
        priority="C",
        next_step_template="核验车队规模、充电设施与调度权后再设计 V2G 方案",
    ),
    OpportunityDefinition(
        code="CHARGING",
        title="充电基础设施",
        description_template="已核验充电站/车桩相关证据，可评估充电设施合作",
        signals=("charging_station", "charging_pile", "electric_vehicle_fleet"),
        priority="C",
        next_step_template="核验场地、配电容量与车流特征后再测算规模",
    ),
    OpportunityDefinition(
        code="ENERGY_EFFICIENCY",
        title="综合节能改造",
        description_template="已核验能耗/设备/节能改造证据，具备节能诊断基础",
        signals=("energy_consumption", "electricity_consumption", "energy_efficiency_signal", "energy_saving_project"),
        priority="B",
        next_step_template="按厂区建立计量边界与能耗基线后再提节能方案",
    ),
    OpportunityDefinition(
        code="COMPRESSED_AIR",
        title="压缩空气系统优化",
        description_template="已核验空压相关设备/能耗证据，可评估空压系统能效",
        signals=("compressed_air", "air_compressor"),
        priority="C",
        next_step_template="核验空压站配置、压力带与泄漏率后再测算节能空间",
    ),
    OpportunityDefinition(
        code="WASTE_HEAT",
        title="余热余压回收",
        description_template="已核验余热回收/热源证据，可评估余热利用方案",
        signals=("waste_heat_recovery", "waste_heat", "heat"),
        priority="B",
        next_step_template="核验余热温度、流量与可回收时段后再设计回收方案",
    ),
    OpportunityDefinition(
        code="HVAC",
        title="冷热源与暖通优化",
        description_template="已核验冷热负荷/暖通设备证据，可评估 HVAC 优化",
        signals=("hvac", "chilled_water", "heat"),
        priority="C",
        next_step_template="核验冷热负荷曲线与主机运行工况后再提优化方案",
    ),
    OpportunityDefinition(
        code="GREEN_POWER",
        title="绿电采购与绿证",
        description_template="已核验绿电交易/可再生能源采购证据，可评估绿电方案",
        signals=("green_electricity_transaction_volume", "green_power", "renewable_energy"),
        priority="B",
        next_step_template="核验企业绿电目标、电量结构与采购预算后再出方案",
    ),
    OpportunityDefinition(
        code="ENERGY_MANAGEMENT",
        title="能源数字化管理",
        description_template="已核验能源管理/计量体系证据，可评估能源数字化合作",
        signals=("energy_management_certified_sites", "energy_management", "metering"),
        priority="B",
        next_step_template="梳理计量点位与数据底座后再设计能源管理平台",
    ),
    OpportunityDefinition(
        code="CARBON_MANAGEMENT",
        title="碳盘查与碳管理",
        description_template="已核验碳盘查/碳减排证据，可评估碳管理服务",
        signals=("carbon_project", "carbon_audit", "emission_reduction"),
        priority="B",
        next_step_template="按厂区建立碳排口径与核查边界后再开展盘查",
    ),
    OpportunityDefinition(
        code="ZERO_CARBON_FACTORY",
        title="零碳工厂",
        description_template="已核验零碳工厂/绿电/碳管理组合证据，可评估零碳工厂路径",
        signals=("zero_carbon_factory", "green_factory_count", "carbon_project"),
        priority="A",
        next_step_template="建立能碳一体数据底座并形成分阶段零碳路线图",
    ),
    OpportunityDefinition(
        code="MICROGRID",
        title="微电网",
        description_template="已核验多能源协同证据，可评估微电网方案",
        signals=("microgrid", "pv_capacity", "storage_power", "load_curve"),
        minimum_signals=2,
        priority="C",
        next_step_template="核验电源结构、负荷特征与并网边界后再设计微网架构",
    ),
    OpportunityDefinition(
        code="ENERGY_DIGITALIZATION",
        title="能源数字化",
        description_template="已核验用能数据/信息化证据，可评估能源数字化",
        signals=("energy_digitalization", "metering", "energy_management"),
        priority="C",
        next_step_template="核验数据采集现状与系统边界后再立项",
    ),
    OpportunityDefinition(
        code="PRODUCT_COOPERATION",
        title="产品联合合作",
        description_template="已核验产品/产能证据，可评估产品联合或配套合作",
        signals=("product_family", "capacity", "model"),
        priority="B",
        next_step_template="对齐产品规格、产能余量与商务边界后再推进",
    ),
    OpportunityDefinition(
        code="JOINT_RND",
        title="联合研发",
        description_template="已核验研发平台/技术路线证据，可评估联合研发",
        signals=("rnd_platform", "technology_route", "technology", "patent"),
        priority="C",
        next_step_template="确认技术路线契合度与知识产权边界后再立项",
    ),
    OpportunityDefinition(
        code="SUPPLY_CHAIN",
        title="供应链合作",
        description_template="已核验供应商/供应链证据，可评估供应链切入",
        signals=("supplier_name", "supply_chain", "procurement"),
        priority="C",
        next_step_template="核验采购目录、准入流程与账期条件后再推进",
    ),
    OpportunityDefinition(
        code="ODM",
        title="ODM 合作",
        description_template="已核验制造能力与产品认证组合证据，可评估 ODM 合作",
        signals=("capacity", "certification", "production_lines"),
        minimum_signals=2,
        priority="C",
        next_step_template="确认品牌责任、整机边界与认证责任后再评估",
    ),
    OpportunityDefinition(
        code="OVERSEAS",
        title="出海合作",
        description_template="已核验海外业务/项目证据，可评估海外能源配套合作",
        signals=("export", "overseas_subsidiary", "overseas_factory", "overseas_project"),
        priority="B",
        next_step_template="核验目标市场准入、绿电与碳足迹要求及本地资源",
    ),
    OpportunityDefinition(
        code="CHANNEL",
        title="渠道合作",
        description_template="已核验销售渠道/客户证据，可评估渠道合作",
        signals=("channel", "customer_segment", "distribution"),
        priority="C",
        next_step_template="核验渠道结构、区域覆盖与分成模式后再推进",
    ),
)


class OpportunityRegistry:
    """Registry of opportunity definitions; extensible without code forks."""

    def __init__(self, definitions: tuple[OpportunityDefinition, ...] | None = None) -> None:
        self.definitions = definitions or OPPORTUNITY_DEFINITIONS
        self._by_code = {definition.code: definition for definition in self.definitions}

    def get(self, code: str) -> OpportunityDefinition | None:
        return self._by_code.get(code)

    def codes(self) -> list[str]:
        return [definition.code for definition in self.definitions]


class EvidenceOpportunityEngine:
    """Generate solutions strictly from evidence; skip everything else."""

    def __init__(self, registry: OpportunityRegistry | None = None) -> None:
        self.registry = registry or OpportunityRegistry()

    def generate(
        self,
        entities: list[Entity],
        profiles: list[EnergyProfile],
        claims: list[Claim],
    ) -> list[Solution]:
        verified = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
        claims_by_entity: dict[str, list[Claim]] = {}
        for claim in verified:
            claims_by_entity.setdefault(claim.entity_id, []).append(claim)
        profile_by_entity = {profile.entity_id: profile for profile in profiles}
        solutions: list[Solution] = []
        for entity in entities:
            entity_claims = claims_by_entity.get(entity.entity_id, [])
            claim_fields = {claim.field_name for claim in entity_claims}
            profile = profile_by_entity.get(entity.entity_id)
            for definition in self.registry.definitions:
                matched, hits = definition.matches(claim_fields, profile)
                if not matched:
                    continue  # SKIP — no evidence, no placeholder chapter
                supporting = [
                    claim.claim_id for claim in entity_claims
                    if claim.field_name in definition.signals
                ]
                solutions.append(Solution(
                    solution_id=new_sortable_id("SOL"),
                    engine=definition.code,  # type: ignore[arg-type]
                    target_ids=[entity.entity_id],
                    opportunity=definition.title,
                    proposed_solution=definition.description_template,
                    benefit_logic=self._value_logic(definition),
                    data_requirements=["经核验的运营数据", "商务与责任边界"],
                    risks=["证据不足", "范围不确定", "数据质量"],
                    next_step=definition.next_step_template,
                    priority=definition.priority,  # type: ignore[arg-type]
                    statement_type=StatementType.EVIDENCE_SUPPORTED,
                    claim_ids=supporting,
                    assumptions=[],
                ))
        return solutions

    @staticmethod
    def _value_logic(definition: OpportunityDefinition) -> str:
        """Describe the commercial contribution in ordinary business language.

        The previous release repeated one abstract sentence for every
        opportunity.  Besides sounding machine-written, it concealed the
        material difference between a technical-development discussion, an
        energy project and a market-access proposal.
        """
        if definition.code in {"JOINT_RND", "PRODUCT_COOPERATION", "ODM", "SUPPLY_CHAIN"}:
            return (
                "通过联合技术验证、产品适配或供应链协同缩短开发与导入周期；"
                "具体贡献需由双方在明确课题、指标和交付边界后确认"
            )
        if definition.code in {
            "PV_EPC", "STORAGE", "ENERGY_EFFICIENCY", "COMPRESSED_AIR",
            "WASTE_HEAT", "HVAC", "GREEN_POWER", "ENERGY_MANAGEMENT",
            "CARBON_MANAGEMENT", "ZERO_CARBON_FACTORY", "MICROGRID",
            "ENERGY_DIGITALIZATION", "V2G", "CHARGING",
        }:
            return (
                "通过降低用能成本、提高供能稳定性或减少碳排放形成项目价值；"
                "容量和收益须按具体基地的实际数据测算"
            )
        if definition.code == "OVERSEAS":
            return "通过市场准入、本地资源和交付协同降低海外项目落地难度，合作范围按目标市场逐项确定"
        if definition.code == "CHANNEL":
            return "通过渠道覆盖和客户触达增加有效销售机会，合作前需明确客户归属、区域和分成规则"
        return "双方围绕一个明确业务事项分工协作，合作价值以可量化的交付结果评价"
