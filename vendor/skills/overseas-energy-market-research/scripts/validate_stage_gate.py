from __future__ import annotations

import argparse
from pathlib import Path

from _common import Issue, add_common_args, print_report
from validate_collection_tasks import validate as validate_collection_tasks
from validate_deliverables import parse_stages, validate as validate_deliverables
from validate_model_identifiers import validate as validate_model_identifiers
from validate_parameter_sources import validate as validate_parameter_sources
from validate_review_corpus import validate_coding, validate_raw
from validate_source_ledger import validate as validate_source_ledger
from validate_outline_approval import validate as validate_outline_approval
from validate_model_integrity import validate as validate_model_integrity
from validate_market_insight import validate as validate_market_insight
from validate_word_delivery import validate as validate_word_delivery
from validate_excel_delivery import validate as validate_excel_delivery
from validate_presentation_delivery import validate as validate_presentation_delivery
from create_modeling_artifacts import modeling_root


STAGE_VALIDATORS = {
    "0": ("deliverables", "outline_approval", "collection_tasks"),
    "1": ("deliverables", "outline_approval", "source_ledger"),
    "2": ("deliverables", "outline_approval", "model_identifiers"),
    "3": ("deliverables", "outline_approval", "parameter_sources"),
    "4": ("deliverables", "outline_approval", "collection_tasks", "source_ledger", "model_identifiers", "review_corpus"),
    "5": ("deliverables", "outline_approval", "source_ledger", "csv_row_counts", "excel_delivery"),
    "6": ("deliverables", "outline_approval", "model_integrity", "modeling_gate", "market_insight_gate"),
    "7": ("deliverables", "outline_approval", "source_ledger", "model_integrity", "market_insight_gate", "word_delivery", "word_char_count"),
    "8": ("deliverables", "outline_approval", "collection_tasks", "source_ledger", "model_identifiers", "parameter_sources", "review_corpus", "model_integrity", "market_insight_gate", "word_delivery", "csv_row_counts", "excel_delivery", "ppt_delivery"),
}


def prefix(stage: str, source: str, issues: list[Issue]) -> list[Issue]:
    return [
        Issue(issue.level, f"stage-{stage}:{issue.row}", f"{source}.{issue.field}", issue.message)
        for issue in issues
    ]


def safe_run(stage: str, source: str, func) -> list[Issue]:
    try:
        return prefix(stage, source, func())
    except FileNotFoundError as exc:
        return [Issue("fail", f"stage-{stage}", source, f"Missing file: {exc}")]




def validate_csv_row_counts(project_dir: Path, mode: str) -> list[Issue]:
    """机械门禁（2026-08-07 固化）：证据 CSV 行数必须 > 表头数。

    根因：脚本 os.chdir 曾导致数据写入子目录，项目根 CSV 保持模板空壳（仅表头），
    sync_csv_to_excel 与 Word 表格填充读到空模板。final 模式强制；draft 模式仅告警。
    """
    import csv as _csv
    issues: list[Issue] = []
    evidence_csvs = [
        "00_Source_Ledger.csv", "01_Market_Scan.csv", "02_Competitor_List.csv",
        "03_Model_Identifier_Check.csv", "04_Product_Parameters.csv",
        "05_Pricing_Channel.csv", "06_Channel_Service.csv", "07_Raw_Reviews.csv",
        "08_Review_Coding.csv", "09_Integrated_Matrix.csv", "10_SWOT_Opportunity.csv",
        "11_Evidence_Issues.csv",
    ]
    if mode == "final":
        evidence_csvs += ["12_Model_Assumptions.csv", "13_Model_Results.csv", "14_Simulated_Modeling_Data.csv"]
    for name in evidence_csvs:
        path = project_dir / name
        if not path.exists():
            if mode == "final":
                issues.append(Issue("fail", name, "csv_row_counts", "Missing evidence CSV"))
            continue
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                n = sum(1 for _ in _csv.reader(f)) - 1  # 减表头
        except Exception as exc:
            issues.append(Issue("fail", name, "csv_row_counts", f"Unreadable: {exc}"))
            continue
        if n <= 0 and name not in {"11_Evidence_Issues.csv", "14_Simulated_Modeling_Data.csv"}:
            issues.append(
                Issue(
                    "fail" if mode == "final" else "warn",
                    name,
                    "csv_row_counts",
                    f"Only header row (0 data rows) - data likely written to wrong directory",
                )
            )
    return issues


def validate_word_char_count(project_dir: Path, mode: str) -> list[Issue]:
    """机械门禁（2026-08-07 固化）：Word 报告字数校验，总字符 <15,000 即 FAIL。

    根因：曾每章仅 2-3 段导致全文约 1.3 万字符，未达 15,000-30,000 字要求。
    SKILL.md 声明该门禁在 Stage 7 调用，此处注册到 STAGE_VALIDATORS["7"] 强制执行，
    不再依赖人工自觉运行 check_word_char_count.py。final 模式强制；draft 模式告警。
    """
    docs = sorted(
        path for path in project_dir.glob("deliverables/*.docx")
        if not path.name.startswith("~$")
    )
    if not docs:
        return [Issue("fail", "deliverables", "word_report", "No .docx report found in deliverables/")]
    issues: list[Issue] = []
    from docx import Document

    for path in docs:
        doc = Document(str(path))
        text = "".join([(p.text or "") for p in doc.paragraphs])
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    text += cell.text or ""
        total = len(text)
        if total < 15000:
            issues.append(
                Issue(
                    "fail" if mode == "final" else "warn",
                    path.name,
                    "word_char_count",
                    f"{total} chars < 15000 min",
                )
            )
    return issues


