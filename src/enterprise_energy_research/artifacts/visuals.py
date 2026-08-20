from __future__ import annotations

import json
import math
import re
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
    source_image_ids: list[str] = Field(default_factory=list)
    source_note: str
    transformation: str
    units: str = "见图中标注"
    display_rounding: str = "整数计数；原始披露值保持其口径"
    artifact_targets: list[str] = Field(default_factory=lambda: ["word", "ppt"])


class VisualManifest(BaseModel):
    schema_version: str = "1.0"
    freeze_id: str
    theme: str = "sevc-kami-broker-v2"
    minimum_font_pt: int = 8
    png_dpi: int = 300
    visuals: list[VisualSpec]


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
            title="证据收集与核验漏斗", purpose="说明来源、主张、核验与缺口之间的关系",
            family="funnel", canonical_type="funnel",
            items=[_datum("来源", len(bundle.sources), unit="个"), _datum("冻结主张", len(bound_claims), unit="条"), _datum("已核验", len(verified), unit="条"), _datum("数据缺口", len(bundle.gaps), unit="项")],
            source_claim_ids=[claim.claim_id for claim in bound_claims], source_note=_source_note(bundle, [claim.claim_id for claim in bound_claims]),
            transformation="按来源、主张状态和缺口记录聚合计数。",
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
            title="生产基地与工艺足迹", purpose="把基地、地址和工艺放入同一核验视图",
            family="timeline", canonical_type="footprint_timeline", items=factory_items,
            source_claim_ids=[claim.claim_id for claim in verified if claim.field_name in {"factory", "address", "process"}],
            source_note=_source_note(bundle), transformation="按冻结生产基地记录展示工艺项数和已披露地址。",
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
            family="horizontal_bar", canonical_type="source_mix",
            items=[_datum(level, count, unit="个来源") for level, count in source_levels.items()] or [_datum("来源", 0, unit="个")],
            source_claim_ids=[], source_note=_source_note(bundle), transformation="按 source_level 聚合来源数。",
        ),
        VisualSpec(
            visual_id="FIG-A2-IMAGE-MIX", chapter_key="appendix_images",
            title="已核验图片类型构成", purpose="披露可用于正式报告的图片证据",
            family="horizontal_bar", canonical_type="image_mix",
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
    return VisualManifest(freeze_id=bundle.freeze.freeze_id, visuals=specs)


def write_visual_manifest(manifest: VisualManifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_visual_bundle(spec: VisualSpec, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / f"{spec.visual_id}.svg"
    png_path = output_dir / f"{spec.visual_id}.png"
    svg_path.write_text(_svg(spec), encoding="utf-8")
    _png(spec, png_path)
    return png_path, svg_path


def _short(value: Any, maximum: int = 28) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "—")).strip()
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _display_value(item: VisualDatum) -> str:
    value = _short(item.value, 16)
    return f"{value}{item.unit or ''}"


def _svg_text(x: int, y: int, text: str, size: int, *, weight: int = 400, color: str = PALETTE["black"], anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" font-family="Arial, Microsoft YaHei, sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(_short(text, 42))}</text>'


def _svg(spec: VisualSpec) -> str:
    width, height = 1280, 720
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{PALETTE["white"]}"/>',
        f'<rect x="0" y="0" width="10" height="{height}" fill="{PALETTE["purple"]}"/>',
        _svg_text(48, 55, spec.purpose, 18, weight=600, color=PALETTE["navy"]),
        _svg_text(1232, 55, spec.visual_id, 13, color=PALETTE["gray"], anchor="end"),
        f'<line x1="48" y1="76" x2="1232" y2="76" stroke="{PALETTE["pale"]}" stroke-width="2"/>',
    ]
    items = spec.items[:8]
    if spec.family == "kpi_tiles":
        card_w = 270
        for index, item in enumerate(items[:4]):
            x = 48 + index * 294
            parts += [f'<rect x="{x}" y="145" width="{card_w}" height="330" rx="8" fill="{PALETTE["canvas"]}" stroke="{PALETTE["pale"]}"/>', _svg_text(x + 22, 205, item.label, 20, weight=600, color=PALETTE["navy"]), _svg_text(x + 22, 325, _display_value(item), 42, weight=700, color=PALETTE["purple"]), _svg_text(x + 22, 410, item.note or "冻结证据计数", 15, color=PALETTE["gray"])]
    elif spec.family in {"horizontal_bar", "donut"}:
        numeric = [float(item.value) if isinstance(item.value, (int, float)) else 0.0 for item in items]
        maximum = max(numeric or [1]) or 1
        for index, (item, value) in enumerate(zip(items, numeric)):
            y = 135 + index * 70
            bar_w = max(8, int(650 * value / maximum))
            parts += [_svg_text(54, y + 25, item.label, 17, weight=600, color=PALETTE["navy"]), f'<rect x="300" y="{y}" width="720" height="34" rx="4" fill="{PALETTE["canvas"]}"/>', f'<rect x="300" y="{y}" width="{bar_w}" height="34" rx="4" fill="{PALETTE["cobalt"]}"/>', _svg_text(1040, y + 25, _display_value(item), 17, weight=700, color=PALETTE["purple"])]
    elif spec.family in {"process", "timeline", "funnel", "decision_tree"}:
        count = max(1, min(len(items), 6))
        card_w = int(1080 / count) - 18
        for index, item in enumerate(items[:count]):
            x = 54 + index * (card_w + 18)
            y = 205 if index % 2 == 0 or spec.family != "decision_tree" else 330
            if index:
                parts.append(f'<path d="M {x-18} {y+72} L {x-5} {y+72}" stroke="{PALETTE["purple"]}" stroke-width="3" marker-end="url(#arrow)"/>')
            parts += [f'<rect x="{x}" y="{y}" width="{card_w}" height="150" rx="8" fill="{PALETTE["canvas"]}" stroke="{PALETTE["pale"]}"/>', _svg_text(x + 16, y + 42, item.label, 17, weight=700, color=PALETTE["navy"]), _svg_text(x + 16, y + 85, _display_value(item), 22, weight=700, color=PALETTE["purple"]), _svg_text(x + 16, y + 120, item.note or "", 13, color=PALETTE["gray"])]
    elif spec.family == "matrix":
        # 行式矩阵：每行一个方案项（方向/状态/下一步），表头 navy
        rows = items[:8]
        row_h, gap = 56, 8
        header_y = 130
        parts.append(_svg_text(54, header_y, "合作方向", 15, weight=700, color=PALETTE["navy"]))
        parts.append(_svg_text(440, header_y, "状态", 15, weight=700, color=PALETTE["navy"]))
        parts.append(_svg_text(880, header_y, "下一步", 15, weight=700, color=PALETTE["navy"]))
        parts.append(f'<line x1="54" y1="{header_y + 10}" x2="1226" y2="{header_y + 10}" stroke="{PALETTE["pale"]}" stroke-width="2"/>')
        for index, item in enumerate(rows):
            y = 150 + index * (row_h + gap)
            parts.append(f'<rect x="54" y="{y}" width="1172" height="{row_h}" rx="6" fill="{PALETTE["canvas"] if index % 2 == 0 else PALETTE["white"]}" stroke="{PALETTE["pale"]}"/>')
            parts.append(f'<rect x="54" y="{y}" width="6" height="{row_h}" fill="{PALETTE["purple"]}"/>')
            parts.append(_svg_text(78, y + 34, item.label, 15, weight=700, color=PALETTE["navy"]))
            parts.append(_svg_text(440, y + 34, _display_value(item), 15, weight=700, color=PALETTE["purple"]))
            parts.append(_svg_text(880, y + 34, _short(item.note or "", 44), 13, color=PALETTE["gray"]))
    elif spec.family == "network":
        parts += [f'<circle cx="640" cy="345" r="95" fill="{PALETTE["navy"]}"/>', _svg_text(640, 340, "企业边界", 21, weight=700, color=PALETTE["white"], anchor="middle"), _svg_text(640, 375, f"{len(items)} 个实体", 17, color=PALETTE["white"], anchor="middle")]
        radius = 245
        for index, item in enumerate(items[:7]):
            angle = 2 * math.pi * index / max(len(items[:7]), 1) - math.pi / 2
            x, y = int(640 + radius * math.cos(angle)), int(345 + radius * math.sin(angle))
            parts += [f'<line x1="640" y1="345" x2="{x}" y2="{y}" stroke="{PALETTE["pale"]}" stroke-width="3"/>', f'<rect x="{x-100}" y="{y-42}" width="200" height="84" rx="8" fill="{PALETTE["canvas"]}" stroke="{PALETTE["cobalt"]}"/>', _svg_text(x, y - 6, item.label, 15, weight=700, color=PALETTE["navy"], anchor="middle"), _svg_text(x, y + 24, _display_value(item), 13, color=PALETTE["gray"], anchor="middle")]
    else:
        cols = 2
        card_w, card_h = 550, 120
        for index, item in enumerate(items[:8]):
            x = 54 + (index % cols) * 590
            y = 120 + (index // cols) * 138
            parts += [f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="8" fill="{PALETTE["canvas"]}" stroke="{PALETTE["pale"]}"/>', f'<rect x="{x}" y="{y}" width="8" height="{card_h}" fill="{PALETTE["purple"]}"/>', _svg_text(x + 24, y + 34, item.label, 17, weight=700, color=PALETTE["navy"]), _svg_text(x + 24, y + 69, _display_value(item), 18, weight=700, color=PALETTE["purple"]), _svg_text(x + 24, y + 99, item.note or item.status or "", 13, color=PALETTE["gray"])]
    parts += [_svg_text(48, 690, spec.source_note.replace("数据来源：", ""), 12, color=PALETTE["gray"]), "</svg>"]
    return "\n".join(parts)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        # Windows（宿主机开发）
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        # Linux 容器（已随镜像安装 fonts-wqy-microhei / fonts-noto-cjk）
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
    return ImageFont.load_default()


def _png(spec: VisualSpec, path: Path) -> None:
    from PIL import Image, ImageDraw

    scale = 1.40625
    width, height = 1800, 1012
    image = Image.new("RGB", (width, height), PALETTE["white"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 14, height), fill=PALETTE["purple"])
    draw.text((68, 44), _short(spec.purpose, 58), font=_font(26, True), fill=PALETTE["navy"])
    draw.text((1600, 48), spec.visual_id, font=_font(17), fill=PALETTE["gray"])
    draw.line((68, 106, 1732, 106), fill=PALETTE["pale"], width=3)
    items = spec.items[:8]
    if spec.family == "kpi_tiles":
        for index, item in enumerate(items[:4]):
            x = 68 + index * 414
            draw.rounded_rectangle((x, 200, x + 380, 670), radius=10, fill=PALETTE["canvas"], outline=PALETTE["pale"], width=2)
            draw.text((x + 28, 250), _short(item.label, 18), font=_font(27, True), fill=PALETTE["navy"])
            draw.text((x + 28, 390), _display_value(item), font=_font(54, True), fill=PALETTE["purple"])
            draw.text((x + 28, 535), _short(item.note or "冻结证据计数", 22), font=_font(20), fill=PALETTE["gray"])
    elif spec.family in {"horizontal_bar", "donut"}:
        numeric = [float(item.value) if isinstance(item.value, (int, float)) else 0.0 for item in items]
        maximum = max(numeric or [1]) or 1
        for index, (item, value) in enumerate(zip(items, numeric)):
            y = 178 + index * 90
            draw.text((74, y), _short(item.label, 18), font=_font(23, True), fill=PALETTE["navy"])
            draw.rounded_rectangle((420, y, 1425, y + 44), radius=6, fill=PALETTE["canvas"])
            draw.rounded_rectangle((420, y, 420 + max(10, int(910 * value / maximum)), y + 44), radius=6, fill=PALETTE["cobalt"])
            draw.text((1460, y), _display_value(item), font=_font(23, True), fill=PALETTE["purple"])
    elif spec.family == "network":
        draw.ellipse((770, 365, 1030, 625), fill=PALETTE["navy"])
        draw.text((825, 445), "企业边界", font=_font(31, True), fill=PALETTE["white"])
        draw.text((840, 505), f"{len(items)} 个实体", font=_font(23), fill=PALETTE["white"])
        radius = 340
        for index, item in enumerate(items[:7]):
            angle = 2 * math.pi * index / max(len(items[:7]), 1) - math.pi / 2
            cx, cy = int(900 + radius * math.cos(angle)), int(495 + radius * math.sin(angle))
            draw.line((900, 495, cx, cy), fill=PALETTE["pale"], width=4)
            draw.rounded_rectangle((cx - 135, cy - 58, cx + 135, cy + 58), radius=10, fill=PALETTE["canvas"], outline=PALETTE["cobalt"], width=2)
            draw.text((cx - 115, cy - 33), _short(item.label, 14), font=_font(20, True), fill=PALETTE["navy"])
            draw.text((cx - 115, cy + 5), _short(_display_value(item), 16), font=_font(18), fill=PALETTE["gray"])
    elif spec.family in {"process", "timeline", "funnel", "decision_tree"}:
        count = max(1, min(len(items), 6))
        card_w = int(1530 / count) - 22
        for index, item in enumerate(items[:count]):
            x = 74 + index * (card_w + 22)
            y = 300 if index % 2 == 0 or spec.family != "decision_tree" else 470
            if index:
                draw.line((x - 20, y + 95, x - 4, y + 95), fill=PALETTE["purple"], width=4)
            draw.rounded_rectangle((x, y, x + card_w, y + 210), radius=10, fill=PALETTE["canvas"], outline=PALETTE["pale"], width=2)
            draw.text((x + 18, y + 28), _short(item.label, 13), font=_font(21, True), fill=PALETTE["navy"])
            draw.text((x + 18, y + 90), _short(_display_value(item), 13), font=_font(27, True), fill=PALETTE["purple"])
            draw.text((x + 18, y + 150), _short(item.note or "", 14), font=_font(17), fill=PALETTE["gray"])
    elif spec.family == "matrix":
        # 行式矩阵：表头 + 斑马行（方向/状态/下一步）
        rows = items[:8]
        row_h, gap = 74, 12
        header_y = 120
        draw.text((90, header_y), "合作方向", font=_font(17, True), fill=PALETTE["navy"])
        draw.text((620, header_y), "状态", font=_font(17, True), fill=PALETTE["navy"])
        draw.text((1240, header_y), "下一步", font=_font(17, True), fill=PALETTE["navy"])
        draw.line((90, header_y + 14, 1730, header_y + 14), fill=PALETTE["pale"], width=3)
        for index, item in enumerate(rows):
            y = 150 + index * (row_h + gap)
            fill = PALETTE["canvas"] if index % 2 == 0 else PALETTE["white"]
            draw.rounded_rectangle((90, y, 1710, y + row_h), radius=8, fill=fill, outline=PALETTE["pale"], width=2)
            draw.rectangle((90, y, 100, y + row_h), fill=PALETTE["purple"])
            draw.text((122, y + 24), _short(item.label, 16), font=_font(18, True), fill=PALETTE["navy"])
            draw.text((620, y + 24), _display_value(item), font=_font(18, True), fill=PALETTE["purple"])
            draw.text((1240, y + 24), _short(item.note or "", 48), font=_font(14), fill=PALETTE["gray"])
    else:
        for index, item in enumerate(items[:8]):
            x = 74 + (index % 2) * 830
            y = 165 + (index // 2) * 185
            draw.rounded_rectangle((x, y, x + 760, y + 150), radius=10, fill=PALETTE["canvas"], outline=PALETTE["pale"], width=2)
            draw.rectangle((x, y, x + 10, y + 150), fill=PALETTE["purple"])
            draw.text((x + 35, y + 22), _short(item.label, 24), font=_font(22, True), fill=PALETTE["navy"])
            draw.text((x + 35, y + 65), _short(_display_value(item), 24), font=_font(24, True), fill=PALETTE["purple"])
            draw.text((x + 35, y + 108), _short(item.note or item.status or "", 38), font=_font(17), fill=PALETTE["gray"])
    draw.text((68, 965), _short(spec.source_note.replace("数据来源：", ""), 100), font=_font(15), fill=PALETTE["gray"])
    image.save(path, format="PNG", dpi=(_png_dpi(), _png_dpi()), optimize=True)
