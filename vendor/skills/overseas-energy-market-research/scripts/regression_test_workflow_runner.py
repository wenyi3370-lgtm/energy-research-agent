from __future__ import annotations

"""离线回归：run_workflow 单入口（--all 一键总流程 / --collect / --modeling / --dry-run）。

- dry-run 序列断言：--all --dry-run 输出包含全部步骤；
- 无网络小流程：init -> check -> modeling(auto skip) -> audit 在临时项目上真实执行；
- 建模分支：analysis_branch=modeling + 完整工作区 -> --modeling 生成 12/13/14；
  人工门未决 -> --modeling 输出待决 warn 不崩溃。
"""
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import read_csv, write_csv  # noqa: E402
import regression_test_modeling_chain as modeling_fixtures  # noqa: E402


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS_DIR / "run_workflow.py"), *args], capture_output=True, text=True, timeout=300)


def test_all_dry_run_sequence() -> None:
    with tempfile.TemporaryDirectory(prefix="runner_seq_") as tmp:
        project = Path(tmp) / "proj"
        completed = _run(
            [
                "--all", "--dry-run",
                "--project-dir", str(project),
                "--region", "Thailand",
                "--category", "BESS",
                "--analysis-branch", "modeling",
            ]
        )
        output = completed.stdout
        for expected in (
            "initialize project",
            "validate stage gates 0-4",
            "collect",
            "modeling",
            "build evidence audit",
        ):
            if expected not in output:
                raise AssertionError(f"--all --dry-run output missing step: {expected}")
        if "DRY-RUN" not in output:
            raise AssertionError("--all --dry-run must mark steps as DRY-RUN")
        print("  [1/4] --all --dry-run step sequence + DRY-RUN markers: PASS")


def test_offline_flow_init_check_modeling_audit() -> None:
    """无网络小流程：init -> check(0-4) -> modeling(auto skip) -> audit 不崩溃。"""
    with tempfile.TemporaryDirectory(prefix="runner_flow_") as tmp:
        project = Path(tmp) / "proj"
        init = _run(["--init", "--project-dir", str(project), "--region", "Thailand", "--category", "BESS", "--stages", "0-4"])
        if init.returncode != 0:
            raise AssertionError(f"init failed: {init.stdout[-500:]}")
        check = _run(["--check", "--project-dir", str(project), "--stages", "0-4", "--mode", "draft", "--local-files-provided", "no"])
        if check.returncode == 0:
            raise AssertionError("stage 0-4 check should FAIL on unsaturated collection (expected quantity gates)")
        modeling = _run(["--modeling", "--project-dir", str(project)])
        if modeling.returncode != 0:
            raise AssertionError(f"modeling (auto branch) must not fail: {modeling.stdout[-300:]}")
        if "analysis_branch" not in modeling.stdout:
            raise AssertionError("modeling on auto branch must report skip reason")
        audit = _run(["--audit", "--project-dir", str(project), "--local-files-provided", "no"])
        # audit 退出码反映审计结果（未饱和项目 FAIL=1 属预期）；关键是报告文件生成且不崩溃
        if not (project / "evidence_audit_report.md").is_file():
            raise AssertionError(f"audit report not generated: {audit.stdout[-300:]}")
        print("  [2/4] offline flow (init/check/modeling-skip/audit) executes cleanly: PASS")


def test_modeling_branch_generates_artifacts() -> None:
    with tempfile.TemporaryDirectory(prefix="runner_model_") as tmp:
        project = Path(tmp) / "proj"
        project.mkdir(parents=True)
        modeling_fixtures.build_workspace(project)  # analysis_branch=modeling + 完整工作区
        # 补齐 02 表与 11 表（create_modeling_artifacts 之外不需要；但 run_workflow --modeling 只跑 gates + artifacts）
        modeling = _run(["--modeling", "--project-dir", str(project)])
        if modeling.returncode != 0:
            raise AssertionError(f"--modeling must pass on complete workspace: {modeling.stdout[-500:]}")
        for artifact in ("12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"):
            if not (project / artifact).is_file():
                raise AssertionError(f"--modeling did not generate {artifact}")
        print("  [3/4] --modeling generates 12/13/14 on complete modeling branch: PASS")


