"""Overseas market research adapter (§17).

The overseas skill is a CLI-driven capability pack. This adapter reaches it
through its structured artifacts — source ledger, collection journal, stage
gate status, gap log — never by reading a final Word report. Human approval
(00_Research_Approval.csv) is a hard gate the adapter cannot bypass (§27).

The default runner shells out to the vendored ``run_workflow.py``; tests inject
a fake runner. All upstream gates remain in effect.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from energy_research_agent.domain.ids import new_sortable_id

from ..models import (
    FailureClass,
    RecoveryPlan,
    ResearchGoal,
    ResearchMission,
    SkillAttempt,
    SkillName,
    SkillPlan,
    SkillRunResult,
    SkillRunStatus,
)

RUNNER = Callable[[dict[str, Any]], dict[str, Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle)]


_CAPTURE_TITLE = re.compile(r"^### \d+\.\s*(.+)$")
_CAPTURE_URL = re.compile(r"-\s*\*\*URL\*\*:\s*(\S+)")


def _is_final_insight(text: str) -> bool:
    """五观报告只有终稿才算交付物：模板骨架（[[填写]] 占位符或 status: draft）绝不外推。"""
    return "[[填写" not in text and "status: draft" not in text[:500]


def _parse_capture_results(text: str) -> list[tuple[str, str]]:
    """从 anysearch 搜索结果 markdown 提取 (title, url) 对。"""
    results: list[tuple[str, str]] = []
    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        match = _CAPTURE_TITLE.match(stripped)
        if match:
            title = match.group(1).strip()
            continue
        match = _CAPTURE_URL.search(stripped)
        if match:
            results.append((title, match.group(1).strip()))
            title = ""
    return results


def register_sources_from_captures(project_dir: Path) -> int:
    """把成功采集的 raw_capture 登记进 00_Source_Ledger.csv（按 URL 去重）。

    vendor skill 原设计中台账由研究型 agent 在 stage2 维护；编排模式下没有该角色，
    由 adapter 按 journal 成功记录机械登记——否则 ledger 永远 0 行，目标全部
    EXHAUSTED，证据也进不了 unified store，整任务零交付物。
    """
    ledger_path = Path(project_dir) / "00_Source_Ledger.csv"
    if not ledger_path.is_file():
        return 0
    project_dir = Path(project_dir)
    journal = _read_csv_rows(project_dir / "13_Collection_Attempt_Journal.csv")
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return 0
    seen = {row.get("source_url", "").strip() for row in rows if row.get("source_url", "").strip()}
    next_no = len(rows) + 1
    added = 0
    for record in journal:
        if record.get("status") != "success":
            continue
        capture_rel = (record.get("raw_capture_path") or "").strip()
        if not capture_rel:
            continue
        capture = project_dir / capture_rel
        if not capture.is_file():
            continue
        try:
            text = capture.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for title, url in _parse_capture_results(text):
            if not url or url in seen:
                continue
            seen.add(url)
            new_row = {name: "" for name in fieldnames}
            candidate = {
                "source_id": f"SRC-{next_no:04d}",
                "stage": "web_collection",
                "evidence_item": record.get("query_or_url", ""),
                "value_class": "observed",
                "source_type": "web_search_result",
                "collection_tool": record.get("tool", "") or "anysearch",
                "source_title": title,
                "source_url": url,
                "root_domain": urlparse(url).netloc,
                "local_file_path": capture_rel,
                "access_date": (record.get("timestamp", "") or "")[:10],
                "verification_status": "unverified",
            }
            # 只写模板表头存在的列（不同版本模板列可能不同）。
            new_row.update({key: value for key, value in candidate.items() if key in fieldnames})
            rows.append(new_row)
            next_no += 1
            added += 1
    if added:
        with ledger_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return added


class OverseasMarketResearchAdapter:
    """OVERSEAS_MARKET_RESEARCH tool backed by the vendored capability pack."""

    skill_name = SkillName.OVERSEAS_MARKET_RESEARCH

    def __init__(
        self,
        *,
        skill_root: Path | None = None,
        python: str | None = None,
        runner: RUNNER | None = None,
    ) -> None:
        from energy_research_agent.vendor import embedded_skill_root

        self.skill_root = Path(skill_root) if skill_root else embedded_skill_root("overseas-energy-market-research")
        self.python = python or sys.executable
        self.runner = runner or self._default_runner
        # Live collection subprocesses tracked by project dir so a user stop
        # can kill the process tree immediately (hard-stop semantics).
        self._procs: dict[str, subprocess.Popen] = {}

    # -- port ---------------------------------------------------------------

    def plan(self, mission: ResearchMission, goals: list[ResearchGoal]) -> SkillPlan:
        project_dir = self._project_dir(mission)
        # §27 unified approval: when the human already approved the mission,
        # materialize the skill's own Stage-0 approval record so the double
        # gate opens exactly once, from the single human decision. Unapproved
        # missions stay PENDING here and execute() blocks (the agent cannot
        # self-approve).
        from ..models import ApprovalStatus

        if mission.approval_status == ApprovalStatus.APPROVED:
            self.ensure_approved(project_dir, mission.mission_id, mission.raw_request)
        parameters = {
            "project_dir": str(project_dir),
            "region": mission.geographies[0] if mission.geographies else "",
            "category": mission.products[0] if mission.products else "energy storage",
            "geographies": list(mission.geographies),
            "goal_specs": [
                {
                    "goal_id": goal.goal_id,
                    "name": goal.goal_name,
                    "description": goal.goal_description,
                    "geography": mission.geographies[0] if mission.geographies else "",
                }
                for goal in goals
            ],
        }
        return SkillPlan(
            skill_plan_id=new_sortable_id("MKT-PLAN"),
            skill_name=self.skill_name,
            mission_id=mission.mission_id,
            goal_ids=[goal.goal_id for goal in goals],
            parameters=parameters,
        )

    def execute(self, plan: SkillPlan) -> SkillRunResult:
        started = _utc_now()
        approval = self.check_approval(Path(plan.parameters["project_dir"]))
        if not approval["approved"]:
            return self._blocked(plan, started, FailureClass.AUTH_REQUIRED, approval["detail"])
        payload = self._invoke(plan, {"recovery_queries": []})
        return self._result_from_payload(plan, payload, started, attempt_no=1, executed=True)

    def recover(self, plan: SkillPlan, recovery_plan: RecoveryPlan) -> SkillRunResult:
        started = _utc_now()
        approval = self.check_approval(Path(plan.parameters["project_dir"]))
        if not approval["approved"]:
            return self._blocked(plan, started, FailureClass.AUTH_REQUIRED, approval["detail"])
        payload = self._invoke(
            plan,
            {
                "recovery_queries": list(recovery_plan.new_queries),
                "source_categories": list(recovery_plan.new_source_categories),
                "strategy": recovery_plan.new_strategy,
            },
        )
        return self._result_from_payload(
            plan, payload, started,
            attempt_no=recovery_plan.failed_round + 1,
            executed=True,
        )

    def inspect(self, run_id: str) -> SkillRunResult:
        return SkillRunResult(
            skill_run_id=run_id,
            skill_name=self.skill_name,
            status=SkillRunStatus.UNAVAILABLE,
            failure_class=FailureClass.ADAPTER_FAILURE,
            diagnostics=["inspect not supported for subprocess-driven skill runs"],
        )

    def stop(self, *, mission_id: str | None = None, project_dir: Path | None = None) -> int:
        """Kill tracked collection subprocesses; returns the kill count.

        Called by the orchestrator's request_stop. On Windows the whole process
        tree is terminated (taskkill /T) because run_workflow.py spawns children.
        """
        targets: list[str] = []
        if project_dir is not None:
            targets.append(str(project_dir))
        if mission_id is not None:
            targets.append(str(self._project_dir_for_mission(mission_id)))
        killed = 0
        for key in targets:
            proc = self._procs.get(key)
            if proc is None or proc.poll() is not None:
                continue
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, check=False,
                    )
                else:
                    proc.kill()
                killed += 1
            except Exception:  # stop must never raise into the API layer
                continue
        return killed

    # -- approval gate --------------------------------------------------------

    def check_approval(self, project_dir: Path) -> dict[str, Any]:
        rows = _read_csv_rows(project_dir / "00_Research_Approval.csv")
        approved = [row for row in rows if (row.get("approval_status") or "").strip().lower() == "approved"]
        if not approved:
            return {
                "approved": False,
                "detail": "00_Research_Approval.csv 不存在或无 approved 记录；市场研究必须有人工审批，Agent 不能自行批准",
            }
        return {
            "approved": True,
            "approval_id": approved[-1].get("approval_id", ""),
            "scope_summary": approved[-1].get("scope_summary", ""),
        }

    def ensure_approved(self, project_dir: Path, approval_id: str, scope_summary: str) -> bool:
        """§27: materialize the skill's Stage-0 approval record from the unified
        mission approval. Idempotent; never downgrades an existing record."""
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        approval_path = project_dir / "00_Research_Approval.csv"
        if self.check_approval(project_dir)["approved"]:
            return True
        from energy_research_agent.domain.models import utc_now

        header = (
            "approval_id,outline_version,outline_path,scope_summary,reviewer,approval_status,"
            "approval_date,approval_message,scope_change_requires_reapproval,notes\n"
        )
        if approval_path.is_file():
            # Append to an existing (unapproved/pending) record set.
            with approval_path.open("a", encoding="utf-8-sig", newline="") as handle:
                handle.write(
                    f"{approval_id},v1,outline.md,{scope_summary.replace(',', '，')},human,approved,"
                    f"{utc_now().date().isoformat()},unified mission approval,yes,\n"
                )
        else:
            approval_path.write_text(
                header
                + f"{approval_id},v1,outline.md,{scope_summary.replace(',', '，')},human,approved,"
                f"{utc_now().date().isoformat()},unified mission approval,yes,\n",
                encoding="utf-8-sig",
            )
        return self.check_approval(project_dir)["approved"]

    # -- structured output harvesting -----------------------------------------

    def harvest(self, project_dir: Path) -> dict[str, Any]:
        """Reads the skill's structured artifacts into one payload dict."""
        project_dir = Path(project_dir)
        ledger_rows = _read_csv_rows(project_dir / "00_Source_Ledger.csv")
        journal_rows = _read_csv_rows(project_dir / "13_Collection_Attempt_Journal.csv")
        scan_rows = _read_csv_rows(project_dir / "01_Market_Scan.csv")
        issues_rows = _read_csv_rows(project_dir / "11_Evidence_Issues.csv")
        stage_status = {}
        stage_file = project_dir / "stage_status.json"
        if stage_file.is_file():
            stage_status = json.loads(stage_file.read_text(encoding="utf-8"))
        gap_lines: list[str] = []
        gap_log = project_dir / "data_gap_log.md"
        if gap_log.is_file():
            gap_lines = gap_log.read_text(encoding="utf-8").splitlines()
        # §37 validated sub-artifacts: the skill's own deliverables (Excel
        # workbook, Word report, PPT, Five Views report) are referenced by the
        # unified artifact planner, never re-published.
        artifact_refs: list[str] = []
        for pattern in ("*.xlsx", "*.docx", "*.pptx", "*.pdf", "*.html"):
            artifact_refs.extend(
                str(path) for path in sorted((project_dir / "deliverables").glob(pattern))
            )
        insight = project_dir / "intermediate" / "market-insight" / "market_insight_report.md"
        # 模板骨架曾被当交付物推送到飞书：只有终稿（无占位符、非 draft）才进清单。
        if insight.is_file() and _is_final_insight(insight.read_text(encoding="utf-8", errors="replace")):
            artifact_refs.append(str(insight))
        return {
            "ledger_rows": ledger_rows,
            "journal_rows": journal_rows,
            "scan_rows": scan_rows,
            "issues_rows": issues_rows,
            "stage_status": stage_status,
            "gap_log_lines": gap_lines,
            "artifact_refs": artifact_refs,
        }

    # -- deliverable production (Stage 5-8) --------------------------------------

    def produce_deliverables(self, project_dir: Path) -> dict[str, Any]:
        """Stage 5-8：LLM 证据蒸馏 + 官方脚本链（Excel/五观/图表/Word）。

        vendor 原设计要求研究型 agent 在环 + 人工门；编排模式以网关 LLM 蒸馏
        证据填表、用脚本自带的自动化验收旗标替代人工门，审计链保持机器可验。
        幂等：已存在正式交付物时跳过，恢复轮不会重复生产。
        """
        project_dir = Path(project_dir)
        deliverables = project_dir / "deliverables"
        if any(deliverables.glob("*.docx")) or any(deliverables.glob("*.xlsx")):
            return {"status": "SKIPPED", "diagnostics": ["deliverables already produced"], "artifacts": [], "gates": {}}
        ledger = _read_csv_rows(project_dir / "00_Source_Ledger.csv")
        registered = [row for row in ledger if (row.get("source_url") or "").strip()]
        if not registered:
            # 零登记证据时蒸馏无输入：与其生成编造内容的报告，不如显式跳过。
            return {"status": "SKIPPED", "diagnostics": ["production skipped: ledger has 0 registered sources"], "artifacts": [], "gates": {}}
        gateway = None
        try:
            from energy_research_agent.settings import Settings

            settings = Settings()
            if settings.deepseek_api_key or settings.openai_api_key:
                from energy_research_agent.gateway import LiteLLMModelGateway

                # 蒸馏里的五观正文是 7500+ 字长文生成，默认 45s 超时必被掐断
                # （实跑实证：两次 insight 调用全部超时→正文空→Word 全是模板占位符）。
                # 只在本链路放宽到 10 分钟/次，全局默认（提取小调用）保持不变。
                gateway = LiteLLMModelGateway(
                    settings.model_copy(update={"model_timeout_seconds": 600})
                )
        except Exception as exc:  # 无网关降级：跳过蒸馏但仍尽力跑脚本链并留诊断
            gateway = None
            diag_note = f"gateway build failed: {type(exc).__name__}: {exc}"
        else:
            diag_note = ""
        try:
            from energy_research_agent.agent.market_production import MarketProductionPipeline

            pipeline = MarketProductionPipeline(
                project_dir, gateway,
                python=self.python,
                scripts_dir=self.skill_root / "scripts",
            )
            result = pipeline.run()
        except Exception as exc:  # 生产失败绝不阻断任务终态，但原因必须可见
            return {"status": "FAILED", "diagnostics": [f"production failed: {type(exc).__name__}: {exc}"], "artifacts": [], "gates": {}}
        if gateway is None and diag_note:
            result["diagnostics"].insert(0, diag_note)
        return result

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _project_dir(mission: ResearchMission) -> Path:
        # Runtime project root: repo outputs dir, one folder per mission.
        # Covered by .gitignore (outputs/), never committed.
        return OverseasMarketResearchAdapter._project_dir_for_mission(mission.mission_id)

    @staticmethod
    def _project_dir_for_mission(mission_id: str) -> Path:
        from energy_research_agent.vendor import repository_root

        return repository_root() / "outputs" / "agent" / mission_id / "market"

    def _invoke(self, plan: SkillPlan, extra: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.runner(
                {
                    **plan.parameters,
                    "skill_root": str(self.skill_root),
                    "python": self.python,
                    **extra,
                }
            )
        except Exception as exc:  # runner boundary is normalized, never leaks
            return {
                "status": "UNAVAILABLE",
                "failure_class": "ADAPTER_FAILURE",
                "diagnostics": [f"overseas runner raised: {type(exc).__name__}: {exc}"],
            }

    def _result_from_payload(
        self,
        plan: SkillPlan,
        payload: dict[str, Any],
        started: datetime,
        *,
        attempt_no: int,
        executed: bool,
    ) -> SkillRunResult:
        project_dir = Path(plan.parameters["project_dir"])
        # 采集轮结束后驱动 Stage 5-8 生产；必须赶在 harvest 之前，
        # 否则本轮结果的 artifact_refs 拿不到新产出的交付物。
        if executed and str(payload.get("status", "")) in {"OK", "PARTIAL"}:
            produced = self.produce_deliverables(project_dir)
            payload = {**payload, "diagnostics": [
                *[str(item) for item in payload.get("diagnostics", [])],
                *[f"production: {line}" for line in produced.get("diagnostics", [])],
            ]}
        harvested = self.harvest(project_dir)
        status = SkillRunStatus(payload.get("status", "PARTIAL"))
        if status == SkillRunStatus.UNAVAILABLE:
            return self._blocked(
                plan, started,
                FailureClass(payload.get("failure_class", "ADAPTER_FAILURE")),
                "\n".join(payload.get("diagnostics", [])),
            )
        attempt = SkillAttempt(
            attempt_id=new_sortable_id("MKT-ATT"),
            attempt_no=attempt_no,
            executed=executed,
            strategy_summary=str(payload.get("strategy", "")),
            queries=[str(query) for query in payload.get("recovery_queries", [])],
            source_categories=[str(category) for category in payload.get("source_categories", [])],
            completed_at=_utc_now(),
        )
        ledger = harvested["ledger_rows"]
        issues = harvested["issues_rows"]
        gaps = [
            {"source": "evidence_issues.csv", "row": row}
            for row in issues
        ] + [
            {"source": "data_gap_log.md", "line": line}
            for line in harvested["gap_log_lines"] if line.strip()
        ]
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=self.skill_name,
            goal_ids=list(plan.goal_ids),
            status=status,
            # 子进程失败时把 stderr 尾部带入结果，否则编排层只能看到
            # EXHAUSTED 而拿不到任何诊断信息。
            diagnostics=[str(item) for item in payload.get("diagnostics", [])],
            # 只导出真正抽取到值的行：00_Source_Ledger 同时保存“只有来源、
            # 没有抽取值”的采集空壳，原样导出会让导入层收到几十条零事实行
            # （观测：88 行全部 raw_value 为空），白烧入库与评估预算。
            evidence_exports=[
                row for row in ledger if str(row.get("raw_value") or "").strip()
            ][:5000],
            source_refs=[row.get("source_id", "") for row in ledger if row.get("source_id")],
            artifact_refs=list(harvested.get("artifact_refs", [])),
            coverage_metrics={
                "ledger_rows": len(ledger),
                "unique_sources": len({row.get("source_id") for row in ledger if row.get("source_id")}),
                "unique_domains": len({row.get("root_domain") for row in ledger if row.get("root_domain")}),
                "attempt_rows": len(harvested["journal_rows"]),
                "scan_rows": len(harvested["scan_rows"]),
            },
            quality_metrics={
                "stage_status": harvested["stage_status"],
                "approval": self.check_approval(project_dir),
            },
            gaps=gaps,
            attempts=[attempt],
            started_at=started,
            completed_at=_utc_now(),
        )

    @staticmethod
    def _blocked(
        plan: SkillPlan, started: datetime, failure_class: FailureClass, detail: str
    ) -> SkillRunResult:
        return SkillRunResult(
            skill_run_id=new_sortable_id("SKILLRUN"),
            skill_name=SkillName.OVERSEAS_MARKET_RESEARCH,
            goal_ids=list(plan.goal_ids),
            status=SkillRunStatus.BLOCKED,
            failure_class=failure_class,
            diagnostics=[detail],
            started_at=started,
            completed_at=_utc_now(),
        )

    # -- default (live) runner --------------------------------------------------

    def _default_runner(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Live path: initialize project, write R1/R2/R3 tasks, run collection gates.

        Every upstream gate keeps working; nothing here overrides approval or
        the anti-fake-completion checks.
        """
        project_dir = Path(spec["project_dir"])
        region = spec.get("region") or "target"
        category = spec.get("category") or "energy storage"
        # 初始化条件必须看 init 的直接产物（00_Source_Ledger.csv 等模板骨架），
        # 不能看 00_Research_Approval.csv：ensure_approved 在 runner 之前就已把
        # 审批记录落盘，旧条件会让 init 永久跳过 → 无 ledger 骨架 → 采集再成功
        # 也是 ledger_rows=0，目标全部 EXHAUSTED 且零交付物。
        if not (project_dir / "00_Source_Ledger.csv").is_file():
            init_cmd = [
                self.python, str(self.skill_root / "scripts" / "init_research_project.py"),
                "--project-dir", str(project_dir),
                "--region", region,
                "--category", category,
            ]
            subprocess.run(init_cmd, check=False, capture_output=True, text=True)
        approval = self.check_approval(project_dir)
        if not approval["approved"]:
            return {
                "status": "BLOCKED",
                "failure_class": "AUTH_REQUIRED",
                "diagnostics": [approval["detail"]],
            }
        self._write_tasks(spec, project_dir)
        collect_cmd = [
            self.python, str(self.skill_root / "scripts" / "run_workflow.py"),
            "--project-dir", str(project_dir),
            "--stages", "0-4",
            "--check",
            "--collect",
            # --json-log 必须带路径参数（脚本定义为 positional 值），裸传会导致
            # argparse 直接报错退出，整个采集子进程 0.3 秒失败。
            "--json-log", str(project_dir / "workflow_run.json"),
        ]
        # Popen (not subprocess.run) so stop() can kill the tree on demand.
        proc = subprocess.Popen(collect_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._procs[str(project_dir)] = proc
        try:
            stdout, stderr = proc.communicate()
        finally:
            self._procs.pop(str(project_dir), None)
        diagnostics: list[str] = []
        if stderr and stderr.strip():
            diagnostics.append(stderr.strip()[-2000:])
        if proc.returncode != 0:
            # 子进程非零退出（如 argparse 报错）时必须暴露原因，否则上层只看到
            # 目标 EXHAUSTED 而拿不到任何可诊断信息；同时带上命令与 stdout 尾部。
            diagnostics.insert(
                0,
                f"run_workflow.py exited with code {proc.returncode}; "
                f"cmd={' '.join(collect_cmd)}; stdout_tail={stdout.strip()[-500:]}",
            )
        # 采集后把成功结果登记进台账：否则 ledger 永远 0 行，编排层判零证据。
        try:
            registered = register_sources_from_captures(project_dir)
        except Exception as exc:  # 登记失败不阻断交付，但要可见
            diagnostics.append(f"ledger registration failed: {type(exc).__name__}: {exc}")
        else:
            if registered:
                diagnostics.append(f"registered {registered} new sources into 00_Source_Ledger.csv")
        # 额度假成功体检：journal 按失败分类记台账；insufficient_balance 大量出现时，
        # 继续恢复轮只会空烧，必须把原因顶到诊断首位让编排层/用户可见。
        journal_rows = _read_csv_rows(project_dir / "13_Collection_Attempt_Journal.csv")
        quota_failures = sum(1 for row in journal_rows if row.get("error_class") == "insufficient_balance")
        if quota_failures >= 5:
            diagnostics.insert(
                0,
                f"anysearch quota exhausted: {quota_failures} attempts failed with insufficient_balance; "
                "collection cannot progress until quota refreshes",
            )
        return {
            "status": "OK" if proc.returncode == 0 else "PARTIAL",
            "diagnostics": diagnostics,
            "strategy": "default overseas collection workflow",
            "recovery_queries": list(spec.get("recovery_queries", [])),
            "source_categories": list(spec.get("source_categories", [])),
        }

    def _write_tasks(self, spec: dict[str, Any], project_dir: Path) -> None:
        """Materializes R1/R2/R3 collection tasks from the mission's market goals.

        Adopts the skill's collection_quantity_policy floors (round floors per
        market goal family) instead of hardcoded targets — the skill's
        anti-under-collection gates then compare against the real policy.
        """
        tasks_path = project_dir / "02_Web_Collection_Tasks.csv"
        if tasks_path.is_file() and _read_csv_rows(tasks_path):
            return  # operator/plan already authored tasks; never overwrite
        goal_specs = spec.get("goal_specs") or []
        region = spec.get("region") or "target"
        category = spec.get("category") or "energy storage"
        floors = self._policy_floors()
        rows = []
        sequence = 1
        for goal in goal_specs:
            family = self._policy_family_for(goal.get("name", ""), floors)
            for round_number in (1, 2, 3):
                floor = ((floors.get(family) or {}).get("rounds") or {}).get(str(round_number)) or {}
                rows.append({
                    "task_id": f"T{sequence:03d}",
                    "stage": "2",
                    "platform": "",
                    "market": region,
                    "language": "zh-CN",
                    "goal_family": family,
                    "collection_goal": f"{goal['name']}（R{round_number}）",
                    "target_geography": region,
                    "target_brand": "",
                    "exact_model": "",
                    "identifier_type": "",
                    "identifier_value": "",
                    "starting_url_or_query": f"{region} {category} {goal['name']}",
                    "required_tool": "anysearch",
                    "source_tier": "1",
                    "planned_fields": goal["description"],
                    "completion_contract": "",
                    "target_unique_sources": str(floor.get("min_unique_sources", 2)),
                    "actual_unique_sources": "0",
                    "target_records": str(floor.get("min_records", 3)),
                    "actual_records": "0",
                    "source_type_count": str(floor.get("min_source_types", "")),
                    "platform_count": "",
                    "primary_source_count": str(floor.get("min_primary_sources", "")),
                    "coverage_requirement": "",
                    "critical_claim_count": "",
                    "dual_sourced_claim_count": "",
                    "remaining_high_priority_count": "",
                    "no_new_high_priority_batches": "",
                    "count_evidence_refs": "",
                    "platform_limit_evidence": "",
                    "quantity_exception_type": "",
                    "quantity_exception_refs": "",
                    "round": str(round_number),
                    "round_goal": {1: "coverage 广度", 2: "structured depth", 3: "triangulation 双源验证"}[round_number],
                    "output_file": "",
                    "raw_capture_path": "",
                    "saturation_evidence": "",
                    "status": "pending",
                    "notes": "generated by Energy Research Agent adapter; floors from collection_quantity_policy",
                })
                sequence += 1
        fieldnames = list(rows[0].keys()) if rows else []
        with tasks_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _policy_floors() -> dict[str, dict[str, dict[str, int]]]:
        """Round floors per market goal family from the vendored policy.

        ``families.<family>.rounds.<1|2|3>`` carries the quantity floors;
        ``market_goal_families`` is the list of valid market family names.
        """
        from energy_research_agent.vendor import embedded_skill_root

        policy_path = (
            embedded_skill_root("overseas-energy-market-research")
            / "assets" / "config" / "collection_quantity_policy.yaml"
        )
        try:
            import yaml as _yaml

            policy = _yaml.safe_load(policy_path.read_text(encoding="utf-8"))
            return policy.get("families", {})
        except Exception:
            return {}

    @staticmethod
    def _policy_family_for(goal_name: str, floors: dict) -> str:
        """Keyword map from goal name to the policy's market family."""
        if not floors:
            return "market"
        name = goal_name or ""
        for keyword, family in (
            ("规模", "market_size_and_demand"), ("需求", "market_size_and_demand"),
            ("政策", "policy_tariff_and_grid"), ("电价", "policy_tariff_and_grid"),
            ("准入", "policy_tariff_and_grid"),
            ("客户", "customer_segments_and_use_cases"), ("场景", "customer_segments_and_use_cases"),
            ("竞争", "competitor_landscape"), ("对标", "competitor_landscape"),
            ("认证", "compliance_and_certification"),
            ("渠道", "channel_and_service"), ("服务", "channel_and_service"),
            ("经济", "economics_and_business_model"), ("商业", "economics_and_business_model"),
        ):
            if keyword in name and family in floors:
                return family
        return next(iter(floors), "market")
