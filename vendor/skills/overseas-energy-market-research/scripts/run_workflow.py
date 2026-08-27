from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _common import now_iso, read_csv, read_json, write_json
from collection_quantity_policy import round_floor
from validate_deliverables import parse_stages


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def resolve_worker_python(required_modules: tuple[str, ...]) -> str:
    """Pick a Python interpreter that can import every module required by a build step.

    Codex's bundled document runtime intentionally omits some plotting packages,
    while a user's system Python may provide them.  Prefer an explicit portable
    override, then the current interpreter, then Python found on PATH.
    """
    candidates = [
        os.environ.get("OVERSEAS_RESEARCH_PYTHON", "").strip(),
        sys.executable,
        shutil.which("python") or "",
        shutil.which("python3") or "",
    ]
    checked: list[str] = []
    probe = "import " + ", ".join(required_modules)
    for raw in candidates:
        if not raw:
            continue
        candidate = str(Path(raw).expanduser().resolve())
        if candidate.lower() in {item.lower() for item in checked} or not Path(candidate).exists():
            continue
        checked.append(candidate)
        try:
            result = subprocess.run(
                [candidate, "-c", probe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate
    modules = ", ".join(required_modules)
    raise RuntimeError(
        f"No Python interpreter can import the required modules: {modules}. "
        "Install them in a PATH Python or set OVERSEAS_RESEARCH_PYTHON. "
        f"Checked: {checked}"
    )


def run_step(label: str, command: list[str], *, keep_going: bool, dry_run: bool = False) -> dict:
    print(f"\n== {label} ==")
    print(" ".join(command))
    if dry_run:
        return {"label": label, "returncode": 0, "command": command, "dry_run": True}
    completed = subprocess.run(command, text=True)
    result = {"label": label, "returncode": completed.returncode, "command": command}
    if completed.returncode and not keep_going:
        raise SystemExit(completed.returncode)
    return result


def collect_min_attempts(task_row: dict[str, str], policy: dict | None) -> int:
    """单任务最低 attempt 数：min(target_unique_sources, policy floor)，至少 1。"""
    target = None
    try:
        target = int(str(task_row.get("target_unique_sources", "")).strip())
    except (TypeError, ValueError):
        target = None
    floor = None
    family = task_row.get("goal_family", "").strip()
    rnd = task_row.get("round", "").strip()
    if policy and family and rnd in {"1", "2", "3"}:
        try:
            floor = round_floor(family, rnd, policy)["min_unique_sources"]
        except (KeyError, ValueError):
            floor = None
    candidates = [value for value in (target, floor) if value is not None and value > 0]
    return min(candidates) if candidates else 1



# FIX round-3 P1-1: --all 的 pre-collection gate 只验证采集前置阶段（0-4），
# 不得复用最终验证的 0-8 默认值。
PRE_COLLECTION_STAGES = "0-4"
FINAL_VALIDATION_STAGES = "0-8"


def _planning_prerequisites_met(project_dir: Path) -> tuple[bool, str]:
    """--all 真实前置条件（FIX round-3 P1-2）: 研究计划、人工审批、采集计划已完成。

    --all 是规划阶段完成后的总执行入口，不自动替代人工研究审批。
    """
    approval = project_dir / "00_Research_Approval.csv"
    tasks = project_dir / "02_Web_Collection_Tasks.csv"
    if not approval.is_file():
        return False, "00_Research_Approval.csv missing (research planning not started)"
    _, approval_rows = read_csv(approval)
    if not approval_rows:
        return False, "00_Research_Approval.csv has no approval record (human approval required)"
    statuses = {str(r.get("approval_status", "")).strip().casefold() for r in approval_rows}
    if not statuses & {"approved", "approved_with_conditions"}:
        return False, "research approval not granted (approval_status != approved)"
    if not tasks.is_file():
        return False, "02_Web_Collection_Tasks.csv missing (collection plan not populated)"
    _, task_rows = read_csv(tasks)
    if not task_rows:
        return False, "02_Web_Collection_Tasks.csv has no tasks (collection plan not populated)"
    return True, ""


# FIX-02: unified sub-step status (PASS/FAIL/BLOCKED/PENDING_HUMAN/SKIP/WARN).
# A workflow must never wrap a real failure as returncode=0 — the final
# exit code is derived from these statuses, not from optimistic wrapping.
def _status_for(label: str, result: dict) -> str:
    """Derive a unified status for a workflow sub-step result."""
    if result.get("dry_run"):
        return "DRY-RUN"
    if "summary" not in result:
        return "PASS" if not result.get("returncode") else "FAIL"
    summary = result["summary"]
    if label == "collect":
        if summary.get("dry_run"):
            return "DRY-RUN"
        if summary.get("error"):
            return "BLOCKED"  # e.g. 02_Web_Collection_Tasks.csv missing
        if summary.get("blocked", 0) > 0:
            return "BLOCKED"
        if summary.get("failed", 0) > 0:
            return "FAIL"
        return "PASS"
    if label == "modeling":
        if summary.get("skipped") or summary.get("dry_run"):
            return "SKIP"
        if summary.get("gates") == "FAIL":
            return "PENDING_HUMAN"  # G2.5/G4.5 await human approval; not a crash
        if summary.get("artifacts") == "FAIL":
            return "FAIL"
        return "PASS"
    return "PASS" if not result.get("returncode") else "FAIL"


def _wrap_step(label: str, result: dict) -> dict:
    """Wrap a collect/modeling result with unified status + honest returncode."""
    status = _status_for(label, {"summary": result})
    rc = 1 if status in ("FAIL", "BLOCKED") else (3 if status == "PENDING_HUMAN" else 0)
    return {"label": label, "status": status, "returncode": rc, "summary": result}


def _handle_gate(results: list[dict], entry: dict) -> int | None:
    """FIX round-2 P1-1: stage gate — return an exit code to terminate the
    pipeline immediately, or None to continue.

    FAIL/BLOCKED -> exit 1 (hard stop). PENDING_HUMAN -> exit 3 (paused,
    never crossed automatically). PASS/WARN/SKIP -> continue.
    """
    # step-produced entries carry only returncode (no status): derive it.
    status = entry.get("status")
    if status is None:
        status = "FAIL" if entry.get("returncode") else "PASS"
    if status in ("FAIL", "BLOCKED"):
        print("[workflow] 阶段 %s 状态=%s —— 立即停止，后续阶段（modeling/build/audit）不执行"
              % (entry.get("label"), status))
        return 1
    if status == "PENDING_HUMAN":
        print("[workflow] 阶段 %s 状态=PENDING_HUMAN —— 暂停等待人工批准（final 模式不生成 final artifacts）"
              % entry.get("label"))
        return 3
    return None


def run_collect(project_dir: Path, *, official_cli: str | None = None, dry_run: bool = False) -> dict:
    """机械执行 02_Web_Collection_Tasks.csv：每行 run_task 到最低 attempt 数（自动台账/状态更新）。

    说明：Agent 负责任务表设计（查询词/URL/目标数），本步骤只做机械执行与留痕。
    """
    from collection_quantity_policy import load_project_policy
    from web_collection.journal import CollectionJournal
    from web_collection.router import TASK_FILE, run_task

    summary: dict[str, object] = {"tasks": 0, "attempts": 0, "completed": 0, "blocked": 0, "failed": 0}
    if dry_run:
        summary["dry_run"] = True  # dry-run is a preview: missing files are NOT failures
    task_path = project_dir / TASK_FILE
    if not task_path.is_file():
        summary["error"] = f"{TASK_FILE} not found - initialize the project first"
        return summary
    policy = None
    try:
        policy = load_project_policy(project_dir)
    except ValueError:
        policy = None
    _, rows = read_csv(task_path)
    journal = CollectionJournal(project_dir)
    for row in rows:
        task_id = row.get("task_id", "").strip()
        rnd = row.get("round", "").strip()
        if not task_id or rnd not in {"1", "2", "3"}:
            continue
        minimum = collect_min_attempts(row, policy)
        summary["tasks"] += 1
        for _ in range(minimum):
            if dry_run:
                summary["attempts"] += 1
                continue
            try:
                outcome = run_task(project_dir, row, journal=journal, official_cli=official_cli)
            except Exception as exc:  # noqa: BLE001 - 单任务异常不中断整批
                summary["failed"] += 1
                print(f"[collect] {task_id}: unexpected error {type(exc).__name__}: {exc}")
                continue
            summary["attempts"] += 1
            if outcome.status == "completed":
                summary["completed"] += 1
            elif outcome.status == "blocked":
                summary["blocked"] += 1
            else:
                summary["failed"] += 1
    return summary


def run_modeling(project_dir: Path, *, mode: str = "draft", dry_run: bool = False) -> dict:
    """建模链脚本化步骤：gates 检查（draft）+ 决策门通过时生成 12/13/14。

    人工门（G2.5/G4.5）AI 不可自置通过：未决时输出待决 warn，不生成产物、不失败。
    """
    manifest = read_json(project_dir / "project_manifest.json", {})
    branch = str(manifest.get("analysis_branch") or "auto").strip().lower()
    if branch != "modeling":
        return {"branch": branch, "skipped": "analysis_branch != modeling (chain not engaged)"}
    root = project_dir / "intermediate" / "modeling"
    if not root.is_dir():
        return {"branch": branch, "skipped": "intermediate/modeling workspace missing - run init with --analysis-branch modeling"}

    gates_command = [
        sys.executable,
        str(script_dir() / "validate_modeling_chain_gates.py"),
        "--project-dir", str(project_dir), "--mode", mode,
    ]
    if dry_run:
        print(" ".join(gates_command))
        return {"branch": branch, "dry_run": True, "artifacts": "skipped"}
    print(" ".join(gates_command))
    gates = subprocess.run(gates_command, text=True)
    if gates.returncode != 0:
        return {
            "branch": branch,
            "gates": "FAIL",
            "note": "human gates or chain artifacts pending (G2.5/G4.5 cannot be self-approved); fix then re-run --modeling",
        }
    artifacts_command = [
        sys.executable,
        str(script_dir() / "create_modeling_artifacts.py"),
        "--project-dir", str(project_dir),
    ]
    print(" ".join(artifacts_command))
    artifacts = subprocess.run(artifacts_command, text=True)
    return {"branch": branch, "gates": "PASS", "artifacts": "FAIL" if artifacts.returncode else "OK"}


def update_stage_status(project_dir: Path, action: str, stages: list[str], results: list[dict]) -> None:
    status_path = project_dir / "stage_status.json"
    status = read_json(status_path, {"stages": {}, "notes": []})
    status["updated_at"] = now_iso()
    status.setdefault("runs", []).append(
        {
            "action": action,
            "stages": stages,
            "results": results,
            "completed_at": now_iso(),
        }
    )
    write_json(status_path, status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestrate the domestic/global energy market research workflow.")
    parser.add_argument("--project-dir", required=True, help="Research project directory.")
    parser.add_argument("--region", help="Target region. Required when --init is used for a new project.")
    parser.add_argument("--category", help="Product category. Required when --init is used for a new project.")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--stages", default="0-8", help="Stage range or list, e.g. 0-8 or 1,2,3,6.")
    parser.add_argument("--local-parameter-path", default="", help="User-confirmed local product parameter path.")
    parser.add_argument("--decision-question", default="")
    parser.add_argument("--outline-version", default="v1")
    parser.add_argument("--analysis-branch", choices=["auto", "modeling", "market-insight"], default="auto")
    parser.add_argument("--currency", default="")
    parser.add_argument("--tax-basis", default="")
    parser.add_argument("--local-files-provided", choices=["yes", "no"], default="yes")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft")
    parser.add_argument("--init", action="store_true", help="Initialize project templates before checking gates.")
    parser.add_argument("--force-init", action="store_true", help="Overwrite copied templates during initialization.")
    parser.add_argument("--check", action="store_true", help="Run stage gate validation.")
    parser.add_argument("--status", action="store_true", help="Build a Markdown status report.")
    parser.add_argument("--audit", action="store_true", help="Build a consolidated evidence audit report.")
    parser.add_argument("--build-package", action="store_true", help="Create Word/Excel/PPT deliverable package from adapted templates.")
    parser.add_argument("--build-stage1", action="store_true", help="Build Stage 1 market quick scan Word report from CSV tables.")
    parser.add_argument("--build-stage7", action="store_true", help="Build Stage 7 integrated matrix and SWOT PPT from CSV tables and charts.")
    parser.add_argument("--build-final-report", action="store_true", help="Build data-populated final Word/PPT/Excel package from CSV tables and charts.")
    parser.add_argument("--collect", action="store_true", help="Execute 02_Web_Collection_Tasks.csv mechanically: run_task per row until target/floor attempts, auto-journaling.")
    parser.add_argument("--official-cli", default=None, help="Explicit official anysearch CLI path for --collect (dual-path fallback).")
    parser.add_argument("--modeling", action="store_true", help="Run modeling chain scripted steps: gates check (draft) + 12/13/14 artifacts when human gates pass.")
    parser.add_argument("--all", action="store_true", help="One-command pipeline: init(if missing) -> check(0-4 draft) -> collect -> modeling -> build-final-report -> audit.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command sequence without executing anything.")
    parser.add_argument("--source-scope", default="待补充：政府/监管/电网、官方产品资料、本地主流渠道、用户评论、政策与市场数据源")
    parser.add_argument("--package-prefix", default="能源产品与行业市场调研报告")
    parser.add_argument("--strict-final-files", action="store_true", help="Require final docx/xlsx/pptx in stage 8 final mode.")
    parser.add_argument("--keep-going", action="store_true", help="Continue after a failed sub-step.")
    parser.add_argument("--json-log", help="Optional JSON log output path.")
    args = parser.parse_args()

    scripts = script_dir()
    project_dir = Path(args.project_dir).expanduser().resolve()
    stages = parse_stages(args.stages)
    results: list[dict] = []

    def step(label: str, command: list[str]) -> dict:
        return run_step(label, command, keep_going=args.keep_going, dry_run=args.dry_run)

    if not (args.init or args.check or args.status or args.audit or args.build_package or args.build_stage1 or args.build_stage7 or args.build_final_report or args.collect or args.modeling or args.all):
        args.check = True
        args.status = True

    if args.all:
        # 一键总流程：init(缺省) -> check(0-4 draft) -> collect -> modeling -> build-final-report -> audit
        if not (project_dir / "project_manifest.json").is_file():
            if not args.region or not args.category:
                parser.error("--region and --category are required with --all when the project is not initialized.")
            init_command = [
                sys.executable,
                str(scripts / "init_research_project.py"),
                "--project-dir", str(project_dir),
                "--region", args.region,
                "--category", args.category,
                "--language", args.language,
                "--stages", args.stages,
                "--outline-version", args.outline_version,
                "--analysis-branch", args.analysis_branch,
            ]
            results.append(step("initialize project", init_command))
        # FIX round-3 P1-2: --all 前置条件 —— planning/approval/collection-plan 必须已完成
        if not args.dry_run:
            prereq_ok, prereq_reason = _planning_prerequisites_met(project_dir)
            if not prereq_ok:
                print("[workflow] 前置条件未满足（BLOCKED）: %s" % prereq_reason)
                print("[workflow] Research planning / human approval required before --all.")
                results.append({"label": "precheck", "status": "BLOCKED", "returncode": 1,
                                "summary": {"error": prereq_reason}})
                return 1
        elif not (project_dir / "project_manifest.json").is_file():
            print("[workflow] [DRY-RUN 提示] 真实执行将要求 research planning / human approval 已完成")
        precheck_entry = step(
            "validate stage gates 0-4",
            [
                sys.executable,
                str(scripts / "validate_stage_gate.py"),
                "--project-dir", str(project_dir),
                "--stages", PRE_COLLECTION_STAGES,
                "--mode", args.mode,
                "--local-files-provided", args.local_files_provided,
            ],
        )
        results.append(precheck_entry)
        # FIX round-4 P1-1: pre-collection gate FAIL/BLOCKED/PENDING_HUMAN must
        # stop the pipeline BEFORE collect — fail fast, never run collect on
        # an unvalidated project.
        rc = _handle_gate(results, precheck_entry)
        if rc is not None:
            return rc
        collect_result = run_collect(project_dir, official_cli=args.official_cli, dry_run=args.dry_run)
        collect_entry = _wrap_step("collect", collect_result)
        results.append(collect_entry)
        # FIX round-2 P1-1: gate EVERY stage immediately — never rely on the
        # last result of a group (collect=BLOCKED + modeling=SKIP must stop).
        rc = _handle_gate(results, collect_entry)
        if rc is not None:
            return rc
        modeling_result = run_modeling(project_dir, mode=args.mode, dry_run=args.dry_run)
        modeling_entry = _wrap_step("modeling", modeling_result)
        results.append(modeling_entry)
        rc = _handle_gate(results, modeling_entry)
        if rc is not None:
            return rc
        if not args.dry_run and (project_dir / "project_manifest.json").is_file():
            manifest = read_json(project_dir / "project_manifest.json", {})
            region = args.region or manifest.get("region")
            category = args.category or manifest.get("category")
            if region and category:
                build_entry = step(
                    "build final report",
                    [
                        resolve_worker_python(("matplotlib", "docx", "openpyxl", "pptx")),
                        str(scripts / "build_final_report_package.py"),
                        "--project-dir", str(project_dir),
                        "--region", region,
                        "--category", category,
                        "--prefix", args.package_prefix,
                    ],
                )
                results.append(build_entry)
                # FIX round-4 P1-2: a failed final package build must block the
                # evidence audit — audit must not pretend to audit a deliverable
                # that was never produced.
                rc = _handle_gate(results, build_entry)
                if rc is not None:
                    return rc
        results.append(
            step(
                "build evidence audit",
                [
                    sys.executable,
                    str(scripts / "build_evidence_audit.py"),
                    "--project-dir", str(project_dir),
                    "--local-files-provided", args.local_files_provided,
                ],
            )
        )

    if args.init:
        if not args.region or not args.category:
            parser.error("--region and --category are required with --init.")
        command = [
            sys.executable,
            str(scripts / "init_research_project.py"),
            "--project-dir",
            str(project_dir),
            "--region",
            args.region,
            "--category",
            args.category,
            "--language",
            args.language,
            "--stages",
            args.stages,
            "--local-parameter-path",
            args.local_parameter_path,
            "--decision-question",
            args.decision_question,
            "--outline-version",
            args.outline_version,
            "--analysis-branch",
            args.analysis_branch,
            "--currency",
            args.currency,
            "--tax-basis",
            args.tax_basis,
        ]
        if args.force_init:
            command.append("--force")
        results.append(step("initialize project", command))

    if args.build_package:
        manifest = read_json(project_dir / "project_manifest.json", {})
        region = args.region or manifest.get("region")
        category = args.category or manifest.get("category")
        if not region or not category:
            parser.error("--region and --category are required for --build-package unless project_manifest.json contains them.")
        command = [
            resolve_worker_python(("docx", "openpyxl", "pptx")),
            str(scripts / "build_deliverable_package.py"),
            "--project-dir",
            str(project_dir),
            "--region",
            region,
            "--category",
            category,
            "--source-scope",
            args.source_scope,
            "--prefix",
            args.package_prefix,
            "--force",
        ]
        results.append(step("build deliverable package", command))

    if args.build_stage1:
        manifest = read_json(project_dir / "project_manifest.json", {})
        region = args.region or manifest.get("region")
        category = args.category or manifest.get("category")
        if not region or not category:
            parser.error("--region and --category are required for --build-stage1 unless project_manifest.json contains them.")
        command = [
            resolve_worker_python(("docx",)),
            str(scripts / "build_stage1_market_scan_docx.py"),
            "--project-dir",
            str(project_dir),
            "--region",
            region,
            "--category",
            category,
        ]
        results.append(step("build stage 1 report", command))

    if args.build_stage7:
        manifest = read_json(project_dir / "project_manifest.json", {})
        region = args.region or manifest.get("region")
        category = args.category or manifest.get("category")
        if not region or not category:
            parser.error("--region and --category are required for --build-stage7 unless project_manifest.json contains them.")
        build_python = resolve_worker_python(("matplotlib", "pptx"))
        chart_command = [
            build_python,
            str(scripts / "render_charts.py"),
            "--project-dir",
            str(project_dir),
        ]
        results.append(step("render charts for stage 7", chart_command))
        command = [
            build_python,
            str(scripts / "build_stage7_swot_pptx.py"),
            "--project-dir",
            str(project_dir),
            "--region",
            region,
            "--category",
            category,
        ]
        results.append(step("build stage 7 deck", command))

    if args.build_final_report:
        manifest = read_json(project_dir / "project_manifest.json", {})
        region = args.region or manifest.get("region")
        category = args.category or manifest.get("category")
        if not region or not category:
            parser.error("--region and --category are required for --build-final-report unless project_manifest.json contains them.")
        command = [
            resolve_worker_python(("matplotlib", "docx", "openpyxl", "pptx")),
            str(scripts / "build_final_report_package.py"),
            "--project-dir",
            str(project_dir),
            "--region",
            region,
            "--category",
            category,
            "--prefix",
            args.package_prefix,
        ]
        results.append(step("build final report package", command))

    if args.collect:
        collect_result = run_collect(project_dir, official_cli=args.official_cli, dry_run=args.dry_run)
        results.append(_wrap_step("collect", collect_result))

    if args.modeling:
        modeling_result = run_modeling(project_dir, mode=args.mode, dry_run=args.dry_run)
        results.append(_wrap_step("modeling", modeling_result))

    if args.check:
        command = [
            sys.executable,
            str(scripts / "validate_stage_gate.py"),
            "--project-dir",
            str(project_dir),
            "--stages",
            args.stages,
            "--mode",
            args.mode,
            "--local-files-provided",
            args.local_files_provided,
        ]
        if args.strict_final_files:
            command.append("--strict-final-files")
        results.append(step("validate stage gates", command))

    if args.status:
        command = [
            sys.executable,
            str(scripts / "build_status_report.py"),
            "--project-dir",
            str(project_dir),
        ]
        results.append(step("build status report", command))

    if args.audit:
        command = [
            sys.executable,
            str(scripts / "build_evidence_audit.py"),
            "--project-dir",
            str(project_dir),
            "--local-files-provided",
            args.local_files_provided,
        ]
        if args.mode == "draft":
            command.append("--allow-empty-reviews")
        if args.strict_final_files:
            command.append("--strict-final-files")
        results.append(step("build evidence audit", command))

    if project_dir.exists():
        update_stage_status(project_dir, "run_workflow", stages, results)

    if args.json_log:
        output = Path(args.json_log).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"project_dir": str(project_dir), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote workflow log: {output}")

    if args.all or args.collect or args.modeling:
        print("\n== workflow summary ==")
        for result in results:
            label = result.get("label", "?")
            status = result.get("status") or _status_for(label, result)
            if "summary" in result and label in ("collect", "modeling"):
                summary = result["summary"]
                if label == "modeling":
                    detail = summary.get("skipped") or summary.get("note") or summary.get("gates") or "ok"
                else:
                    detail = summary.get("error") or f"tasks={summary.get('tasks', 0)} attempts={summary.get('attempts', 0)} ok={summary.get('completed', 0)} blocked={summary.get('blocked', 0)} failed={summary.get('failed', 0)}"
                print(f"  [{status}] {label} ({detail})")
            else:
                print(f"  [{status}] {label}")

    failed = [r for r in results if r.get("returncode") and r.get("status") != "PENDING_HUMAN"]
    pending = [r for r in results if r.get("status") == "PENDING_HUMAN"]
    if failed:
        return len(failed)
    if pending:
        return 3  # PENDING_HUMAN: paused for human gate (not a crash, but not success)
    return 0


def _final_return(results: list[dict]) -> int:
    failed = [r for r in results if r.get("returncode") and r.get("status") != "PENDING_HUMAN"]
    pending = [r for r in results if r.get("status") == "PENDING_HUMAN"]
    if failed:
        return len(failed)
    if pending:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
