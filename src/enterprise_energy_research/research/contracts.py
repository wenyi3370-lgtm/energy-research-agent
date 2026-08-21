"""GoalExtractionContract registry (P0-3).

Every Goal Family declares WHAT the extractor must look for on a page, so the
LLM never has to guess "what matters" for the current research goal. The
contract travels with the ResearchQuery into the EvidenceExtractor prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoalExtractionContract(BaseModel):
    goal_family: str
    business_question: str
    expected_fields: list[str] = Field(default_factory=list)
    preferred_source_types: list[str] = Field(default_factory=list)
    normalization_rules: list[str] = Field(default_factory=list)
    criticality: str = "major"  # critical | major | minor
    report_destination: str = "appendix"  # body | appendix | diagnostic


FINANCIAL_FIELDS = [
    "revenue", "profit", "gross_profit", "gross_margin", "operating_profit",
    "total_assets", "total_liabilities", "operating_cash_flow", "investment",
    "capex", "reporting_period", "currency", "scope", "yoy",
]
FACTORY_FIELDS = [
    "factory_name", "operator", "address", "city", "province", "products",
    "processes", "capacity", "production_lines", "investment",
    "commissioning_date", "project_status",
]
PRODUCT_FIELDS = [
    "product_family", "series", "model", "category", "description",
    "application", "customer_segment", "commercial_status",
]
PARAMETER_FIELDS = [
    "product", "series", "model", "parameter_name", "value", "unit",
    "test_condition", "source_document",
]
ENERGY_FIELDS = [
    "electricity_consumption", "energy_consumption", "load", "load_curve",
    "transformer_capacity", "natural_gas", "steam", "compressed_air",
    "roof_area", "energy_equipment",
]
ENERGY_PROJECT_FIELDS = [
    "project_name", "site", "project_type", "pv_capacity", "storage_power",
    "storage_capacity", "annual_generation", "investment", "EPC_party",
    "commissioning_date", "project_status",
]

OFFICIAL_TYPES = ["official_company", "official_manual", "official_announcement", "government", "annual_report"]
DEEP_TYPES = OFFICIAL_TYPES + ["industry_association", "certification_body", "commercial_database"]

GOAL_CONTRACTS: dict[str, GoalExtractionContract] = {
    "company_identity": GoalExtractionContract(
        goal_family="company_identity",
        business_question="查明企业法定全称、注册名称、曾用名、统一社会信用代码与官方身份。",
        expected_fields=["canonical_company_name", "registered_name", "aliases", "former_names", "official_website", "registration_identifier", "founded_date", "core_business", "business_segment"],
        preferred_source_types=OFFICIAL_TYPES,
        normalization_rules=["官方页面明确写出的公司全称必须形成 identity Claim，并保留原文引用"],
        criticality="critical",
        report_destination="body",
    ),
    "ownership_structure": GoalExtractionContract(
        goal_family="ownership_structure",
        business_question="查明股权结构、母公司、控股股东与实际控制人。",
        expected_fields=["parent_company", "actual_controller", "ownership_structure", "shareholder", "equity_ratio", "stock_code"],
        preferred_source_types=OFFICIAL_TYPES,
        normalization_rules=["股东与持股比例只采信公开披露来源；不得用行业常识推断控制关系"],
        criticality="critical",
        report_destination="body",
    ),
    "organization": GoalExtractionContract(
        goal_family="organization",
        business_question="查明组织架构、成员企业与核心管理层设置。",
        expected_fields=["organization_structure", "member_company", "management_team", "department"],
        preferred_source_types=OFFICIAL_TYPES,
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "subsidiaries": GoalExtractionContract(
        goal_family="subsidiaries",
        business_question="查明子公司、控股公司与参股公司名录及其业务职能。",
        expected_fields=["subsidiary_name", "subsidiary_relation", "shareholding_ratio", "subsidiary_business"],
        preferred_source_types=OFFICIAL_TYPES + ["annual_report"],
        normalization_rules=["每家子公司必须来自明确披露；关系边必须绑定支撑 Claim"],
        criticality="critical",
        report_destination="body",
    ),
    "factories": GoalExtractionContract(
        goal_family="factories",
        business_question="查明企业主要生产基地、运营主体及生产活动。",
        expected_fields=FACTORY_FIELDS,
        preferred_source_types=DEEP_TYPES,
        normalization_rules=["产能、投资与投产时间必须保留时间与范围限定词"],
        criticality="critical",
        report_destination="body",
    ),
    "locations": GoalExtractionContract(
        goal_family="locations",
        business_question="查明总部、园区与基地的地理位置。",
        expected_fields=["headquarters", "address", "city", "province", "site"],
        preferred_source_types=OFFICIAL_TYPES,
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "financials": GoalExtractionContract(
        goal_family="financials",
        business_question="查明年度财务报告与经营数据。",
        expected_fields=FINANCIAL_FIELDS,
        preferred_source_types=["annual_report", "official_announcement", "government"],
        normalization_rules=["财务数值必须保留报告期、币种与口径；不同年份不得混用"],
        criticality="critical",
        report_destination="body",
    ),
    "revenue": GoalExtractionContract(
        goal_family="revenue",
        business_question="查明营业收入规模与年度变化。",
        expected_fields=FINANCIAL_FIELDS,
        preferred_source_types=["annual_report", "official_announcement"],
        normalization_rules=["营业收入统一为 revenue，保留 raw_field_name"],
        criticality="critical",
        report_destination="body",
    ),
    "profit": GoalExtractionContract(
        goal_family="profit",
        business_question="查明净利润、利润总额与年度变化。",
        expected_fields=FINANCIAL_FIELDS,
        preferred_source_types=["annual_report", "official_announcement"],
        normalization_rules=["净利润与利润总额不得混淆"],
        criticality="critical",
        report_destination="body",
    ),
    "employees": GoalExtractionContract(
        goal_family="employees",
        business_question="查明员工人数与人员规模。",
        expected_fields=["employee_count", "staff_count", "as_of_date"],
        preferred_source_types=["annual_report", "recruitment", "official_company"],
        normalization_rules=["员工数统一为 employee_count，保留统计时点"],
        criticality="major",
        report_destination="body",
    ),
    "capacity": GoalExtractionContract(
        goal_family="capacity",
        business_question="查明产能、年产量、技改与投资项目。",
        expected_fields=["capacity", "annual_output", "expansion_project", "investment", "commissioning_date"],
        preferred_source_types=DEEP_TYPES,
        normalization_rules=["产能必须保留单位、口径与投产时间"],
        criticality="critical",
        report_destination="body",
    ),
    "production_lines": GoalExtractionContract(
        goal_family="production_lines",
        business_question="查明生产线、工艺、设备与环评信息。",
        expected_fields=["production_line", "process", "equipment", "environmental_assessment", "factory_name"],
        preferred_source_types=["government", "industry_association", "official_company"],
        normalization_rules=["工艺与设备归属具体生产基地"],
        criticality="major",
        report_destination="body",
    ),
    "products": GoalExtractionContract(
        goal_family="products",
        business_question="查明产品中心、产品分类与产品清单。",
        expected_fields=PRODUCT_FIELDS,
        preferred_source_types=["official_company"],
        normalization_rules=["产品族、系列与型号保持三个层级，不得用类别替代系列"],
        criticality="critical",
        report_destination="body",
    ),
    "product_series": GoalExtractionContract(
        goal_family="product_series",
        business_question="查明产品系列与产品族分类目录。",
        expected_fields=PRODUCT_FIELDS,
        preferred_source_types=["official_company"],
        normalization_rules=["系列必须与族、型号分层记录"],
        criticality="critical",
        report_destination="body",
    ),
    "product_models": GoalExtractionContract(
        goal_family="product_models",
        business_question="查明产品型号、牌号与 SKU。",
        expected_fields=PRODUCT_FIELDS,
        preferred_source_types=["official_company"],
        normalization_rules=["型号必须来自官方页面，不得推测定制牌号"],
        criticality="critical",
        report_destination="body",
    ),
    "product_parameters": GoalExtractionContract(
        goal_family="product_parameters",
        business_question="查明产品技术参数、规格书与检测条件。",
        expected_fields=PARAMETER_FIELDS,
        preferred_source_types=["official_manual", "official_company", "certification_body"],
        normalization_rules=["参数必须带数值、单位、测试条件与来源文档"],
        criticality="critical",
        report_destination="body",
    ),
    "customers": GoalExtractionContract(
        goal_family="customers",
        business_question="查明核心客户、中标记录、供应关系与应用案例。",
        expected_fields=["customer_name", "customer_segment", "contract", "application_case"],
        preferred_source_types=["government", "official_announcement", "industry_association"],
        normalization_rules=["客户关系只采信公开中标、公告或官方披露"],
        criticality="major",
        report_destination="body",
    ),
    "suppliers": GoalExtractionContract(
        goal_family="suppliers",
        business_question="查明供应商、采购与供应链信息。",
        expected_fields=["supplier_name", "procurement", "tender", "supply_chain"],
        preferred_source_types=["official_announcement", "government"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "certifications": GoalExtractionContract(
        goal_family="certifications",
        business_question="查明认证体系、证书与检测报告。",
        expected_fields=["certification", "certificate_number", "issuing_body", "valid_until"],
        preferred_source_types=["certification_body", "official_company"],
        normalization_rules=["证书必须带发证机构与有效期"],
        criticality="major",
        report_destination="body",
    ),
    "technology": GoalExtractionContract(
        goal_family="technology",
        business_question="查明核心技术、研发平台与技术路线。",
        expected_fields=["technology", "rnd_platform", "technology_route", "rd_expense"],
        preferred_source_types=["official_company", "annual_report", "industry_association"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "patents": GoalExtractionContract(
        goal_family="patents",
        business_question="查明专利、发明专利与知识产权。",
        expected_fields=["patent", "patent_number", "patent_type", "grant_date"],
        preferred_source_types=["government"],
        normalization_rules=["专利必须带专利号或授权公告信息"],
        criticality="minor",
        report_destination="body",
    ),
    "industry_position": GoalExtractionContract(
        goal_family="industry_position",
        business_question="查明行业地位、市占率、排名与竞争力。",
        expected_fields=["industry_position", "market_share", "ranking", "competitive_edge"],
        preferred_source_types=["industry_association", "government", "annual_report"],
        normalization_rules=["市占率必须保留统计口径与来源"],
        criticality="major",
        report_destination="body",
    ),
    "energy_consumption": GoalExtractionContract(
        goal_family="energy_consumption",
        business_question="查明综合能耗、用电量与能源消费。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "annual_report", "official_company"],
        normalization_rules=["能耗数值必须保留统计期、单位与厂区归属"],
        criticality="critical",
        report_destination="body",
    ),
    "energy_equipment": GoalExtractionContract(
        goal_family="energy_equipment",
        business_question="查明变压器、锅炉、空压机、冷机等能源设备。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=["设备必须归属具体工厂或车间"],
        criticality="major",
        report_destination="body",
    ),
    "electricity_load": GoalExtractionContract(
        goal_family="electricity_load",
        business_question="查明电力负荷、峰谷、需量与负荷曲线。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "natural_gas": GoalExtractionContract(
        goal_family="natural_gas",
        business_question="查明天然气、用气量与燃气锅炉。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="minor",
        report_destination="body",
    ),
    "compressed_air": GoalExtractionContract(
        goal_family="compressed_air",
        business_question="查明压缩空气、空压站与空压机配置。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="minor",
        report_destination="body",
    ),
    "heat": GoalExtractionContract(
        goal_family="heat",
        business_question="查明蒸汽、热力、供热与冷热负荷。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="minor",
        report_destination="body",
    ),
    "waste_heat": GoalExtractionContract(
        goal_family="waste_heat",
        business_question="查明余热余压回收与节能改造。",
        expected_fields=["waste_heat_recovery", "energy_saving_project", "annual_saving"],
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "roof_area": GoalExtractionContract(
        goal_family="roof_area",
        business_question="查明屋顶面积、厂房面积与光伏可用面积。",
        expected_fields=ENERGY_FIELDS,
        preferred_source_types=["government", "official_company"],
        normalization_rules=["屋顶面积统一为 roof_area，保留单位与厂区归属"],
        criticality="major",
        report_destination="body",
    ),
    "renewable_energy": GoalExtractionContract(
        goal_family="renewable_energy",
        business_question="查明绿色电力、可再生能源与光伏利用。",
        expected_fields=ENERGY_PROJECT_FIELDS,
        preferred_source_types=["government", "official_announcement"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "energy_projects": GoalExtractionContract(
        goal_family="energy_projects",
        business_question="查明能源项目、光伏、储能与充电站项目。",
        expected_fields=ENERGY_PROJECT_FIELDS,
        preferred_source_types=["government", "official_announcement", "official_company"],
        normalization_rules=["项目容量、投资与并网时间必须带来源与状态"],
        criticality="critical",
        report_destination="body",
    ),
    "carbon_projects": GoalExtractionContract(
        goal_family="carbon_projects",
        business_question="查明碳盘查、零碳工厂与碳项目。",
        expected_fields=["carbon_project", "carbon_audit", "zero_carbon_factory", "emission_reduction"],
        preferred_source_types=["government", "certification_body", "official_company"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "EPC_opportunities": GoalExtractionContract(
        goal_family="EPC_opportunities",
        business_question="查明新能源 EPC 与综合能源项目机会。",
        expected_fields=ENERGY_PROJECT_FIELDS,
        preferred_source_types=["government", "official_announcement"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "energy_saving_opportunities": GoalExtractionContract(
        goal_family="energy_saving_opportunities",
        business_question="查明节能诊断、节能改造与合同能源管理机会。",
        expected_fields=["energy_saving_project", "baseline_energy", "saving_potential"],
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "storage_opportunities": GoalExtractionContract(
        goal_family="storage_opportunities",
        business_question="查明储能、削峰填谷与需量管理机会。",
        expected_fields=["storage_power", "storage_capacity", "peak_valley_price", "demand_charge"],
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="major",
        report_destination="body",
    ),
    "V2G_opportunities": GoalExtractionContract(
        goal_family="V2G_opportunities",
        business_question="查明 V2G 车网互动与双向充放电机会。",
        expected_fields=["v2g", "bidirectional_charging", "charging_station"],
        preferred_source_types=["government", "official_company"],
        normalization_rules=[],
        criticality="minor",
        report_destination="body",
    ),
    "overseas_opportunities": GoalExtractionContract(
        goal_family="overseas_opportunities",
        business_question="查明海外业务、出口、海外工厂与经销商。",
        expected_fields=["export", "overseas_subsidiary", "overseas_factory", "overseas_project", "overseas_certification"],
        preferred_source_types=["official_company", "official_announcement", "government"],
        normalization_rules=["海外项目只采信官方披露，不得用行业动态替代企业事实"],
        criticality="major",
        report_destination="body",
    ),
    "risks": GoalExtractionContract(
        goal_family="risks",
        business_question="查明经营风险、合规风险与项目风险。",
        expected_fields=["business_risk", "compliance_risk", "project_risk"],
        preferred_source_types=["annual_report", "official_announcement"],
        normalization_rules=["风险条目必须来自披露原文"],
        criticality="major",
        report_destination="body",
    ),
    "image_evidence": GoalExtractionContract(
        goal_family="image_evidence",
        business_question="收集企业 logo、总部、厂区、生产线、产品与证书图片证据。",
        expected_fields=["image_url", "image_type", "alt_text", "surrounding_text", "product_name", "factory_name"],
        preferred_source_types=["official_company", "government", "official_manual"],
        normalization_rules=["产品图片必须绑定具体产品；厂区图片必须尽量绑定具体工厂"],
        criticality="major",
        report_destination="body",
    ),
}


def contract_for(goal_family: str) -> GoalExtractionContract:
    """Return the extraction contract for a goal family.

    Unknown families receive a generic discovery contract rather than None,
    so every goal keeps explicit extraction guidance.
    """
    return GOAL_CONTRACTS.get(goal_family, GoalExtractionContract(
        goal_family=goal_family,
        business_question="收集与该主题直接相关的公开企业事实。",
        expected_fields=[goal_family],
        preferred_source_types=OFFICIAL_TYPES,
        criticality="minor",
        report_destination="appendix",
    ))


# Identity fields that must carry a supporting Claim before they may appear
# on a formally published Entity (P0-1 IdentityEvidenceContract).
IDENTITY_FIELDS = (
    "canonical_company_name",
    "registered_name",
    "aliases",
    "official_website",
    "registration_region",
    "headquarters",
    "founded_date",
    "parent_company",
    "actual_controller",
    "ownership_structure",
    "registration_identifier",
)
