from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle


_DEFAULT_PALETTE = {
    "navy": "#1B365D",
    "cobalt": "#2D5A8A",
    "purple": "#6F2B86",
    "gray": "#6B7280",
    "pale": "#D9E2EC",
    "canvas": "#F7F8FA",
    "black": "#111111",
    "white": "#FFFFFF",
}


def _palette() -> dict[str, str]:
    """Chart palette driven by config/office_visual_policy.yaml theme colors.

    Falls back to the built-in SEVC palette when the policy file is absent;
    edits to the policy restyle every generated chart without code changes.
    """
    try:
        from enterprise_energy_research.artifacts.visual_policy import colors as theme_colors

        tc = theme_colors()
        return {
            "navy": tc["navy"],
            "cobalt": tc["cobalt"],
            "purple": tc["sevc_purple"],
            "gray": tc["cool_gray"],
            "pale": tc["pale_gray"],
            "canvas": tc["canvas"],
            "black": tc["black"],
            "white": tc["white"],
        }
    except Exception:  # noqa: BLE001 - policy is optional
        return dict(_DEFAULT_PALETTE)


PALETTE = _palette()


def _png_dpi() -> int:
    """Chart PNG DPI driven by config/office_visual_policy.yaml (default 300)."""
    try:
        from enterprise_energy_research.artifacts.visual_policy import word_policy

        return int(word_policy().get("figure_png_dpi", 300))
    except Exception:  # noqa: BLE001 - policy is optional
        return 300


class VisualDatum(BaseModel):
    label: str
    value: float | int | str | None = None
    unit: str | None = None
    note: str | None = None
    status: str | None = None


class VisualSpec(BaseModel):
    visual_id: str
    chapter_key: str
    title: str
    purpose: str
    family: str
    canonical_type: str
    items: list[VisualDatum] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_image_ids: list[str] = Field(default_factory=list)
    source_note: str
    transformation: str
    units: str = "见图中标注"
    display_rounding: str = "整数计数；原始披露值保持其口径"
    visual_class: str = "analysis"
    artifact_targets: list[str] = Field(default_factory=lambda: ["word", "html", "ppt"])
    renderer: str | None = None
    template_id: str | None = None
    template_name: str | None = None
    template_candidates: list[str] = Field(default_factory=list)
    template_rationale: str | None = None
    data_contract: str | None = None
    chart_license: str | None = None
    template_source: str | None = None
    template_card_title: str | None = None
    color_system: str | None = None


class VisualManifest(BaseModel):
    schema_version: str = "1.0"
    freeze_id: str
    theme: str = "sevc-kami-broker-v2"
    minimum_font_pt: int = 8
    png_dpi: int = 300
    visuals: list[VisualSpec]


_LIEFLAT_LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"
_LIEFLAT_SELECTIONS: dict[str, dict[str, Any]] = {
    "horizontal_bar": {
        "template_id": "F5",
        "template_name": "Tick Rows",
        "template_candidates": ["F5 Tick Rows", "F1 Rung Bars", "L2 Dot Cascade"],
        "template_rationale": "F5 preserves long labels, exact row-end values, and countable units for up to eight ranked categories.",
        "data_contract": "2–8 nonnegative numeric categories sharing a comparable count unit with at least two distinct values",
        "template_source": "templates/basics-gallery.html",
        "template_card_title": "Six teams, shipped and counted",
    },
    "donut": {
        "template_id": "F4",
        "template_name": "Tick Donut",
        "template_candidates": ["F4 Tick Donut", "L14 Hundred Field", "G4 Dot Waffle"],
        "template_rationale": "F4 preserves a compact composition silhouette while exposing every percentage point as a countable tick.",
        "data_contract": "2–6 nonnegative numeric segments with a positive total",
        "template_source": "templates/basics-gallery.html",
        "template_card_title": "Where the traffic comes from",
    },
    "funnel": {
        "template_id": "L13",
        "template_name": "Hourglass Stream",
        "template_candidates": ["L13 Hourglass Stream", "F5 Tick Rows", "L15 Ballot Tally"],
        "template_rationale": "L13 is the catalog's direct match for an ordered, decreasing stage-count funnel while keeping every stage value explicit.",
        "data_contract": "3–6 nonnegative numeric stages in non-increasing order with at least one drop",
        "template_source": "templates/lupi-gallery.html",
        "template_card_title": "The funnel, poured",
    },
}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _lieflat_license_status() -> str:
    """Fail closed only when the caller explicitly declares commercial use.

    Local evaluation remains usable under the upstream PolyForm Noncommercial
    terms.  Setting ``EER_LIEFLAT_COMMERCIAL_USE=true`` requires a separate
    authorization acknowledgement before a report can be rendered.
    """
    commercial_use = _truthy_env("EER_LIEFLAT_COMMERCIAL_USE")
    commercial_authorized = _truthy_env("EER_LIEFLAT_COMMERCIAL_LICENSED")
    if commercial_use and not commercial_authorized:
        raise RuntimeError(
            "Lieflat Charts commercial use was declared but no commercial authorization was acknowledged; "
            "set EER_LIEFLAT_COMMERCIAL_LICENSED=true only after obtaining the necessary rights."
        )
    return "commercial-authorized" if commercial_use else "polyform-noncommercial-1.0.0"


