from __future__ import annotations

"""安装自检：依赖 / 内嵌组件 / 门禁脚本 / 台账初始化。

用法: python scripts/verify_install.py [--project-dir <临时项目>]
输出 PASS/FAIL 报告；任一失败返回非 0 退出码（供 install 脚本判断）。
"""
import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

# FIX round-2 P2-9: capability lists come from the requirements manifests
# via common.requirements — no hand-maintained module lists (drift source).
from common.requirements import core_packages, optional_packages

REQUIRED_MODULES = core_packages()
OPTIONAL_MODULES = optional_packages()

EXPECTED_MODELING_DOCS = 24
EXPECTED_MANIFEST = "assets/config/integration_manifest.yaml"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def check_dependencies() -> list[str]:
    problems = []
    for module in REQUIRED_MODULES:
        if importlib.util.find_spec(module) is None:
            problems.append(f"missing Python module: {module}")
    return problems


def check_optional_dependencies() -> list[str]:
    """可选增强缺失：提示安装 requirements-optional.txt，不 FAIL。"""
    notes = []
    for module in OPTIONAL_MODULES:
        if importlib.util.find_spec(module) is None:
            notes.append(f"optional module not installed: {module} (pip install -r requirements-optional.txt for the feature)")
    return notes


def check_embedded_components(root: Path) -> list[str]:
    problems = []
    anysearch_cli = root / "scripts" / "anysearch" / "anysearch_cli.py"
    if not anysearch_cli.is_file():
        problems.append("missing embedded anysearch CLI (scripts/anysearch/anysearch_cli.py)")
    else:
        try:
            completed = subprocess.run(
                [sys.executable, str(anysearch_cli), "doc"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            if completed.returncode or "AnySearch" not in completed.stdout:
                problems.append("embedded anysearch CLI 'doc' did not run correctly")
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"embedded anysearch CLI check failed: {exc}")
    chain_dir = root / "references" / "modeling_chain"
    docs = [p for p in chain_dir.glob("*.md") if p.name != "README_embedded.md"] if chain_dir.is_dir() else []
    if len(docs) != EXPECTED_MODELING_DOCS:
        problems.append(f"modeling chain docs: expected {EXPECTED_MODELING_DOCS}, found {len(docs)}")
    if not (root / EXPECTED_MANIFEST).is_file():
        problems.append(f"missing integration manifest ({EXPECTED_MANIFEST})")
    for gate in ("validate_stage_gate.py", "validate_collection_attempts.py", "validate_modeling_chain_gates.py"):
        if not (root / "scripts" / gate).is_file():
            problems.append(f"missing gate script: scripts/{gate}")
    return problems


def check_journal_init(root: Path, project_dir: Path) -> list[str]:
    problems = []
    try:
        sys.path.insert(0, str(root / "scripts"))
        from web_collection.journal import CollectionJournal

        journal = CollectionJournal(project_dir, strict=True)
        attempt_id = journal.append(
            task_id="verify", round_number="1", round_goal="coverage", tool="anysearch",
            action="search", query_or_url="install self-check", status="success",
            raw_capture_path="", session="verify",
        )
        if not attempt_id or not journal.path.is_file():
            problems.append("attempt journal did not initialize")
        journal_path = journal.path
        journal_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"attempt journal init failed: {exc}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Install self-check for overseas-energy-market-research.")
    parser.add_argument("--project-dir", default=None, help="Temporary project dir for journal init (default: temp).")
    args = parser.parse_args()

    root = skill_root()
    project_dir = Path(args.project_dir) if args.project_dir else Path(tempfile.mkdtemp(prefix="verify_install_"))
    project_dir.mkdir(parents=True, exist_ok=True)

    print(f"==> verify_install for {root}")
    checks: dict[str, list[str]] = {
        "dependencies": check_dependencies(),
        "embedded_components": check_embedded_components(root),
        "journal_init": check_journal_init(root, project_dir),
    }
    optional_notes = check_optional_dependencies()
    for note in optional_notes:
        print(f"[INFO] {note}")
    total = 0
    failed = 0
    for name, problems in checks.items():
        total += 1
        if problems:
            failed += 1
            print(f"[FAIL] {name}:")
            for problem in problems:
                print(f"       - {problem}")
        else:
            print(f"[PASS] {name}")
    if failed:
        print(f"==> verify_install: FAIL ({failed}/{total} checks failed)")
        return 1
    print("==> verify_install: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
