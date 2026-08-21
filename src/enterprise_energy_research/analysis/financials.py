"""Analysis layer (P0 refactor): evidence-bound quantitative analysis.

AnalysisSeries / AnalysisResult are the ONLY carriers of derived numbers
(YoY, CAGR, margin change, share change).  Every result keeps the raw
``source_values``, ``source_ids``, ``period``, ``unit`` and the exact
``formula``/``transformation`` used, so a reviewer can re-derive the number
by hand.  When evidence is insufficient (fewer than the required number of
real periods), the analyst returns nothing for that metric — it never
fabricates a time series to feed a chart.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim

# Field groups the analyst understands.  Unknown fields are ignored, never guessed.
METRICS: dict[str, dict[str, str]] = {
    "revenue": {"label": "营业收入", "method": "flow"},
    "profit": {"label": "净利润", "method": "flow"},
    "employee_count": {"label": "员工人数", "method": "flow"},
    "capacity": {"label": "产能", "method": "flow"},
    "electricity_consumption": {"label": "年度用电量", "method": "flow"},
    "gross_margin": {"label": "毛利率", "method": "pp"},
    "net_margin": {"label": "净利率", "method": "pp"},
    "market_share": {"label": "市场份额", "method": "pp"},
    "unit_price": {"label": "单位售价", "method": "flow"},
}

NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


class SeriesPoint(BaseModel):
    period: str
    value: float
    unit: str | None = None
    source_value: Any = None
    source_id: str
    claim_id: str


class AnalysisSeries(BaseModel):
    """A real, claim-bound time series for one metric of one entity."""

    series_id: str
    entity_id: str
    metric: str
    metric_label: str
    points: list[SeriesPoint] = Field(default_factory=list)

    @property
    def span_years(self) -> int | None:
        years = sorted({point.period[:4] for point in self.points if len(point.period or "") >= 4})
        if len(years) < 2:
            return None
        try:
            return int(years[-1]) - int(years[0])
        except ValueError:
            return None


class AnalysisResult(BaseModel):
    """One derived metric with full derivation trace (P0 anti-fabrication)."""

    result_id: str
    entity_id: str
    metric: str
    metric_label: str
    method: Literal["yoy", "cagr", "delta_pp", "total"]
    value: float
    value_display: str
    source_values: list[Any] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    period: list[str] = Field(default_factory=list)
    unit: str | None = None
    formula: str = ""
    transformation: str = "仅使用已验证冻结证据，无新增假设。"
    verified: bool = True
    assumption_status: Literal["evidence", "analytical_inference"] = "evidence"
    series: AnalysisSeries | None = None

    def items(self, *, unit: str | None = None) -> list[dict[str, Any]]:
        """Export as VisualDatum-compatible rows for a time-series visual."""
        if not self.series:
            return []
        return [
            {
                "label": f"{self.metric_label}{point.period}",
                "value": point.value,
                "unit": point.unit or unit or self.unit,
                "period": point.period,
            }
            for point in self.series.points
        ]


def parse_number(value: Any) -> float | None:
    """Parse a numeric claim value into a float. Chinese magnitude suffixes
    (万/亿/万亿) are applied only when they appear in the value/unit text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    multiplier = 1.0
    if "万亿" in text:
        multiplier = 1e12
    elif "亿" in text:
        multiplier = 1e8
    elif "万" in text:
        multiplier = 1e4
    match = NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0)) * multiplier
    except ValueError:
        return None


class FinancialAnalyst:
    """Build AnalysisSeries / AnalysisResult only from VERIFIED claims."""

    def analyze(self, entity_id: str, claims: list[Claim]) -> list[AnalysisResult]:
        verified = [claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED]
        by_metric: dict[str, list[Claim]] = defaultdict(list)
        for claim in verified:
            if claim.entity_id == entity_id and claim.field_name in METRICS:
                by_metric[claim.field_name].append(claim)
        results: list[AnalysisResult] = []
        for metric, rows in by_metric.items():
            series = self._build_series(entity_id, metric, rows)
            if not series or len(series.points) < 2:
                continue
            results.extend(self._derive(metric, series))
        return results

    @staticmethod
    def _period_of(claim: Claim) -> str:
        if claim.period_start:
            return claim.period_start.strftime("%Y-%m")
        if claim.period_end:
            return claim.period_end.strftime("%Y-%m")
        if claim.as_of_date:
            return claim.as_of_date.strftime("%Y-%m")
        return ""

    def _build_series(self, entity_id: str, metric: str, rows: list[Claim]) -> AnalysisSeries | None:
        points: list[SeriesPoint] = []
        for claim in rows:
            value = parse_number(claim.value)
            if value is None:
                continue
            period = self._period_of(claim)
            points.append(SeriesPoint(
                period=period or f"未标注{len(points) + 1}",
                value=value,
                unit=claim.unit,
                source_value=claim.value,
                source_id=claim.source_id,
                claim_id=claim.claim_id,
            ))
        points.sort(key=lambda point: point.period)
        if len(points) < 2:
            return None
        return AnalysisSeries(
            series_id=new_sortable_id("SERIES"),
            entity_id=entity_id,
            metric=metric,
            metric_label=METRICS[metric]["label"],
            points=points,
        )

    def _derive(self, metric: str, series: AnalysisSeries) -> list[AnalysisResult]:
        results: list[AnalysisResult] = []
        info = METRICS[metric]
        points = series.points
        method: Literal["yoy", "cagr", "delta_pp", "total"] = "total"
        if info["method"] == "pp":
            method = "delta_pp"
        elif len(points) >= 3:
            method = "cagr"
        else:
            method = "yoy"
        first, last = points[0], points[-1]
        years = series.span_years
        if method == "cagr" and years and years >= 1:
            ratio = last.value / first.value if first.value else None
            if ratio is None or ratio <= 0:
                return results
            cagr = (ratio ** (1 / years) - 1) * 100
            formula = f"(({last.value}/{first.value})^(1/{years})-1)×100"
            value_display = f"年均复合增速 {cagr:+.1f}%"
        elif method == "yoy":
            delta = (last.value - first.value) / first.value * 100 if first.value else None
            if delta is None:
                return results
            formula = f"({last.value}-{first.value})/{first.value}×100"
            value_display = f"较前期 {delta:+.1f}%"
        else:  # delta_pp
            delta = last.value - first.value
            formula = f"{last.value}-{first.value}"
            value_display = f"变化 {delta:+.2f} 个百分点"
        results.append(AnalysisResult(
            result_id=new_sortable_id("ANL"),
            entity_id=series.entity_id,
            metric=metric,
            metric_label=info["label"],
            method=method,
            value=round(cagr if method == "cagr" else delta, 4),
            value_display=value_display,
            source_values=[point.source_value for point in points],
            source_ids=[point.source_id for point in points],
            source_claim_ids=[point.claim_id for point in points],
            period=[point.period for point in points],
            unit=points[0].unit,
            formula=formula,
            transformation=f"仅使用已验证冻结证据（{len(points)} 个真实期间），无插值、无预测。",
            series=series,
        ))
        return results


def analysis_series_items(result: AnalysisResult) -> list[dict[str, Any]]:
    return result.items()