def _with_renderer_metadata(spec: VisualSpec) -> VisualSpec | None:
    selection = _LIEFLAT_SELECTIONS.get(spec.family)
    if not selection:
        return None
    rows = _numeric_items(spec, limit=8)
    values = [value for _, value in rows]
    if spec.family == "horizontal_bar" and not (
        2 <= len(rows) <= 8 and max(values, default=0) > 0 and len(set(values)) >= 2
    ):
        return None
    if spec.family == "donut" and not (2 <= len(rows) <= 6 and sum(values) > 0):
        return None
    if spec.family == "funnel":
        valid_order = all(left >= right for left, right in zip(values, values[1:]))
        if not (3 <= len(rows) <= 6 and valid_order and any(left > right for left, right in zip(values, values[1:]))):
            return None
    return spec.model_copy(update={
        **selection,
        "renderer": "lieflat-charts-gallery-port-svg-v2",
        "color_system": "mono",
        "chart_license": _lieflat_license_status(),
    })


class VisualPlanner:
    """Deterministically route data semantics to Lieflat catalog templates.

    The router intentionally has no process, organization, hierarchy, or
    generic-network route.  A text-only LLM can choose a data kind and receive
    the same audited template without making visual judgments.
    """

    RECOMMENDATIONS: dict[str, tuple[str, ...]] = {
        "time_series": ("F2", "F3", "L3"),
        "category_comparison": ("F5", "F1", "L2"),
        "two_metrics": ("F6", "F12"),
        "composition": ("F4", "L14", "F7"),
        "multi_dimension_score": ("L20",),
        "two_dimension_opportunity": ("F8",),
        "entity_opportunity": ("L16", "G20"),
        "distribution": ("G19", "L19", "F15"),
        "funnel": ("L13",),
    }

    def recommend(self, data_kind: str, *, preferred: str | None = None) -> str:
        candidates = self.RECOMMENDATIONS.get(data_kind)
        if not candidates:
            raise ValueError(f"Unsupported visual data kind: {data_kind}")
        if preferred and preferred in candidates:
            return preferred
        return candidates[0]


def _datum(label: str, value: Any = None, *, unit: str | None = None, note: str | None = None, status: str | None = None) -> VisualDatum:
    return VisualDatum(label=str(label)[:34], value=value, unit=unit, note=note, status=status)


def _source_note(bundle: FrozenResearchBundle, claim_ids: Iterable[str] = ()) -> str:
    ids = list(dict.fromkeys(claim_ids))
    suffix = f"；来源主张：{', '.join(ids[:8])}" if ids else "；由冻结实体记录派生"
    return f"数据来源：证据冻结 {bundle.freeze.freeze_id}{suffix}。"


