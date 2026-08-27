"""数学建模链机械门验证（G1/G2/G3/G6；G2.5/G4.5/G4 基于 create_modeling_artifacts 的决策校验）。

门表（与 references/modeling-chain-adaptation.md 一致）：
- G1 PROBLEM_PARSED: planning/parse/ + planning/classification/ 存在，无哨兵
- G2 METHOD_VALIDATED: 每 Qx methods/Qx/qx_method_candidates.md 含 2-4 候选（按编号去重）+ PoC + baseline
- G3 CODE_REVIEWED: code/Qx/reviews/ 评审 ≥5 pass 项（行首格式，排除 NOT PASS）+ run_summary.json
- G2.5★ 人工门: qx_method_choice 决策工件 DECIDED ∧ decided_by=human（final 模式非 DECIDED 即 fail）
- G4 RESULTS_FROZEN: frozen_numbers.json 可读且含 frozen_at 且新鲜 + qx_package_signoff DECIDED
- G4.5★ 人工门: qx_result_verdict / qx_stability_verdict / qx_method_explanation 全 DECIDED
- G6 AUDIT_LAYER_PASSED: audit/consistency|completeness|quality_assurance.md 含整行 PASSED 判定

analysis_branch 非 modeling 或缺少 manifest（视为 auto）→ note 提示，不 FAIL。
"""
import argparse
import json
import re
from pathlib import Path

from _common import Issue, add_common_args, print_report
from create_modeling_artifacts import (
    check_frozen_freshness,
    modeling_root,
    parse_frontmatter,
    validate_decisions,
)

SENTINELS = ("[AI-DRAFT", "[MODELER INPUT NEEDED", "<<<HUMAN>>>")
BASELINE_TOKENS = ("baseline", "基准", "baseline model")
POC_TOKENS = ("poc", "proof of concept", "prototype", "可行性")

# G2.5 只查方法抉择；G4.5 只查三个 verdict；qx_package_signoff 归 G4
G25_DECISION_IDS = {"qx_method_choice"}
G45_DECISION_IDS = {"qx_result_verdict", "qx_stability_verdict", "qx_method_explanation"}
SIGNOFF_DECISION_ID = "qx_package_signoff"

_CANDIDATE_HEAD_RE = re.compile(r"(?im)^#{2,3}\s*(?:candidate|method|方案|候选)\s+(\d+)\s*[:：]?(\s|$)")
_PASS_ITEM_RE = re.compile(r"(?im)^\s*(?:\d+[.、)]\s*)?[-*]?\s*(?:PASS|通过)\b(?!ED)")
_NOT_PASS_RE = re.compile(r"(?im)^\s*(?:\d+[.、)]\s*)?[-*]?\s*(?:NOT\s+PASS|FAIL(?:ED)?)\b")
_G6_PASSED_RE = re.compile(r"(?im)^\s*(?:verdict|status|结论|结果)?\s*[:：]?\s*PASSED\s*$")
_G6_NOT_PASSED_RE = re.compile(r"(?im)^\s*(?:verdict|status|结论|结果)?\s*[:：]?\s*NOT\s+PASSED\s*$")
QX_DIR_RE = re.compile(r"^Q\d+$")


def _find_qx_dirs(root: Path) -> list[Path]:
    methods = root / "methods"
    if not methods.is_dir():
        return []
    return sorted(path for path in methods.iterdir() if path.is_dir() and QX_DIR_RE.match(path.name))


def _has_sentinel(text: str) -> bool:
    return any(sentinel in text for sentinel in SENTINELS)


def check_g1(root: Path) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    parse_dir = root / "planning" / "parse"
    classification_dir = root / "planning" / "classification"
    if not parse_dir.is_dir() or not any(parse_dir.iterdir()):
        issues.append(("fail", "G1: planning/parse/ missing or empty - run problem-parser first"))
    if not classification_dir.is_dir() or not any(classification_dir.iterdir()):
        issues.append(("fail", "G1: planning/classification/ missing or empty - run problem-classifier first"))
    planning_dir = root / "planning"
    if planning_dir.is_dir():
        for path in planning_dir.rglob("*.md"):
            if _has_sentinel(path.read_text(encoding="utf-8", errors="replace")):
                issues.append(("fail", f"G1: sentinel in {path.relative_to(root)} - resolve [MODELER INPUT NEEDED]/[AI-DRAFT]"))
    return issues


