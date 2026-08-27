from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from _common import now_iso, read_json, write_json
from presentation_production import PIPELINE_ID, RENDERER_ID, resolve_path, sha256_file, stored_path


NAVY = "0B1F4B"
ROYAL = "0033A0"
COBALT = "2E5BFF"
INK = "111827"
GRAY = "4A4A4A"
COOL = "8C8C8C"
PALE = "F7F8FA"
BORDER = "D0D3D9"
WHITE = "FFFFFF"
RED = "B00020"
GREEN = "147D64"
SLIDE_W = 13.333
SLIDE_H = 7.5


def rgb(value: str) -> RGBColor:
    value = value.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def add_rect(slide, x, y, w, h, *, fill=WHITE, line=None, radius=False):
    shape_type = MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE if radius else MSO_AUTO_SHAPE_TYPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(line or fill)
    shape.line.width = Pt(0.75)
    if radius:
        try:
            shape.adjustments[0] = 0.08
        except (IndexError, ValueError):
            pass
    return shape


def add_text(
    slide,
    x,
    y,
    w,
    h,
    text,
    *,
    size=14,
    color=INK,
    bold=False,
    font="Microsoft YaHei",
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin=0.02,
    line_spacing=1.08,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    paragraphs = str(text).split("\n")
    for index, value in enumerate(paragraphs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = line_spacing
        paragraph.space_after = Pt(2)
        run = paragraph.add_run()
        run.text = value
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = rgb(color)
    return box


def add_bullets(slide, x, y, w, h, items, *, size=12, color=INK, accent=ROYAL):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.03)
    frame.margin_top = frame.margin_bottom = Inches(0.02)
    for index, raw in enumerate(items):
        item = raw if isinstance(raw, dict) else {"title": "", "text": str(raw)}
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.level = 0
        paragraph.space_after = Pt(7)
        paragraph.line_spacing = 1.08
        marker = paragraph.add_run()
        marker.text = "■  "
        marker.font.name = "Arial"
        marker.font.size = Pt(size - 2)
        marker.font.color.rgb = rgb(accent)
        title = str(item.get("title") or "").strip()
        if title:
            lead = paragraph.add_run()
            lead.text = title + "："
            lead.font.name = "Microsoft YaHei"
            lead.font.size = Pt(size)
            lead.font.bold = True
            lead.font.color.rgb = rgb(color)
        body = paragraph.add_run()
        body.text = str(item.get("text") or "")
        body.font.name = "Microsoft YaHei"
        body.font.size = Pt(size)
        body.font.color.rgb = rgb(color)
    return box


def add_title(slide, title: str, section: str, slide_no: int) -> None:
    add_text(slide, 0.52, 0.19, 1.45, 0.24, section.upper(), size=8.5, color=ROYAL, bold=True, font="Arial")
    add_text(slide, 0.52, 0.50, 11.75, 0.58, title, size=23, color=INK, bold=True, font="Microsoft YaHei")
    add_rect(slide, 0.52, 1.10, 12.25, 0.015, fill=BORDER)
    add_text(slide, 12.35, 0.20, 0.42, 0.22, f"{slide_no:02d}", size=8, color=COOL, align=PP_ALIGN.RIGHT, font="Arial")


def add_footer(slide, source: str, update_date: str, bias_note: str) -> None:
    text = f"来源：{source}  |  更新：{update_date}  |  口径/限制：{bias_note}"
    add_rect(slide, 0.52, 7.03, 12.25, 0.012, fill=BORDER)
    add_text(slide, 0.52, 7.09, 12.25, 0.20, text, size=7.2, color=COOL, font="Arial")


def add_kpi(slide, x, y, w, h, value: str, label: str, *, accent=ROYAL):
    add_rect(slide, x, y, w, h, fill=PALE, line=BORDER)
    add_rect(slide, x, y, 0.05, h, fill=accent)
    add_text(slide, x + 0.22, y + 0.13, w - 0.35, 0.38, value, size=22, color=accent, bold=True, font="Georgia")
    add_text(slide, x + 0.22, y + 0.61, w - 0.35, h - 0.68, label, size=9.5, color=GRAY)


def add_picture_crop(slide, path: Path, x, y, w, h):
    picture = slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))
    return picture


def request_record(acquisition: dict, request_id: str) -> dict | None:
    return next((item for item in acquisition.get("requests", []) if item.get("request_id") == request_id), None)