def _numeric_value(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        compact = value.replace(",", "").replace("，", "").strip()
        match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", compact)
        if match:
            number = float(compact)
            return int(number) if number.is_integer() else number
    return None


def build_visual_manifest(bundle: FrozenResearchBundle, binding: ArtifactBinding) -> VisualManifest:
    bound_claims = [claim for claim in bundle.claims if claim.claim_id in binding.claim_ids]
    verified = [claim for claim in bound_claims if claim.verification_status == VerificationStatus.VERIFIED]
    numeric_claims = [(claim, _numeric_value(claim.value)) for claim in verified]
    numeric_claims = [(claim, value) for claim, value in numeric_claims if value is not None][:4]
    status_counts = Counter(claim.verification_status.value for claim in bound_claims)
    category_counts = Counter(product.category or "未分类" for product in bundle.products)
    priority_counts = Counter(solution.priority for solution in bundle.solutions)
    engine_counts = Counter(solution.engine for solution in bundle.solutions)
    image_counts = Counter(image.image_type for image in bundle.images if image.image_id in binding.image_ids)
    source_levels = Counter(source.source_level.value for source in bundle.sources)
    factory_items = [
        _datum(factory.name or f"生产基地 {index}", len(factory.processes), unit="项工艺", note=factory.address or "地址待核验")
        for index, factory in enumerate(bundle.factories[:6], start=1)
    ] or [_datum("生产基地信息", "待尽调", note="冻结证据未形成可发布基地记录")]
    product_items = [_datum(label, value, unit="项") for label, value in category_counts.most_common(6)]
    if not product_items:
        product_items = [_datum("实体产品记录", "待补充", note="不把业务描述推断为产品目录")]
    entity_items = [
        _datum(entity.canonical_name, entity.entity_type, note=entity.registration_region or "区域待核验")
        for entity in bundle.entities[:7]
    ]
    energy_items: list[VisualDatum] = []
    for profile in bundle.energy_profiles[:4]:
        label = profile.factory_id or profile.entity_id
        equipment_count = len(profile.electricity_equipment) + len(profile.gas_equipment)
        energy_items.append(_datum(label, equipment_count, unit="类设备", note="、".join(profile.processes[:3]) or "工艺待核验"))
    if not energy_items:
        energy_items = [_datum("工艺", "待核验"), _datum("用能设备", "待核验"), _datum("负荷与设施", "现场尽调")]
    gap_items = [_datum(gap.field_name, gap.importance, note=gap.next_action, status=gap.reason) for gap in bundle.gaps[:6]]
    if not gap_items:
        gap_items = [_datum("关键数据缺口", "未登记", note="正式决策前仍需现场测量与商务核验")]
    risk_items: list[VisualDatum] = []
    for solution in bundle.solutions:
        for risk in solution.risks[:2]:
            risk_items.append(_datum(solution.engine, solution.priority, note=risk, status=solution.statement_type.value))
    if not risk_items:
        risk_items = [_datum("技术", "待尽调"), _datum("商务", "待尽调"), _datum("合规", "待尽调"), _datum("现场数据", "待尽调")]
    solution_items = [
        _datum(solution.engine, solution.priority, note=solution.opportunity, status=solution.statement_type.value)
        for solution in bundle.solutions[:8]
    ] or [_datum(engine, "待形成方案") for engine in ("EPC", "ZERO CARBON", "STORAGE ODM", "OVERSEAS")]

    specs = [
        VisualSpec(
            visual_id="FIG-01-EXECUTIVE-DASHBOARD", chapter_key="executive_summary",
            title="调研对象与冻结证据概览", purpose="用少量关键计数建立报告边界",
            family="kpi_tiles", canonical_type="kpi_cards",
            items=[_datum("核验主张", len(verified), unit="条"), _datum("企业实体", len(bundle.entities), unit="个"), _datum("生产基地", len(bundle.factories), unit="个"), _datum("实体产品", len(bundle.products), unit="项")],
            source_claim_ids=[claim.claim_id for claim in verified], source_note=_source_note(bundle, [claim.claim_id for claim in verified]),
            transformation="对冻结记录按对象类型去重计数。",
        ),
        VisualSpec(
            visual_id="FIG-02-RESEARCH-FUNNEL", chapter_key="research_scope",
            title="冻结主张核验漏斗", purpose="展示绑定主张、已核验主张与可发布数值的逐级收敛",
            family="funnel", canonical_type="funnel",
            items=[_datum("绑定主张", len(bound_claims), unit="条"), _datum("已核验主张", len(verified), unit="条"), _datum("可发布数值", len(numeric_claims), unit="项")],
            source_claim_ids=[claim.claim_id for claim in bound_claims], source_note=_source_note(bundle, [claim.claim_id for claim in bound_claims]),
            transformation="按绑定范围、verification_status 和可解析数值逐级筛选；各阶段为前一阶段子集。",
        ),
        VisualSpec(
            visual_id="FIG-03-ENTITY-MAP", chapter_key="entity_overview",
            title="企业实体与集团边界", purpose="展示冻结范围内的企业主体和核验边界",
            family="network", canonical_type="entity_network", items=entity_items,
            source_claim_ids=[claim.claim_id for claim in verified if claim.field_name in {"canonical_company_name", "controller", "subsidiary"}],
            source_note=_source_note(bundle), transformation="按冻结实体记录展示，不推断未核验控制关系。",
        ),
        VisualSpec(
            visual_id="FIG-04-PRODUCT-PORTFOLIO", chapter_key="products",
            title="已核验产品组合", purpose="展示产品目录覆盖而非关键词样本",
            family="horizontal_bar", canonical_type="ranking_bar", items=product_items,
            source_claim_ids=[claim.claim_id for claim in verified if "product" in claim.field_name.lower()],
            source_note=_source_note(bundle), transformation="按冻结产品 category 字段分组计数；未分类单列。", units="产品项数",
        ),
        VisualSpec(
            visual_id="FIG-05-FACTORY-FOOTPRINT", chapter_key="factories",
            title="生产基地已披露工艺项数", purpose="按基地比较冻结记录中已披露的工艺项数",
            family="horizontal_bar", canonical_type="ranking_bar", items=factory_items,
            source_claim_ids=[claim.claim_id for claim in verified if claim.field_name in {"factory", "address", "process"}],
            source_note=_source_note(bundle), transformation="按冻结生产基地记录计数工艺项；地址仅作行级备注，不构造空间关系。",
        ),
        VisualSpec(
            visual_id="FIG-06-EVIDENCE-COVERAGE", chapter_key="core_evidence",
            title="核心证据核验状态", purpose="区分已核验、冲突与待核验材料",
            family="donut", canonical_type="donut",
            items=[_datum(status, count, unit="条") for status, count in status_counts.items()] or [_datum("无绑定主张", 1, unit="项")],
            source_claim_ids=[claim.claim_id for claim in bound_claims], source_note=_source_note(bundle, [claim.claim_id for claim in bound_claims]),
            transformation="按 verification_status 聚合计数。", units="主张条数",
        ),
        VisualSpec(
            visual_id="FIG-06-OPERATING-KPIS", chapter_key="operating_metrics",
            title="已核验经营与生产指标", purpose="保留数值、单位、时间与范围口径并列展示",
            family="kpi_tiles", canonical_type="operating_kpi_cards",
            items=[
                _datum(claim.field_name.replace("_", " "), value, unit=claim.unit, note=" / ".join(filter(None, [str(claim.as_of_date or ""), claim.scope or ""])) or "原披露口径")
                for claim, value in numeric_claims
            ] or [
                _datum("已核验主张", len(verified), unit="条"), _datum("冲突组", len(bundle.conflicts), unit="组"),
                _datum("数据缺口", len(bundle.gaps), unit="项"), _datum("来源", len(bundle.sources), unit="个"),
            ],
            source_claim_ids=[claim.claim_id for claim, _ in numeric_claims] or [claim.claim_id for claim in verified],
            source_note=_source_note(bundle, [claim.claim_id for claim, _ in numeric_claims] or [claim.claim_id for claim in verified]),
            transformation="直接展示最多四项已核验数值；不同单位不在同一坐标轴比较。",
        ),
        VisualSpec(
            visual_id="FIG-07-ENERGY-CHAIN", chapter_key="energy",
            title="工艺—设备—负荷—合作机会链", purpose="显示公开证据与现场尽调之间的衔接",
            family="process", canonical_type="energy_process", items=energy_items,
            source_claim_ids=list(dict.fromkeys(cid for profile in bundle.energy_profiles for cid in profile.claim_ids)),
            source_note=_source_note(bundle), transformation="按冻结能源画像将工艺和用能设备建立展示关系；缺口保持待尽调。",
        ),
    ]
    engine_meta = [
        ("epc", "EPC", "FIG-08-EPC", "新能源 EPC 机会证据链"),
        ("zero_carbon", "ZERO_CARBON", "FIG-09-ZERO-CARBON", "零碳与节能改造决策框架"),
        ("storage_odm", "STORAGE_ODM", "FIG-10-STORAGE-ODM", "储能 ODM 适配框架"),
        ("overseas", "OVERSEAS", "FIG-11-OVERSEAS", "出海合作进入框架"),
    ]
    # family 差异化：四章合作视觉不得同型（规范：任一标准图型最多重复 2 次）
    engine_families = {
        "epc": "process", "zero_carbon": "decision_tree",
        "storage_odm": "matrix", "overseas": "funnel",
    }
    for chapter_key, engine, visual_id, title in engine_meta:
        matched = [item for item in solution_items if item.label == engine]
        specs.append(VisualSpec(
            visual_id=visual_id, chapter_key=chapter_key, title=title,
            purpose="将证据、方案、风险与下一步放在同一决策画布",
            family=engine_families[chapter_key], canonical_type=f"{chapter_key}_decision_canvas",
            items=matched or [_datum(engine, "证据不足", note="保留合作方向并进入尽调，不作收益承诺")],
            source_claim_ids=list(dict.fromkeys(cid for solution in bundle.solutions if solution.engine == engine for cid in solution.claim_ids)),
            source_note=_source_note(bundle), transformation="直接映射冻结解决方案记录，不新增收益假设。",
        ))
    specs.extend([
        VisualSpec(
            visual_id="FIG-12-COOPERATION-MODEL", chapter_key="cooperation",
            title="四类合作模式组合", purpose="比较合作方向、优先级与证据状态",
            family="matrix", canonical_type="cooperation_matrix", items=solution_items,
            source_claim_ids=list(dict.fromkeys(cid for solution in bundle.solutions for cid in solution.claim_ids)),
            source_note=_source_note(bundle), transformation="按 engine、priority 与 statement_type 映射。",
        ),
        VisualSpec(
            visual_id="FIG-13-ROADMAP", chapter_key="roadmap",
            title="90 天合作推进路线", purpose="把尽调、验证和商务决策转换为阶段动作",
            family="timeline", canonical_type="roadmap_timeline",
            items=[_datum("0–30 天", "证据补齐", note="确认边界、基地、负荷和产品目录"), _datum("31–60 天", "联合验证", note="样品、测量、方案和口径核验"), _datum("61–90 天", "商务决策", note="报价、合同、M&V 和实施计划"), _datum("90+ 天", "复制扩展", note="基于已验证结果扩展基地或市场")],
            source_claim_ids=list(dict.fromkeys(cid for solution in bundle.solutions for cid in solution.claim_ids)),
            source_note=_source_note(bundle), transformation="把冻结解决方案 next_step 按阶段归纳；具体日期须双方确认。",
        ),
        VisualSpec(
            visual_id="FIG-14-RISK-MATRIX", chapter_key="risks",
            title="风险与核验边界矩阵", purpose="把风险归属和待核验动作显性化",
            family="risk_matrix", canonical_type="risk_matrix", items=risk_items,
            source_claim_ids=list(dict.fromkeys(cid for solution in bundle.solutions for cid in solution.claim_ids)),
            source_note=_source_note(bundle), transformation="按解决方案风险原文分组；不虚构概率或损失等级。",
        ),
        VisualSpec(
            visual_id="FIG-15-DECISION-GATES", chapter_key="conclusion",
            title="从公开证据到项目决策的闸门", purpose="明确报告结论可支持和不可替代的决策",
            family="decision_tree", canonical_type="decision_gates",
            items=[_datum("公开证据", "已冻结"), _datum("关键缺口", len(bundle.gaps), unit="项"), _datum("现场尽调", "必须"), _datum("技术/商务核验", "必须"), _datum("投资决策", "条件通过")],
            source_claim_ids=[claim.claim_id for claim in verified], source_note=_source_note(bundle),
            transformation="依据冻结证据、缺口和方案边界形成决策门，不构成投资承诺。",
        ),
        VisualSpec(
            visual_id="FIG-A1-SOURCE-MIX", chapter_key="appendix_sources",
            title="来源层级构成", purpose="披露证据来源层级",
            family="donut", canonical_type="source_mix",
            items=[_datum(level, count, unit="个来源") for level, count in source_levels.items()] or [_datum("来源", 0, unit="个")],
            source_claim_ids=[], source_note=_source_note(bundle), transformation="按 source_level 聚合来源数。",
        ),
        VisualSpec(
            visual_id="FIG-A2-IMAGE-MIX", chapter_key="appendix_images",
            title="已核验图片类型构成", purpose="披露可用于正式报告的图片证据",
            family="donut", canonical_type="image_mix",
            items=[_datum(kind, count, unit="张") for kind, count in image_counts.items()] or [_datum("已核验图片", 0, unit="张")],
            source_image_ids=list(binding.image_ids), source_note=_source_note(bundle), transformation="按 image_type 聚合绑定图片数。",
        ),
        VisualSpec(
            visual_id="FIG-A3-GAP-REGISTER", chapter_key="appendix_gaps",
            title="数据缺口与尽调动作", purpose="将缺口转化为可执行的补数计划",
            family="risk_matrix", canonical_type="gap_register", items=gap_items,
            source_claim_ids=[], source_note=_source_note(bundle), transformation="直接映射冻结 data_gap 记录。",
        ),
    ])
    claim_source = {claim.claim_id: claim.source_id for claim in bundle.claims}
    hydrated: list[VisualSpec] = []
    for spec in specs:
        selected = _with_renderer_metadata(spec.model_copy(update={
            "source_ids": list(dict.fromkeys(claim_source[claim_id] for claim_id in spec.source_claim_ids if claim_id in claim_source)),
            "visual_class": "data",
        }))
        if selected is not None:
            hydrated.append(selected)
    return VisualManifest(freeze_id=bundle.freeze.freeze_id, visuals=hydrated)


def write_visual_manifest(manifest: VisualManifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_visual_bundle(spec: VisualSpec, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / f"{spec.visual_id}.svg"
    png_path = output_dir / f"{spec.visual_id}.png"
    html_path = output_dir / f"{spec.visual_id}.html"
    svg_path.write_text(render_visual_svg(spec), encoding="utf-8")
    _png(spec, png_path)
    html_path.write_text(_standalone_html(spec), encoding="utf-8")
    return png_path, svg_path


def _short(value: Any, maximum: int = 28) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "—")).strip()
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _display_value(item: VisualDatum) -> str:
    value = _short(item.value, 16)
    return f"{value}{item.unit or ''}"


def _svg_text(x: int, y: int, text: str, size: int, *, weight: int = 400, color: str = PALETTE["black"], anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" font-family="Inter, Microsoft YaHei, sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(_short(text, 58))}</text>'


def _numeric_items(spec: VisualSpec, limit: int = 8) -> list[tuple[VisualDatum, float]]:
    return [
        (item, max(0.0, float(item.value)))
        for item in spec.items[:limit]
        if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
    ]


def _tick_unit(maximum: float, target_ticks: int = 40) -> float:
    if maximum <= target_ticks:
        return 1.0
    raw = maximum / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    nice = 1 if normalized <= 1 else 2 if normalized <= 2 else 5 if normalized <= 5 else 10
    return nice * magnitude


def _hundred_allocation(values: list[float]) -> list[int]:
    total = sum(values)
    if total <= 0:
        return [0 for _ in values]
    exact = [value / total * 100 for value in values]
    counts = [math.floor(value) for value in exact]
    for index in sorted(range(len(values)), key=lambda i: exact[i] - counts[i], reverse=True)[: 100 - sum(counts)]:
        counts[index] += 1
    return counts


_LF = {
    "ink": "#1C1C1A",
    "paper": "#F0EFEB",
    "muted": "#8F8E88",
    "faint": "#C6C5BF",
    "grid": "#DEDDD6",
    "ladder": ["#1C1C1A", "#4A4944", "#6A6963", "#8F8E88", "#B0AFA9", "#C6C5BF"],
}


def _lf_rnd(i: int, k: int) -> float:
    """Port the gallery's deterministic JavaScript rnd(i, k) to Python."""
    value = ((i * 73856093) & 0xFFFFFFFF) ^ ((k * 19349663) & 0xFFFFFFFF)
    if value >= 0x80000000:
        value -= 0x100000000
    remainder = value - int(value / 1000) * 1000
    return abs(remainder) / 1000


def _svg_shell(spec: VisualSpec) -> list[str]:
    title_id = f"{spec.visual_id}-title"
    desc_id = f"{spec.visual_id}-desc"
    return [
        f'<svg class="lieflat-chart" data-template-source="{escape(spec.template_source or "")}" data-template-card="{escape(spec.template_card_title or "")}" xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 560 315" role="img" aria-labelledby="{title_id} {desc_id}">',
        f'<title id="{title_id}">{escape(spec.title)}</title>',
        f'<desc id="{desc_id}">{escape(spec.purpose)}。模板 {escape(spec.template_id or "")} {escape(spec.template_name or "")}。</desc>',
        '<style>.lf-mark{transition:opacity .16s ease;outline:none}.lf-mark:hover,.lf-mark:focus{opacity:1!important}.lf-rule{shape-rendering:crispEdges}.fade{animation:fade .9s ease both}@keyframes fade{from{opacity:0}}@media(prefers-reduced-motion:reduce){.fade{animation:none}}</style>',
        f'<rect width="560" height="315" fill="{_LF["paper"]}"/>',
        _svg_text(24, 22, spec.title, 16.5, weight=700, color=_LF["ink"]),
        _svg_text(24, 38, spec.purpose, 8.5, color=_LF["muted"]),
        _svg_text(536, 22, f"{spec.template_id} · {spec.template_name}", 7.5, weight=700, color=_LF["muted"], anchor="end"),
    ]


def _svg_tick_rows(spec: VisualSpec) -> str:
    rows = _numeric_items(spec)
    maximum = max((value for _, value in rows), default=1.0) or 1.0
    unit = _tick_unit(maximum)
    max_ticks = max(1, math.ceil(maximum / unit))
    x0, x1 = 150, 475
    px = (x1 - x0) / max_ticks
    gap = min(44, 205 / max(len(rows) - 1, 1))
    y0 = 155 - gap * (len(rows) - 1) / 2
    parts = _svg_shell(spec)
    parts.append(_svg_text(150, 54, f"一根刻线 = {unit:g} 个单位 · 每第五根附点标 · 行尾保留精确值", 7, weight=600, color=_LF["muted"]))
    for row_index, (item, value) in enumerate(rows):
        y = y0 + row_index * gap
        ticks = 0 if value <= 0 else max(1, math.ceil(value / unit))
        tooltip = escape(f"{item.label}: {_display_value(item)}")
        parts.append(f'<g class="lf-mark" tabindex="0" data-label="{escape(item.label)}" data-value="{escape(_display_value(item))}"><title>{tooltip}</title>')
        parts.append(_svg_text(138, y + 3, item.label, 9, weight=700, color=_LF["ladder"][2], anchor="end"))
        parts.append(f'<line class="lf-rule fade" x1="{x0}" y1="{y+9}" x2="{x1}" y2="{y+9}" stroke="{_LF["grid"]}" stroke-width=".8"/>')
        for tick in range(ticks):
            x = x0 + tick * px + px / 2
            height = 9 + _lf_rnd(tick + 1, row_index + 2) * 6
            opacity = .55 + _lf_rnd(tick + 3, row_index + 5) * .45
            parts.append(f'<line class="fade" x1="{x:.2f}" y1="{y+9}" x2="{x:.2f}" y2="{y+9-height:.2f}" stroke="{_LF["ink"]}" stroke-width=".9" opacity="{opacity:.3f}"/>')
            if tick % 5 == 4:
                parts.append(f'<circle class="fade" cx="{x:.2f}" cy="{y+13}" r=".8" fill="{_LF["faint"]}"/>')
        parts.append(_svg_text(min(520, x0 + ticks * px + 10), y + 4, _display_value(item), 11, weight=800, color=_LF["ink"]))
        parts.append('</g>')
    parts.append(_svg_text(280, 304, "TICK ROWS · MONO-BASIC · SOURCE: BASICS-GALLERY.HTML", 7, weight=600, color=_LF["faint"], anchor="middle"))
    parts.append('</svg>')
    return "\n".join(parts)


def _svg_tick_donut(spec: VisualSpec) -> str:
    rows = _numeric_items(spec, limit=6)
    values = [value for _, value in rows]
    total = sum(values)
    allocated = _hundred_allocation(values)
    colors = _LF["ladder"]
    parts = _svg_shell(spec)
    cx, cy, radius = 280, 164, 72
    start = 0
    for segment, ((item, value), count) in enumerate(zip(rows, allocated)):
        shade = colors[segment % len(colors)]
        tooltip = escape(f"{item.label}: {_display_value(item)} ({(value / total * 100 if total else 0):.1f}%)")
        parts.append(f'<g class="lf-mark" tabindex="0" data-label="{escape(item.label)}" data-value="{escape(_display_value(item))}"><title>{tooltip}</title>')
        for tick in range(count):
            index = start + tick
            angle = math.radians(index * 3.6 - 90)
            length = 10 + _lf_rnd(index + 1, segment + 2) * 6
            x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            x2, y2 = cx + (radius + length) * math.cos(angle), cy + (radius + length) * math.sin(angle)
            parts.append(f'<line class="fade" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{shade}" stroke-width="1"/>')
            if index % 10 == 0:
                dx, dy = cx + (radius - 5) * math.cos(angle), cy + (radius - 5) * math.sin(angle)
                parts.append(f'<circle class="fade" cx="{dx:.2f}" cy="{dy:.2f}" r=".8" fill="{_LF["faint"]}"/>')
        parts.append('</g>')
        mid = (start + count / 2) * 3.6 - 90
        angle = math.radians(mid)
        gx, gy = cx + (radius + 20) * math.cos(angle), cy + (radius + 20) * math.sin(angle)
        lx, ly = cx + (radius + 38) * math.cos(angle), cy + (radius + 38) * math.sin(angle)
        anchor = "start" if math.cos(angle) > .3 else "end" if math.cos(angle) < -.3 else "middle"
        parts.append(f'<line class="fade" x1="{gx:.2f}" y1="{gy:.2f}" x2="{lx:.2f}" y2="{ly:.2f}" stroke="{_LF["faint"]}" stroke-width=".7" stroke-dasharray="1 3"/>')
        parts.append(_svg_text(lx, ly + 3, f"{item.label} · {value / total * 100:.1f}%", 8, weight=800, color=shade, anchor=anchor))
        start += count
    parts.append(_svg_text(cx, cy - 2, "100", 22, weight=800, color=_LF["ink"], anchor="middle"))
    parts.append(_svg_text(cx, cy + 14, "TICKS · ONE = 1%", 7, weight=600, color=_LF["muted"], anchor="middle"))
    parts.append(_svg_text(280, 304, "TICK DONUT · MONO-BASIC · SOURCE: BASICS-GALLERY.HTML", 7, weight=600, color=_LF["faint"], anchor="middle"))
    parts.append('</svg>')
    return "\n".join(parts)


def _svg_hourglass(spec: VisualSpec) -> str:
    rows = _numeric_items(spec, limit=6)
    maximum = max((value for _, value in rows), default=1.0) or 1.0
    unit = _tick_unit(maximum, target_ticks=60)
    cx, y0 = 255, 62
    gap = 205 / max(len(rows) - 1, 1)
    parts = _svg_shell(spec)
    parts.append(_svg_text(255, 52, f"每根刻线约表示 {unit:g} 个单位 · 发丝线表示阶段流失", 7, weight=600, color=_LF["muted"], anchor="middle"))
    for index, (item, value) in enumerate(rows):
        y = y0 + index * gap
        half = max(8, value / maximum * 190)
        ticks = max(1, round(value / unit)) if value > 0 else 0
        tooltip = escape(f"{item.label}: {_display_value(item)}")
        parts.append(f'<g class="lf-mark" tabindex="0"><title>{tooltip}</title>')
        for tick in range(ticks):
            x = cx - half + (tick + 0.5) / ticks * half * 2 + (_lf_rnd(tick + 1, index + 3) - .5) * 3
            opacity = .45 + _lf_rnd(tick + 2, index + 5) * .5
            parts.append(f'<line class="fade" x1="{x:.2f}" y1="{y-6:.2f}" x2="{x:.2f}" y2="{y+6:.2f}" stroke="{_LF["ink"]}" stroke-width=".8" opacity="{opacity:.3f}"/>')
        parts.append(f'<line class="fade" x1="{cx+half+6:.2f}" y1="{y:.2f}" x2="474" y2="{y:.2f}" stroke="{_LF["grid"]}" stroke-width=".8"/>')
        parts.append(_svg_text(480, y - 1, item.label, 7.5, weight=700, color=_LF["ladder"][1]))
        parts.append(_svg_text(480, y + 11, _display_value(item), 9.5, weight=800, color=_LF["ink"]))
        if index < len(rows) - 1:
            next_value = rows[index + 1][1]
            next_half = max(8, next_value / maximum * 190)
            threads = min(34, max(1, ticks))
            for thread in range(threads):
                xt = cx + (_lf_rnd(thread + 1, index * 7 + 1) - .5) * 2 * half * .94
                xb = cx + (_lf_rnd(thread + 3, index * 7 + 5) - .5) * 2 * next_half * .94
                parts.append(f'<path class="fade" d="M{xt:.2f} {y+8:.2f} C{xt:.2f} {y+gap*.53:.2f} {xb:.2f} {y+gap*.47:.2f} {xb:.2f} {y+gap-8:.2f}" fill="none" stroke="{_LF["ladder"][4]}" stroke-width=".5" opacity=".32"/>')
            pct = next_value / value * 100 if value else 0
            parts.append(_svg_text(26, y + gap / 2 + 3, f"{pct:.0f}%", 8.5, weight=800, color=_LF["muted"]))
            parts.append(_svg_text(26, y + gap / 2 + 13, "GET THROUGH", 6, weight=600, color=_LF["faint"]))
        parts.append('</g>')
    parts.append(_svg_text(280, 304, "HOURGLASS STREAM · MONO-EDITORIAL2 · SOURCE: LUPI-GALLERY.HTML", 7, weight=600, color=_LF["faint"], anchor="middle"))
    parts.append('</svg>')
    return "\n".join(parts)


def render_visual_svg(spec: VisualSpec) -> str:
    if spec.template_id == "F5" and spec.family == "horizontal_bar":
        return _svg_tick_rows(spec)
    if spec.template_id == "F4" and spec.family == "donut":
        return _svg_tick_donut(spec)
    if spec.template_id == "L13" and spec.family == "funnel":
        return _svg_hourglass(spec)
    raise ValueError(f"No Lieflat renderer is registered for {spec.family!r}/{spec.template_id!r}")


def _standalone_html(spec: VisualSpec) -> str:
    rows = "".join(
        f"<tr><th>{escape(item.label)}</th><td>{escape(_display_value(item))}</td><td>{escape(item.note or '')}</td></tr>"
        for item in spec.items
    )
    license_note = (
        f"Lieflat Charts template {escape(spec.template_id or '')} · {escape(spec.chart_license or '')} · "
        f"License: {_LIEFLAT_LICENSE_URL}"
    )
    style = (
        "*{box-sizing:border-box}body{margin:0;background:#eef2f5;color:" + PALETTE["black"] + ";font-family:Arial,'Microsoft YaHei',sans-serif}"
        "main{width:min(1180px,94vw);margin:28px auto;background:#fff;border:1px solid " + PALETTE["pale"] + ";padding:28px}"
        "header span{font-size:11px;letter-spacing:.12em;color:" + PALETTE["purple"] + ";font-weight:700}"
        "h1{color:" + PALETTE["navy"] + ";margin:.35rem 0}p{color:" + PALETTE["gray"] + ";line-height:1.65}"
        ".canvas{overflow:auto;border-top:1px solid " + PALETTE["pale"] + ";border-bottom:1px solid " + PALETTE["pale"] + "}"
        "svg{display:block;width:100%;height:auto;min-width:720px}button{border:1px solid " + PALETTE["navy"] + ";background:#fff;color:" + PALETTE["navy"] + ";padding:8px 12px;font-weight:700;cursor:pointer}"
        "table{border-collapse:collapse;width:100%;margin-top:20px;font-size:13px}th,td{border-bottom:1px solid " + PALETTE["pale"] + ";padding:8px;text-align:left}"
        "footer{margin-top:18px;color:" + PALETTE["gray"] + ";font-size:10px}@media print{body{background:#fff}main{border:0;width:100%;margin:0}button{display:none}}"
    )
    script = (
        "document.getElementById('download').addEventListener('click',()=>{"
        "const svg=document.querySelector('svg').outerHTML;const a=document.createElement('a');"
        "a.href=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));"
        f"a.download='{escape(spec.visual_id)}.svg';"
        "a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)});"
    )
    return (
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(spec.title)}</title><style>{style}</style></head><body><main><header>'
        f'<span>{escape(spec.template_id or "")} · {escape(spec.template_name or "")}</span><h1>{escape(spec.title)}</h1>'
        f'<p>{escape(spec.purpose)}</p><button id="download">下载可编辑 SVG</button></header><div class="canvas">{render_visual_svg(spec)}</div>'
        f'<table><tbody>{rows}</tbody></table><p>{escape(spec.source_note)}<br>{escape(spec.transformation)}</p>'
        f'<footer>{escape(license_note)}</footer></main><script>{script}</script></body></html>'
    )


