from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from _common import Issue, add_common_args, print_report, read_json, split_ids


METHOD_ID = "embedded-market-insight-five-views-v1"
REPORT_PATH = Path("intermediate/market-insight/market_insight_report.md")
REQUIRED_HEADINGS = (
    "决策问题与证据边界",
    "看宏观",
    "看行业",
    "看客户",
    "看竞争",
    "看自己",
    "跨视角综合与反证",
    "So What",
    "优先行动建议",
    "风险与不确定性",
)
EVIDENCE_RE = re.compile(r"【证据\s*[:：]\s*([^】]+)】")
PLACEHOLDER_RE = re.compile(r"\[\[[^\]]+\]\]")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def project_evidence_ids(project_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in project_dir.glob("*.csv"):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                id_fields = [name for name in (reader.fieldnames or []) if name == "id" or name.endswith("_id")]
                for row in reader:
                    for field in id_fields:
                        ids.update(split_ids(row.get(field, "")))
        except (OSError, UnicodeError, csv.Error):
            continue
    return {item for item in ids if item}


def validate(project_dir: Path, mode: str = "draft") -> list[Issue]:
    manifest = read_json(project_dir / "project_manifest.json", {})
    branch = str(manifest.get("analysis_branch") or "auto").strip().lower()
    if branch == "modeling":
        return []
    if branch == "auto":
        if mode == "final":
            return [Issue("fail", "manifest", "analysis_branch", "Resolve analysis_branch to modeling or market-insight before final Stage 6")]
        return []
    if branch != "market-insight":
        return [Issue("fail", "manifest", "analysis_branch", f"Unsupported analysis branch: {branch}")]

    report_path = project_dir / REPORT_PATH
    if not report_path.exists():
        return [Issue("fail", "market-insight", str(REPORT_PATH), "Embedded market-insight report is missing")]

    text = report_path.read_text(encoding="utf-8-sig")
    frontmatter = parse_frontmatter(text)
    issues: list[Issue] = []
    if frontmatter.get("method_id") != METHOD_ID:
        issues.append(Issue("fail", "market-insight", "method_id", f"Expected {METHOD_ID}"))
    if frontmatter.get("analysis_branch") != "market-insight":
        issues.append(Issue("fail", "market-insight", "analysis_branch", "Report frontmatter must declare market-insight"))

    outline_version = str(manifest.get("outline_version") or "").strip()
    if frontmatter.get("outline_version") != outline_version:
        issues.append(Issue("fail", "market-insight", "outline_version", "Report outline_version must match project_manifest.json"))
    if mode == "final" and frontmatter.get("status", "").lower() != "final":
        issues.append(Issue("fail", "market-insight", "status", "Final gate requires status: final"))

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"^##+\s+.*{re.escape(heading)}.*$", text, flags=re.MULTILINE | re.IGNORECASE):
            issues.append(Issue("fail", "market-insight", "section", f"Missing required section: {heading}"))

    implication_count = len(re.findall(r"^###\s+对本企业/产品的启示\s*$", text, flags=re.MULTILINE))
    if implication_count < 5:
        issues.append(Issue("fail", "market-insight", "implications", "Each of the Five Views requires 对本企业/产品的启示"))

    placeholders = PLACEHOLDER_RE.findall(text)
    if mode == "final" and placeholders:
        issues.append(Issue("fail", "market-insight", "placeholders", f"Unresolved template placeholders: {len(placeholders)}"))

    anchors = EVIDENCE_RE.findall(text)
    if mode == "final" and len(anchors) < 5:
        issues.append(Issue("fail", "market-insight", "evidence_anchors", "Final report requires at least five inline evidence anchors"))
    if mode == "final":
        known_ids = project_evidence_ids(project_dir)
        for anchor in anchors:
            for evidence_id in split_ids(anchor):
                if evidence_id not in known_ids:
                    issues.append(Issue("fail", evidence_id, "evidence_anchor", "Evidence ID does not exist in project CSV files"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the embedded Five Views market-insight branch.")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft")
    add_common_args(parser)
    args = parser.parse_args()
    return print_report(
        "Embedded market-insight validation",
        validate(Path(args.project_dir).resolve(), args.mode),
        json_output=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