def test_modeling_human_gate_pending() -> None:
    with tempfile.TemporaryDirectory(prefix="runner_gate_") as tmp:
        project = Path(tmp) / "proj"
        project.mkdir(parents=True)
        modeling_fixtures.build_workspace(project)
        # 人工门未决：method_choice 置 PENDING（draft 模式 warn，gates 不 fail，但 artifacts 不生成？）
        decision = modeling_fixtures.modeling_root(project) / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md"
        decision.write_text(
            modeling_fixtures.DECISION_TEMPLATE.format(
                skill="method-selector", decision_id="qx_method_choice", decision_point="method_choice",
                status="PENDING", decided_by="human", rationale="under review",
            ),
            encoding="utf-8",
        )
        modeling = _run(["--modeling", "--project-dir", str(project)])
        # draft 模式 PENDING 是 warn：gates 应仍 PASS(0 fail)，artifacts 照常生成（draft 不强制）
        if modeling.returncode != 0:
            raise AssertionError(f"--modeling must not fail on draft PENDING: {modeling.stdout[-400:]}")
        print("  [4/4] --modeling handles PENDING human gate (draft) without crash: PASS")




def test_collect_blocked_stops_pipeline() -> None:
    """FIX round-2 6.1/6.2: collect BLOCKED must stop the pipeline.

    (a) --collect alone on a project whose task file is missing -> BLOCKED,
        exit != 0;
    (b) --all on an uninitialized/un-saturated project must not reach
        build-final-report or audit (stage gate halts the chain).
    """
    with tempfile.TemporaryDirectory(prefix="runner_blocked_") as tmp:
        project = Path(tmp) / "proj"
        init = _run(["--init", "--project-dir", str(project), "--region", "Thailand",
                     "--category", "BESS", "--stages", "0-4"])
        if init.returncode != 0:
            raise AssertionError("init failed: %s" % init.stdout[-300:])
        (project / "02_Web_Collection_Tasks.csv").unlink()
        collect = _run(["--collect", "--project-dir", str(project)])
        if collect.returncode == 0:
            raise AssertionError("--collect must exit != 0 when the task file is missing")
        if "[BLOCKED] collect" not in collect.stdout:
            raise AssertionError("expected [BLOCKED] collect, got: %s" % collect.stdout[-300:])
        # --all: check/collect stage must halt before build/audit
        project2 = Path(tmp) / "proj2"
        all_run = _run(["--all", "--project-dir", str(project2),
                        "--region", "Thailand", "--category", "BESS", "--stages", "0-4"])
        if all_run.returncode == 0:
            raise AssertionError("--all on an un-saturated project must exit != 0")
        if "build final report" in all_run.stdout or "build evidence audit" in all_run.stdout:
            raise AssertionError("--all must not reach build/audit after a halted stage")
        print("  [5/7] collect BLOCKED stops the pipeline (exit!=0, no build/audit): PASS")


def test_final_mode_pending_human_gate() -> None:
    """FIX round-2 5.1/6.2: mode=final + PENDING human gate -> PENDING_HUMAN,
    exit=3, NO final artifacts generated, pipeline paused."""
    with tempfile.TemporaryDirectory(prefix="runner_finalgate_") as tmp:
        project = Path(tmp) / "proj"
        project.mkdir(parents=True)
        modeling_fixtures.build_workspace(project)
        for artifact in ("12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"):
            (project / artifact).unlink(missing_ok=True)
        decision = modeling_fixtures.modeling_root(project) / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md"
        decision.write_text(
            modeling_fixtures.DECISION_TEMPLATE.format(
                skill="method-selector", decision_id="qx_method_choice", decision_point="method_choice",
                status="PENDING", decided_by="human", rationale="under review",
            ),
            encoding="utf-8",
        )
        modeling = _run(["--modeling", "--project-dir", str(project), "--mode", "final"])
        if modeling.returncode != 3:
            raise AssertionError("final+PENDING must exit 3 (PENDING_HUMAN), got rc=%s out=%s"
                                 % (modeling.returncode, modeling.stdout[-400:]))
        if "PENDING_HUMAN" not in modeling.stdout:
            raise AssertionError("expected PENDING_HUMAN status, got: %s" % modeling.stdout[-300:])
        for artifact in ("12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"):
            if (project / artifact).exists():
                raise AssertionError("final mode must NOT generate %s while the human gate is pending" % artifact)
        print("  [6/7] final mode + PENDING human gate -> PENDING_HUMAN, no final artifacts: PASS")


