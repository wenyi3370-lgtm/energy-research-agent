from __future__ import annotations

"""离线回归：数学建模链内嵌（G1-G6 机械门 + 12/13/14 完整性 + 决策工件防伪造）。

临时项目构造 intermediate/modeling/ 工作区，覆盖：
- 通过场景：完整工件 → G1/G2/G3/G2.5/G4/G4.5/G6 全 PASS
- 失败场景：缺 parse / 候选不足 / review<5 / decided_by=ai / frozen 过期 / 缺审计
- 12/13/14：create_modeling_artifacts 生成 + validate_model_integrity 通过
"""
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import write_csv  # noqa: E402
from create_modeling_artifacts import modeling_root  # noqa: E402

DECISION_TEMPLATE = """---
schema_version: 1
skill: {skill}
scope: Q1
decision_id: {decision_id}
decision_point: {decision_point}
status: {status}
decided_by: {decided_by}
decided_at: 2026-08-10T10:00:00+08:00
ai_suggestion: candidate A
choice: candidate A
rejected_alternatives: []
confidence: 0.8
evidence_refs:
  - methods/Q1/qx_decision_log.md
---

## Modeler's rationale

{rationale}
"""

CANDIDATES = """# Q1 Method Candidates

## Candidate 1
- **method**: bottom-up sizing
- **PoC (<=30 lines)**: prototype computes installed base x price
- feasibility: 0.9

## Candidate 2
- **method**: regression on historical growth
- **PoC (<=30 lines)**: linear fit prototype
- feasibility: 0.7

## Candidate 3
- **method**: Monte Carlo scenario
- **PoC (<=30 lines)**: 100-path prototype
- feasibility: 0.8

## Baseline
- baseline model: price-per-kWh x installed base, no storage
"""

REVIEW_6_PASS = """# Q1 Python Code Review

1. PASS - module imports verified
2. PASS - input parsing validated
3. PASS - core loop correct
4. PASS - units consistent
5. PASS - error handling present
6. PASS - output schema matches
"""

REVIEW_3_PASS = """# Q1 Python Code Review

1. PASS - imports ok
2. PASS - loop ok
3. PASS - units ok
- WARN - missing error handling
- WARN - output schema unverified
"""

FROZEN = {
    "numbers": {
        "tam_mwh": {"value": 5000, "unit": "MWh", "scenario": "base",
                    "assumption_ids": "A-Q1-001", "excel_formula": "={{assumption:A-Q1-001:base}}*1000"},
    },
    "geography": "Thailand", "period": "2030",
    "formula_or_method": "bottom-up sizing",
    "robustness_pass": True, "confidence": "0.8",
    "interpretation": "TAM estimate under base assumptions",
}


