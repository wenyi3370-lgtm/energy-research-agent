from __future__ import annotations

import argparse
import math
from pathlib import Path

from openpyxl import load_workbook

from _common import Issue, add_common_args, print_report, read_csv
from sync_csv_to_excel import REQUIRED_NONEMPTY_CSVS, SHEET_CSV_MAP
from style_excel_consulting import THEMES


FORMULA_ERROR_VALUES = {
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#N/A",
    "#NAME?",
    "#NUM!",
    "#NULL!",
}
ALLOWED_HEADER_COLORS = {palette["header"] for palette in THEMES.values()}


def _rgb(color) -> str | None:
    if color is None or color.type != "rgb" or not color.rgb:
        return None
    return str(color.rgb)[-6:].upper()


def _workbooks(project_dir: Path) -> list[Path]:
    return sorted((project_dir / "deliverables").glob("*.xlsx"))


def _data_rows(ws) -> int:
    return sum(
        1
        for row in ws.iter_rows(min_row=2, values_only=True)
        if any(value not in (None, "") for value in row)
    )


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _numeric(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_workbook(project_dir: Path, workbook_path: Path, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    try:
        formulas = load_workbook(workbook_path, data_only=False, read_only=False)
        values = load_workbook(workbook_path, data_only=True, read_only=False)
    except Exception as exc:
        return [Issue("fail", workbook_path.name, "workbook", f"Unreadable workbook: {exc}")]

    for sheet_name in ("09_Integrated_Matrix", "10_SWOT_Opportunity"):
        if sheet_name not in formulas.sheetnames:
            issues.append(Issue("fail", sheet_name, "sheet", "Required strategy sheet is missing"))
            continue
        if _data_rows(formulas[sheet_name]) <= 0:
            issues.append(Issue("fail", sheet_name, "rows", "Required strategy sheet has no data rows"))

    csv_to_sheet = {csv_name: sheet for sheet, csv_name in SHEET_CSV_MAP.items()}
    for csv_name, sheet_name in csv_to_sheet.items():
        csv_path = project_dir / csv_name
        if not csv_path.exists() or sheet_name not in formulas.sheetnames:
            continue
        _, csv_rows = read_csv(csv_path)
        workbook_rows = _data_rows(formulas[sheet_name])
        if csv_name in REQUIRED_NONEMPTY_CSVS and not csv_rows:
            issues.append(Issue("fail", csv_name, "rows", "Required CSV has no data rows"))
        if workbook_rows != len(csv_rows):
            issues.append(
                Issue(
                    "fail",
                    sheet_name,
                    "row_reconciliation",
                    f"Workbook has {workbook_rows} data rows but {csv_name} has {len(csv_rows)}",
                )
            )

    formula_count = 0
    for ws in formulas.worksheets:
        cached_ws = values[ws.title]
        for row in ws.iter_rows():
            for cell in row:
                if not _is_formula(cell.value):
                    continue
                formula_count += 1
                cached = cached_ws[cell.coordinate].value
                if cached in FORMULA_ERROR_VALUES:
                    issues.append(Issue("fail", f"{ws.title}!{cell.coordinate}", "formula", f"Formula error: {cached}"))
                elif cached is None:
                    issues.append(
                        Issue(
                            "fail" if mode == "final" else "warn",
                            f"{ws.title}!{cell.coordinate}",
                            "formula_cache",
                            "Formula has not been recalculated and saved",
                        )
                    )

    results_csv = project_dir / "13_Model_Results.csv"
    if results_csv.exists():
        result_fields, result_rows = read_csv(results_csv)
        if result_rows:
            if "excel_formula" not in result_fields:
                issues.append(Issue("fail", results_csv.name, "excel_formula", "Missing formula contract column"))
            if "13_Model_Results" not in formulas.sheetnames:
                issues.append(Issue("fail", "13_Model_Results", "sheet", "Model result sheet is missing"))
            else:
                formula_ws = formulas["13_Model_Results"]
                value_ws = values["13_Model_Results"]
                headers = {cell.value: cell.column for cell in formula_ws[1]}
                value_column = headers.get("value")
                if value_column is None:
                    issues.append(Issue("fail", "13_Model_Results", "value", "Result value column is missing"))
                else:
                    for row_number, result in enumerate(result_rows, start=2):
                        result_id = result.get("result_id", "") or f"row-{row_number}"
                        formula = formula_ws.cell(row_number, value_column).value
                        if not _is_formula(formula):
                            issues.append(Issue("fail", result_id, "value", "Modeled result is not an Excel formula"))
                            continue
                        expected = _numeric(result.get("value"))
                        cached = _numeric(value_ws.cell(row_number, value_column).value)
                        if mode == "final" and expected is not None and cached is not None:
                            tolerance = max(1e-9, abs(expected) * 1e-6)
                            if abs(expected - cached) > tolerance:
                                issues.append(
                                    Issue(
                                        "fail",
                                        result_id,
                                        "formula_reconciliation",
                                        f"Recalculated value {cached} does not match frozen value {expected}",
                                    )
                                )

    if formula_count == 0 and results_csv.exists():
        _, result_rows = read_csv(results_csv)
        if result_rows:
            issues.append(Issue("fail", workbook_path.name, "formula_count", "Workbook has modeled results but zero formulas"))

    if formulas.sheetnames and formulas.sheetnames[-1] != "99_来源与口径":
        issues.append(Issue("fail", workbook_path.name, "sheet_order", "99_来源与口径 must be the final sheet"))

    for ws in formulas.worksheets:
        if ws._charts:
            issues.append(Issue("fail", ws.title, "native_charts", "Excel-native charts are not allowed"))
        print_area = str(ws.print_area).strip()
        if not print_area:
            issues.append(Issue("fail", ws.title, "print_area", "Print area is not set"))
        properties = ws.sheet_properties.pageSetUpPr
        if not properties or not properties.fitToPage:
            issues.append(Issue("fail", ws.title, "fitToPage", "Fit-to-page mode is not enabled"))
        if ws.page_setup.fitToWidth != 1 or ws.page_setup.fitToHeight != 0:
            issues.append(Issue("fail", ws.title, "page_fit", "Expected fitToWidth=1 and fitToHeight=0"))
        if ws.page_setup.scale is not None:
            issues.append(Issue("fail", ws.title, "scale", "Fixed print scale conflicts with fit-to-page settings"))
        expected_orientation = "landscape" if ws.max_column >= 9 else "portrait"
        if ws.page_setup.orientation != expected_orientation:
            issues.append(Issue("fail", ws.title, "orientation", f"Expected {expected_orientation} orientation"))
        if ws.sheet_view.showGridLines is not False:
            issues.append(Issue("fail", ws.title, "gridlines", "Worksheet gridlines must be hidden"))
        if ws.freeze_panes != "A2":
            issues.append(Issue("fail", ws.title, "freeze_panes", "Expected frozen header at A2"))
        if not ws.auto_filter.ref:
            issues.append(Issue("fail", ws.title, "autofilter", "Header filter range is missing"))

        populated_columns = [cell.column for cell in ws[1] if cell.value not in (None, "")]
        for column in populated_columns:
            header = ws.cell(1, column)
            if _rgb(header.fill.fgColor) not in ALLOWED_HEADER_COLORS:
                issues.append(Issue("fail", f"{ws.title}!{header.coordinate}", "header_fill", "Header does not use an embedded light consulting theme"))
            if header.font.name != "Arial" or header.font.sz != 11 or not header.font.bold or _rgb(header.font.color) != "FFFFFF":
                issues.append(Issue("fail", f"{ws.title}!{header.coordinate}", "header_font", "Expected Arial 11 bold white header text"))
            if header.alignment.horizontal != "right":
                issues.append(Issue("fail", f"{ws.title}!{header.coordinate}", "header_alignment", "Header must be right aligned"))
            if header.border.left.style or header.border.right.style:
                issues.append(Issue("fail", f"{ws.title}!{header.coordinate}", "vertical_border", "Vertical table borders are not allowed"))

        for row_number in range(2, ws.max_row + 1):
            if not any(ws.cell(row_number, column).value not in (None, "") for column in populated_columns):
                continue
            if ws.row_dimensions[row_number].height != 18:
                issues.append(Issue("fail", f"{ws.title}!{row_number}", "row_height", "Data row height must be 18"))
            for column in populated_columns:
                cell = ws.cell(row_number, column)
                if cell.value in (None, ""):
                    continue
                if cell.font.name != "Arial" or cell.font.sz != 11:
                    issues.append(Issue("fail", f"{ws.title}!{cell.coordinate}", "data_font", "Expected Arial 11 data font"))
                if cell.border.left.style or cell.border.right.style:
                    issues.append(Issue("fail", f"{ws.title}!{cell.coordinate}", "vertical_border", "Vertical table borders are not allowed"))
                if _is_formula(cell.value) and _rgb(cell.font.color) != "000000":
                    issues.append(Issue("fail", f"{ws.title}!{cell.coordinate}", "formula_font", "Formula cells must use black font"))
                if cell.fill.fill_type == "solid" and _rgb(cell.fill.fgColor) in ALLOWED_HEADER_COLORS:
                    issues.append(Issue("fail", f"{ws.title}!{cell.coordinate}", "data_fill", "Data rows must not inherit the header fill"))

    return issues


def validate(project_dir: Path, mode: str = "final") -> list[Issue]:
    workbooks = _workbooks(project_dir)
    if not workbooks:
        return [Issue("fail", "deliverables", "xlsx", "No Excel workbook found")]
    issues: list[Issue] = []
    for workbook in workbooks:
        issues.extend(validate_workbook(project_dir, workbook, mode))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Excel formulas, strategy sheets, row reconciliation, and print layout.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--mode", choices=("draft", "final"), default="final")
    add_common_args(parser)
    args = parser.parse_args()
    return print_report(
        "Excel delivery validation",
        validate(Path(args.project_dir).resolve(), args.mode),
        json_output=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