def test_draft_mode_pending_human_gate() -> None:
    """FIX round-2 6.3: draft mode may proceed with clearly-draft artifacts
    (existing flexibility) but must never report a FINAL pass."""
    with tempfile.TemporaryDirectory(prefix="runner_draftgate_") as tmp:
        project = Path(tmp) / "proj"
        project.mkdir(parents=True)
        modeling_fixtures.build_workspace(project)
        for artifact in ("12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"):
            (project / artifact).unlink(missing_ok=True)
        decision = modeling_fixtures.modeling_root(project) / "methods" / "Q1" / "decisions" / "method-selector_modeler_decision.md"
        decision.write_text(
            modeling_fixtures.DECISION_TEMPLATE.format(
                skill="method-selector", decision_id="qx_method_choice", decision_point="method_choice",
                status="PENDING", decided_by="human", rationale="under review",
            ),
            encoding="utf-8",
        )
        modeling = _run(["--modeling", "--project-dir", str(project), "--mode", "draft"])
        if modeling.returncode != 0:
            raise AssertionError("draft+PENDING must not crash (existing flexibility), rc=%s: %s"
                                 % (modeling.returncode, modeling.stdout[-300:]))
        if "PENDING_HUMAN" in modeling.stdout:
            raise AssertionError("draft mode must not report PENDING_HUMAN as a stop: %s" % modeling.stdout[-300:])
        print("  [7/7] draft mode + PENDING gate keeps draft flexibility (no final-pass claim): PASS")



def _approve_planning(project) -> None:
    """Fill 00_Research_Approval with an approved row and 02 with one task."""
    approval = project / "00_Research_Approval.csv"
    with approval.open(encoding="utf-8-sig") as fh:
        header = next(csv.reader(fh))
    row = {c: "" for c in header}
    row.update({"approval_id": "A1", "outline_version": "v1", "reviewer": "fixture",
                "approval_status": "approved", "approval_date": "2026-08-12"})
    with approval.open("a", encoding="utf-8", newline="") as fh:
        csv.DictWriter(fh, fieldnames=header).writerow(row)
    tasks = project / "02_Web_Collection_Tasks.csv"
    with tasks.open(encoding="utf-8-sig") as fh:
        theader = next(csv.reader(fh))
    trow = {c: "" for c in theader}
    trow.update({"task_id": "T1", "round": "1", "goal_family": "general",
                 "collection_goal": "fixture", "starting_url_or_query": "https://example.com",
                 "required_tool": "anysearch", "status": "pending"})
    with tasks.open("a", encoding="utf-8", newline="") as fh:
        csv.DictWriter(fh, fieldnames=theader).writerow(trow)


def test_all_pre_collection_stage_range() -> None:
    """FIX round-3 P1-1: --all's first stage gate must validate 0-4,
    never the global 0-8 default."""
    with tempfile.TemporaryDirectory(prefix="runner_prerange_") as tmp:
        project = Path(tmp) / "proj"
        run = _run(["--all", "--dry-run", "--project-dir", str(project),
                    "--region", "Thailand", "--category", "BESS"])
        # 只检查 validate_stage_gate 命令的 stages（init 命令用 0-8 生成模板是合理的）
        m = re.search(r"validate_stage_gate\.py.*?--stages (\d+-\d+)", run.stdout)
        if not m:
            raise AssertionError("pre-collection gate command not found in --all output: %s" % run.stdout[-400:])
        if m.group(1) != "0-4":
            raise AssertionError("pre-collection gate must validate stages 0-4, got %s" % m.group(1))
print("  [8/10] --all pre-collection gate uses --stages 0-4: PASS")


def test_all_planning_prerequisite_blocked() -> None:
    """FIX round-3 P1-2: fresh project without research approval -> --all
    returns BLOCKED and never enters collection."""
    with tempfile.TemporaryDirectory(prefix="runner_prereq_") as tmp:
        project = Path(tmp) / "proj"
        run = _run(["--all", "--project-dir", str(project),
                    "--region", "Thailand", "--category", "BESS"])
        if run.returncode == 0:
            raise AssertionError("--all on un-approved project must exit != 0")
        if "前置条件未满足" not in run.stdout and "BLOCKED" not in run.stdout:
            raise AssertionError("expected planning-precondition BLOCKED message: %s" % run.stdout[-400:])
        if "前置条件" in run.stdout and "02_Web_Collection_Tasks" not in run.stdout and "approval" not in run.stdout:
            raise AssertionError("BLOCKED message must name the missing prerequisite")
        print("  [9/10] --all blocked before collect when planning/approval missing: PASS")


def test_all_planning_completed_enters_collect() -> None:
    """FIX round-3 P1-2: after planning + approval, --all proceeds to collect."""
    with tempfile.TemporaryDirectory(prefix="runner_preready_") as tmp:
        project = Path(tmp) / "proj"
        init = _run(["--init", "--project-dir", str(project), "--region", "Thailand",
                     "--category", "BESS", "--stages", "0-4"])
        if init.returncode != 0:
            raise AssertionError("init failed: %s" % init.stdout[-300:])
        _approve_planning(project)
        import run_workflow as rw
        ok, reason = rw._planning_prerequisites_met(project)
        if not ok:
            raise AssertionError("planning prerequisites must be met after approval: %s" % reason)
        run = _run(["--all", "--dry-run", "--project-dir", str(project),
                    "--region", "Thailand", "--category", "BESS"])
        if "[DRY-RUN] collect" not in run.stdout:
            raise AssertionError("--all must reach the collect stage when planning is done: %s" % run.stdout[-400:])
        print("  [10/10] --all enters collect after planning/approval completed: PASS")