def add_cover(slide, deck: dict, acquisition: dict, project_dir: Path) -> dict:
    decision = acquisition.get("cover_decision") or {}
    path_taken = decision.get("path_taken") or "B_light_consulting"
    title = str(deck.get("title") or "海外能源市场研究")
    subtitle = str(deck.get("subtitle") or "市场、竞争与进入策略")
    meta = str(deck.get("meta") or "内部决策材料")
    date = str(deck.get("update_date") or now_iso()[:10])
    used_images: list[dict] = []
    if path_taken == "A_ai_image":
        add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY)
        add_rect(slide, 0, 0, SLIDE_W, 0.06, fill=COBALT)
        request = request_record(acquisition, str(decision.get("ai_image_request_id") or ""))
        if not request or request.get("status") != "generated":
            raise ValueError("Path A requires a generated cover request")
        image_path = resolve_path(str(request["path"]), project_dir)
        add_picture_crop(slide, image_path, 7.15, 0.06, 6.18, 7.10)
        overlay = add_rect(slide, 6.76, 0.06, 1.35, 7.10, fill=NAVY)
        overlay.fill.transparency = 25
        used_images.append({"request_id": request["request_id"], "path": stored_path(image_path, project_dir), "sha256": sha256_file(image_path)})
        add_text(slide, 0.72, 0.72, 6.15, 0.30, str(deck.get("eyebrow") or "ENERGY MARKET & PRODUCT INTELLIGENCE"), size=9.5, color="A8B5CE", bold=True, font="Arial")
        add_text(slide, 0.72, 1.52, 6.18, 1.55, title, size=34, color=WHITE, bold=True, font="Georgia")
        add_rect(slide, 0.72, 3.30, 1.02, 0.035, fill=COBALT)
        add_text(slide, 0.72, 3.64, 5.85, 0.74, subtitle, size=17, color="D7DEEA", bold=True)
        add_text(slide, 0.72, 6.54, 5.90, 0.33, meta, size=9, color="A8B5CE")
        add_text(slide, 0.72, 6.90, 5.90, 0.28, f"更新日期：{date}", size=8, color="71809E")
    else:
        add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE)
        add_rect(slide, 0, 0, SLIDE_W, 0.045, fill=ROYAL)
        add_rect(slide, 0, 7.455, SLIDE_W, 0.045, fill=ROYAL)
        add_text(slide, 0.82, 0.78, 10.0, 0.28, str(deck.get("eyebrow") or "ENERGY MARKET & PRODUCT INTELLIGENCE"), size=9.5, color=ROYAL, bold=True, font="Arial")
        add_text(slide, 0.82, 1.66, 10.7, 1.45, title, size=32, color=INK, bold=True, font="Georgia")
        add_rect(slide, 0.82, 3.35, 1.05, 0.035, fill=ROYAL)
        add_text(slide, 0.82, 3.70, 9.8, 0.62, subtitle, size=16, color=GRAY, bold=True)
        add_rect(slide, 0.82, 5.58, 11.65, 0.015, fill=BORDER)
        columns = [("报告日期", date), ("编制口径", meta), ("密级", str(deck.get("confidentiality") or "内部使用"))]
        for idx, (label, value) in enumerate(columns):
            x = 0.82 + idx * 3.88
            add_text(slide, x, 5.82, 3.45, 0.22, label, size=8, color=COOL, bold=True)
            add_text(slide, x, 6.14, 3.45, 0.36, value, size=11, color=INK, bold=True)
        add_text(slide, 0.82, 6.94, 11.65, 0.20, "数据以来源台账及最终证据审计为准；未核实信息不得作为决策事实。", size=7.5, color=COOL)
    return {"visual_kind": "ai_raster" if path_taken == "A_ai_image" else "typographic_vector", "used_images": used_images}


