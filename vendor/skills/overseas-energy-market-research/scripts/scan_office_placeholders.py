from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


PLACEHOLDER_PATTERNS = {
    "double_bracket": re.compile(r"\[\[[^\]\r\n]{1,160}\]\]"),
    "triple_angle": re.compile(r"<<<[^>\r\n]{1,160}>>>", re.I),
    "ai_draft": re.compile(r"\[AI[-_ ]?DRAFT[^\]]*\]", re.I),
    "modeler_input": re.compile(r"\[(?:MODELER|HUMAN)[-_ ]INPUT[^\]]*\]", re.I),
}
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx", ".xlsm"}


def _entry_text(payload: bytes) -> str:
    decoded = payload.decode("utf-8", errors="ignore")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return html.unescape(decoded)
    return html.unescape("".join(root.itertext())) + "\n" + html.unescape(decoded)


def scan_file(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() not in OFFICE_SUFFIXES:
        raise ValueError(f"Unsupported Office file type: {path.suffix}")
    findings: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        for entry in archive.namelist():
            if not entry.lower().endswith((".xml", ".rels")):
                continue
            text = _entry_text(archive.read(entry))
            seen: set[tuple[str, str]] = set()
            for pattern_name, pattern in PLACEHOLDER_PATTERNS.items():
                for match in pattern.finditer(text):
                    token = match.group(0)
                    key = (pattern_name, token)
                    if key in seen:
                        continue
                    seen.add(key)
                    start = max(0, match.start() - 60)
                    end = min(len(text), match.end() + 60)
                    findings.append(
                        {
                            "file": str(path),
                            "entry": entry,
                            "pattern": pattern_name,
                            "token": token,
                            "context": re.sub(r"\s+", " ", text[start:end]).strip(),
                        }
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan OOXML Office files for unresolved delivery placeholders.")
    parser.add_argument("files", nargs="+", help="One or more .docx/.pptx/.xlsx/.xlsm files")
    parser.add_argument("--json-out", help="Optional JSON report path")
    args = parser.parse_args()
    findings: list[dict[str, str]] = []
    for raw_path in args.files:
        path = Path(raw_path).resolve()
        findings.extend(scan_file(path))
    report = {"status": "fail" if findings else "pass", "finding_count": len(findings), "findings": findings}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        output = Path(args.json_out).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
