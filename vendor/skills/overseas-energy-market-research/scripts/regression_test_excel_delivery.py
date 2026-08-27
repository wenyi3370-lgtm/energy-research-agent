from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from _common import read_csv, write_csv
from init_research_project import CSV_TARGETS
from recalculate_excel import recalculate
from scan_office_placeholders import scan_file
from sync_csv_to_excel import SHEET_CSV_MAP, sync
from validate_excel_delivery import validate


def fixture_row(target: str, fields: list[str]) -> dict[str, str]:
    row = {field: "" for field in fields}
    if fields:
        row[fields[0]] = "fixture"
    if target == "12_Model_Assumptions.csv":
        row.update(
            {
                "assumption_id": "A-Q1-001",
                "model_module": "Q1",
                "parameter_symbol": "N",
                "parameter_name": "Fixture fleet",
                "value_class": "scenario_assumption",
                "low_value": "80",
                "base_value": "100",
                "high_value": "120",
                "unit": "cars",
                "geography": "Fixture market",
                "period": "2030",
                "rationale": "Regression fixture",
                "formula_or_use": "Model input",
                "source_ids": "S-FIXTURE",
                "source_urls": "https://example.com/source",
                "confidence": "high",
                "owner": "modeler",
                "approval_status": "approved",
            }
        )
    elif target == "13_Model_Results.csv":
        row.update(
            {
                "result_id": "R-Q1-001",
                "model_module": "Q1",
                "scenario": "base",
                "metric": "fixture_result",
                "value": "200",
                "unit": "cars",
                "geography": "Fixture market",
                "period": "2030",
                "value_class": "modeled_estimate",
                "formula_or_method": "Fixture multiplication",
                "excel_formula": "={{assumption:A-Q1-001:base}}*2",
                "input_assumption_ids": "A-Q1-001",
                "evidence_row_ids": "S-FIXTURE",
                "validation_check": "passed",
                "sensitivity_or_uncertainty": "low/base/high",
                "confidence": "high",
                "interpretation": "Regression fixture",
                "verification_status": "verified",
            }
        )
    return row


def build_fixture(project_dir: Path) -> Path:
    skill_root = Path(__file__).resolve().parents[1]
    template_root = skill_root / "assets" / "templates" / "csv"
    reverse_targets = {target: source for source, target in CSV_TARGETS.items()}
    for target in sorted(set(SHEET_CSV_MAP.values())):
        source = template_root / reverse_targets[target]
        fields, _ = read_csv(source)
        write_csv(project_dir / target, fields, [fixture_row(target, fields)])
    output = project_dir / "deliverables" / "fixture.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    sync(project_dir, output, force_template=True)
    return output


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="excel_delivery_regression_") as raw:
        project_dir = Path(raw)
        workbook = build_fixture(project_dir)
        formula_book = load_workbook(workbook, data_only=False)
        formula = formula_book["13_Model_Results"]["E2"].value
        expected = "='12_Model_Assumptions'!$G$2*2"
        if formula != expected:
            raise AssertionError(f"Compiled formula mismatch: {formula!r} != {expected!r}")
        if scan_file(workbook):
            raise AssertionError("Clean workbook unexpectedly contains delivery placeholders")

        placeholder_book = project_dir / "placeholder_must_fail.xlsx"
        shutil.copy2(workbook, placeholder_book)
        dirty = load_workbook(placeholder_book)
        dirty["01_Market_Scan"]["A2"] = "[[fixture_placeholder]]"
        dirty.save(placeholder_book)
        findings = scan_file(placeholder_book)
        if not any(item["token"] == "[[fixture_placeholder]]" for item in findings):
            raise AssertionError("Embedded Office placeholder scanner missed a known placeholder")

        report = recalculate(workbook, 120)
        if report["status"] != "success" or report["total_formulas"] != 1:
            raise AssertionError(f"Recalculation failed: {report}")
        issues = validate(project_dir, "final")
        fails = [issue for issue in issues if issue.level == "fail"]
        if fails:
            raise AssertionError("Excel validator failed: " + "; ".join(issue.message for issue in fails))

        fields, _ = read_csv(project_dir / "09_Integrated_Matrix.csv")
        write_csv(project_dir / "09_Integrated_Matrix.csv", fields, [])
        try:
            sync(project_dir, project_dir / "deliverables" / "must_fail.xlsx", force_template=True)
        except ValueError as exc:
            if "09_Integrated_Matrix.csv" not in str(exc):
                raise
        else:
            raise AssertionError("Empty 09_Integrated_Matrix.csv was not rejected")

        write_csv(
            project_dir / "09_Integrated_Matrix.csv",
            fields,
            [fixture_row("09_Integrated_Matrix.csv", fields)],
        )
        result_fields, result_rows = read_csv(project_dir / "13_Model_Results.csv")
        result_rows[0]["excel_formula"] = ""
        write_csv(project_dir / "13_Model_Results.csv", result_fields, result_rows)
        try:
            sync(project_dir, project_dir / "deliverables" / "must_fail_formula.xlsx", force_template=True)
        except ValueError as exc:
            if "excel_formula" not in str(exc):
                raise
        else:
            raise AssertionError("Modeled result without excel_formula was not rejected")

    print("Excel delivery regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
