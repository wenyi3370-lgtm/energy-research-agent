from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from libreoffice_render import build_env, profile_uri, resolve_soffice, run_bounded


FORMULA_ERRORS = {
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#N/A",
    "#NAME?",
    "#NUM!",
    "#NULL!",
}


def remove_fixed_print_scales(path: Path) -> None:
    """Remove LibreOffice's conflicting scale=100 without rewriting formula caches."""
    staged = path.with_name(f".{path.name}.print-layout.tmp")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
        staged, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename.startswith("xl/worksheets/sheet") and info.filename.endswith(".xml"):
                payload = re.sub(rb'\s+scale="\d+"', b"", payload)
            target.writestr(info, payload)
    staged.replace(path)


def restore_consulting_fonts(path: Path) -> None:
    """Undo LibreOffice's CJK font substitution after recalculation.

    LibreOffice replaces Arial with the system CJK font (e.g. Noto Sans SC) for
    cells containing East-Asian text when it re-saves an .xlsx, which breaks the
    consulting-style validator's 'Expected Arial 11 data font' check.  This is a
    zip-level styles.xml edit so formula caches written by the recalculation are
    preserved (openpyxl round-trips would discard them).
    """
    staged = path.with_name(f".{path.name}.font-restore.tmp")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
        staged, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "xl/styles.xml":
                text = payload.decode("utf-8")
                # LibreOffice writes the substituted family into <name val="..."/>.
                # Replace the known CJK substitutions with Arial (family 0 = swiss).
                text = text.replace('<name val="Noto Sans SC"/>', '<name val="Arial"/>')
                text = text.replace('<name val="Noto Sans SC" />', '<name val="Arial"/>')
                payload = text.encode("utf-8")
            target.writestr(info, payload)
    staged.replace(path)


def recalculate(path: Path, timeout_seconds: int) -> dict:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Only .xlsx workbooks are supported")

    soffice = resolve_soffice()
    with tempfile.TemporaryDirectory(prefix="excel_recalc_") as output_raw:
        output_dir = Path(output_raw)
        with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_raw:
            profile = Path(profile_raw)
            command = [
                soffice,
                f"-env:UserInstallation={profile_uri(profile)}",
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "xlsx:Calc MS Excel 2007 XML",
                "--outdir",
                str(output_dir),
                str(path),
            ]
            result = run_bounded(command, build_env(profile), timeout_seconds)
        recalculated = output_dir / f"{path.stem}.xlsx"
        if result.returncode != 0 or not recalculated.exists() or recalculated.stat().st_size <= 0:
            raise RuntimeError(
                "LibreOffice formula recalculation failed.\n"
                f"EXIT: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        staged = path.with_name(f".{path.name}.recalculated.tmp")
        shutil.copy2(recalculated, staged)
        staged.replace(path)
    remove_fixed_print_scales(path)
    restore_consulting_fonts(path)

    formula_book = load_workbook(path, data_only=False, read_only=False)
    value_book = load_workbook(path, data_only=True, read_only=False)
    formulas = 0
    errors: list[dict[str, str]] = []
    missing_cache: list[str] = []
    for ws in formula_book.worksheets:
        values = value_book[ws.title]
        for row in ws.iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    continue
                formulas += 1
                cached = values[cell.coordinate].value
                if cached in FORMULA_ERRORS:
                    errors.append(
                        {
                            "sheet": ws.title,
                            "cell": cell.coordinate,
                            "error": str(cached),
                        }
                    )
                elif cached is None:
                    missing_cache.append(f"{ws.title}!{cell.coordinate}")
    return {
        "status": "errors_found" if errors or missing_cache else "success",
        "workbook": str(path),
        "total_formulas": formulas,
        "total_errors": len(errors),
        "formula_errors": errors,
        "missing_formula_cache": missing_cache,
        "libreoffice": soffice,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recalculate Excel formulas with an isolated LibreOffice profile and scan cached results.")
    parser.add_argument("workbook")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    report = recalculate(Path(args.workbook).expanduser().resolve(), args.timeout_seconds)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] != "success" else 0


if __name__ == "__main__":
    raise SystemExit(main())
