from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from _common import now_iso, read_csv, write_csv


OUTPUT_FIELDS = [
    "parameter_id",
    "brand",
    "exact_model",
    "parameter_group",
    "parameter_name",
    "raw_value",
    "unit",
    "source_priority",
    "source_url",
    "local_file_path",
    "local_file_location",
    "access_or_extraction_date",
    "identifier",
    "verification_status",
    "web_source_reason",
    "notes",
]

PAIR_RE = re.compile(r"^\s*([^:：]{2,80})\s*[:：]\s*(.{1,300})\s*$")


def clean(value) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def make_row(
    *,
    parameter_id: str,
    brand: str,
    exact_model: str,
    parameter_name: str,
    raw_value: str,
    local_file_path: Path,
    local_file_location: str,
    identifier: str,
    notes: str = "",
) -> dict[str, str]:
    return {
        "parameter_id": parameter_id,
        "brand": brand,
        "exact_model": exact_model,
        "parameter_group": "",
        "parameter_name": parameter_name,
        "raw_value": raw_value,
        "unit": "待核实",
        "source_priority": "local file",
        "source_url": "",
        "local_file_path": str(local_file_path),
        "local_file_location": local_file_location,
        "access_or_extraction_date": now_iso(),
        "identifier": identifier,
        "verification_status": "local_file_extracted",
        "web_source_reason": "",
        "notes": notes,
    }


def infer_pair_from_cells(cells: list[str]) -> tuple[str, str] | None:
    values = [clean(cell) for cell in cells if clean(cell)]
    if len(values) >= 2:
        return values[0], values[1]
    if len(values) == 1:
        match = PAIR_RE.match(values[0])
        if match:
            return clean(match.group(1)), clean(match.group(2))
    return None


def extract_csv(path: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        reader = csv.reader(f, dialect)
        for row_index, cells in enumerate(reader, start=1):
            pair = infer_pair_from_cells(cells)
            if pair:
                rows.append((pair[0], pair[1], f"row {row_index}"))
    return rows


def extract_xlsx(path: Path) -> list[tuple[str, str, str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for .xlsx extraction") from exc

    rows: list[tuple[str, str, str]] = []
    workbook = load_workbook(path, data_only=True, read_only=True)
    for sheet in workbook.worksheets:
        for row_index, cells in enumerate(sheet.iter_rows(values_only=True), start=1):
            pair = infer_pair_from_cells([clean(cell) for cell in cells])
            if pair:
                rows.append((pair[0], pair[1], f"sheet={sheet.title}; row={row_index}"))
    workbook.close()
    return rows


def extract_docx(path: Path) -> list[tuple[str, str, str]]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required for .docx extraction") from exc

    rows: list[tuple[str, str, str]] = []
    document = Document(path)
    for paragraph_index, paragraph in enumerate(document.paragraphs, start=1):
        match = PAIR_RE.match(clean(paragraph.text))
        if match:
            rows.append((clean(match.group(1)), clean(match.group(2)), f"paragraph {paragraph_index}"))
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            pair = infer_pair_from_cells([cell.text for cell in row.cells])
            if pair:
                rows.append((pair[0], pair[1], f"table={table_index}; row={row_index}"))
    return rows


def extract_pdf(path: Path) -> list[tuple[str, str, str]]:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for .pdf extraction") from exc

    rows: list[tuple[str, str, str]] = []
    with pymupdf.open(path) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            for line_index, line in enumerate(text.splitlines(), start=1):
                match = PAIR_RE.match(clean(line))
                if match:
                    rows.append((clean(match.group(1)), clean(match.group(2)), f"page={page_index}; line={line_index}"))
            tables = page.find_tables().tables
            for table_index, table in enumerate(tables, start=1):
                for row_index, cells in enumerate(table.extract() or [], start=1):
                    pair = infer_pair_from_cells([clean(cell) for cell in cells])
                    if pair:
                        rows.append((pair[0], pair[1], f"page={page_index}; table={table_index}; row={row_index}"))
    return rows


def extract_file(path: Path) -> list[tuple[str, str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return extract_csv(path)
    if suffix in {".xlsx", ".xlsm"}:
        return extract_xlsx(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import product parameters from user-provided local files into 04_Product_Parameters.csv.")
    parser.add_argument("--project-dir", default=".", help="Research project directory.")
    parser.add_argument("--input-file", action="append", required=True, help="Local parameter file. Repeat for multiple files.")
    parser.add_argument("--brand", required=True)
    parser.add_argument("--exact-model", required=True)
    parser.add_argument("--identifier", required=True, help="Model identifier, SKU, ASIN, or user-defined local identifier.")
    parser.add_argument("--output", default="04_Product_Parameters.csv", help="Output CSV path relative to project dir unless absolute.")
    parser.add_argument("--append", action="store_true", help="Append to existing parameter table.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output

    existing_rows: list[dict[str, str]] = []
    if args.append and output.exists():
        _, existing_rows = read_csv(output)

    new_rows: list[dict[str, str]] = []
    counter = len(existing_rows) + 1
    for raw_path in args.input_file:
        path = Path(raw_path).expanduser().resolve()
        extracted = extract_file(path)
        for parameter_name, raw_value, location in extracted:
            if not parameter_name or not raw_value:
                continue
            new_rows.append(
                make_row(
                    parameter_id=f"P{counter:04d}",
                    brand=args.brand,
                    exact_model=args.exact_model,
                    parameter_name=parameter_name,
                    raw_value=raw_value,
                    local_file_path=path,
                    local_file_location=location,
                    identifier=args.identifier,
                    notes="自动抽取候选参数，交付前需人工核对字段含义与单位。",
                )
            )
            counter += 1

    write_csv(output, OUTPUT_FIELDS, existing_rows + new_rows)
    print(f"Imported {len(new_rows)} candidate parameter rows into: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
