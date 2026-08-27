"""CanonicalFieldRegistry (P0-4).

Raw extracted field names flow through an alias mapping into one canonical
field per family, so ``revenue`` / ``annual_revenue`` / ``营业收入`` are never
treated as different fields downstream. The exact raw name is preserved on
the Claim as ``raw_field_name``.
"""

from __future__ import annotations

# Family name -> canonical field name. Used for goal-family membership checks.
FIELD_FAMILIES: dict[str, str] = {
    "IDENTITY": "canonical_company_name",
    "OWNERSHIP": "ownership_structure",
    "BUSINESS": "core_business",
    "FINANCIAL": "revenue",
    "ORGANIZATION": "organization_structure",
    "SUBSIDIARY": "subsidiary_name",
    "FACTORY": "factory_name",
    "PRODUCTION": "process",
    "CAPACITY": "capacity",
    "PRODUCT": "product_family",
    "PRODUCT_PARAMETER": "parameter_name",
    "CUSTOMER": "customer_name",
    "SUPPLIER": "supplier_name",
    "TECHNOLOGY": "technology",
    "CERTIFICATION": "certification",
    "ENERGY": "energy_consumption",
    "PROJECT": "project_name",
    "CARBON": "carbon_project",
    "OVERSEAS": "export",
    "RISK": "business_risk",
}

# Canonical field -> accepted aliases (English + Chinese + variants).
ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("annual_revenue", "operating_revenue", "sales_revenue", "营业收入", "营收", "年度营收", "营业总收入", "total_revenue"),
    "profit": ("net_profit", "净利润", "归母净利润", "attributable_profit", "net_income", "net_profit_attributable_to_parent"),
    "gross_profit": ("毛利", "gross_income"),
    "gross_margin": ("毛利率", "gross_profit_margin"),
    "operating_profit": ("营业利润", "profit_from_operations"),
    "total_assets": ("assets", "总资产", "资产总额"),
    "total_liabilities": ("liabilities", "总负债", "负债总额"),
    "operating_cash_flow": ("经营现金流", "经营活动现金流量净额", "cash_flow_from_operations"),
    "investment": ("总投资", "投资额", "项目投资", "planned_investment", "total_investment"),
    "capex": ("资本开支", "资本性支出", "capital_expenditure"),
    "employee_count": ("employees", "staff_count", "employee_number", "员工人数", "人员规模", "在职员工", "number_of_employees"),
    "electricity_consumption": ("annual_electricity", "power_consumption", "electricity_usage", "年用电量", "年度耗电量", "用电量"),
    "energy_consumption": ("综合能耗", "综合能源消费量", "total_energy_consumption", "能耗"),
    "roof_area": ("rooftop_area", "factory_roof_area", "usable_roof_area", "屋顶面积", "厂房屋面面积", "屋面面积"),
    "transformer_capacity": ("变压器容量", "transformer_rating", "主变容量"),
    "load_curve": ("负荷曲线", "load_shape", "load_profile"),
    "capacity": ("产能", "production_capacity", "annual_capacity", "design_capacity", "规划产能"),
    "factory_name": ("工厂名称", "生产基地名称", "基地名称", "plant_name", "site_name"),
    "operator": ("运营主体", "运营公司", "operating_entity"),
    "address": ("地址", "厂区地址", "factory_address", "site_address"),
    "city": ("城市", "所在市"),
    "province": ("省份", "所在省"),
    "processes": ("工艺", "主要工艺", "production_process", "process"),
    "production_lines": ("生产线", "产线", "production_line"),
    "commissioning_date": ("投产时间", "投产日期", "建成时间", "commissioned", "production_date"),
    "project_status": ("项目状态", "建设进度", "项目进展", "status"),
    "product_family": ("产品族", "product_category", "产品类别", "product_type", "类别"),
    "series": ("产品系列", "product_series", "系列"),
    "model": ("型号", "牌号", "product_model", "sku", "规格型号"),
    "category": ("品类", "产品分类", "classification"),
    "description": ("产品描述", "product_description", "介绍"),
    "application": ("应用", "应用领域", "applications", "application_area", "适用场景"),
    "customer_segment": ("客户群体", "目标客户", "客户类型", "target_customer"),
    "sales_channel": ("销售渠道", "渠道结构", "经销渠道", "分销渠道", "distribution_channel", "sales network"),
    "commercial_status": ("商业化状态", "在售状态", "上市状态", "commercialization", "launch_status"),
    "parameter_name": ("参数名称", "parameter", "spec_name"),
    "value": ("数值", "参数值", "parameter_value", "spec_value"),
    "unit": ("单位", "计量单位"),
    "test_condition": ("测试条件", "检测条件", "test_method", "测试方法"),
    "source_document": ("来源文档", "规格书", "datasheet", "spec_sheet"),
    "canonical_company_name": ("company_name", "公司名称", "公司全称", "企业名称", "企业全称", "legal_name"),
    "registered_name": ("注册名称", "registered_company_name", "工商注册名", "法定名称"),
    "aliases": ("别名", "曾用名", "formerly_known_as", "alias"),
    "official_website": ("官网", "官方网站", "website", "company_website"),
    "registration_region": ("注册区域", "注册地", "注册地区", "registered_region", "registration_area"),
    "registration_identifier": ("统一社会信用代码", "uscc", "credit_code", "注册号", "registration_number"),
    "headquarters": ("总部", "总部地址", "总部所在地", "company_headquarters"),
    "founded_date": ("成立时间", "成立日期", "established", "founding_date", "注册时间"),
    "parent_company": ("母公司", "控股股东母公司", "parent"),
    "actual_controller": ("实际控制人", "实控人", "ultimate_controller"),
    "ownership_structure": ("股权结构", "shareholding_structure", "equity_structure"),
    "core_business": ("主营业务", "主要业务", "main_business", "business_scope", "业务范围"),
    "business_segment": ("业务板块", "business_sector", "segment", "板块"),
    "subsidiary_name": ("子公司名称", "subsidiary", "子公司"),
    "subsidiary_relation": ("持股关系", "控股比例", "shareholding_ratio", "股权比例"),
    "organization_structure": ("组织架构", "org_structure", "organizational_structure"),
    "management_team": ("管理层", "高管", "management", "executives"),
    "customer_name": ("客户名称", "customer", "核心客户", "key_customer"),
    "supplier_name": ("供应商名称", "supplier", "核心供应商"),
    "technology": ("核心技术", "技术路线", "core_technology", "技术优势"),
    "certification": ("认证", "体系认证", "certificate", "资质"),
    "export": ("出口", "海外销售", "export_revenue", "overseas_revenue", "出口额"),
    "energy_equipment": ("能源设备", "energy_devices", "用能设备"),
    "project_name": ("项目名称", "project", "energy_project", "能源项目"),
    "project_type": ("项目类型", "project_category"),
    "pv_capacity": ("光伏容量", "光伏装机", "pv_power", "solar_capacity"),
    "storage_power": ("储能功率", "storage_power_rating"),
    "storage_capacity": ("储能容量", "储能电量", "storage_energy"),
    "annual_generation": ("年发电量", "annual_output", "发电量"),
    "EPC_party": ("EPC方", "总承包方", "epc_contractor"),
    "business_risk": ("经营风险", "risk", "主要风险"),
    "compliance_risk": ("合规风险", "regulatory_risk"),
    "project_risk": ("项目风险", "implementation_risk"),
    "carbon_project": ("碳项目", "碳减排项目", "carbon_reduction_project"),
    "waste_heat_recovery": ("余热回收", "余热利用", "waste_heat"),
    "reporting_period": ("报告期", "report_period", "会计期间"),
    "currency": ("币种", "货币"),
    "scope": ("口径", "范围", "statistical_scope"),
    "yoy": ("同比", "同比增长", "year_over_year"),
}