def validate_stage(
    project_dir: Path,
    stage: str,
    *,
    mode: str,
    local_files_provided: bool,
    strict_final_files: bool,
) -> list[Issue]:
    issues: list[Issue] = []
    validators = STAGE_VALIDATORS.get(stage)
    if not validators:
        return [Issue("fail", f"stage-{stage}", "stage", "Unknown stage")]

    if "deliverables" in validators:
        strict = strict_final_files and stage == "8" and mode == "final"
        issues.extend(prefix(stage, "deliverables", validate_deliverables(project_dir, [stage], strict)))

    if "outline_approval" in validators:
        issues.extend(safe_run(stage, "outline_approval", lambda: validate_outline_approval(project_dir)))

    if "source_ledger" in validators:
        issues.extend(safe_run(stage, "source_ledger", lambda: validate_source_ledger(project_dir / "00_Source_Ledger.csv")))

    if "collection_tasks" in validators:
        issues.extend(
            safe_run(
                stage,
                "collection_tasks",
                lambda: validate_collection_tasks(
                    project_dir / "02_Web_Collection_Tasks.csv",
                    require_actual=(mode == "final" and int(stage) >= 4),
                ),
            )
        )

    if "model_identifiers" in validators:
        issues.extend(safe_run(stage, "model_identifiers", lambda: validate_model_identifiers(project_dir / "03_Model_Identifier_Check.csv")))

    if "parameter_sources" in validators:
        issues.extend(
            safe_run(
                stage,
                "parameter_sources",
                lambda: validate_parameter_sources(project_dir / "04_Product_Parameters.csv", local_files_provided),
            )
        )

    if "review_corpus" in validators:
        def review_check() -> list[Issue]:
            raw_issues, raw_ids = validate_raw(project_dir / "07_Raw_Reviews.csv", allow_empty=mode == "draft")
            coding_issues = validate_coding(project_dir / "08_Review_Coding.csv", raw_ids)
            return raw_issues + coding_issues

        issues.extend(safe_run(stage, "review_corpus", review_check))

    if "csv_row_counts" in validators:
        issues.extend(
            safe_run(
                stage,
                "csv_row_counts",
                lambda: validate_csv_row_counts(project_dir, mode),
            )
        )

    if "excel_delivery" in validators:
        issues.extend(
            safe_run(
                stage,
                "excel_delivery",
                lambda: validate_excel_delivery(project_dir, mode),
            )
        )

    if "word_char_count" in validators:
        issues.extend(
            safe_run(
                stage,
                "word_char_count",
                lambda: validate_word_char_count(project_dir, mode),
            )
        )

    if "model_integrity" in validators:
        issues.extend(
            safe_run(
                stage,
                "model_integrity",
                lambda: validate_model_integrity(project_dir, allow_empty=mode == "draft"),
            )
        )

    if "modeling_gate" in validators:
        issues.extend(safe_run(stage, "modeling_gate", lambda: check_modeling_gate(project_dir, mode)))

    if "market_insight_gate" in validators:
        issues.extend(
            safe_run(
                stage,
                "market_insight_gate",
                lambda: validate_market_insight(project_dir, mode),
            )
        )

    if "word_delivery" in validators:
        issues.extend(
            safe_run(
                stage,
                "word_delivery",
                lambda: validate_word_delivery(
                    project_dir,
                    Path(__file__).resolve().parents[1],
                    allow_draft=mode == "draft",
                ),
            )
        )

    if "ppt_delivery" in validators:
        issues.extend(
            safe_run(
                stage,
                "ppt_delivery",
                lambda: validate_presentation_delivery(project_dir, mode),
            )
        )

    return issues


def check_modeling_gate(project_dir: Path, mode: str) -> list[Issue]:
    """Modeling chain gates G1/G2/G2.5/G3/G4/G4.5/G6 via validate_modeling_chain_gates.

    Covers human decision gates (decided_by=human), frozen freshness, problem parse,
    method candidates, code review and the three-layer audit. analysis_branch != modeling
    or a missing workspace emits a note and is not a failure.
    """
    from validate_modeling_chain_gates import validate as chain_validate

    return chain_validate(project_dir, mode=mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a stage gate for the domestic/global energy research workflow.")
    parser.add_argument("--project-dir", default=".", help="Project directory.")
    parser.add_argument("--stage", help="Single stage id, e.g. 3.")
    parser.add_argument("--stages", help="Stage range or list, e.g. 0-8 or 1,2,3,6.")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft", help="Draft allows empty review corpus during setup.")
    parser.add_argument("--local-files-provided", choices=["yes", "no"], default="yes")
    parser.add_argument("--strict-final-files", action="store_true", help="Require final Office files for stage 8 final gate.")
    add_common_args(parser)
    args = parser.parse_args()

    if not args.stage and not args.stages:
        parser.error("Provide --stage or --stages.")

    stages = [args.stage] if args.stage else parse_stages(args.stages)
    project_dir = Path(args.project_dir).resolve()
    local_files_provided = args.local_files_provided == "yes"

    issues: list[Issue] = []
    for stage in stages:
        issues.extend(
            validate_stage(
                project_dir,
                stage,
                mode=args.mode,
                local_files_provided=local_files_provided,
                strict_final_files=args.strict_final_files,
            )
        )

    return print_report("Stage gate validation", issues, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
