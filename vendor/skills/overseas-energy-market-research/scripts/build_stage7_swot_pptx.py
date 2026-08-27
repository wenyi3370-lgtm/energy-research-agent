from __future__ import annotations

import argparse
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from _common import now_iso, read_csv


BLUE = RGBColor(18, 58, 140)
COBALT = RGBColor(47, 111, 237)
CHARCOAL = RGBColor(48, 52, 59)
GRAY = RGBColor(210, 215, 224)
WHITE = RGBColor(255, 255, 255)


def add_textbox(slide, left, top, width, height, text, *, size=14, bold=False, color=CHARCOAL):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.LEFT
    run = paragraph.add_run()
    run.text = text
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def add_footer(slide, update_date: str, source_note: str) -> None:
    add_textbox(slide, Inches(0.45), Inches(7.05), Inches(12.4), Inches(0.25), f"更新日期：{update_date}｜来源与限制：{source_note}", size=7, color=CHARCOAL)


def add_title(slide, title: str, subtitle: str = "") -> None:
    add_textbox(slide, Inches(0.45), Inches(0.25), Inches(11.8), Inches(0.35), title, size=20, bold=True, color=BLUE)
    if subtitle:
        add_textbox(slide, Inches(0.45), Inches(0.68), Inches(11.8), Inches(0.28), subtitle, size=9, color=CHARCOAL)
    line = slide.shapes.add_shape(1, Inches(0.45), Inches(1.03), Inches(12.4), Inches(0.02))
    line.fill.solid()
    line.fill.fore_color.rgb = BLUE
    line.line.color.rgb = BLUE


def add_table(slide, headers: list[str], rows: list[dict[str, str]], left, top, width, height, max_rows: int = 8) -> None:
    shown = rows[:max_rows] or [{header: "待补充" for header in headers}]
    table_shape = slide.shapes.add_table(len(shown) + 1, len(headers), left, top, width, height)
    table = table_shape.table
    for col_idx, header in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.text = header
        cell.fill.solid()
        cell.fill.fore_color.rgb = BLUE
        for paragraph in cell.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.name = "Microsoft YaHei"
                run.font.size = Pt(7)
                run.font.bold = True
                run.font.color.rgb = WHITE
    for row_idx, row in enumerate(shown, start=1):
        for col_idx, header in enumerate(headers):
            cell = table.cell(row_idx, col_idx)
            cell.text = str(row.get(header, ""))[:160]
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(248, 249, 252) if row_idx % 2 else WHITE
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = "Microsoft YaHei"
                    run.font.size = Pt(6.5)
                    run.font.color.rgb = CHARCOAL


def read_chart_manifest(project_dir: Path) -> list[dict]:
    path = project_dir / "deliverables" / "charts" / "chart_manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("charts", [])


def add_chart_if_exists(slide, chart: dict | None, left, top, width, height) -> None:
    if chart and Path(chart.get("path", "")).exists():
        slide.shapes.add_picture(chart["path"], left, top, width=width, height=height)
    else:
        placeholder = slide.shapes.add_shape(1, left, top, width, height)
        placeholder.fill.solid()
        placeholder.fill.fore_color.rgb = RGBColor(244, 246, 250)
        placeholder.line.color.rgb = GRAY
        add_textbox(slide, left + Inches(0.2), top + Inches(0.2), width - Inches(0.4), Inches(0.4), "图表待补充：缺少可绘制数据", size=10)


def build(project_dir: Path, output: Path, region: str, category: str) -> None:
    _, integrated_rows = read_csv(project_dir / "09_Integrated_Matrix.csv") if (project_dir / "09_Integrated_Matrix.csv").exists() else ([], [])
    _, swot_rows = read_csv(project_dir / "10_SWOT_Opportunity.csv") if (project_dir / "10_SWOT_Opportunity.csv").exists() else ([], [])
    _, gap_rows = read_csv(project_dir / "11_Evidence_Issues.csv") if (project_dir / "11_Evidence_Issues.csv").exists() else ([], [])
    charts = {chart["name"]: chart for chart in read_chart_manifest(project_dir)}
    update_date = now_iso()

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    add_title(slide, f"{region}{category}竞品综合对比与SWOT分析", "基于已核验来源、型号一致性与用户评论语料的阶段性策略判断")
    add_textbox(slide, Inches(0.65), Inches(1.55), Inches(8.8), Inches(0.8), "核心结论必须来自综合矩阵、来源台账和审计报告；缺失项保留为“待核实”。", size=18, bold=True, color=CHARCOAL)
    add_textbox(slide, Inches(0.65), Inches(2.65), Inches(4.0), Inches(0.5), f"竞品记录：{len(integrated_rows)}", size=16, bold=True, color=BLUE)
    add_textbox(slide, Inches(4.9), Inches(2.65), Inches(4.0), Inches(0.5), f"SWOT记录：{len(swot_rows)}", size=16, bold=True, color=BLUE)
    add_textbox(slide, Inches(9.1), Inches(2.65), Inches(3.2), Inches(0.5), f"待核实项：{len(gap_rows)}", size=16, bold=True, color=BLUE)
    add_footer(slide, update_date, "所有判断需引用 evidence_row_ids 或 URL")

    slide = prs.slides.add_slide(blank)
    add_title(slide, "综合对比矩阵", "容量、功率、光伏输入、价格、渠道、智能化与战略判断")
    add_table(slide, ["brand", "exact_model", "capacity_kwh", "power_kw", "price", "channel_coverage", "strategic_judgment", "verification_status"], integrated_rows, Inches(0.45), Inches(1.25), Inches(12.45), Inches(5.55))
    add_footer(slide, update_date, "来源：09_Integrated_Matrix.csv")

    slide = prs.slides.add_slide(blank)
    add_title(slide, "定位与能力视图", "价格-容量散点与能力雷达用于识别价格空白带和能力短板")
    add_chart_if_exists(slide, charts.get("price_capacity_scatter"), Inches(0.55), Inches(1.25), Inches(6.0), Inches(4.9))
    add_chart_if_exists(slide, charts.get("capability_radar"), Inches(6.8), Inches(1.25), Inches(5.55), Inches(4.9))
    add_footer(slide, update_date, "来源：09_Integrated_Matrix.csv；缺失数据不插补")

    slide = prs.slides.add_slide(blank)
    add_title(slide, "SWOT与机会空间", "机会优先级必须绑定证据行；风险等级不明确则标待核实")
    add_table(slide, ["brand", "exact_model", "strength", "weakness", "opportunity", "threat", "risk_level", "opportunity_priority"], swot_rows, Inches(0.45), Inches(1.25), Inches(12.45), Inches(5.55))
    add_footer(slide, update_date, "来源：10_SWOT_Opportunity.csv")

    slide = prs.slides.add_slide(blank)
    add_title(slide, "证据限制与下一步", "交付前关闭高风险问题，或在报告中说明限制并建立透明模型假设")
    add_table(slide, ["stage", "topic", "geography", "exact_model", "field", "issue_type", "reason", "resolution_path", "status"], gap_rows, Inches(0.45), Inches(1.25), Inches(12.45), Inches(5.55))
    add_footer(slide, update_date, "来源：内部证据问题清单（未写入最终Excel）")

    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Stage 7 integrated competitor SWOT PPT from CSV and rendered charts.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--region", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--output", default="deliverables/竞品综合对比与SWOT分析.pptx")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    build(project_dir, output, args.region, args.category)
    print(f"Wrote Stage 7 PPT: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
