from __future__ import annotations

import argparse
import re
from copy import copy
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins, PrintPageSetup
from openpyxl.worksheet.properties import PageSetupProperties


THEMES = {
    "default": {
        "header": "4472C4",
        "summary": "D9E2F3",
        "numeric": "4472C4",
    },
    "jade": {
        "header": "375623",
        "summary": "E2EFDA",
        "numeric": "375623",
    },
}

PCT_RE = re.compile(r"(?:率|占比|百分比|rate|ratio|share|percent|pct)\s*$", re.I)
DATE_RE = re.compile(r"日期|时间|年月|年份|date|year|month|period", re.I)
TEXT_RE = re.compile(
    r"名称|姓名|地址|电话|邮箱|备注|说明|编号|编码|代码|型号|证书|id|url|link|"
    r"phone|email|code|desc|address|name|model|asin|sku|status|class|type",
    re.I,
)
MONEY_RE = re.compile(
    r"金额|价格|收入|成本|利润|费用|预算|现金流|capex|opex|price|cost|revenue|"
    r"total|budget|expense|value|npv",
    re.I,
)
SUMMARY_RE = re.compile(r"^(?:合计|总计|小计|汇总|total|subtotal)$", re.I)
URL_RE = re.compile(r"^https?://", re.I)

THIN_GRAY = Side(style="dashed", color="B7C0CD")
MEDIUM_DARK = Side(style="medium", color="1F2937")
NO_SIDE = Side(style=None)


def _display(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def infer_column_type(header: object, values: list[object]) -> str:
    label = _display(header).strip()
    if PCT_RE.search(label):
        return "pct"
    if DATE_RE.search(label):
        return "date"
    if TEXT_RE.search(label):
        return "text"
    if MONEY_RE.search(label):
        return "money"
    nonempty = [value for value in values if value not in (None, "")]
    if nonempty and all(isinstance(value, (date, datetime)) for value in nonempty):
        return "date"
    if nonempty and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in nonempty):
        return "number"
    return "text"


def _is_formula(cell) -> bool:
    return cell.data_type == "f" or (
        isinstance(cell.value, str) and cell.value.startswith("=")
    )


def _is_summary_row(ws, row_number: int) -> bool:
    for cell in ws[row_number]:
        text = _display(cell.value).strip()
        if text:
            return bool(SUMMARY_RE.match(text))
    return False


def _column_width(ws, column: int, data_end: int) -> float:
    values = [ws.cell(row=row, column=column).value for row in range(1, data_end + 1)]
    if any(_is_formula(ws.cell(row=row, column=column)) for row in range(2, data_end + 1)):
        return 15.0
    texts = [_display(value) for value in values if value not in (None, "")]
    if not texts:
        return 12.0
    width = max(len(text.encode("gb18030", errors="ignore")) / 2 for text in texts)
    return float(min(max(round(width + 2, 1), 12), 36))


def style_worksheet(ws, theme: str = "default") -> None:
    if theme not in THEMES:
        raise ValueError(f"Unsupported Excel theme: {theme}; choose one of {sorted(THEMES)}")
    palette = THEMES[theme]
    data_end = max(
        (row for row in range(1, ws.max_row + 1) if any(ws.cell(row, col).value not in (None, "") for col in range(1, ws.max_column + 1))),
        default=1,
    )
    data_cols = max(
        (col for col in range(1, ws.max_column + 1) if any(ws.cell(row, col).value not in (None, "") for row in range(1, data_end + 1))),
        default=1,
    )
    header_fill = PatternFill("solid", fgColor=palette["header"])
    summary_fill = PatternFill("solid", fgColor=palette["summary"])
    header_border = Border(top=MEDIUM_DARK, bottom=MEDIUM_DARK, left=NO_SIDE, right=NO_SIDE)
    mid_border = Border(bottom=THIN_GRAY, left=NO_SIDE, right=NO_SIDE)
    bottom_border = Border(bottom=MEDIUM_DARK, left=NO_SIDE, right=NO_SIDE)
    column_types: dict[int, str] = {}

    for column in range(1, data_cols + 1):
        values = [ws.cell(row, column).value for row in range(2, data_end + 1)]
        column_types[column] = infer_column_type(ws.cell(1, column).value, values)
        header = ws.cell(1, column)
        header.fill = copy(header_fill)
        header.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        header.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        header.border = copy(header_border)

    ws.row_dimensions[1].height = 22
    for row in range(2, data_end + 1):
        summary = _is_summary_row(ws, row)
        ws.row_dimensions[row].height = 18
        for column in range(1, data_cols + 1):
            cell = ws.cell(row, column)
            col_type = column_types[column]
            is_formula = _is_formula(cell)
            is_numeric = isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
            font_color = "000000" if is_formula or not is_numeric else palette["numeric"]
            cell.font = Font(name="Arial", size=11, bold=summary, color=font_color)
            cell.fill = copy(summary_fill) if summary else PatternFill(fill_type=None)
            cell.alignment = Alignment(
                horizontal="right" if col_type in {"money", "number", "pct", "date"} else "left",
                vertical="center",
                wrap_text=col_type == "text",
            )
            if col_type == "pct":
                cell.number_format = "0.00%"
            elif col_type == "date":
                cell.number_format = "yyyy/mm/dd"
            elif col_type == "money":
                cell.number_format = "#,##0.00"
            elif col_type == "number":
                cell.number_format = "#,##0"
            else:
                cell.number_format = "@" if not is_formula else cell.number_format
            cell.border = copy(bottom_border if row == data_end else mid_border)
            if isinstance(cell.value, str) and URL_RE.match(cell.value.strip()):
                cell.hyperlink = cell.value.strip()
                cell.font = Font(name="Arial", size=11, color="0563C1", underline="single")

    for column in range(1, data_cols + 1):
        ws.column_dimensions[get_column_letter(column)].width = _column_width(ws, column, data_end)
    ws.column_dimensions[get_column_letter(data_cols + 1)].width = 3
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(data_cols)}{data_end}"
    ws.sheet_view.showGridLines = False
    ws.print_area = f"$A$1:${get_column_letter(data_cols)}${data_end}"
    ws.print_title_rows = "1:1"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True, autoPageBreaks=False)
    ws.page_setup = PrintPageSetup(
        worksheet=ws,
        orientation="landscape" if data_cols >= 9 else "portrait",
        paperSize=ws.PAPERSIZE_A4,
        fitToWidth=1,
        fitToHeight=0,
    )
    ws.page_setup.scale = None
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.5, bottom=0.5, header=0.2, footer=0.2)


def apply_workbook_style(workbook, theme: str = "default") -> None:
    if theme not in THEMES:
        raise ValueError(f"Unsupported Excel theme: {theme}; choose one of {sorted(THEMES)}")
    for worksheet in workbook.worksheets:
        style_worksheet(worksheet, theme)
    if "99_来源与口径" in workbook.sheetnames:
        source_sheet = workbook["99_来源与口径"]
        workbook._sheets.remove(source_sheet)
        workbook._sheets.append(source_sheet)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the embedded light consulting style to an Excel workbook.")
    parser.add_argument("input", help="Input .xlsx workbook")
    parser.add_argument("output", nargs="?", help="Output workbook; omit to update in place")
    parser.add_argument("--theme", choices=sorted(THEMES), default="default")
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve() if args.output else input_path
    workbook = load_workbook(input_path)
    apply_workbook_style(workbook, args.theme)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    print(f"Styled workbook ({args.theme}): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