def _count_candidates(text: str) -> int:
    """候选计数：整行标题 + 编号，按编号去重（小节 '### Candidate 1 feasibility' 不重复计）。"""
    numbers = [int(match.group(1)) for match in _CANDIDATE_HEAD_RE.finditer(text)]
    return len(set(numbers))


def check_g2(root: Path) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    qx_dirs = _find_qx_dirs(root)
    if not qx_dirs:
        issues.append(("fail", "G2: no methods/Qx/ directories - run method-selector per subquestion"))
        return issues
    for qx_dir in qx_dirs:
        qx = qx_dir.name
        candidates = qx_dir / "qx_method_candidates.md"
        if not candidates.is_file():
            issues.append(("fail", f"G2: {qx}: qx_method_candidates.md missing"))
            continue
        text = candidates.read_text(encoding="utf-8", errors="replace")
        count = _count_candidates(text)
        if not (2 <= count <= 4):
            issues.append(("fail", f"G2: {qx}: expected 2-4 method candidates, found {count}"))
        if not any(token in text.casefold() for token in POC_TOKENS):
            issues.append(("fail", f"G2: {qx}: candidates lack PoC/proof-of-concept section (<=30-line prototype)"))
        if not any(token in text.casefold() for token in BASELINE_TOKENS):
            issues.append(("fail", f"G2: {qx}: candidates lack a baseline definition"))
    return issues


def _count_pass_items(text: str) -> int:
    """评审 pass 项：只数行首 'PASS'/'通过' 项目行（排除 NOT PASS / FAIL / 总结行）。"""
    if _NOT_PASS_RE.search(text):
        return 0
    return len(_PASS_ITEM_RE.findall(text))


