from __future__ import annotations

"""
Generate 12_Model_Assumptions.csv / 13_Model_Results.csv /
14_Simulated_Modeling_Data.csv from the modeling workspace
(intermediate/modeling/) and mechanically validate the human decision artifacts.

The modeling workspace follows references/modeling-chain-adaptation.md (single source of
truth). 12/13/14 CSV are the only handoff to the evidence workflow; this script is their
SOLE writer - never hand-edit them.

Exit codes: 0 = ok (warnings allowed in dry-run mode), 1 = validation failures.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from _common import now_iso, read_csv, write_csv


DECISION_IDS = {
    "qx_method_choice",
    "qx_result_verdict",
    "qx_stability_verdict",
    "qx_method_explanation",
    "qx_package_signoff",
}
DECISION_SKILLS = {
    "method-selector",
    "result-report-generator",
    "robustness-checker",
    "final-method-explainer",
    "solution-package-builder",
}
SENTINELS = ("[AI-DRAFT", "[MODELER INPUT NEEDED", "<<<HUMAN>>>")


def modeling_root(project_dir: Path) -> Path:
    return project_dir / "intermediate" / "modeling"


def find_decision_artifacts(root: Path) -> list[Path]:
    decisions = root / "methods"
    if not decisions.exists():
        return []
    return sorted(decisions.glob("Q*/decisions/*_modeler_decision.md"))


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")  # utf-8-sig: Windows BOM 容错
    text = text.replace("\r\n", "\n")  # CRLF 容错（Windows 编辑器）
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    data = {}
    for line in m.group(1).splitlines():
        if line.startswith(("- ", "  ")) or not line.strip():
            continue  # 跳过数组元素/缩进行（如多行 evidence_refs）
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


def validate_decisions(root: Path, decision_ids: set[str] | None = None) -> list[tuple[str, str]]:
    """Return [(level, message)] where level in {fail, warn}.

    decision_ids 可选过滤：None=全部（向后兼容）；传集合时只检查指定 decision_id
    （供 G2.5 只查 qx_method_choice、G4.5 只查三个 verdict 使用）。
    """
    issues: list[tuple[str, str]] = []
    artifacts = find_decision_artifacts(root)
    for path in artifacts:
        fm = parse_frontmatter(path)
        label = str(path.relative_to(root))
        skill = fm.get("skill", "")
        decision_id = fm.get("decision_id", "")
        if decision_ids is not None and decision_id not in decision_ids:
            continue
        if skill not in DECISION_SKILLS:
            issues.append(("fail", f"{label}: unknown skill {skill!r}"))
        if decision_id not in DECISION_IDS:
            issues.append(("fail", f"{label}: unknown decision_id {decision_id!r}"))
        status = fm.get("status", "")
        decided_by = fm.get("decided_by", "")
        if status != "DECIDED":
            issues.append(("warn", f"{label}: status={status!r} (not DECIDED) - human gate open"))
        if decided_by != "human":
            issues.append(("fail", f"{label}: decided_by={decided_by!r} (must be human)"))
        text = path.read_text(encoding="utf-8")
        for sentinel in SENTINELS:
            if sentinel in text:
                issues.append(("fail", f"{label}: sentinel {sentinel!r} still present"))
        rationale = ""
        if "## Modeler's rationale" in text:
            rationale = text.split("## Modeler's rationale", 1)[1].strip()
        if status == "DECIDED" and not rationale:
            issues.append(("fail", f"{label}: DECIDED but Modeler's rationale is empty"))
        if status == "DECIDED" and rationale and rationale.strip().startswith(("AI", "The AI")):
            issues.append(("warn", f"{label}: rationale looks AI-authored, verify human authorship"))
        if status == "DECIDED":
            # 机械有效性第 4 条：引用 evidence_refs token（adaptation 文档承诺）
            if "evidence_refs:" not in text:
                issues.append(("fail", f"{label}: DECIDED but missing evidence_refs section"))
            ai_suggestion = fm.get("ai_suggestion", "").strip()
            if rationale and ai_suggestion and rationale.strip() == ai_suggestion.strip():
                issues.append(("fail", f"{label}: rationale is a verbatim copy of ai_suggestion"))
    return issues


def check_frozen_freshness(root: Path) -> list[tuple[str, str]]:
    """frozen_at must be newer than referenced code mtime (Frozen Numbers Convention)."""
    issues: list[tuple[str, str]] = []
    for frozen in sorted((root / "results").glob("Q*/reports/frozen_numbers.json")):
        try:
            data = json.loads(frozen.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append(("warn", f"{frozen}: unreadable frozen_numbers.json"))
            continue
        frozen_at = data.get("frozen_at", "")
        if not frozen_at:
            issues.append(("warn", f"{frozen}: missing frozen_at"))
            continue
        qx = frozen.parent.parent.name
        code_dir = root / "code" / qx
        if code_dir.exists():
            latest = max((p.stat().st_mtime for p in code_dir.rglob("*") if p.is_file()), default=0)
            if latest > 0:
                try:
                    import datetime
                    frozen_ts = datetime.datetime.fromisoformat(frozen_at).timestamp()
                    if frozen_ts < latest:
                        issues.append(("fail", f"{frozen}: frozen_at older than code mtime - unfreeze, fix, re-freeze"))
                except ValueError:
                    issues.append(("warn", f"{frozen}: frozen_at not ISO parseable"))
    return issues


def read_assumptions_md(root: Path) -> list[dict]:
    """Parse planning/model_assumptions.md rows (best-effort markdown table)."""
    md_path = root / "planning" / "model_assumptions.md"
    rows: list[dict] = []
    if not md_path.exists():
        return rows
    lines = md_path.read_text(encoding="utf-8").splitlines()
    headers: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and not stripped.replace("|", "").replace("-", "").replace(" ", "").replace(":", ""):
            continue  # separator row
        cells = [c.strip() for c in stripped.strip("|").split("|")] if stripped.startswith("|") else []
        if not headers and cells:
            headers = cells
        elif headers and cells:
            row = dict(zip(headers, cells))
            if any(row.values()):
                rows.append(row)
    return rows


def build_assumptions_csv(project_dir: Path, root: Path) -> int:
    header = [
        "assumption_id", "model_module", "parameter_symbol", "parameter_name", "value_class",
        "low_value", "base_value", "high_value", "unit", "geography", "period", "rationale",
        "formula_or_use", "source_ids", "source_urls", "confidence", "owner", "approval_status", "notes",
    ]
    rows = []
    for i, row in enumerate(read_assumptions_md(root), start=1):
        qx = row.get("model_module") or row.get("Qx") or row.get("scope") or "Q1"
        rows.append({
            "assumption_id": row.get("assumption_id") or f"A-{qx}-{i:03d}",
            "model_module": qx,
            "parameter_symbol": row.get("parameter_symbol", row.get("symbol", "")),
            "parameter_name": row.get("parameter_name", row.get("name", "")),
            "value_class": row.get("value_class", "scenario_assumption"),
            "low_value": row.get("low_value", row.get("low", "")),
            "base_value": row.get("base_value", row.get("base", "")),
            "high_value": row.get("high_value", row.get("high", "")),
            "unit": row.get("unit", ""),
            "geography": row.get("geography", ""),
            "period": row.get("period", ""),
            "rationale": row.get("rationale", row.get("description", "")),
            "formula_or_use": row.get("formula_or_use", row.get("formula", "")),
            "source_ids": row.get("source_ids", ""),
            "source_urls": row.get("source_urls", ""),
            "confidence": row.get("confidence", ""),
            "owner": row.get("owner", "modeler"),
            "approval_status": row.get("approval_status", "pending"),
            "notes": "mapped_from: intermediate/modeling/planning/model_assumptions.md",
        })
    write_csv(project_dir / "12_Model_Assumptions.csv", header, rows)
    return len(rows)


def build_results_csv(project_dir: Path, root: Path) -> int:
    header = [
        "result_id", "model_module", "scenario", "metric", "value", "unit", "geography", "period",
        "value_class", "formula_or_method", "excel_formula", "input_assumption_ids", "evidence_row_ids",
        "validation_check", "sensitivity_or_uncertainty", "confidence", "interpretation",
        "verification_status", "notes",
    ]
    rows = []
    for frozen in sorted((root / "results").glob("Q*/reports/frozen_numbers.json")):
        qx = frozen.parent.parent.name
        try:
            data = json.loads(frozen.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        numbers = data.get("numbers", data)
        if not isinstance(numbers, dict):
            numbers = {"result": data}
        for i, (metric, item) in enumerate(numbers.items(), start=1):
            if isinstance(item, dict):
                value = item.get("value", "")
                unit = item.get("unit", "")
                scenario = item.get("scenario", "base")
                excel_formula = item.get("excel_formula", "")
                assumption_ids = item.get("assumption_ids") or item.get("input_assumption_ids") or data.get("assumption_ids") or data.get("input_assumption_ids", "")
                evidence_ids = item.get("evidence_row_ids") or data.get("evidence_row_ids", "")
                sensitivity = item.get("sensitivity", "")
            else:
                value = item
                unit = data.get("unit", "")
                scenario = data.get("scenario", "base")
                excel_formula = ""
                assumption_ids = data.get("assumption_ids") or data.get("input_assumption_ids", "")
                evidence_ids = data.get("evidence_row_ids", "")
                sensitivity = ""
            rows.append({
                "result_id": data.get(f"result_id_{metric}") or f"R-{qx}-{i:03d}",
                "model_module": qx,
                "scenario": scenario,
                "metric": metric,
                "value": value,
                "unit": unit,
                "geography": data.get("geography", ""),
                "period": data.get("period", ""),
                "value_class": "modeled_estimate",
                "formula_or_method": data.get("formula_or_method", ""),
                "excel_formula": excel_formula,
                "input_assumption_ids": assumption_ids,
                "evidence_row_ids": evidence_ids,
                "validation_check": data.get("validation_check", "robustness_pass" if data.get("robustness_pass") else "pending"),
                "sensitivity_or_uncertainty": sensitivity,
                "confidence": data.get("confidence", ""),
                "interpretation": data.get("interpretation", ""),
                "verification_status": "verified" if data.get("robustness_pass") else "pending_verification",
                "notes": f"mapped_from: {frozen.relative_to(root).as_posix()}",
            })
    write_csv(project_dir / "13_Model_Results.csv", header, rows)
    return len(rows)


def build_simulated_data_csv(project_dir: Path, root: Path) -> int:
    """Copy the canonical simulation manifest produced by modeling code into artifact 14.

    The actual generated samples remain at generated_data_path. This manifest records
    calibration, physical constraints, seed, generator code, validation and uncertainty.
    """
    header = [
        "simulation_id", "assumption_id", "model_module", "variable", "geography", "period", "unit",
        "simulation_method", "distribution_or_process", "calibration_source_ids", "calibration_source_urls",
        "calibration_parameters", "physical_lower_bound", "physical_upper_bound",
        "correlation_or_time_structure", "random_seed", "sample_size", "generator_code_path",
        "generated_data_path", "validation_method", "validation_result", "sensitivity_or_uncertainty",
        "value_class", "approval_status", "notes",
    ]
    source = root / "workspace" / "data" / "simulated_modeling_data.csv"
    rows: list[dict[str, str]] = []
    if source.exists():
        source_fields, rows = read_csv(source)
        missing = [field for field in header if field not in source_fields]
        if missing:
            raise ValueError(f"Simulation manifest missing required columns: {missing}")
    write_csv(project_dir / "14_Simulated_Modeling_Data.csv", header, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 12/13/14 CSV from modeling workspace and validate human decision gates.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write 12/13/14 CSV.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    root = modeling_root(project_dir)

    if not root.exists():
        msg = f"Modeling workspace not found: {root} (init with --analysis-branch modeling)"
        print(("JSON: " if args.json else "") + json.dumps({"status": "warn", "message": msg}, ensure_ascii=False))
        return 0 if args.dry_run else 0  # workspace absent is not a gate failure for evidence workflow

    issues = validate_decisions(root)
    issues.extend(check_frozen_freshness(root))
    fails = [m for lvl, m in issues if lvl == "fail"]
    warns = [m for lvl, m in issues if lvl == "warn"]

    if args.dry_run:
        print(f"Decision artifacts: {len(find_decision_artifacts(root))}")
        print(f"Warnings: {len(warns)}")
        for m in warns:
            print(f"  [warn] {m}")
        print(f"Failures: {len(fails)}")
        for m in fails:
            print(f"  [fail] {m}")
        return 1 if fails else 0

    n_assump = build_assumptions_csv(project_dir, root)
    n_results = build_results_csv(project_dir, root)
    try:
        n_simulated = build_simulated_data_csv(project_dir, root)
    except ValueError as exc:
        print(f"[fail] {exc}")
        return 1
    print(
        f"Wrote 12_Model_Assumptions.csv ({n_assump} rows), "
        f"13_Model_Results.csv ({n_results} rows), "
        f"14_Simulated_Modeling_Data.csv ({n_simulated} rows)"
    )

    # Final self-check against the evidence-workflow validator.
    from validate_model_integrity import validate as validate_integrity
    from _common import Issue
    integrity = validate_integrity(project_dir, allow_empty=(n_assump == 0 and n_results == 0 and n_simulated == 0))
    integrity_fails = [i for i in integrity if i.level == "fail"]
    print(f"Model integrity: {len(integrity_fails)} fail(s)")
    for i in integrity_fails:
        print(f"  [{i.level}] {i.row or '-'} {i.field} - {i.message}")
    return 1 if (fails or integrity_fails) else 0


if __name__ == "__main__":
    raise SystemExit(main())