def add_summary(slide, spec):
    messages = spec.get("items") or []
    for index, item in enumerate(messages[:3]):
        y = 1.35 + index * 1.47
        add_text(slide, 0.62, y, 0.46, 0.38, f"{index + 1:02d}", size=15, color=ROYAL, bold=True, font="Georgia")
        add_text(slide, 1.16, y, 5.55, 0.36, str(item.get("title") or "关键结论"), size=13.5, color=INK, bold=True)
        add_text(slide, 1.16, y + 0.43, 5.55, 0.60, str(item.get("text") or ""), size=10.2, color=GRAY)
        add_rect(slide, 0.62, y + 1.18, 6.08, 0.012, fill=BORDER)
    kpis = spec.get("kpis") or []
    for index, item in enumerate(kpis[:4]):
        row, col = divmod(index, 2)
        add_kpi(slide, 7.08 + col * 2.82, 1.40 + row * 1.75, 2.56, 1.48, str(item.get("value") or "—"), str(item.get("label") or "关键指标"), accent=COBALT if index == 1 else ROYAL)
    add_rect(slide, 7.08, 5.10, 5.38, 1.25, fill=NAVY)
    add_text(slide, 7.38, 5.34, 4.78, 0.70, str(spec.get("takeaway") or "关键决策应同时满足市场、政策与经济性三重门槛。"), size=13, color=WHITE, bold=True)


def add_figure_slide(slide, spec, project_dir: Path, acquisition: dict) -> list[dict]:
    used_images: list[dict] = []
    request_id = str(spec.get("image_request_id") or "")
    request = request_record(acquisition, request_id) if request_id else None
    figure_value = str(spec.get("figure_path") or "").strip()
    figure_path = resolve_path(figure_value, project_dir) if figure_value else None
    picture_path = None
    if request and request.get("status") == "generated":
        picture_path = resolve_path(str(request["path"]), project_dir)
    elif figure_path and figure_path.exists():
        picture_path = figure_path
    if picture_path is not None:
        add_rect(slide, 0.58, 1.34, 7.65, 5.28, fill=WHITE, line=BORDER)
        add_picture_crop(slide, picture_path, 0.72, 1.50, 7.36, 4.84)
        used_images.append({"path": stored_path(picture_path, project_dir), "sha256": sha256_file(picture_path), "request_id": request_id})
    else:
        add_rect(slide, 0.58, 1.34, 7.65, 5.28, fill=PALE, line=BORDER)
        add_text(slide, 0.92, 1.68, 6.95, 0.35, str(spec.get("diagram_title") or "结构化场景示意"), size=14, color=ROYAL, bold=True)
        stages = spec.get("diagram_steps") or ["需求/场景", "能源设备", "控制平台", "用户价值"]
        for index, label in enumerate(stages[:4]):
            x = 0.92 + index * 1.70
            add_rect(slide, x, 2.55, 1.35, 1.12, fill=WHITE, line=ROYAL, radius=True)
            add_text(slide, x + 0.12, 2.87, 1.11, 0.48, str(label), size=10, color=INK, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
            if index < min(len(stages), 4) - 1:
                connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x + 1.37), Inches(3.10), Inches(x + 1.66), Inches(3.10))
                connector.line.color.rgb = rgb(COBALT)
                connector.line.width = Pt(1.5)
        add_rect(slide, 0.92, 4.30, 6.65, 1.40, fill=NAVY)
        add_text(slide, 1.18, 4.65, 6.13, 0.66, str(spec.get("takeaway") or "无 AI 插图时使用可编辑的原生矢量框架，不替代数据证据。"), size=13, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    add_text(slide, 8.62, 1.42, 3.83, 0.28, "决策含义", size=10, color=ROYAL, bold=True)
    add_bullets(slide, 8.62, 1.85, 3.83, 3.55, spec.get("items") or [], size=11.2)
    add_rect(slide, 8.62, 5.55, 3.83, 0.90, fill=PALE, line=BORDER)
    side_note = (
        str(spec.get("takeaway") or "")
        if picture_path is not None
        else "降级说明：EWO不可用时采用可编辑矢量示意；该示意不构成数据证据。"
    )
    add_text(slide, 8.84, 5.75, 3.39, 0.48, side_note, size=10.0, color=INK, bold=True)
    return used_images


def add_timeline(slide, spec):
    items = spec.get("items") or []
    count = max(1, min(len(items), 5))
    x0, x1, y = 1.05, 12.25, 3.06
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y), Inches(x1), Inches(y))
    line.line.color.rgb = rgb(BORDER)
    line.line.width = Pt(2)
    for index, item in enumerate(items[:5]):
        x = x0 + (x1 - x0) * index / max(count - 1, 1)
        add_rect(slide, x - 0.15, y - 0.15, 0.30, 0.30, fill=ROYAL, radius=True)
        add_text(slide, x - 0.62, 1.55, 1.24, 0.30, str(item.get("period") or f"阶段{index + 1}"), size=9, color=ROYAL, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x - 0.92, 2.02, 1.84, 0.66, str(item.get("title") or "关键节点"), size=11.5, color=INK, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x - 0.96, 3.48, 1.92, 1.32, str(item.get("text") or ""), size=9.2, color=GRAY, align=PP_ALIGN.CENTER)
    add_rect(slide, 0.78, 5.42, 11.80, 0.92, fill=NAVY)
    add_text(slide, 1.05, 5.66, 11.26, 0.44, str(spec.get("takeaway") or "时间节点以监管开放、标准落地和单位经济性为共同触发器。"), size=12.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER)


