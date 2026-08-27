from __future__ import annotations

import argparse
import re
import shutil
from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.page import PageMargins, PrintPageSetup
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.styles import Font, PatternFill

from _common import read_csv
from style_excel_consulting import THEMES, apply_workbook_style


SHEET_CSV_MAP = {
    "00_调研审批": "00_Research_Approval.csv",
    "01_Market_Scan": "01_Market_Scan.csv",
    "02_Competitor_List": "02_Competitor_List.csv",
    "03_Model_Identifier_Check": "03_Model_Identifier_Check.csv",
    "04_Product_Parameters": "04_Product_Parameters.csv",
    "05_Pricing_Channel": "05_Pricing_Channel.csv",
    "06_Channel_Service": "06_Channel_Service.csv",
    "07_Raw_Reviews": "07_Raw_Reviews.csv",
    "08_Review_Coding": "08_Review_Coding.csv",
    "09_Integrated_Matrix": "09_Integrated_Matrix.csv",
    "10_SWOT_Opportunity": "10_SWOT_Opportunity.csv",
    "12_Model_Assumptions": "12_Model_Assumptions.csv",
    "13_Model_Results": "13_Model_Results.csv",
    "14_Simulated_Modeling_Data": "14_Simulated_Modeling_Data.csv",
    "99_来源与口径": "00_Source_Ledger.csv",
}

REQUIRED_NONEMPTY_CSVS = {
    "01_Market_Scan.csv",
    "02_Competitor_List.csv",
    "03_Model_Identifier_Check.csv",
    "04_Product_Parameters.csv",
    "05_Pricing_Channel.csv",
    "06_Channel_Service.csv",
    "07_Raw_Reviews.csv",
    "08_Review_Coding.csv",
    "09_Integrated_Matrix.csv",
    "10_SWOT_Opportunity.csv",
}
CALCULATED_RESULT_CLASSES = {"derived", "modeled_estimate", "modelled_estimate"}
ASSUMPTION_TOKEN_RE = re.compile(
    r"\{\{assumption:([^:}]+):(low|base|high)\}\}", re.IGNORECASE
)
CELL_REFERENCE_RE = re.compile(
    r"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!\$?[A-Z]{1,3}\$?\d+"
)


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copy_template_if_needed(output: Path, force: bool) -> None:
    if output.exists() and not force:
        return
    template = skill_root() / "assets" / "templates" / "excel" / "energy_market_research_workbook_template.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)


def copy_style(src, dst, copy_fill: bool = True) -> None:
    if src.has_style:
        dst.font = copy(src.font)
        if copy_fill:
            dst.fill = copy(src.fill)
        else:
            # 数据行保持无填充（白底），不继承表头填充色（如 #123A7A 深蓝）
            dst.fill = copy(PatternFill())
            # 数据行字体必须为深色常规体：表头是白色加粗，只清填充不清字色
            # 会导致"白字白底"数据不可见（2026-08-06 修复）
            dst.font = Font(name=src.font.name, size=src.font.size, bold=False, color="FF1F2937")
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)


def configure_print_layout(ws, data_end: int, column_count: int) -> None:
    last_column = get_column_letter(max(1, column_count))
    ws.print_area = f"$A$1:${last_column}${max(1, data_end)}"
    ws.print_title_rows = "1:1"
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(
        fitToPage=True,
        autoPageBreaks=False,
    )
    ws.page_setup = PrintPageSetup(
        worksheet=ws,
        orientation="landscape" if column_count >= 9 else "portrait",
        paperSize=ws.PAPERSIZE_A4,
        fitToWidth=1,
        fitToHeight=0,
    )
    ws.page_setup.scale = None
    ws.page_margins = PageMargins(
        left=0.25,
        right=0.25,
        top=0.5,
        bottom=0.5,
        header=0.2,
        footer=0.2,
    )
    ws.sheet_view.showGridLines = False


