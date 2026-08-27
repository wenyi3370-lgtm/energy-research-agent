from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

from _common import now_iso


TEMPLATES = {
    "word": ("assets/templates/word/energy_market_research_report_template.docx", "产品竞品调研报告.docx"),
    "excel": ("assets/templates/excel/energy_market_research_workbook_template.xlsx", "产品竞品调研报告.xlsx"),
    "ppt": ("assets/templates/ppt/energy_market_research_presentation_template.pptx", "产品竞品调研报告.pptx"),
}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def replacements(region: str, category: str, update_date: str, source_scope: str) -> dict[str, str]:
    return {
        "[[目标区域]]": region,
        "[[产品类别]]": category,
        "[[更新日期]]": update_date,
        "[[来源机构/平台清单]]": source_scope,
        "[[项目名称]]": f"{region}{category}产品与行业市场调研",
    }


def replace_text(value: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        value = value.replace(old, new)
    return value


def replace_docx(path: Path, mapping: dict[str, str]) -> None:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required to replace Word placeholders") from exc

    document = Document(path)
    containers = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)

    for paragraph in containers:
        for run in paragraph.runs:
            run.text = replace_text(run.text, mapping)
    document.save(path)


def replace_xlsx(path: Path, mapping: dict[str, str]) -> None:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to replace Excel placeholders") from exc

    workbook = load_workbook(path)
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = replace_text(cell.value, mapping)
    workbook.save(path)


def replace_pptx(path: Path, mapping: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / path.name
        with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".xml"):
                    text = data.decode("utf-8")
                    data = replace_text(text, mapping).encode("utf-8")
                zout.writestr(item, data)
        shutil.copy2(tmp, path)


def build_package(project_dir: Path, region: str, category: str, update_date: str, source_scope: str, prefix: str, force: bool) -> list[Path]:
    output_dir = project_dir / "deliverables"
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = replacements(region, category, update_date, source_scope)

    outputs: list[Path] = []
    for kind, (template_rel, default_name) in TEMPLATES.items():
        template = skill_root() / template_rel
        suffix = Path(default_name).suffix
        output = output_dir / (f"{prefix}{suffix}" if prefix else default_name)
        if output.exists() and not force:
            raise FileExistsError(f"Output already exists: {output}. Use --force to overwrite.")
        shutil.copy2(template, output)
        if kind == "word":
            replace_docx(output, mapping)
        elif kind == "excel":
            replace_xlsx(output, mapping)
        elif kind == "ppt":
            replace_pptx(output, mapping)
        outputs.append(output)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Word/Excel/PPT deliverable package from adapted templates.")
    parser.add_argument("--project-dir", default=".", help="Research project directory.")
    parser.add_argument("--region", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--update-date", default="", help="Visible update date. Defaults to current local timestamp.")
    parser.add_argument("--source-scope", default="待补充：官网、Amazon、零售商、评测网站、用户评论、政策与市场数据源")
    parser.add_argument("--prefix", default="产品竞品调研报告", help="Output filename prefix without extension.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    update_date = args.update_date or now_iso()
    outputs = build_package(
        Path(args.project_dir).resolve(),
        args.region,
        args.category,
        update_date,
        args.source_scope,
        args.prefix,
        args.force,
    )
    for output in outputs:
        print(f"Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