def add_segments(slide, spec):
    items = spec.get("items") or []
    widths = [3.78, 3.78, 3.78]
    for index, item in enumerate(items[:3]):
        x = 0.62 + index * 4.11
        add_rect(slide, x, 1.46, widths[index], 4.83, fill=WHITE, line=BORDER)
        add_rect(slide, x, 1.46, widths[index], 0.08, fill=[ROYAL, COBALT, GREEN][index])
        add_text(slide, x + 0.25, 1.82, 3.28, 0.36, str(item.get("title") or "客群"), size=14, color=INK, bold=True)
        add_text(slide, x + 0.25, 2.35, 3.28, 1.22, str(item.get("text") or ""), size=10.2, color=GRAY)
        add_text(slide, x + 0.25, 3.86, 3.28, 0.28, "关键门槛", size=9, color=COOL, bold=True)
        add_text(slide, x + 0.25, 4.22, 3.28, 0.88, str(item.get("barrier") or "待验证"), size=10.5, color=INK, bold=True)
        add_rect(slide, x + 0.25, 5.54, 3.28, 0.46, fill=PALE, line=PALE)
        add_text(slide, x + 0.38, 5.65, 3.02, 0.24, str(item.get("metric") or "证据待补"), size=9, color=ROYAL, bold=True, align=PP_ALIGN.CENTER)


def add_matrix(slide, spec):
    add_rect(slide, 1.05, 1.48, 8.24, 4.98, fill=WHITE, line=BORDER)
    cx, cy = 5.17, 3.97
    v = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(cx), Inches(1.74), Inches(cx), Inches(6.20))
    h = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1.33), Inches(cy), Inches(9.02), Inches(cy))
    for connector in (v, h):
        connector.line.color.rgb = rgb(BORDER)
        connector.line.width = Pt(1.2)
    labels = spec.get("quadrants") or ["高价值/低门槛", "高价值/高门槛", "低价值/低门槛", "低价值/高门槛"]
    positions = [(1.48, 1.92), (5.45, 1.92), (1.48, 4.25), (5.45, 4.25)]
    for label, (x, y) in zip(labels, positions):
        add_text(slide, x, y, 3.35, 0.30, str(label), size=9, color=COOL, bold=True)
    for index, point in enumerate(spec.get("points") or []):
        px = 1.55 + float(point.get("x", 0.5)) * 7.15
        py = 5.88 - float(point.get("y", 0.5)) * 3.60
        color = [ROYAL, COBALT, GREEN, RED][index % 4]
        add_rect(slide, px - 0.10, py - 0.10, 0.20, 0.20, fill=color, radius=True)
        add_text(slide, px + 0.12, py - 0.14, 1.10, 0.28, str(point.get("label") or f"对象{index + 1}"), size=7.8, color=INK)
    add_text(slide, 9.72, 1.55, 2.75, 0.28, "判断与动作", size=10, color=ROYAL, bold=True)
    add_bullets(slide, 9.72, 1.98, 2.75, 3.58, spec.get("items") or [], size=10.4)
    add_rect(slide, 9.72, 5.68, 2.75, 0.67, fill=NAVY)
    add_text(slide, 9.90, 5.84, 2.39, 0.36, str(spec.get("takeaway") or "优先级以证据强度校准"), size=9.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER)