def check_g3(root: Path) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    qx_dirs = _find_qx_dirs(root)
    for qx_dir in qx_dirs:
        qx = qx_dir.name
        review_dir = root / "code" / qx / "reviews"
        best_pass = -1
        best_review: str | None = None
        if review_dir.is_dir():
            for review in review_dir.glob("qx_*_review.md"):
                pass_items = _count_pass_items(review.read_text(encoding="utf-8", errors="replace"))
                if pass_items > best_pass:
                    best_pass = pass_items
                    best_review = review.name
        if best_review is None:
            issues.append(("fail", f"G3: {qx}: no code review found (code/Qx/reviews/qx_*_review.md)"))
        elif best_pass < 5:
            issues.append(("fail", f"G3: {qx}: {best_review} has {best_pass} explicit pass items (<5 required)"))
        experiments = root / "results" / qx / "experiments"
        run_summaries = list(experiments.glob("round*/run_summary.json")) if experiments.is_dir() else []
        if not run_summaries:
            issues.append(("fail", f"G3: {qx}: run_summary.json missing (results/Qx/experiments/roundN/)"))
        else:
            for summary in run_summaries:
                try:
                    json.loads(summary.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    issues.append(("fail", f"G3: {qx}: {summary} is not valid JSON"))
    return issues


def check_g4(root: Path, mode: str) -> list[tuple[str, str]]:
    issues = list(check_frozen_freshness(root))
    qx_dirs = _find_qx_dirs(root)
    for qx_dir in qx_dirs:
        qx = qx_dir.name
        frozen = root / "results" / qx / "reports" / "frozen_numbers.json"
        if not frozen.is_file():
            issues.append(("fail", f"G4: {qx}: frozen_numbers.json missing - freeze after human verdicts"))
        else:
            try:
                data = json.loads(frozen.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(("fail", f"G4: {qx}: frozen_numbers.json unreadable ({exc})"))
                data = {}
            if not data.get("frozen_at"):
                issues.append(("fail", f"G4: {qx}: frozen_numbers.json missing frozen_at - freeze convention violated"))
        signoff = qx_dir / "decisions" / "solution-package-builder_modeler_decision.md"
        if not signoff.is_file():
            issues.append(("fail", f"G4: {qx}: qx_package_signoff decision missing"))
        elif mode == "final":
            fm = parse_frontmatter(signoff)
            if fm.get("decision_id") != SIGNOFF_DECISION_ID or fm.get("status") != "DECIDED" or fm.get("decided_by") != "human":
                issues.append(("fail", f"G4: {qx}: qx_package_signoff not DECIDED by human"))
    return issues


def check_g6(root: Path) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    audit_dir = root / "audit"
    required = {
        "consistency.md": "consistency-auditor",
        "completeness.md": "completeness-auditor",
        "quality_assurance.md": "quality-assurance-auditor",
    }
    for filename, auditor in required.items():
        path = audit_dir / filename
        if not path.is_file():
            issues.append(("fail", f"G6: audit/{filename} missing - run {auditor}"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _G6_NOT_PASSED_RE.search(text) or not _G6_PASSED_RE.search(text):
            issues.append(("fail", f"G6: audit/{filename} lacks an explicit PASSED verdict line"))
        if _has_sentinel(text):
            issues.append(("fail", f"G6: audit/{filename} still contains sentinels"))
    return issues


def _finalize_human_gates(issues: list[tuple[str, str]], mode: str) -> list[tuple[str, str]]:
    """draft 模式：非 DECIDED 保持 warn（门开着）；final 模式：升为 fail。"""
    if mode != "final":
        return issues
    upgraded: list[tuple[str, str]] = []
    for level, message in issues:
        if level == "warn" and "(not DECIDED)" in message:
            upgraded.append(("fail", message.replace("(not DECIDED)", "(not DECIDED - final mode requires human verdict)")))
        else:
            upgraded.append((level, message))
    return upgraded


def validate(project_dir: Path, mode: str = "draft") -> list[Issue]:
    project_root = project_dir.resolve()
    root = modeling_root(project_root)
    issues: list[Issue] = []

    # 与 validate_stage_gate.check_modeling_gate 一致：缺 manifest 视为 auto（建模未启用）
    manifest_path = project_root / "project_manifest.json"
    branch = "auto"
    if manifest_path.is_file():
        try:
            branch = str(json.loads(manifest_path.read_text(encoding="utf-8-sig")).get("analysis_branch", "auto")).strip() or "auto"
        except (OSError, json.JSONDecodeError):
            branch = "auto"
    if branch != "modeling":
        issues.append(Issue("note", "modeling_workspace", "analysis_branch", f"analysis_branch={branch}; modeling chain not engaged - not a failure"))
        return issues
    if not root.is_dir():
        issues.append(Issue("note", "modeling_workspace", "intermediate/modeling", "No modeling workspace - modeling branch not engaged; not a failure"))
        return issues

    g25 = _finalize_human_gates(validate_decisions(root, G25_DECISION_IDS), mode)
    g45 = _finalize_human_gates(validate_decisions(root, G45_DECISION_IDS), mode)
    gates: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("G1", "PROBLEM_PARSED", check_g1(root)),
        ("G2", "METHOD_VALIDATED", check_g2(root)),
        ("G2.5", "METHOD_CHOSEN_BY_HUMAN", g25),
        ("G3", "CODE_REVIEWED", check_g3(root)),
        ("G4", "RESULTS_FROZEN", check_g4(root, mode)),
        ("G4.5", "RESULTS_JUDGED_BY_HUMAN", g45),
        ("G6", "AUDIT_LAYER_PASSED", check_g6(root)),
    ]
    for gate, name, gate_issues in gates:
        fails = [item for item in gate_issues if item[0] == "fail"]
        warns = [item for item in gate_issues if item[0] == "warn"]
        if not fails and not warns:
            issues.append(Issue("note", gate, name, "PASS"))
        for level, message in gate_issues:
            issues.append(Issue(level, gate, name, message))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate modeling chain mechanical gates G1/G2/G3/G6 (G2.5/G4.5/G4 via create_modeling_artifacts).")
    parser.add_argument("--project-dir", required=True, help="Project directory containing intermediate/modeling workspace.")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft", help="final mode requires DECIDED human verdicts and signoff.")
    add_common_args(parser)
    args = parser.parse_args()
    return print_report("Modeling chain gate validation", validate(Path(args.project_dir).resolve(), mode=args.mode), json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
