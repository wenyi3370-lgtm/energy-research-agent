#!/usr/bin/env python
"""Deterministic Excel chart placement, captioning, and layout audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.legend import Legend
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Font, NamedStyle
from openpyxl.utils import get_column_letter, range_boundaries


CAPTION_STYLE = "Chart Caption"
SOURCE_STYLE = "Chart Source"
LEGEND_POSITIONS = {"b", "r", "l", "t", "tr"}
LABEL_POSITIONS = {"bestFit", "b", "ctr", "inBase", "inEnd", "l", "outEnd", "r", "t"}


def _ensure_styles(wb) -> None:
    if CAPTION_STYLE not in wb.named_styles:
        wb.add_named_style(
            NamedStyle(
                name=CAPTION_STYLE,
                font=Font(name="Microsoft YaHei", size=10.5, bold=True, color="1F1F1F"),
                alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
            )
        )
    if SOURCE_STYLE not in wb.named_styles:
        wb.add_named_style(
            NamedStyle(
                name=SOURCE_STYLE,
                font=Font(name="Microsoft YaHei", size=9, color="666666"),
                alignment=Alignment(horizontal="left", vertical="center", wrap_text=True),
            )
        )


def _bounds(cell_range: str) -> tuple[int, int, int, int]:
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    if min_col >= max_col or min_row >= max_row:
        raise ValueError(f"Chart anchor must span at least 2 columns and 2 rows: {cell_range}")
    return min_col, min_row, max_col, max_row


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _prepare_merged_row(ws, min_col: int, max_col: int, row: int, value: str, style: str) -> str:
    target = (min_col, row, max_col, row)
    target_ref = f"{get_column_letter(min_col)}{row}:{get_column_letter(max_col)}{row}"
    for merged in list(ws.merged_cells.ranges):
        existing = range_boundaries(str(merged))
        if existing == target:
            break
        if _intersects(existing, target):
            raise ValueError(f"Caption range {target_ref} intersects merged range {merged}")
    else:
        ws.merge_cells(target_ref)

    cell = ws.cell(row=row, column=min_col)
    if cell.value not in (None, "", value):
        raise ValueError(f"Caption target {cell.coordinate} contains existing content")
    cell.value = value
    cell.style = style
    return target_ref


def place_chart_block(
    ws,
    chart,
    anchor_range: str,
    caption: str,
    source: str,
    *,
    title: str | None = None,
    legend_position: str = "b",
    data_label_position: str | None = None,
    show_values: bool | None = None,
) -> dict[str, str]:
    """Anchor a chart to cells and place stable caption/source rows below it."""
    if legend_position not in LEGEND_POSITIONS:
        raise ValueError(f"Unsupported legend position: {legend_position}")
    if data_label_position and data_label_position not in LABEL_POSITIONS:
        raise ValueError(f"Unsupported data label position: {data_label_position}")
    if not caption.strip():
        raise ValueError("Chart caption is required")
    if not source.strip():
        raise ValueError("Chart source note is required")

    _ensure_styles(ws.parent)
    min_col, min_row, max_col, max_row = _bounds(anchor_range)

    chart.anchor = TwoCellAnchor(
        editAs="twoCell",
        _from=AnchorMarker(col=min_col - 1, row=min_row - 1, colOff=0, rowOff=0),
        to=AnchorMarker(col=max_col, row=max_row, colOff=0, rowOff=0),
    )
    if title is not None:
        chart.title = title
    if chart.title is not None:
        chart.title.overlay = False

    if chart.legend is None:
        chart.legend = Legend()
    chart.legend.position = legend_position
    chart.legend.overlay = False
    chart.legend.layout = None
    chart.layout = None

    if data_label_position is not None or show_values is not None:
        if getattr(chart, "dLbls", None) is None:
            chart.dLbls = DataLabelList()
        if data_label_position is not None:
            chart.dLbls.dLblPos = data_label_position
        if show_values is not None:
            chart.dLbls.showVal = show_values
            chart.dLbls.showCatName = False
            chart.dLbls.showSerName = False
            chart.dLbls.showLegendKey = False
            chart.dLbls.showPercent = False
            chart.dLbls.showBubbleSize = False

    caption_row = max_row + 1
    source_row = max_row + 2
    caption_ref = _prepare_merged_row(ws, min_col, max_col, caption_row, caption.strip(), CAPTION_STYLE)
    source_ref = _prepare_merged_row(ws, min_col, max_col, source_row, source.strip(), SOURCE_STYLE)
    ws.row_dimensions[caption_row].height = max(ws.row_dimensions[caption_row].height or 0, 18)
    ws.row_dimensions[source_row].height = max(ws.row_dimensions[source_row].height or 0, 18)

    return {"anchor": anchor_range, "caption": caption_ref, "source": source_ref}


def _anchor_rect(anchor) -> tuple[int, int, int, int] | None:
    if not isinstance(anchor, TwoCellAnchor):
        return None
    return (anchor._from.col, anchor._from.row, anchor.to.col, anchor.to.row)


def audit_workbook(path: str | Path) -> dict[str, Any]:
    wb = load_workbook(path, data_only=False, read_only=False, keep_vba=str(path).lower().endswith(".xlsm"))
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    chart_count = 0

    for ws in wb.worksheets:
        rects: list[tuple[int, tuple[int, int, int, int]]] = []
        for idx, chart in enumerate(ws._charts):
            chart_count += 1
            tag = {"sheet": ws.title, "chart_index": idx}
            rect = _anchor_rect(chart.anchor)
            if rect is None:
                errors.append({**tag, "code": "floating-anchor", "message": "Use a TwoCellAnchor."})
                continue
            rects.append((idx, rect))

            if chart.title is None:
                errors.append({**tag, "code": "missing-title", "message": "Chart title is required."})
            elif getattr(chart.title, "overlay", False):
                errors.append({**tag, "code": "title-overlay", "message": "Chart title must not overlay the plot area."})

            if chart.legend is not None:
                if chart.legend.position != "b":
                    warnings.append({**tag, "code": "legend-position", "message": "Bottom legend is the portable default."})
                if getattr(chart.legend, "overlay", False):
                    errors.append({**tag, "code": "legend-overlay", "message": "Legend must not overlay the plot area."})
                if chart.legend.layout is not None:
                    warnings.append({**tag, "code": "manual-legend-layout", "message": "Manual legend layout may drift across Office engines."})

            if chart.layout is not None:
                warnings.append({**tag, "code": "manual-plot-layout", "message": "Manual plot layout may drift across Office engines."})

            start_col = rect[0] + 1
            caption_row = rect[3] + 1
            source_row = rect[3] + 2
            caption_cell = ws.cell(row=caption_row, column=start_col)
            source_cell = ws.cell(row=source_row, column=start_col)
            if not caption_cell.value or caption_cell.style != CAPTION_STYLE:
                errors.append({**tag, "code": "missing-caption", "cell": caption_cell.coordinate})
            if not source_cell.value or source_cell.style != SOURCE_STYLE:
                errors.append({**tag, "code": "missing-source", "cell": source_cell.coordinate})

        for pos, (idx_a, rect_a) in enumerate(rects):
            for idx_b, rect_b in rects[pos + 1 :]:
                if _intersects(rect_a, rect_b):
                    errors.append(
                        {
                            "sheet": ws.title,
                            "chart_index": idx_a,
                            "code": "chart-overlap",
                            "other_chart_index": idx_b,
                        }
                    )

    wb.close()
    return {
        "status": "pass" if not errors else "fail",
        "file": str(Path(path).resolve()),
        "charts": chart_count,
        "errors": errors,
        "warnings": warnings,
    }


def normalize_from_manifest(input_path: str | Path, output_path: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    keep_vba = str(input_path).lower().endswith(".xlsm")
    wb = load_workbook(input_path, data_only=False, read_only=False, keep_vba=keep_vba)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    for sheet_name, items in manifest.get("sheets", {}).items():
        if sheet_name not in wb.sheetnames:
            raise KeyError(f"Worksheet not found: {sheet_name}")
        ws = wb[sheet_name]
        for item in items:
            idx = int(item["chart_index"])
            if idx < 0 or idx >= len(ws._charts):
                raise IndexError(f"{sheet_name} chart_index {idx} is out of range")
            place_chart_block(
                ws,
                ws._charts[idx],
                item["anchor"],
                item["caption"],
                item["source"],
                title=item.get("title"),
                legend_position=item.get("legend_position", "b"),
                data_label_position=item.get("data_label_position"),
                show_values=item.get("show_values"),
            )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()
    return audit_workbook(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize and audit Excel chart layout.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("workbook")
    audit.add_argument("--json-out")

    normalize = sub.add_parser("normalize")
    normalize.add_argument("workbook")
    normalize.add_argument("--output", required=True)
    normalize.add_argument("--manifest", required=True)
    normalize.add_argument("--json-out")

    args = parser.parse_args()
    if args.command == "audit":
        result = audit_workbook(args.workbook)
    else:
        result = normalize_from_manifest(args.workbook, args.output, args.manifest)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out:
        Path(args.json_out).write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