def compile_excel_formula(
    raw_formula: str,
    assumption_refs: dict[tuple[str, str], str],
    result_id: str,
) -> str:
    formula = raw_formula.strip()
    if not formula.startswith("="):
        raise ValueError(f"{result_id}: excel_formula must begin with '='")
    has_assumption_tokens = bool(ASSUMPTION_TOKEN_RE.search(formula))

    def replace_token(match: re.Match[str]) -> str:
        assumption_id = match.group(1).strip()
        value_kind = match.group(2).lower()
        key = (assumption_id, value_kind)
        if key not in assumption_refs:
            raise ValueError(
                f"{result_id}: excel_formula references unknown assumption/value {assumption_id}:{value_kind}"
            )
        return assumption_refs[key]

    compiled = ASSUMPTION_TOKEN_RE.sub(replace_token, formula)
    if "{{" in compiled or "}}" in compiled:
        raise ValueError(f"{result_id}: excel_formula contains an unsupported token")
    if not has_assumption_tokens and "!" not in formula:
        raise ValueError(
            f"{result_id}: excel_formula must use assumption tokens or an explicit cross-sheet cell reference"
        )
    if not CELL_REFERENCE_RE.search(compiled):
        raise ValueError(
            f"{result_id}: excel_formula must reference at least one workbook cell; constant-only formulas are forbidden"
        )
    return compiled


def prepare_formula_rows(
    sheet_name: str,
    rows: list[dict[str, str]],
    assumption_refs: dict[tuple[str, str], str],
) -> list[dict[str, str]]:
    prepared = [dict(row) for row in rows]
    if sheet_name != "13_Model_Results":
        return prepared
    for index, row in enumerate(prepared, start=2):
        value_class = row.get("value_class", "").strip().lower()
        if value_class not in CALCULATED_RESULT_CLASSES:
            continue
        result_id = row.get("result_id", "").strip() or f"row-{index}"
        raw_formula = row.get("excel_formula", "").strip()
        if not raw_formula:
            raise ValueError(
                f"{result_id}: modeled/derived result is missing excel_formula"
            )
        row["value"] = compile_excel_formula(raw_formula, assumption_refs, result_id)
        # Preserve the portable token formula as documentation without letting
        # Excel execute the token syntax as a second formula cell.
        row["excel_formula"] = "'" + raw_formula
    return prepared


