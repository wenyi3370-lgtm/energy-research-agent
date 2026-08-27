from __future__ import annotations

import argparse
import re
from pathlib import Path

from _common import Issue, add_common_args, print_report, read_csv, require_columns, row_label


ASSUMPTION_REQUIRED = [
    "assumption_id", "model_module", "parameter_symbol", "parameter_name", "value_class",
    "base_value", "unit", "geography", "period", "rationale", "formula_or_use",
    "source_ids", "source_urls", "confidence", "approval_status",
]

RESULT_REQUIRED = [
    "result_id", "model_module", "scenario", "metric", "value", "unit", "geography",
    "period", "value_class", "formula_or_method", "excel_formula", "input_assumption_ids", "evidence_row_ids",
    "validation_check", "sensitivity_or_uncertainty", "confidence", "verification_status",
]

GAP_REQUIRED = ["issue_id", "issue_type", "data_domain", "reason", "status"]

SIMULATION_REQUIRED = [
    "simulation_id", "assumption_id", "model_module", "variable", "geography", "period", "unit",
    "simulation_method", "distribution_or_process", "calibration_source_ids", "calibration_source_urls",
    "calibration_parameters", "physical_lower_bound", "physical_upper_bound",
    "correlation_or_time_structure", "random_seed", "sample_size", "generator_code_path",
    "generated_data_path", "validation_method", "validation_result", "sensitivity_or_uncertainty",
    "value_class", "approval_status",
]

ASSUMPTION_CLASSES = {"observed", "derived", "modeled_estimate", "scenario_assumption", "simulated"}
RESULT_CLASSES = {"derived", "modeled_estimate"}
APPROVED_STATUSES = {"approved", "confirmed", "decided"}
ASSUMPTION_TOKEN_RE = re.compile(
    r"\{\{assumption:([^:}]+):(low|base|high)\}\}", re.IGNORECASE
)