def add_comparison(slide, spec):
    items = spec.get("items") or []
    count = max(1, min(4, len(items)))
    gap = 0.18
    total_w = 12.02
    col_w = (total_w - gap * (count - 1)) / count
    for index, item in enumerate(items[:4]):
        x = 0.64 + index * (col_w + gap)
        add_rect(slide, x, 1.42, col_w, 4.98, fill=WHITE, line=BORDER)
        add_rect(slide, x, 1.42, col_w, 0.62, fill=ROYAL if index == 0 else PALE, line=ROYAL if index == 0 else BORDER)
        add_text(slide, x + 0.16, 1.60, col_w - 0.32, 0.28, str(item.get("title") or f"方案{index + 1}"), size=11, color=WHITE if index == 0 else INK, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x + 0.22, 2.35, col_w - 0.44, 0.68, str(item.get("headline") or ""), size=13, color=ROYAL, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x + 0.22, 3.27, col_w - 0.44, 1.74, str(item.get("text") or ""), size=9.6, color=GRAY)
        add_rect(slide, x + 0.22, 5.42, col_w - 0.44, 0.55, fill=PALE, line=PALE)
        add_text(slide, x + 0.30, 5.56, col_w - 0.60, 0.28, str(item.get("metric") or ""), size=8.5, color=INK, bold=True, align=PP_ALIGN.CENTER)


def add_swot(slide, spec):
    items = spec.get("items") or []
    colors = [ROYAL, COBALT, GREEN, RED]
    labels = ["优势 Strengths", "劣势 Weaknesses", "机会 Opportunities", "威胁 Threats"]
    for index in range(4):
        row, col = divmod(index, 2)
        x, y = 0.64 + col * 6.11, 1.42 + row * 2.50
        add_rect(slide, x, y, 5.82, 2.24, fill=WHITE, line=BORDER)
        add_rect(slide, x, y, 0.08, 2.24, fill=colors[index])
        item = items[index] if index < len(items) else {}
        add_text(slide, x + 0.28, y + 0.22, 5.24, 0.32, str(item.get("title") or labels[index]), size=12, color=colors[index], bold=True)
        body = item.get("text") or item.get("items") or "待补充"
        if isinstance(body, list):
            body = "\n".join(f"• {value}" for value in body)
        add_text(slide, x + 0.28, y + 0.72, 5.24, 1.22, str(body), size=10, color=GRAY)


def add_roadmap(slide, spec):
    items = spec.get("items") or []
    for index, item in enumerate(items[:3]):
        x = 0.66 + index * 4.13
        add_text(slide, x, 1.44, 3.75, 0.25, str(item.get("period") or f"阶段 {index + 1}"), size=9, color=ROYAL, bold=True)
        add_rect(slide, x, 1.86, 3.75, 0.10, fill=[ROYAL, COBALT, GREEN][index])
        add_text(slide, x, 2.22, 3.75, 0.50, str(item.get("title") or "阶段目标"), size=14, color=INK, bold=True)
        add_text(slide, x, 2.98, 3.75, 1.48, str(item.get("text") or ""), size=10.2, color=GRAY)
        add_text(slide, x, 4.70, 3.75, 0.26, "退出/升级门槛", size=8.5, color=COOL, bold=True)
        add_rect(slide, x, 5.10, 3.75, 0.86, fill=PALE, line=BORDER)
        add_text(slide, x + 0.18, 5.30, 3.39, 0.44, str(item.get("gate") or "依据最新证据复核"), size=9.5, color=INK, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, 0.66, 6.35, 12.02, 0.34, str(spec.get("takeaway") or "每阶段均保留停止条件，避免在政策或经济性未成立前重资产投入。"), size=10.5, color=ROYAL, bold=True, align=PP_ALIGN.CENTER)


