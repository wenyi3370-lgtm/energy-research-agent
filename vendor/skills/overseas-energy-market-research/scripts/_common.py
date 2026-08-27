from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


URL_RE = re.compile(r"^https?://", re.IGNORECASE)
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


@dataclass
class Issue:
    level: str
    row: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "row": self.row,
            "field": self.field,
            "message": self.message,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def read_json(path: Path, default):
    if not path.exists():
        return default
    # Windows editors and PowerShell commonly emit UTF-8 with a BOM.  utf-8-sig
    # accepts both BOM and BOM-less JSON while returning the same decoded text.
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def is_url(value: str) -> bool:
    return bool(URL_RE.match((value or "").strip()))


def is_asin(value: str) -> bool:
    return bool(ASIN_RE.match((value or "").strip().upper()))


def split_ids(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,|\s]+", value or "") if part.strip()]


def has_any(row: dict[str, str], fields: Iterable[str]) -> bool:
    return any((row.get(field) or "").strip() for field in fields)


def row_label(index: int, row: dict[str, str]) -> str:
    for key in ("source_id", "review_id", "model_id", "parameter_id", "gap_id", "theme_id"):
        if row.get(key):
            return row[key]
    return str(index)


def require_columns(fieldnames: list[str], required: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    present = set(fieldnames)
    for field in required:
        if field not in present:
            issues.append(Issue("fail", "header", field, "Missing required column"))
    return issues


def print_report(title: str, issues: list[Issue], *, json_output: bool = False) -> int:
    fails = [i for i in issues if i.level == "fail"]
    warns = [i for i in issues if i.level == "warn"]
    payload = {
        "title": title,
        "status": "fail" if fails else "ok",
        "fail_count": len(fails),
        "warn_count": len(warns),
        "issues": [i.as_dict() for i in issues],
    }
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{title}: {payload['status'].upper()} ({len(fails)} fail, {len(warns)} warn)")
        for issue in issues:
            print(f"[{issue.level.upper()}] row={issue.row} field={issue.field}: {issue.message}")
    return 1 if fails else 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report.")


def resolve_project_file(project_dir: Path, explicit_file: str | None, candidates: list[str]) -> Path:
    if explicit_file:
        return Path(explicit_file).expanduser().resolve()
    for candidate in candidates:
        path = project_dir / candidate
        if path.exists():
            return path
    return project_dir / candidates[0]


def find_presentation_project(project_dir: Path, explicit: str | None = None) -> Path | None:
    """Locate the high-fidelity presentation project directory.

    Resolution order (CHANGELOG v1.2.6):
    1. --presentation-project explicit value (absolute or project-relative).
    2. <project_dir>/presentation_project            (legacy single-project layout)
    3. Any single-level child of <project_dir> that contains both
       design_spec.md and svg_output/  (e.g. <name>_ppt169_<YYYYMMDD>/ produced
       by `high_fidelity_presentation.py init`, or <name>/).

    Returns None when nothing is found so callers can print candidate hints.
    """
    project_root = Path(project_dir).expanduser().resolve()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate if candidate.is_dir() else None

    legacy = project_root / "presentation_project"
    if legacy.is_dir() and ((legacy / "design_spec.md").is_file() or (legacy / "svg_output").is_dir()):
        return legacy

    if not project_root.is_dir():
        return None
    try:
        children = sorted(p for p in project_root.iterdir() if p.is_dir())
    except OSError:
        return None
    for child in children:
        if child == legacy:
            continue
        if (child / "design_spec.md").is_file() and (child / "svg_output").is_dir():
            return child
    return None


def presentation_project_hint(project_dir: Path) -> str:
    """Human-readable hint listing candidate presentation-project directories."""
    project_root = Path(project_dir).expanduser().resolve()
    names = ["presentation_project/"]
    if project_root.is_dir():
        try:
            names += [f"{p.name}/" for p in sorted(project_root.iterdir()) if p.is_dir()]
        except OSError:
            pass
    return "candidates: " + ", ".join(names)


def main_guard(func) -> None:
    try:
        raise SystemExit(func())
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        raise SystemExit(2)