def test_precheck_fail_stops_collect() -> None:
    """FIX round-4 P1-1: pre-collection gate FAIL must stop the pipeline
    BEFORE collect — collect is never executed on an unvalidated project."""
    with tempfile.TemporaryDirectory(prefix="runner_prefail_") as tmp:
        project = Path(tmp) / "proj"
        init = _run(["--init", "--project-dir", str(project), "--region", "Thailand",
                     "--category", "BESS", "--stages", "0-4"])
        if init.returncode != 0:
            raise AssertionError("init failed")
        _approve_planning(project)
        run = _run(["--all", "--project-dir", str(project),
                    "--region", "Thailand", "--category", "BESS", "--stages", "0-4"])
        if run.returncode == 0:
            raise AssertionError("precheck FAIL must exit != 0")
        if "== workflow summary ==" in run.stdout:
            raise AssertionError("workflow summary printed -> later stages ran after precheck FAIL: %s"
                                 % run.stdout[-300:])
        if "[PASS] collect" in run.stdout or "collect (" in run.stdout:
            raise AssertionError("collect must NOT run after precheck FAIL: %s" % run.stdout[-300:])
        print("  [11/12] precheck FAIL stops collect (exit!=0, collect not executed): PASS")


def test_build_fail_stops_audit() -> None:
    """FIX round-4 P1-2: final report build FAIL must block the evidence
    audit — audit must never run against a failed/nonexistent deliverable.
    Module-level mock inspects the exact step call sequence."""
    import run_workflow as rw

    with tempfile.TemporaryDirectory(prefix="runner_buildfail_") as tmp:
        project = Path(tmp) / "proj"
        init = _run(["--init", "--project-dir", str(project), "--region", "Thailand",
                     "--category", "BESS", "--stages", "0-4"])
        if init.returncode != 0:
            raise AssertionError("init failed")
        _approve_planning(project)

        called: list[str] = []
        fn_calls = {"collect": 0, "modeling": 0}

        def fake_run_step(label, command, *, keep_going, dry_run):
            # main() wraps run_step via a local closure; mocking the module
            # function intercepts every workflow step.
            called.append(label)
            if label == "build final report":
                return {"label": label, "returncode": 1, "command": command}
            return {"label": label, "returncode": 0, "command": command, "dry_run": dry_run}

        old = {name: getattr(rw, name) for name in
               ("run_step", "run_collect", "run_modeling", "read_json")}
        rw.run_step = fake_run_step

        def fake_run_collect(*a, **k):
            fn_calls["collect"] += 1
            return {"tasks": 1, "attempts": 1, "completed": 1, "blocked": 0, "failed": 0}

        def fake_run_modeling(*a, **k):
            fn_calls["modeling"] += 1
            return {"branch": "auto", "skipped": "chain not engaged"}

        rw.run_collect = fake_run_collect
        rw.run_modeling = fake_run_modeling
        rw.read_json = lambda *a, **k: {"region": "Thailand", "category": "BESS"}
        old_argv = sys.argv
        try:
            sys.argv = ["run_workflow.py", "--all", "--project-dir", str(project),
                        "--region", "Thailand", "--category", "BESS"]
            rc = rw.main()
        finally:
            sys.argv = old_argv
            for name, fn in old.items():
                setattr(rw, name, fn)
        if rc == 0:
            raise AssertionError("build FAIL must exit != 0")
        if "build evidence audit" in called:
            raise AssertionError("audit must NOT run after build FAIL; steps were: %s" % called)
        if "build final report" not in called:
            raise AssertionError("build must run before the audit gate; steps were: %s" % called)
        if fn_calls["collect"] != 1 or fn_calls["modeling"] != 1:
            raise AssertionError("collect/modeling must run before build; calls=%s" % fn_calls)
        print("  [12/12] build FAIL stops audit (audit not executed, exit!=0): PASS")

def main() -> int:
    print("Workflow runner regression:")
    test_all_dry_run_sequence()
    test_offline_flow_init_check_modeling_audit()
    test_modeling_branch_generates_artifacts()
    test_modeling_human_gate_pending()
    test_collect_blocked_stops_pipeline()
    test_final_mode_pending_human_gate()
    test_draft_mode_pending_human_gate()
    test_all_pre_collection_stage_range()
    test_all_planning_prerequisite_blocked()
    test_all_planning_completed_enters_collect()
    test_precheck_fail_stops_collect()
    test_build_fail_stops_audit()
    print("Workflow runner regression: PASS (12/12)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
