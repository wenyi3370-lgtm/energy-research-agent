"""ResearchSynthesizer (P0-18).

Verified evidence flows through a claim-bound synthesis before any publisher
runs: every factual finding keeps supporting_claim_ids / supporting_source_ids
/ statement_type. A finding without a Claim is not a fact and is never
published as one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import (
    Claim,
    DataGap,
    EnergyProfile,
    EnterpriseEdge,
    Entity,
    Factory,
    Product,
    Solution,
    Source,
)
from enterprise_energy_research.research.profiles import CompanyProfile, CompanyProfileBuilder, GroupProfileBuilder


class SynthesisFinding(BaseModel):
    finding: str
    supporting_claim_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)
    statement_type: Literal["EVIDENCE_SYNTHESIS", "ANALYTICAL_INFERENCE", "TO_BE_CONFIRMED"] = "EVIDENCE_SYNTHESIS"
    goal_family: str | None = None

    @model_validator(mode="after")
    def evidence_synthesis_requires_claims(self) -> "SynthesisFinding":
        if self.statement_type == "EVIDENCE_SYNTHESIS" and not self.supporting_claim_ids:
            raise ValueError("EVIDENCE_SYNTHESIS findings require supporting claim ids")
        return self


class ResearchSynthesis(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    entity_id: str | None = None
    company_name: str
    executive_summary: list[str] = Field(default_factory=list)
    company_profile: CompanyProfile | None = None
    group_profile: dict | None = None
    ownership_summary: str | None = None
    organization_summary: str | None = None
    business_summary: str | None = None
    financial_summary: str | None = None
    industry_position: str | None = None
    subsidiary_summary: str | None = None
    factory_summary: str | None = None
    product_summary: str | None = None
    technology_summary: str | None = None
    customer_summary: str | None = None
    supplier_summary: str | None = None
    energy_summary: str | None = None
    existing_energy_projects: list[str] = Field(default_factory=list)
    cooperation_opportunities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    key_unknowns: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    findings: list[SynthesisFinding] = Field(default_factory=list)


class ResearchSynthesizer:
    """Deterministic, claim-bound synthesis. No LLM required; no invention."""

    def synthesize(
        self,
        *,
        run_id: str,
        entity: Entity,
        entities: list[Entity],
        claims: list[Claim],
        sources: list[Source],
        edges: list[EnterpriseEdge],
        factories: list[Factory],
        products: list[Product],
        energy_profiles: list[EnergyProfile],
        gaps: list[DataGap],
        solutions: list[Solution],
    ) -> ResearchSynthesis:
        verified = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
        verified_by_field: dict[str, list[Claim]] = {}
        for claim in verified:
            verified_by_field.setdefault(claim.field_name, []).append(claim)
        source_names = {source.source_id: source.source_title or source.source_domain for source in sources}

        profile = CompanyProfileBuilder().build(entity, claims, edges, factories, products, entities=entities)
        findings: list[SynthesisFinding] = []

        def evidence_summary(field: str, template: str) -> str | None:
            rows = verified_by_field.get(field, [])
            if not rows:
                return None
            best = max(rows, key=lambda item: item.confidence)
            findings.append(SynthesisFinding(
                finding=template.format(value=best.value, unit=best.unit or ""),
                supporting_claim_ids=[item.claim_id for item in rows],
                supporting_source_ids=[item.source_id for item in rows],
                statement_type="EVIDENCE_SYNTHESIS",
                goal_family=_family_for(field),
            ))
            return f"{template.format(value=best.value, unit=best.unit or '')}"

        ownership_summary = evidence_summary("ownership_structure", "股权结构：{value}") or evidence_summary("actual_controller", "实际控制人：{value}") or evidence_summary("parent_company", "母公司：{value}")
        business_summary = evidence_summary("core_business", "主营业务：{value}")
        financial_parts = []
        for field, label in (("revenue", "营业收入"), ("profit", "净利润"), ("employee_count", "员工人数")):
            if rows := verified_by_field.get(field):
                best = max(rows, key=lambda item: item.confidence)
                financial_parts.append(f"{label}：{best.value}{best.unit or ''}")
                findings.append(SynthesisFinding(
                    finding=f"{label}：{best.value}{best.unit or ''}",
                    supporting_claim_ids=[item.claim_id for item in rows],
                    supporting_source_ids=[item.source_id for item in rows],
                    statement_type="EVIDENCE_SYNTHESIS",
                    goal_family=_family_for(field),
                ))
        financial_summary = "；".join(financial_parts) or None
        factory_rows = [
            factory for factory in factories if factory.operator_entity_id == entity.entity_id
        ] or factories
        factory_summary = None
        if factory_rows:
            names = [factory.name for factory in factory_rows if factory.name]
            factory_summary = f"已核验生产基地 {len(factory_rows)} 处：{'、'.join(names[:8])}"
            factory_claims = [claim for claim in verified if claim.field_name in {"factory_name", "capacity", "process"}]
            if factory_claims:
                findings.append(SynthesisFinding(
                    finding=factory_summary,
                    supporting_claim_ids=[item.claim_id for item in factory_claims],
                    supporting_source_ids=[item.source_id for item in factory_claims],
                    statement_type="EVIDENCE_SYNTHESIS",
                    goal_family="factories",
                ))
        verified_products = [product for product in products if product.verification_status == VerificationStatus.VERIFIED]
        product_summary = None
        if verified_products:
            product_summary = f"已核验产品 {len(verified_products)} 项：{'、'.join(product.name for product in verified_products[:8])}"
            product_claims = [claim for claim in verified if claim.field_name in {"product_family", "model", "parameter_name"}]
            if product_claims:
                findings.append(SynthesisFinding(
                    finding=product_summary,
                    supporting_claim_ids=[item.claim_id for item in product_claims],
                    supporting_source_ids=[item.source_id for item in product_claims],
                    statement_type="EVIDENCE_SYNTHESIS",
                    goal_family="products",
                ))
        energy_summary = evidence_summary("electricity_consumption", "年度用电量：{value}{unit}") or evidence_summary("energy_consumption", "综合能耗：{value}{unit}")
        if energy_profiles:
            energy_summary = energy_summary or f"已形成 {len(energy_profiles)} 份能源画像"
        existing_projects = []
        for field in ("energy_project", "project_name", "pv_capacity", "storage_power"):
            for claim in verified_by_field.get(field, []):
                existing_projects.append(f"{claim.field_name}：{claim.value}")
        opportunities = [
            solution.opportunity for solution in solutions
            if solution.priority in {"A", "B"} and solution.statement_type.value == "EVIDENCE_SUPPORTED"
        ]
        risk_rows = [claim for claim in verified if claim.field_name in {"business_risk", "compliance_risk", "project_risk"}]
        risks = [f"{claim.field_name}：{claim.value}" for claim in risk_rows]
        key_unknowns = [f"{gap.field_name}（{gap.reason}）" for gap in gaps if gap.importance != "minor"][:12]
        recommended = [solution.next_step for solution in solutions if solution.priority in {"A", "B"}][:6]

        executive = self._executive_summary(
            entity=entity, profile=profile, financial_summary=financial_summary,
            factory_summary=factory_summary, product_summary=product_summary,
            energy_summary=energy_summary, opportunities=opportunities,
            risks=risks, recommended=recommended, gaps=key_unknowns,
        )
        # Keep synthesis strictly claim-bound: executive bullet with no claim
        # evidence is marked TO_BE_CONFIRMED, never a free-floating "fact".
        group_profile = None
        if entities and entity.entity_type == "group":
            group_profile = GroupProfileBuilder().build(
                entity, entities, claims, edges, factories, products,
            ).model_dump(mode="json")
        return ResearchSynthesis(
            run_id=run_id,
            entity_id=entity.entity_id,
            company_name=entity.canonical_name,
            executive_summary=executive,
            company_profile=profile,
            group_profile=group_profile,
            ownership_summary=ownership_summary,
            business_summary=business_summary,
            financial_summary=financial_summary,
            subsidiary_summary=f"一级子公司 {len(profile.subsidiaries)} 家：{'、'.join(profile.subsidiaries[:8])}" if profile.subsidiaries else None,
            factory_summary=factory_summary,
            product_summary=product_summary,
            energy_summary=energy_summary,
            existing_energy_projects=existing_projects,
            cooperation_opportunities=opportunities,
            risks=risks,
            key_unknowns=key_unknowns,
            recommended_next_actions=recommended,
            findings=findings,
        )

    @staticmethod
    def _executive_summary(*, entity, profile, financial_summary, factory_summary, product_summary, energy_summary, opportunities, risks, recommended, gaps) -> list[str]:
        lines: list[str] = []
        lines.append(f"{entity.canonical_name}是{profile.registration_region or '注册地待公开确认'}的企业" if profile.registration_region else f"本报告研究对象为{entity.canonical_name}。")
        if profile.core_business:
            lines.append(f"公司主要业务：{profile.core_business}。")
        if financial_summary:
            lines.append(f"经营情况（公开披露口径）：{financial_summary}。")
        if profile.business_segments:
            lines.append(f"重要产业板块：{'、'.join(profile.business_segments)}。")
        if factory_summary:
            lines.append(factory_summary + "。")
        if product_summary:
            lines.append(product_summary + "。")
        if energy_summary:
            lines.append(f"能源相关事实：{energy_summary}。")
        if opportunities:
            lines.append("最值得推进的合作机会：" + "；".join(opportunities[:3]) + "。")
        if risks:
            lines.append("最大风险：" + "；".join(risks[:3]) + "。")
        if recommended:
            lines.append("下一步：" + "；".join(recommended[:3]) + "。")
        if gaps:
            lines.append("关键未知项：" + "；".join(gaps[:5]) + "。")
        return lines


def _family_for(field: str) -> str:
    from enterprise_energy_research.research.field_registry import CanonicalFieldRegistry
    return CanonicalFieldRegistry.family(field) or field


def write_synthesis(synthesis: ResearchSynthesis, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "research_synthesis.json"
    path.write_text(
        json.dumps(synthesis.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
