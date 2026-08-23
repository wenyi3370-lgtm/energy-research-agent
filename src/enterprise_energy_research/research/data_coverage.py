"""Research Data Coverage Contract + audit (P0 third round).

The old pipeline stopped when it had "enough claims".  The new contract
states WHICH data a formal research report actually needs, and audits the
accumulated evidence against it.  A missing high-value dataset (e.g. only
one year of revenue for a listed company) becomes a machine-readable
CoverageGap that triggers a TARGETED retry (annual reports, exchange
filings, investor relations) — instead of being papered over with prose.

Audit never fabricates: every requirement is either met from verified
evidence or reported as a gap.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import EnterpriseComplexity, VerificationStatus

YEAR_RE_STR = r"(?:19|20)\d{2}"


class CoverageGap(BaseModel):
    gap_code: str
    field_name: str
    description: str
    requirement: str
    found: str
    severity: str = Field(default="high")  # high | medium | low
    retry_hint: str = ""

    @property
    def searchable(self) -> bool:
        return bool(self.retry_hint)


class CoverageAudit(BaseModel):
    entity_name: str
    listed: bool
    status: str = "OK"  # OK | GAPS
    gaps: list[CoverageGap] = Field(default_factory=list)

    @property
    def high_gaps(self) -> list[CoverageGap]:
        return [gap for gap in self.gaps if gap.severity == "high"]

    @property
    def high_value_missing(self) -> bool:
        return any(gap.severity == "high" for gap in self.gaps)


class ResearchDataCoverageValidator:
    """Audit one evidence collection against the research data contract."""

    FINANCIAL_REQUIREMENTS = [
        ("revenue", "营业收入", "high", 3),
        ("profit", "归母净利润", "high", 3),
        ("gross_margin", "毛利率", "medium", 3),
        ("rnd_expense", "研发投入", "high", 3),
        ("rnd_expense_ratio", "研发费用率", "medium", 1),
        ("operating_cash_flow", "经营活动现金流", "medium", 3),
    ]
    SEGMENT_FIELDS = (
        "battery_revenue", "storage_revenue", "material_revenue",
        "energy_business_revenue", "domestic_revenue", "overseas_revenue",
        "segment_revenue", "business_segment",
    )

    def audit(
        self,
        *,
        entity_name: str,
        claims: list[Any],
        products: list[Any],
        factories: list[Any],
        images: list[Any] | None = None,
        complexity: EnterpriseComplexity | None = None,
        has_stock_code: bool = False,
    ) -> CoverageAudit:
        verified = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
        by_field: dict[str, list[Any]] = {}
        for claim in verified:
            by_field.setdefault(claim.field_name, []).append(claim)
        listed = has_stock_code or complexity in {
            EnterpriseComplexity.GROUP_LARGE, EnterpriseComplexity.ENTERPRISE_NORMAL,
        }
        gaps: list[CoverageGap] = []

        def distinct_years(rows: list[Any]) -> set[str]:
            years: set[str] = set()
            for claim in rows:
                period = (
                    claim.period_start.year if getattr(claim, "period_start", None)
                    else claim.period_end.year if getattr(claim, "period_end", None)
                    else claim.as_of_date.year if getattr(claim, "as_of_date", None)
                    else None
                )
                if period is not None:
                    years.add(str(period))
            return years

        if listed:
            for field_name, label, severity, min_years in self.FINANCIAL_REQUIREMENTS:
                rows = by_field.get(field_name, [])
                years = distinct_years(rows)
                if len(years) >= min_years:
                    continue
                # Year-specific annual-report targeting: the old generic
                # "最近5年 年报" query returned current-year pages only.
                retry_hint = (
                    f"2022年年度报告 2023年年度报告 2024年年度报告 主要会计数据 {label} 上年同期 可比口径"
                    if field_name in {"revenue", "profit"} and severity == "high"
                    else f"最近{min_years + 2}年 年报 主要会计数据 {label} 分年度 可比口径"
                    if severity != "low" else f"年报 {label} 期间"
                )
                gaps.append(CoverageGap(
                    gap_code=f"coverage-{field_name}", field_name=field_name,
                    description=f"缺少 {min_years} 个以上可比年度的{label}数据",
                    requirement=f"≥ {min_years} 个年度",
                    found=f"现有 {len(years)} 个年度（{','.join(sorted(years)) or '无明确期间'}）",
                    severity=severity,
                    retry_hint=retry_hint,
                ))
            segment_rows = [row for field in self.SEGMENT_FIELDS for row in by_field.get(field, [])]
            if len(segment_rows) < 2:
                gaps.append(CoverageGap(
                    gap_code="coverage-segments", field_name="segment_revenue",
                    description="缺少分业务/分区域收入构成数据",
                    requirement="≥ 2 个业务板块或区域口径",
                    found=f"现有 {len(segment_rows)} 条",
                    severity="medium",
                    retry_hint="分业务收入 动力电池 储能 境内 境外 营业收入构成 年报 董事会报告",
                ))
            if not (by_field.get("market_share") or by_field.get("industry_position")):
                gaps.append(CoverageGap(
                    gap_code="coverage-market-position", field_name="market_share",
                    description="缺少市场地位数据（份额/装机量/排名）",
                    requirement="≥ 1 条可靠行业来源",
                    found="无",
                    severity="medium",
                    retry_hint="装机量 市场份额 全球排名 行业数据",
                ))

        if not factories:
            if "capacity" in by_field or any("factory" in field for field in by_field):
                gaps.append(CoverageGap(
                    gap_code="coverage-factories", field_name="factories",
                    description="缺少生产基地结构化数据",
                    requirement="≥ 1 处基地（名称+地区）",
                    found="无",
                    severity="high",
                    retry_hint="生产基地 工厂 厂区 地址 产能布局",
                ))
        else:
            located = [factory for factory in factories if getattr(factory, "address", None)]
            if len(located) < min(3, len(factories)):
                gaps.append(CoverageGap(
                    gap_code="coverage-factory-regions", field_name="factory_regions",
                    description="生产基地缺少可用于区域布局分析的地点信息",
                    requirement=f"≥ {min(3, len(factories))} 处基地具有地区/地址",
                    found=f"现有 {len(located)} 处",
                    severity="medium",
                    retry_hint="全球生产基地 区域布局 工厂 地址 海外基地 官方",
                ))
            with_process = [factory for factory in factories if getattr(factory, "processes", None)]
            if not with_process:
                gaps.append(CoverageGap(
                    gap_code="coverage-factory-products", field_name="factory_products",
                    description="基地与产品/工艺之间尚未形成结构化映射",
                    requirement="≥ 1 处基地披露产品或主要工艺",
                    found="无",
                    severity="medium",
                    retry_hint="生产基地 主要产品 生产线 工艺 产能 官方",
                ))
            capacity_rows = [
                row for field in ("capacity", "production_capacity", "battery_production_capacity")
                for row in by_field.get(field, [])
            ]
            if not capacity_rows:
                gaps.append(CoverageGap(
                    gap_code="coverage-factory-capacity", field_name="factory_capacity",
                    description="制造布局缺少可核验的产能口径",
                    requirement="≥ 1 条带单位、期间或范围的产能数据",
                    found="无",
                    severity="medium",
                    retry_hint="生产基地 产能 GWh 年产能 项目环评 官方公告",
                ))

        parameterized = [
            product for product in products
            if product.verification_status == VerificationStatus.VERIFIED and product.parameters
        ]
        if len(parameterized) < 3:
            gaps.append(CoverageGap(
                gap_code="coverage-product-parameters", field_name="product_parameters",
                description="带公开参数的重点产品不足",
                requirement="≥ 3 项产品具有参数",
                found=f"现有 {len(parameterized)} 项",
                severity="medium",
                retry_hint="产品 技术参数 能量密度 循环寿命 充电倍率 规格书 datasheet",
            ))

        verified_products = [product for product in products if product.verification_status == VerificationStatus.VERIFIED]
        product_images = [
            image for image in (images or [])
            if getattr(image, "product_id", None) is not None
            and getattr(image, "target_entity_type", None) == "product"
            and getattr(image, "target_entity_id", None) == getattr(image, "product_id", None)
            and image.verification_status == VerificationStatus.VERIFIED
            and getattr(image, "visual_verified", False)
        ]
        required_product_images = min(5, len(verified_products))
        bound_product_ids = {
            getattr(image, "product_id", None)
            for image in product_images
        }
        if required_product_images and len(bound_product_ids) < required_product_images:
            gaps.append(CoverageGap(
                gap_code="coverage-product-images", field_name="product_images",
                description="重点产品的官网图片覆盖不足",
                requirement=f"≥ {required_product_images} 个不同产品具有 product_id 绑定且视觉核验通过的图片",
                found=f"现有 {len(bound_product_ids)} 个产品（{len(product_images)} 张图片）",
                severity="high",
                retry_hint="官网 产品中心 产品详情 官方手册 产品图片 高清图",
            ))

        own_energy_fields = {
            "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
            "peak_demand", "electricity_cost", "load_curve", "renewable_share",
        }
        energy_capability_fields = {
            "storage_capacity", "storage_power", "pv_capacity", "energy_project",
            "carbon_project", "technology", "product_family",
        }
        own_energy_rows = [row for field in own_energy_fields for row in by_field.get(field, [])]
        capability_rows = [row for field in energy_capability_fields for row in by_field.get(field, [])]
        if capability_rows and not own_energy_rows:
            gaps.append(CoverageGap(
                gap_code="coverage-own-energy", field_name="own_energy_metrics",
                description="已识别能源产品/项目能力，但缺少企业自身能源消费数据",
                requirement="企业自身用电量、负荷、电价或可再生能源占比至少 1 项；不得以产品容量替代",
                found="企业能源能力与企业能源消费尚未形成双口径数据",
                severity="medium",
                retry_hint="可持续发展报告 用电量 能源消耗 绿电比例 峰值负荷 电费",
            ))

        return CoverageAudit(
            entity_name=entity_name, listed=listed,
            status="OK" if not gaps else "GAPS", gaps=gaps,
        )