_ALIAS_INDEX: dict[str, str] = {}
for _canonical, _aliases in ALIASES.items():
    _ALIAS_INDEX[_canonical] = _canonical
    for _alias in _aliases:
        _ALIAS_INDEX[_alias] = _canonical
# English canonical fields resolve to themselves.
for _field in FIELD_FAMILIES.values():
    _ALIAS_INDEX.setdefault(_field, _field)


class CanonicalFieldRegistry:
    """Map any raw extracted field name to its canonical field, preserving the raw name."""

    @staticmethod
    def canonicalize(raw_field_name: str) -> str:
        if not raw_field_name:
            return ""
        exact = _ALIAS_INDEX.get(raw_field_name)
        if exact:
            return exact
        folded = "".join(raw_field_name.lower().split())
        for alias, canonical in _ALIAS_INDEX.items():
            if folded in {alias, "".join(alias.lower().split())}:
                return canonical
        # Unrecognized fields keep their raw name as the canonical name; the
        # registry never silently merges unknown fields into a wrong family.
        return raw_field_name

    @staticmethod
    def family(canonical_field: str) -> str | None:
        """Return the field family name for a canonical field, if known."""
        alias = _ALIAS_INDEX.get(canonical_field)
        if alias is None:
            return None
        canonical = alias if alias in FIELD_FAMILIES.values() else alias
        for family, family_field in FIELD_FAMILIES.items():
            if family_field == canonical:
                return family
        return None

    @staticmethod
    def aliases_of(canonical_field: str) -> list[str]:
        return list(ALIASES.get(canonical_field, ()))