def add_decision(slide, spec):
    items = spec.get("items") or []
    rows = max(2, min(len(items), 5))
    table_shape = slide.shapes.add_table(rows + 1, 4, Inches(0.64), Inches(1.46), Inches(12.02), Inches(4.68))
    table = table_shape.table
    headers = ["决策事项", "建议动作", "责任人/时间", "通过门槛"]
    widths = [2.65, 4.42, 2.10, 2.85]
    for index, width in enumerate(widths):
        table.columns[index].width = Inches(width)
    table.rows[0].height = Inches(0.48)
    body_height = 4.20 / rows
    for row in range(1, rows + 1):
        table.rows[row].height = Inches(body_height)
    for col, header in enumerate(headers):
        cell = table.cell(0, col)
        cell.text = header
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(ROYAL)
    for row in range(1, rows + 1):
        item = items[row - 1] if row - 1 < len(items) else {}
        values = [item.get("title", "待决策"), item.get("text", "待补充"), item.get("owner", "待指定"), item.get("gate", "证据闭环")]
        for col, value in enumerate(values):
            cell = table.cell(row, col)
            cell.text = str(value)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(PALE if row % 2 else WHITE)
    for row in range(rows + 1):
        for col in range(4):
            cell = table.cell(row, col)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.LEFT
                for run in paragraph.runs:
                    run.font.name = "Microsoft YaHei"
                    run.font.size = Pt(9 if row else 9.5)
                    run.font.bold = row == 0 or col == 0
                    run.font.color.rgb = rgb(WHITE if row == 0 else INK)
    add_rect(slide, 0.64, 6.35, 12.02, 0.36, fill=NAVY)
    add_text(slide, 0.86, 6.42, 11.58, 0.20, str(spec.get("takeaway") or "建议只批准可逆、可度量且有明确退出条件的下一步。"), size=9.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER)


def add_closing(slide, spec):
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY)
    add_rect(slide, 0, 0, SLIDE_W, 0.06, fill=COBALT)
    add_text(slide, 0.78, 0.80, 2.30, 0.26, str(spec.get("section") or "DECISION & NEXT STEP"), size=9, color="A8B5CE", bold=True, font="Arial")
    add_text(slide, 0.78, 1.56, 10.90, 1.06, str(spec.get("title") or "以小规模验证换取下一阶段选择权"), size=30, color=WHITE, bold=True, font="Georgia")
    add_rect(slide, 0.78, 2.92, 1.05, 0.035, fill=COBALT)
    items = spec.get("items") or []
    for index, item in enumerate(items[:3]):
        x = 0.78 + index * 4.03
        add_text(slide, x, 3.52, 0.55, 0.40, f"0{index + 1}", size=16, color=COBALT, bold=True, font="Georgia")
        add_text(slide, x + 0.62, 3.48, 3.05, 0.43, str(item.get("title") or "下一步"), size=12.5, color=WHITE, bold=True)
        add_text(slide, x + 0.62, 4.08, 3.05, 1.12, str(item.get("text") or ""), size=10, color="C7D2E5")
    add_text(slide, 0.78, 6.65, 11.65, 0.28, str(spec.get("source") or "内部决策材料｜以最终证据审计为准"), size=8, color="71809E")


def add_notes(slide, notes: str) -> None:
    if not notes.strip():
        return
    try:
        slide.notes_slide.notes_text_frame.text = notes.strip()
    except (AttributeError, ValueError):
        pass


def validate_plan(plan: dict) -> None:
    slides = plan.get("slides") or []
    if not 10 <= len(slides) <= 18:
        raise ValueError("Final executive deck must contain 10-18 slides")
    if str(slides[0].get("layout") or "") != "cover":
        raise ValueError("The first slide must use the cover layout")
    allowed = {"cover", "executive_summary", "figure", "timeline", "segments", "matrix", "comparison", "swot", "roadmap", "decision", "closing"}
    for index, slide in enumerate(slides, start=1):
        layout = str(slide.get("layout") or "")
        if layout not in allowed:
            raise ValueError(f"Unsupported layout on slide {index}: {layout}")
        if layout not in {"cover", "closing"}:
            if not slide.get("answer_first"):
                raise ValueError(f"Slide {index} must explicitly set answer_first=true")
            if len(str(slide.get("title") or "").strip()) < 10:
                raise ValueError(f"Slide {index} title is too short to carry a conclusion")
            for field in ("source", "bias_note"):
                if not str(slide.get(field) or "").strip():
                    raise ValueError(f"Slide {index} is missing {field}")


