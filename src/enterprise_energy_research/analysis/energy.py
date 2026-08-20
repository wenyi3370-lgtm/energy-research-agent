from __future__ import annotations

from collections import defaultdict

from enterprise_energy_research.domain.enums import GapStatus, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, DataGap, EnergyProfile, Entity, Factory


PROCESS_KEYWORDS = {
    "冲压": "electricity_equipment", "熔炼": "electricity_equipment",
    "石墨化": "electricity_equipment", "包覆": "electricity_equipment",
    "成品加工": "electricity_equipment", "前端工程": "electricity_equipment",
    "后端工程": "electricity_equipment", "涂布": "electricity_equipment",
    "拉伸": "electricity_equipment", "机加工": "electricity_equipment",
    "注塑": "electricity_equipment", "空压": "electricity_equipment",
    "冷冻": "electricity_equipment", "空调": "electricity_equipment",
    "变压器": "electricity_equipment", "热处理": "gas_equipment",
    "蒸汽": "gas_equipment",
}
REQUIRED_FIELDS = ["operating_schedule", "electricity_consumption", "load_curve", "roof_area", "transformer_capacity"]


class EnergyAnalyst:
    def analyze(self, entities: list[Entity], factories: list[Factory], claims: list[Claim]) -> tuple[list[EnergyProfile], list[DataGap]]:
        claims_by_entity: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            if claim.verification_status == VerificationStatus.VERIFIED:
                claims_by_entity[claim.entity_id].append(claim)
        profiles: list[EnergyProfile] = []
        gaps: list[DataGap] = []
        for entity in entities:
            if entity.verification_status != VerificationStatus.VERIFIED:
                continue
            entity_claims = claims_by_entity.get(entity.entity_id, [])
            entity_factories = [item for item in factories if item.operator_entity_id == entity.entity_id]
            text = " ".join(
                [f"{item.field_name} {item.value} {item.context_text}" for item in entity_claims]
                + [" ".join(item.processes) for item in entity_factories]
            )
            processes = sorted({keyword for keyword in PROCESS_KEYWORDS if keyword in text})
            electricity = sorted({keyword for keyword in processes if PROCESS_KEYWORDS[keyword] == "electricity_equipment"})
            gas = sorted({keyword for keyword in processes if PROCESS_KEYWORDS[keyword] == "gas_equipment"})
            fields = {claim.field_name: claim for claim in entity_claims}
            status = {field: ("observed" if field in fields else "requires_on_site_due_diligence") for field in REQUIRED_FIELDS}
            factory = entity_factories[0] if entity_factories else None
            profiles.append(EnergyProfile(
                energy_profile_id=new_sortable_id("ENERGY"), entity_id=entity.entity_id,
                factory_id=factory.factory_id if factory else None,
                processes=processes or (factory.processes if factory else []),
                electricity_equipment=electricity, gas_equipment=gas,
                operating_schedule={"value": fields["operating_schedule"].value} if "operating_schedule" in fields else None,
                roof={"area": fields["roof_area"].value, "unit": fields["roof_area"].unit} if "roof_area" in fields else None,
                load_shape={"source_claim_id": fields["load_curve"].claim_id} if "load_curve" in fields else None,
                field_status=status,
                claim_ids=[claim.claim_id for claim in entity_claims if claim.field_name in set(REQUIRED_FIELDS) | {"process", "products", "energy_efficiency_signal"}],
            ))
            for field_name in REQUIRED_FIELDS:
                if field_name not in fields:
                    gaps.append(DataGap(
                        gap_id=new_sortable_id("GAP"), entity_id=entity.entity_id,
                        field_name=field_name, importance="critical" if field_name in {"load_curve", "electricity_consumption"} else "major",
                        reason="requires_site_due_diligence", next_action=f"现场获取并核验 {field_name} 数据", status=GapStatus.OPEN,
                    ))
        return profiles, gaps