def build_workspace(project: Path, *, frozen_old: bool = False, audit_present: bool = True) -> Path:
    root = modeling_root(project)
    # 建模分支项目 manifest（branch=modeling 才启用链门禁）
    (project / "project_manifest.json").write_text(
        json.dumps({"region": "Thailand", "category": "BESS", "analysis_branch": "modeling"}), encoding="utf-8"
    )
    (root / "planning" / "parse").mkdir(parents=True, exist_ok=True)
    (root / "planning" / "classification").mkdir(parents=True, exist_ok=True)
    (root / "methods" / "Q1" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "code" / "Q1" / "reviews").mkdir(parents=True, exist_ok=True)
    (root / "results" / "Q1" / "experiments" / "round1").mkdir(parents=True, exist_ok=True)
    (root / "results" / "Q1" / "reports").mkdir(parents=True, exist_ok=True)

    (root / "planning" / "parse" / "parse.md").write_text("# Q1 Parse\n\nGoal: TAM for Thailand residential BESS.\n", encoding="utf-8")
    (root / "planning" / "classification" / "classification.md").write_text("# Q1 Classification\n\nType: forecasting/estimation.\n", encoding="utf-8")
    # 真实项目由 init 生成 11 表；测试夹具补齐（validate_model_integrity 读取并按 GAP_REQUIRED 校验）
    write_csv(project / "11_Evidence_Issues.csv", ["issue_id", "issue_type", "data_domain", "reason", "status"])
    (root / "planning" / "model_assumptions.md").write_text(
        "| assumption_id | model_module | parameter_symbol | parameter_name | value_class | low_value | base_value | high_value | unit | geography | period | rationale | formula_or_use | source_ids | source_urls | confidence | approval_status |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| A-Q1-001 | Q1 | cap_price | capital price per kWh | observed | 400 | 500 | 600 | USD/kWh | Thailand | 2030 | calibrated from retail quotes | price_per_kwh = cap_price | S001 | https://example.com/price | 0.8 | pending |\n",
        encoding="utf-8",
    )

    (root / "methods" / "Q1" / "qx_method_candidates.md").write_text(CANDIDATES, encoding="utf-8")
    decisions = [
        ("method-selector", "qx_method_choice", "method_choice", "candidate A chosen by human"),
        ("result-report-generator", "qx_result_verdict", "result_verdict", "round decision: proceed"),
        ("robustness-checker", "qx_stability_verdict", "confidence", "robust within +/-10%"),
        ("final-method-explainer", "qx_method_explanation", "claim_scope", "method explanation approved"),
        ("solution-package-builder", "qx_package_signoff", "figure_role", "package signed off"),
    ]
    for skill, decision_id, point, rationale in decisions:
        (root / "methods" / "Q1" / "decisions" / f"{skill}_modeler_decision.md").write_text(
            DECISION_TEMPLATE.format(skill=skill, decision_id=decision_id, decision_point=point,
                                     status="DECIDED", decided_by="human", rationale=rationale),
            encoding="utf-8",
        )

    (root / "code" / "Q1" / "reviews" / "qx_python_review.md").write_text(REVIEW_6_PASS, encoding="utf-8")
    (root / "results" / "Q1" / "experiments" / "round1" / "run_summary.json").write_text(
        json.dumps({"round": 1, "status": "completed", "metrics": {"tam_mwh": 5000}}), encoding="utf-8"
    )

    frozen = dict(FROZEN)
    code_mtime = max(p.stat().st_mtime for p in (root / "code" / "Q1").rglob("*") if p.is_file())
    frozen_at = datetime.fromtimestamp(code_mtime + 60) if not frozen_old else datetime.fromtimestamp(code_mtime - 3600)
    frozen["frozen_at"] = frozen_at.isoformat(timespec="seconds")
    (root / "results" / "Q1" / "reports" / "frozen_numbers.json").write_text(json.dumps(frozen, ensure_ascii=False), encoding="utf-8")

    if audit_present:
        audit_dir = root / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("consistency.md", "completeness.md", "quality_assurance.md"):
            (audit_dir / filename).write_text(f"# {filename}\n\nverdict: PASSED\n", encoding="utf-8")
    return root


def test_full_chain_passes() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_ok_") as tmp:
        project = Path(tmp)
        build_workspace(project)
        issues = gates_validate(project)
        fails = [i for i in issues if i.level == "fail"]
        if fails:
            raise AssertionError(f"full chain must pass, got: {[i.message for i in fails]}")
        # 12/13/14 完整性：真实生成 + validate_model_integrity 通过
        subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "create_modeling_artifacts.py"), "--project-dir", str(project)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        from validate_model_integrity import validate as integrity_validate

        integrity_issues = integrity_validate(project)
        fails = [i for i in integrity_issues if i.level == "fail"]
        if fails:
            raise AssertionError(f"model integrity must pass, got: {[i.message for i in fails]}")
        for artifact in ("12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"):
            if not (project / artifact).is_file():
                raise AssertionError(f"{artifact} not generated")
        print("  [1/7] full chain G1-G6 + 12/13/14 integrity: PASS")