def build(project_dir: Path, plan_path: Path, acquisition_path: Path, output: Path) -> dict:
    plan = read_json(plan_path, {})
    acquisition = read_json(acquisition_path, {})
    validate_plan(plan)
    deck = plan.get("deck") or {}
    update_date = str(deck.get("update_date") or now_iso()[:10])
    presentation_project = project_dir / "presentation_project"
    presentation_project.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    blank = prs.slide_layouts[6]
    registry: list[dict[str, Any]] = []
    for slide_no, spec in enumerate(plan["slides"], start=1):
        slide = prs.slides.add_slide(blank)
        layout = str(spec["layout"])
        used_images: list[dict] = []
        if layout == "cover":
            result = add_cover(slide, deck, acquisition, project_dir)
            visual_kind = result["visual_kind"]
            used_images = result["used_images"]
        elif layout == "closing":
            add_closing(slide, spec)
            visual_kind = "native_vector_closing"
        else:
            add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE)
            add_title(slide, str(spec["title"]), str(spec.get("section") or "ANALYSIS"), slide_no)
            if layout == "executive_summary":
                add_summary(slide, spec)
            elif layout == "figure":
                used_images = add_figure_slide(slide, spec, project_dir, acquisition)
            elif layout == "timeline":
                add_timeline(slide, spec)
            elif layout == "segments":
                add_segments(slide, spec)
            elif layout == "matrix":
                add_matrix(slide, spec)
            elif layout == "comparison":
                add_comparison(slide, spec)
            elif layout == "swot":
                add_swot(slide, spec)
            elif layout == "roadmap":
                add_roadmap(slide, spec)
            elif layout == "decision":
                add_decision(slide, spec)
            add_footer(slide, str(spec["source"]), update_date, str(spec["bias_note"]))
            visual_kind = "approved_figure" if used_images else f"native_vector_{layout}"
        add_notes(slide, str(spec.get("speaker_notes") or ""))
        registry.append(
            {
                "slide_no": slide_no,
                "slide_id": str(spec.get("slide_id") or f"S{slide_no:02d}"),
                "layout": layout,
                "title": str(spec.get("title") or deck.get("title") or ""),
                "answer_first": bool(spec.get("answer_first")) if layout not in {"cover", "closing"} else True,
                "visual_kind": visual_kind,
                "source": str(spec.get("source") or deck.get("meta") or ""),
                "bias_note": str(spec.get("bias_note") or ""),
                "used_images": used_images,
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)
    design_spec = (
        "# Presentation Design Specification\n\n"
        f"- Pipeline: {PIPELINE_ID}\n"
        "- Canvas: 16:9, 13.333 × 7.5 inches\n"
        "- Content slides: white consulting canvas, answer-first titles, royal-blue evidence accents\n"
        "- Cover: EWO deep-navy image path when available; light consulting typography fallback otherwise\n"
        "- Typography: Georgia for cover/hero numbers; Microsoft YaHei/Arial for analytical content\n"
        "- Visual policy: reuse approved figures first; EWO only for non-data illustrations; native editable vectors on fallback\n"
        "- QA: every slide rendered, inspected, fixed at least once, and registered by final hash\n"
    )
    (presentation_project / "design_spec.md").write_text(design_spec, encoding="utf-8")
    write_json(
        presentation_project / "spec_lock.json",
        {
            "pipeline_id": PIPELINE_ID,
            "renderer_id": RENDERER_ID,
            "canvas": {"width_inches": SLIDE_W, "height_inches": SLIDE_H},
            "colors": {"navy": NAVY, "primary": ROYAL, "accent": COBALT, "ink": INK, "gray": GRAY, "border": BORDER},
            "fonts": {"hero": "Georgia", "body": "Microsoft YaHei", "latin": "Arial"},
            "minimum_font_pt": 7,
        },
    )
    write_json(presentation_project / "slide_registry.json", {"slides": registry})
    build_manifest = {
        "created_at": now_iso(),
        "pipeline_id": PIPELINE_ID,
        "renderer_id": RENDERER_ID,
        "plan_path": stored_path(plan_path, project_dir),
        "plan_sha256": sha256_file(plan_path),
        "image_acquisition_manifest": stored_path(acquisition_path, project_dir),
        "image_acquisition_sha256": sha256_file(acquisition_path),
        "output_path": stored_path(output, project_dir),
        "output_sha256": sha256_file(output),
        "slide_count": len(registry),
        "serial_slide_generation": True,
    }
    write_json(presentation_project / "build_manifest.json", build_manifest)
    return build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an editable executive energy-market PPTX with the embedded renderer.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--image-manifest", default="presentation_project/image_acquisition_manifest.json")
    parser.add_argument("--output", default="deliverables/市场调研内部宣讲PPT.pptx")
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    plan_path = resolve_path(args.plan, project_dir)
    acquisition_path = resolve_path(args.image_manifest, project_dir)
    output = resolve_path(args.output, project_dir)
    manifest = build(project_dir, plan_path, acquisition_path, output)
    print(output)
    print(f"Slides: {manifest['slide_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