def _browser_executable() -> Path:
    configured = os.environ.get("EER_CHROME_PATH", "").strip()
    candidates = [
        Path(configured) if configured else None,
        *(Path(found) if found else None for found in (
            shutil.which("chromium"),
            shutil.which("chromium-headless-shell"),
            shutil.which("chromium-browser"),
            shutil.which("google-chrome"),
            shutil.which("chrome"),
            shutil.which("msedge"),
        )),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("D:/Users/Wenyi Zhang/Downloads/chrome-win64/chrome-win64/chrome.exe"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-headless-shell"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise RuntimeError(
        "Lieflat Word rendering requires Chrome/Chromium so the exact HTML SVG can be rasterized. "
        "Install Chromium or set EER_CHROME_PATH; the legacy Pillow chart fallback is intentionally disabled."
    )


def _png(spec: VisualSpec, path: Path) -> None:
    """Rasterize the canonical Lieflat SVG for Word; never redraw chart geometry."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    svg = render_visual_svg(spec)
    wrapper = (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        'html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#fff}'
        'svg{display:block;width:1280px!important;height:720px!important}'
        f'</style></head><body>{svg}<style>svg .fade{{animation:none!important}}</style></body></html>'
    )
    with tempfile.TemporaryDirectory(prefix="eer-lieflat-") as temp:
        temp_dir = Path(temp)
        html_path = temp_dir / "chart.html"
        raw_png = temp_dir / "chart.png"
        profile = temp_dir / "chrome-profile"
        html_path.write_text(wrapper, encoding="utf-8")
        command = [
            str(_browser_executable()),
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            # Windows headless Chrome reserves roughly 100 px for window chrome;
            # 820 guarantees a 720 px page viewport. Linux simply captures 820
            # and is cropped to the canonical 1280x720 canvas below.
            "--window-size=1280,820",
            f"--user-data-dir={profile}",
            f"--screenshot={raw_png}",
            html_path.as_uri(),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode != 0 or not raw_png.is_file():
            detail = (completed.stderr or completed.stdout or "unknown browser failure").strip()[-800:]
            raise RuntimeError(f"Lieflat SVG rasterization failed: {detail}")
        with Image.open(raw_png) as image:
            if image.width < 1280 or image.height < 720:
                raise RuntimeError(f"Lieflat rasterization returned undersized image {image.size}; expected at least 1280x720")
            image.crop((0, 0, 1280, 720)).convert("RGB").save(
                path, format="PNG", dpi=(_png_dpi(), _png_dpi()), optimize=True
            )