def write_sheet(workbook, sheet_name: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    ws = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook.create_sheet(sheet_name)
    header_styles = [copy(ws.cell(row=1, column=i + 1)) for i in range(max(len(fieldnames), ws.max_column))]
    for row in ws.iter_rows():
        for cell in row:
            cell.value = None
    for col_idx, field in enumerate(fieldnames, start=1):
        cell = ws.cell(row=1, column=col_idx, value=field)
        if col_idx <= len(header_styles) and header_styles[col_idx - 1].has_style:
            copy_style(header_styles[col_idx - 1], cell)
        else:
            # 模板未覆盖的列：表头套用统一的深蓝底白字样式（2026-08-06 修复）
            cell.font = Font(bold=True, color="FFFFFFFF")
            cell.fill = PatternFill("solid", fgColor="FF123A7A")
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, field in enumerate(fieldnames, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row.get(field, ""))
            if col_idx <= len(header_styles):
                copy_style(header_styles[col_idx - 1], cell, copy_fill=False)
    ws.freeze_panes = "A2"
    for col_idx, field in enumerate(fieldnames, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max(len(field) + 2, 12), 36)
    # 压缩工作表维度：删除数据区以下的空行（图表锚点可能把 max_row 撑大，
    # 避免 Excel 显示大量带格式的空行导致数据"位移"）
    data_end = len(rows) + 1
    if ws.max_row > data_end:
        ws.delete_rows(data_end + 1, ws.max_row - data_end)
    configure_print_layout(ws, data_end, len(fieldnames))


def sync(project_dir: Path, output: Path, force_template: bool, theme: str = "default") -> list[str]:
    copy_template_if_needed(output, force_template)
    workbook = load_workbook(output)
    for internal_sheet in ("11_Data_Gaps", "11_Evidence_Issues"):
        if internal_sheet in workbook.sheetnames:
            workbook.remove(workbook[internal_sheet])
    if "00_Source_Ledger" in workbook.sheetnames and "99_来源与口径" not in workbook.sheetnames:
        workbook["00_Source_Ledger"].title = "99_来源与口径"
    tables: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for sheet, csv_name in SHEET_CSV_MAP.items():
        path = project_dir / csv_name
        if not path.exists():
            continue
        fieldnames, rows = read_csv(path)
        if csv_name in REQUIRED_NONEMPTY_CSVS and not rows:
            raise ValueError(f"{csv_name}: required evidence table has no data rows")
        tables[sheet] = (fieldnames, rows)

    assumption_refs: dict[tuple[str, str], str] = {}
    assumption_table = tables.get("12_Model_Assumptions")
    if assumption_table:
        fields, rows = assumption_table
        field_columns = {field: index for index, field in enumerate(fields, start=1)}
        for row_number, row in enumerate(rows, start=2):
            assumption_id = row.get("assumption_id", "").strip()
            if not assumption_id:
                continue
            for value_kind, field in (("low", "low_value"), ("base", "base_value"), ("high", "high_value")):
                column = field_columns.get(field)
                if column:
                    assumption_refs[(assumption_id, value_kind)] = (
                        f"{quote_sheetname('12_Model_Assumptions')}!${get_column_letter(column)}${row_number}"
                    )

    updated: list[str] = []
    for sheet, csv_name in SHEET_CSV_MAP.items():
        if sheet not in tables:
            continue
        fieldnames, rows = tables[sheet]
        prepared_rows = prepare_formula_rows(sheet, rows, assumption_refs)
        write_sheet(workbook, sheet, fieldnames, prepared_rows)
        if workbook[sheet].max_row - 1 != len(rows):
            raise RuntimeError(
                f"{sheet}: workbook row count does not match {csv_name}"
            )
        updated.append(sheet)
    apply_workbook_style(workbook, theme)
    workbook.save(output)
    return updated


def normalize_data_fonts(output: Path) -> int:
    """LibreOffice 重算往返会把含 CJK 文本的单元格字体替换为回退字体（如
    Noto Sans CJK SC），而交付校验要求数据区统一 Arial 11；重算后把数据区
    字体规范化回 Arial 11（保留加粗/字色等其余属性）。幂等：全部达标时返回 0。"""
    workbook = load_workbook(output)
    fixed = 0
    for ws in workbook.worksheets:
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.value in (None, ""):
                    continue
                font = cell.font
                if font.name == "Arial" and font.sz == 11:
                    continue
                cell.font = Font(
                    name="Arial",
                    size=11,
                    bold=bool(font.b),
                    italic=bool(font.i),
                    color=copy(font.color) if font.color else None,
                )
                fixed += 1
    if fixed:
        workbook.save(output)
    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync project CSV tables into the adapted Excel workbook.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--output", default="deliverables/产品竞品调研报告.xlsx")
    parser.add_argument("--force-template", action="store_true", help="Re-copy the Excel template before syncing.")
    parser.add_argument("--theme", choices=sorted(THEMES), default="default")
    parser.add_argument(
        "--skip-recalc",
        action="store_true",
        help="Do not recalculate formula caches after syncing (CHANGELOG v1.2.6).",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    updated = sync(project_dir, output, args.force_template, args.theme)
    print(f"Synced {len(updated)} sheets into: {output}")
    if updated:
        print(", ".join(updated))
    if not args.skip_recalc:
        # CHANGELOG v1.2.6: sync alone leaves stale formula caches and the
        # final audit fails with excel_delivery.formula_cache.  Recalculate
        # with LibreOffice when available; otherwise print a clear reminder.
        import shutil
        import subprocess
        import sys

        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice is None:
            win = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
            if win.exists():
                soffice = str(win)
        if soffice is None:
            print("NOTE: LibreOffice not found — run recalculate_excel.py manually before validate_excel_delivery.py")
            return 0
        script = Path(__file__).resolve().parent / "recalculate_excel.py"
        result = subprocess.run(
            [sys.executable, str(script), str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print("Formula caches recalculated (LibreOffice).")
            font_fixes = normalize_data_fonts(output)
            if font_fixes:
                print(f"Data fonts re-normalized to Arial 11 after recalc: {font_fixes} cells")
        else:
            print(
                "NOTE: recalculate_excel.py failed — run it manually before validate_excel_delivery.py:\n"
                + (result.stdout + result.stderr).strip()[-400:]
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