def test_g1_missing_parse() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    import shutil

    with tempfile.TemporaryDirectory(prefix="mchain_g1_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        shutil.rmtree(root / "planning" / "parse")
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G1" for i in issues):
            raise AssertionError("missing planning/parse must fail G1")
        print("  [2/7] G1 missing parse/classification -> FAIL: PASS")


def test_g2_insufficient_candidates() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g2_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (root / "methods" / "Q1" / "qx_method_candidates.md").write_text(
            "# Q1 Method Candidates\n\n## Candidate 1\n- PoC: prototype\n- feasibility: 0.9\n\n## Baseline\n- baseline: linear\n",
            encoding="utf-8",
        )
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G2" and "expected 2-4" in i.message for i in issues):
            raise AssertionError("single candidate must fail G2")
        print("  [3/7] G2 insufficient candidates -> FAIL: PASS")


def test_g3_insufficient_review() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g3_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (root / "code" / "Q1" / "reviews" / "qx_python_review.md").write_text(REVIEW_3_PASS, encoding="utf-8")
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G3" and "<5" in i.message for i in issues):
            raise AssertionError("review with <5 pass items must fail G3")
        print("  [4/7] G3 review <5 pass items -> FAIL: PASS")


def test_g25_ai_self_approval() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g25_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        decision = root / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md"
        decision.write_text(
            DECISION_TEMPLATE.format(skill="method-selector", decision_id="qx_method_choice",
                                     decision_point="method_choice", status="DECIDED",
                                     decided_by="ai", rationale="I the AI chose candidate A"),
            encoding="utf-8",
        )
        issues = gates_validate(project)
        if not any(i.level == "fail" and "decided_by='ai'" in i.message for i in issues):
            raise AssertionError(f"decided_by=ai must fail the human gate: {[i.message for i in issues if i.level=='fail']}")
        print("  [5/7] G2.5 AI self-approval (decided_by=ai) -> FAIL: PASS")


def test_g4_stale_frozen() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g4_") as tmp:
        project = Path(tmp)
        build_workspace(project, frozen_old=True)
        issues = gates_validate(project)
        if not any(i.level == "fail" and "frozen_at older" in i.message for i in issues):
            raise AssertionError("stale frozen_at must fail G4")
        print("  [6/7] G4 stale frozen_numbers -> FAIL: PASS")


def test_g6_missing_audit() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g6_") as tmp:
        project = Path(tmp)
        build_workspace(project, audit_present=False)
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G6" for i in issues):
            raise AssertionError("missing audit verdicts must fail G6")
        print("  [7/7] G6 missing audit PASSED -> FAIL: PASS")


def test_no_workspace_is_note() -> None:
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_none_") as tmp:
        project = Path(tmp)
        issues = gates_validate(project)
        if any(i.level == "fail" for i in issues):
            raise AssertionError("no workspace must not fail")
        if not any(i.level == "note" for i in issues):
            raise AssertionError("no workspace must emit a note")
        print("  [8/8] no modeling workspace -> note (not failure): PASS")


def test_g6_not_passed_must_fail() -> None:
    """假绿反例：审计文件写 'NOT PASSED' 必须 FAIL。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g6neg_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (root / "audit" / "consistency.md").write_text("## Verdict\n\nNOT PASSED - symbols inconsistent\n", encoding="utf-8")
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G6" and "PASSED verdict" in i.message for i in issues):
            raise AssertionError("'NOT PASSED' audit must fail G6 (false-green guard)")
        print("  [9/12] G6 'NOT PASSED' verdict -> FAIL (false-green guard): PASS")


def test_g3_not_pass_lines_must_fail() -> None:
    """假绿反例：评审含 NOT PASS/FAIL 行不得计为 pass 项。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g3neg_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (root / "code" / "Q1" / "reviews" / "qx_python_review.md").write_text(
            "1. NOT PASS - imports broken\n2. PASS - loop ok\n3. PASS - units ok\n4. PASS - output ok\n5. FAIL - error handling\n",
            encoding="utf-8",
        )
        issues = gates_validate(project)
        if not any(i.level == "fail" and i.row == "G3" and "pass items" in i.message for i in issues):
            raise AssertionError("NOT PASS/FAIL lines must not count as pass items (false-green guard)")
        print("  [10/12] G3 NOT PASS/FAIL lines -> FAIL (false-green guard): PASS")


def test_g2_subsection_headings_not_overcounted() -> None:
    """反例：候选带 pros/cons 小节（'### Candidate 1 feasibility'）不得重复计数误报。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_g2sub_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (root / "methods" / "Q1" / "qx_method_candidates.md").write_text(
            "# Q1 Method Candidates\n\n"
            "## Candidate 1\n- PoC: prototype A\n- feasibility: 0.9\n"
            "### Candidate 1 feasibility\n- data: quotes\n"
            "### Candidate 1 risks\n- none\n"
            "## Candidate 2\n- PoC: prototype B\n- feasibility: 0.7\n"
            "## Baseline\n- baseline: linear\n",
            encoding="utf-8",
        )
        issues = gates_validate(project)
        if any(i.level == "fail" and i.row == "G2" and "expected 2-4" in i.message for i in issues):
            raise AssertionError("subsection headings must not overcount candidates (false-positive guard)")
        print("  [11/12] G2 subsection headings not overcounted -> PASS (false-positive guard): PASS")


def test_crlf_decisions_and_gate_dispatch() -> None:
    """CRLF 决策工件可解析 + G2.5/G4.5 按 decision_id 分派（不串门）。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_crlf_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        # Q1 的 result_verdict 改为 decided_by=ai（G4.5 应 FAIL），method_choice 保持 human
        verdict = root / "methods" / "Q1" / "decisions" / "result-report-generator_modeler_decision.md"
        crlf_text = DECISION_TEMPLATE.format(skill="result-report-generator", decision_id="qx_result_verdict",
                                             decision_point="result_verdict", status="DECIDED",
                                             decided_by="ai", rationale="I the AI judged").replace("\n", "\r\n")
        verdict.write_text(crlf_text, encoding="utf-8")  # CRLF 保存（Windows 编辑器场景）
        (root / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md").write_bytes(
            (root / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md").read_bytes().replace(b"\n", b"\r\n")
        )
        issues = gates_validate(project)
        g25_fails = [i for i in issues if i.level == "fail" and i.row == "G2.5"]
        g45_fails = [i for i in issues if i.level == "fail" and i.row == "G4.5"]
        if g25_fails:
            raise AssertionError(f"G2.5 must not fail when only the verdict artifact is bad (gate dispatch): {[i.message for i in g25_fails]}")
        if not any("decided_by='ai'" in i.message for i in g45_fails):
            raise AssertionError("G4.5 must catch the verdict decided_by=ai even with CRLF artifacts")
        print("  [12/12] CRLF artifacts parse + G2.5/G4.5 decision-id dispatch: PASS")


def test_draft_vs_final_pending() -> None:
    """draft：PENDING 决策 warn；final：升为 fail。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_mode_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        decision = root / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md"
        decision.write_text(
            DECISION_TEMPLATE.format(skill="method-selector", decision_id="qx_method_choice",
                                     decision_point="method_choice", status="PENDING",
                                     decided_by="human", rationale="under review"),
            encoding="utf-8",
        )
        draft_issues = gates_validate(project, mode="draft")
        if any(i.level == "fail" and i.row == "G2.5" for i in draft_issues):
            raise AssertionError("draft mode must keep PENDING as warn")
        final_issues = gates_validate(project, mode="final")
        if not any(i.level == "fail" and i.row == "G2.5" and "final mode" in i.message for i in final_issues):
            raise AssertionError("final mode must fail PENDING human gates")
        print("  [13/13] draft=PENDING warn / final=PENDING fail: PASS")


def test_missing_manifest_is_auto() -> None:
    """缺 manifest → 视为 auto（建模未启用），不误报门禁。"""
    from validate_modeling_chain_gates import validate as gates_validate

    with tempfile.TemporaryDirectory(prefix="mchain_manifest_") as tmp:
        project = Path(tmp)
        root = build_workspace(project)
        (project / "project_manifest.json").unlink()
        issues = gates_validate(project)
        if any(i.level == "fail" for i in issues):
            raise AssertionError("missing manifest must default to auto (not engaged)")
        print("  [14/14] missing manifest -> auto note (not failure): PASS")


def main() -> int:
    print("Modeling chain embed regression:")
    test_full_chain_passes()
    test_g1_missing_parse()
    test_g2_insufficient_candidates()
    test_g3_insufficient_review()
    test_g25_ai_self_approval()
    test_g4_stale_frozen()
    test_g6_missing_audit()
    test_no_workspace_is_note()
    test_g6_not_passed_must_fail()
    test_g3_not_pass_lines_must_fail()
    test_g2_subsection_headings_not_overcounted()
    test_crlf_decisions_and_gate_dispatch()
    test_draft_vs_final_pending()
    test_missing_manifest_is_auto()
    print("Modeling chain embed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
