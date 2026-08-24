"""PublicationRelevanceFilter: decide which claims may enter a formal report.

P0 third-round rule: a claim is VERIFIED does NOT mean it belongs in the
user-facing report body.  A publishable claim must carry a clear metric
name, business semantics, unit, (where applicable) period, scope, a
reliable source AND an answer to the current research question.  Junk and
fragment values — phone numbers, customer-service hotlines, marketing
page counters, isolated ``+`` numbers, orphan percentages, page-UI
numbers — stay in the internal evidence store but never reach the body.

The filter never deletes evidence: it only splits claims into a
``body`` list (publication-relevant) and an ``internal`` list (evidence
lineage kept for QA), with machine-readable reasons.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import SourceLevel, VerificationStatus
from enterprise_energy_research.domain.models import Claim, FrozenResearchBundle
from enterprise_energy_research.research.entity_scope import allowed_publication_entity_ids

# ── metric fields that answer real research questions ─────────────────────
RESEARCH_METRIC_FIELDS = {
    # 企业经营
    "revenue", "profit", "net_profit", "gross_margin", "net_margin",
    "rnd_expense", "rnd_expense_ratio", "operating_cash_flow",
    "employee_count", "investment", "export", "market_share", "ranking",
    "industry_position",
    # 分业务 / 区域
    "business_segment", "segment_revenue", "domestic_revenue", "overseas_revenue",
    "sales_channel",
    "battery_revenue", "storage_revenue", "material_revenue", "energy_business_revenue",
    # 产能与制造
    "capacity", "production_capacity", "battery_production_capacity",
    "production_lines", "annual_output", "output", "factory_count",
    "factory_area", "utilization",
    # 能源（企业自身用能数据）
    "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
    "peak_demand", "electricity_cost", "load_curve", "pv_capacity",
    "storage_capacity", "storage_power", "renewable_share",
    "transformer_capacity", "roof_area", "energy_project", "project_name",
    "carbon_project", "carbon_intensity",
    # 产品参数
    "product_family", "product_name", "model", "series", "parameter_name",
    "product_parameter", "technology", "technology_route", "certification",
    "application", "energy_density", "cycle_life", "charge_rate", "voltage",
    "temperature_range", "product_catalog_scope",
    # 关键参数语义（能量密度/循环/倍率等动态归一后可能落入的参数名）
    "rated_capacity", "installed_capacity",
}

# Energy semantic fields (own consumption) — shared taxonomy with the
# analysis and decision layers.
ENERGY_FIELDS = {
    "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
    "peak_demand", "electricity_cost", "load_curve", "pv_capacity", "storage_capacity",
    "storage_power", "renewable_share", "transformer_capacity", "roof_area",
}

# Manufacturing semantic fields.
MANUFACTURING_FIELDS = {
    "capacity", "production_capacity", "factory_capacity", "battery_production_capacity",
    "production_lines", "output", "annual_output", "factory_name", "process", "processes",
    "factory_address", "address", "commissioning_date", "project_status", "factory_count",
}

# Dimensionless-numeric fields are legitimate without a unit string.
UNITLESS_FIELDS = {
    "product_family", "product_name", "model", "series", "category",
    "employee_count", "factory_count", "production_lines", "ranking",
    "certification", "technology", "technology_route", "application",
    "business_segment", "product_catalog_scope", "industry_position",
    "sales_channel",
}

# Identity/org fields: publishable in profile context, low visualization value.
IDENTITY_FIELDS = {
    "canonical_company_name", "registered_name", "registration_identifier",
    "headquarters", "founded_date", "official_website", "aliases",
    "parent_company", "actual_controller", "ownership_structure",
    "shareholder", "equity_ratio", "core_business", "stock_code",
    "registration_region", "management_team",
}

# Contact / marketing / page-UI fields: evidence only, never body text.
JUNK_FIELDS = {
    "service_hotline", "customer_service", "contact_phone", "phone",
    "fax", "email", "qq", "wechat", "service_stations",
    "regional_supervisors", "regional_technical_experts",
    "spare_parts_warehouses", "store_count", "navigation",
    "page_views", "banner", "footer",
}

# Stable non-numeric identity facts are fine without a period.
PERIODLESS_FIELDS = IDENTITY_FIELDS | {
    "core_business", "business_segment", "product_family", "product_name",
    "model", "series", "technology", "technology_route", "certification",
    "application", "product_catalog_scope", "factory_name", "factory_address",
    "process", "processes", "project_status", "commissioning_date",
    "industry_position",
    "sales_channel",
}

# Separators are REQUIRED inside phone alternatives: without them any
# 11-digit integer (e.g. 12000000000) would be misread as a phone number.
PHONE_RE = re.compile(
    r"(?<!\d)(?:400[- ]\d{3}[- ]\d{4}|\d{3}[- ]\d{4}[- ]\d{4}|"
    r"0\d{2,3}[- ]\d{7,8})(?!\d)"
)
COUNTER_RE = re.compile(r"^\d{1,6}\s*\+?$")           # "1100+" / "200"
ORPHAN_PERCENT_RE = re.compile(r"^\d{1,3}(?:\.\d+)?\s*%$")
DURATION_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:小时|分钟|天|月|年)$")


class Relevance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PublicationRelevanceScore(BaseModel):
    claim_id: str
    relevance: Relevance
    semantic_relevance: float = Field(ge=0.0, le=1.0)
    metric_completeness: float = Field(ge=0.0, le=1.0)
    source_quality: float = Field(ge=0.0, le=1.0)
    period_completeness: float = Field(ge=0.0, le=1.0)
    scope_completeness: float = Field(ge=0.0, le=1.0)
    visualization_value: float = Field(ge=0.0, le=1.0)
    decision_relevance: float = Field(ge=0.0, le=1.0)
    research_value: float = Field(ge=0.0, le=1.0)
    junk_guard: bool = True
    reasons: list[str] = Field(default_factory=list)


class RelevanceReport(BaseModel):
    total_verified: int = 0
    target_scope_verified: int = 0
    body: list[PublicationRelevanceScore] = Field(default_factory=list)
    internal: list[PublicationRelevanceScore] = Field(default_factory=list)

    @property
    def body_claim_ids(self) -> list[str]:
        return [item.claim_id for item in self.body]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.search(r"\d", text) is None:
        return None
    return text


def _junk_reasons(claim: Claim) -> list[str]:
    """Junk/fragment guard (P0 third round): why this value is NOT body data."""
    reasons: list[str] = []
    field = claim.field_name
    text = _numeric_text(claim.value)
    if field in JUNK_FIELDS:
        reasons.append("marketing/contact/UI field")
    if text and PHONE_RE.search(text):
        reasons.append("contact phone number")
    if text and COUNTER_RE.fullmatch(text) and field not in RESEARCH_METRIC_FIELDS and claim.unit is None:
        reasons.append("isolated + counter without metric semantics")
    if text and ORPHAN_PERCENT_RE.fullmatch(text) and field not in RESEARCH_METRIC_FIELDS and claim.unit is None and not claim.scope:
        reasons.append("orphan percentage without metric semantics")
    if text and DURATION_RE.fullmatch(text) and field not in RESEARCH_METRIC_FIELDS:
        reasons.append("orphan duration without metric semantics")
    if text and field not in RESEARCH_METRIC_FIELDS | IDENTITY_FIELDS and not claim.unit:
        reasons.append("unrecognized metric without unit")
    if text and text.startswith("+") and field not in RESEARCH_METRIC_FIELDS:
        reasons.append("leading + fragment")
    return reasons


def score_claim(claim: Claim, source_levels: dict[str, SourceLevel] | None = None) -> PublicationRelevanceScore:
    """Deterministic relevance score for one VERIFIED claim."""
    source_levels = source_levels or {}
    reasons = _junk_reasons(claim)
    junk = bool(reasons)
    field = claim.field_name
    text = _numeric_text(claim.value)
    is_number = _is_number(claim.value) or (text is not None and re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?(?:亿|万|万亿|%)?%?", text) is not None)

    if field in RESEARCH_METRIC_FIELDS:
        semantic = 1.0
    elif field in IDENTITY_FIELDS:
        semantic = 0.6
    else:
        semantic = 0.25
    if junk:
        semantic = min(semantic, 0.1)

    # metric completeness: metric name + (unit | unitless field | string fact)
    if field in UNITLESS_FIELDS or not is_number:
        metric_complete = 0.9
    elif claim.unit:
        metric_complete = 1.0
    else:
        metric_complete = 0.4

    level = source_levels.get(claim.source_id)
    if level == SourceLevel.SOURCE_A:
        source_quality = 1.0
    elif level == SourceLevel.SOURCE_B:
        source_quality = 0.8
    elif level == SourceLevel.SOURCE_C:
        source_quality = 0.55
    else:
        source_quality = 0.3

    has_period = bool(claim.period_start or claim.period_end or claim.as_of_date)
    if field in PERIODLESS_FIELDS and not is_number:
        period_complete = 1.0
    elif has_period:
        period_complete = 1.0
    else:
        period_complete = 0.4

    scope_complete = 1.0 if claim.scope else (0.9 if field in PERIODLESS_FIELDS else 0.45)

    if is_number and has_period:
        visualization = 1.0
    elif is_number:
        visualization = 0.5
    else:
        visualization = 0.2

    decision_relevance = 1.0 if field in RESEARCH_METRIC_FIELDS else (0.6 if field in IDENTITY_FIELDS else 0.3)

    research_value = round(
        0.30 * semantic + 0.15 * metric_complete + 0.10 * source_quality
        + 0.15 * period_complete + 0.10 * scope_complete
        + 0.10 * visualization + 0.10 * decision_relevance, 4,
    )
    if junk:
        relevance = Relevance.LOW
    elif research_value >= 0.70:
        relevance = Relevance.HIGH
    elif research_value >= 0.45:
        relevance = Relevance.MEDIUM
    else:
        relevance = Relevance.LOW
    return PublicationRelevanceScore(
        claim_id=claim.claim_id, relevance=relevance,
        semantic_relevance=round(semantic, 2),
        metric_completeness=round(metric_complete, 2),
        source_quality=round(source_quality, 2),
        period_completeness=round(period_complete, 2),
        scope_completeness=round(scope_complete, 2),
        visualization_value=round(visualization, 2),
        decision_relevance=round(decision_relevance, 2),
        research_value=research_value, junk_guard=not junk, reasons=reasons,
    )


class PublicationRelevanceFilter:
    """Filter verified claims into body-relevant vs internal-only evidence."""

    def filter(self, bundle: FrozenResearchBundle) -> tuple[list[Claim], RelevanceReport]:
        verified = [claim for claim in bundle.claims if claim.verification_status == VerificationStatus.VERIFIED]
        allowed_entities = allowed_publication_entity_ids(bundle)
        source_levels = {source.source_id: source.source_level for source in bundle.sources}
        body: list[Claim] = []
        internal: list[PublicationRelevanceScore] = []
        body_scores: list[PublicationRelevanceScore] = []
        by_id = {claim.claim_id: claim for claim in verified}
        for claim in verified:
            score = score_claim(claim, source_levels)
            if claim.entity_id not in allowed_entities:
                internal.append(score.model_copy(update={
                    "relevance": Relevance.LOW,
                    "junk_guard": False,
                    "reasons": [*score.reasons, "entity outside canonical enterprise group"],
                }))
            elif score.relevance == Relevance.LOW:
                internal.append(score)
            else:
                body.append(claim)
                body_scores.append(score)
        report = RelevanceReport(
            total_verified=len(verified),
            target_scope_verified=sum(
                1 for claim in verified if claim.entity_id in allowed_entities
            ),
            body=body_scores,
            internal=internal,
        )
        return body, report
