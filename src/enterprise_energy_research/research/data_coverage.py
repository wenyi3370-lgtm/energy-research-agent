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
        ("gross_margin", "毛利率", "medium", 2),
        ("rnd_expense", "研发投入", "medium", 1),
        ("rnd_expense_ratio", "研发费用率", "medium", 1),
        ("operating_cash_flow", "经营活动现金流", "low", 1),
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
            and image.verification_status == VerificationStatus.VERIFIED
        ]
        if len(verified_products) >= 5 and not product_images:
            gaps.append(CoverageGap(
                gap_code="coverage-product-images", field_name="product_images",
                description="已核验产品 ≥5 项但缺少绑定产品的合格图片",
                requirement="≥ 1 张 product_id 绑定且视觉核验通过的图片",
                found=f"现有 {len(product_images)} 张",
                severity="high",
                retry_hint="官网产品页 产品图片 产品中心 高清图",
            ))

        return CoverageAudit(
            entity_name=entity_name, listed=listed,
            status="OK" if not gaps else "GAPS", gaps=gaps,
        )