def _resolve_artifact(project_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_dir / path


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate(project_dir: Path, allow_empty: bool = False) -> list[Issue]:
    assumption_fields, assumptions = read_csv(project_dir / "12_Model_Assumptions.csv")
    result_fields, results = read_csv(project_dir / "13_Model_Results.csv")
    gap_fields, gaps = read_csv(project_dir / "11_Evidence_Issues.csv")
    simulation_fields, simulations = read_csv(project_dir / "14_Simulated_Modeling_Data.csv")

    issues = require_columns(assumption_fields, ASSUMPTION_REQUIRED)
    issues.extend(require_columns(result_fields, RESULT_REQUIRED))
    issues.extend(require_columns(gap_fields, GAP_REQUIRED))
    issues.extend(require_columns(simulation_fields, SIMULATION_REQUIRED))
    if issues:
        return issues

    if not assumptions and not allow_empty:
        issues.append(Issue("fail", "assumptions", "rows", "Model/insight branch requires at least one assumption or evidence-basis row"))
    if not results and not allow_empty:
        issues.append(Issue("fail", "results", "rows", "Model/insight branch requires at least one result or evidence-synthesis row"))

    for index, row in enumerate(gaps, start=2):
        label = row_label(index, row)
        for field in GAP_REQUIRED:
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required evidence-issue value is blank"))
        if row.get("data_domain", "").strip().lower() != "market":
            issues.append(Issue("fail", label, "data_domain", "Only missing market evidence may be logged in 11_Evidence_Issues.csv; missing modeling inputs must be simulated"))

    assumption_ids: set[str] = set()
    simulated_assumption_ids: set[str] = set()
    for index, row in enumerate(assumptions, start=2):
        label = row_label(index, row)
        assumption_id = row.get("assumption_id", "").strip()
        if assumption_id in assumption_ids:
            issues.append(Issue("fail", label, "assumption_id", f"Duplicate assumption ID: {assumption_id}"))
        assumption_ids.add(assumption_id)
        for field in ("assumption_id", "model_module", "parameter_name", "value_class", "base_value", "unit", "geography", "period", "rationale", "formula_or_use", "confidence", "approval_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required assumption value is blank"))
        value_class = row.get("value_class", "").strip()
        if value_class not in ASSUMPTION_CLASSES:
            issues.append(Issue("fail", label, "value_class", "Use observed, derived, modeled_estimate, scenario_assumption, or simulated; unresolved modeling inputs are not allowed"))
        if value_class in ASSUMPTION_CLASSES and not (row.get("source_ids") or row.get("source_urls")):
            issues.append(Issue("fail", label, "source_ids/source_urls", "Assumption requires supporting or calibration evidence IDs/URLs"))
        if value_class == "simulated":
            simulated_assumption_ids.add(assumption_id)
            if not row.get("low_value") or not row.get("high_value"):
                issues.append(Issue("fail", label, "low_value/high_value", "Simulated inputs require low/base/high bounds or quantiles"))
            if row.get("approval_status", "").strip().lower() not in APPROVED_STATUSES:
                issues.append(Issue("fail", label, "approval_status", "Material simulated-input assumptions require human approval"))

    simulation_ids: set[str] = set()
    linked_simulated_ids: set[str] = set()
    for index, row in enumerate(simulations, start=2):
        label = row_label(index, row)
        for field in SIMULATION_REQUIRED:
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required simulation traceability value is blank"))
        simulation_id = row.get("simulation_id", "").strip()
        if simulation_id in simulation_ids:
            issues.append(Issue("fail", label, "simulation_id", f"Duplicate simulation ID: {simulation_id}"))
        simulation_ids.add(simulation_id)
        assumption_id = row.get("assumption_id", "").strip()
        if assumption_id not in assumption_ids:
            issues.append(Issue("fail", label, "assumption_id", f"Unknown assumption ID: {assumption_id}"))
        elif assumption_id not in simulated_assumption_ids:
            issues.append(Issue("fail", label, "assumption_id", "Simulation row must link to an assumption labeled value_class=simulated"))
        else:
            linked_simulated_ids.add(assumption_id)
        if row.get("value_class", "").strip() != "simulated":
            issues.append(Issue("fail", label, "value_class", "Simulated data must be explicitly labeled simulated and never observed"))
        if row.get("approval_status", "").strip().lower() not in APPROVED_STATUSES:
            issues.append(Issue("fail", label, "approval_status", "Simulation calibration requires human approval"))
        try:
            int(row.get("random_seed", ""))
        except ValueError:
            issues.append(Issue("fail", label, "random_seed", "random_seed must be a fixed integer"))
        try:
            if int(row.get("sample_size", "")) <= 0:
                raise ValueError
        except ValueError:
            issues.append(Issue("fail", label, "sample_size", "sample_size must be a positive integer"))
        lower = _number(row.get("physical_lower_bound", ""))
        upper = _number(row.get("physical_upper_bound", ""))
        if lower is None or upper is None:
            issues.append(Issue("fail", label, "physical_lower_bound/physical_upper_bound", "Physical bounds must be numeric"))
        elif lower > upper:
            issues.append(Issue("fail", label, "physical_lower_bound/physical_upper_bound", "Physical lower bound cannot exceed upper bound"))
        for field in ("generator_code_path", "generated_data_path"):
            value = row.get(field, "").strip()
            if value and not _resolve_artifact(project_dir, value).exists():
                issues.append(Issue("fail", label, field, f"Referenced artifact does not exist: {value}"))
        generator_value = row.get("generator_code_path", "").strip()
        if generator_value and Path(generator_value).suffix.lower() != ".py":
            issues.append(Issue("fail", label, "generator_code_path", "Simulation generator must be a Python .py file"))

    missing_manifests = sorted(simulated_assumption_ids - linked_simulated_ids)
    for assumption_id in missing_manifests:
        issues.append(Issue("fail", assumption_id, "simulation_manifest", "Every simulated assumption must have a traceable row in 14_Simulated_Modeling_Data.csv"))

    for index, row in enumerate(results, start=2):
        label = row_label(index, row)
        for field in ("result_id", "model_module", "scenario", "metric", "value", "unit", "geography", "period", "value_class", "formula_or_method", "excel_formula", "validation_check", "confidence", "verification_status"):
            if not row.get(field):
                issues.append(Issue("fail", label, field, "Required result value is blank"))
        if row.get("value_class", "").strip() not in RESULT_CLASSES:
            issues.append(Issue("fail", label, "value_class", "Results must be labeled derived or modeled_estimate"))
        linked = [item.strip() for item in row.get("input_assumption_ids", "").replace(";", ",").split(",") if item.strip()]
        for item in linked:
            if item not in assumption_ids:
                issues.append(Issue("fail", label, "input_assumption_ids", f"Unknown assumption ID: {item}"))
        if not linked and not row.get("evidence_row_ids"):
            issues.append(Issue("fail", label, "inputs", "Result must reference assumption IDs or evidence row IDs"))
        formula = row.get("excel_formula", "").strip()
        if formula and not formula.startswith("="):
            issues.append(Issue("fail", label, "excel_formula", "Excel formula must begin with '='"))
        formula_assumptions = {match.group(1).strip() for match in ASSUMPTION_TOKEN_RE.finditer(formula)}
        for assumption_id in sorted(formula_assumptions):
            if assumption_id not in assumption_ids:
                issues.append(Issue("fail", label, "excel_formula", f"Formula token references unknown assumption ID: {assumption_id}"))
            elif assumption_id not in linked:
                issues.append(Issue("fail", label, "excel_formula", f"Formula token assumption is missing from input_assumption_ids: {assumption_id}"))
        if formula and not formula_assumptions and "!" not in formula:
            issues.append(Issue("fail", label, "excel_formula", "Formula must use assumption tokens or an explicit workbook cell reference"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate model inputs, realistic simulation traceability, formulas, and result checks.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--allow-empty", action="store_true")
    add_common_args(parser)
    args = parser.parse_args()
    return print_report("Model integrity validation", validate(Path(args.project_dir).resolve(), allow_empty=args.allow_empty), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
