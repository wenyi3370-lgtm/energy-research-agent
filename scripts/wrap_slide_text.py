from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
NO_SPLIT = re.compile(r"(?:[A-Za-z][A-Za-z0-9&+./_-]*|[-+]?\d[\d,.]*(?:%|[A-Za-z\u4e00-\u9fff²³/·-]+)?)")


def token_width(token: str, font_size: float) -> float:
    width = 0.0
    for char in token:
        if "\u2e80" <= char <= "\u9fff":
            width += font_size
        elif char.isspace():
            width += font_size * 0.32
        elif char.isdigit():
            width += font_size * 0.56
        else:
            width += font_size * 0.58
    return width


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    cursor = 0
    for match in NO_SPLIT.finditer(text):
        if match.start() > cursor:
            tokens.extend(list(text[cursor:match.start()]))
        tokens.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        tokens.extend(list(text[cursor:]))
    return [token for token in tokens if token]


def wrap_text(text: str, maximum_width: float, font_size: float) -> list[str]:
    lines: list[str] = []
    current = ""
    current_width = 0.0
    for token in tokenize(text):
        width = token_width(token, font_size)
        if current and current_width + width > maximum_width:
            lines.append(current.rstrip())
            current, current_width = token.lstrip(), token_width(token.lstrip(), font_size)
        else:
            current += token
            current_width += width
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def process(path: Path, *, check_only: bool) -> list[str]:
    tree = ET.parse(path)
    root = tree.getroot()
    findings: list[str] = []
    changed = False
    for node in root.iter(f"{{{SVG_NS}}}text"):
        text = "".join(node.itertext()).strip()
        if not text:
            continue
        max_width_raw = node.get("data-max-width")
        no_wrap = node.get("data-no-wrap", "false").lower() == "true"
        role = node.get("data-role", "")
        if role in {"page-number", "badge", "kpi-value-unit"}:
            no_wrap = True
        if not max_width_raw:
            if no_wrap and "\n" in text:
                findings.append(f"{path.name}: {role or 'no-wrap text'} already contains a line break: {text!r}")
            continue
        try:
            maximum_width = float(max_width_raw)
            font_size = float(node.get("font-size", "18").replace("px", ""))
        except ValueError:
            findings.append(f"{path.name}: invalid width/font metadata for {text!r}")
            continue
        lines = wrap_text(text, maximum_width, font_size)
        if len(lines) <= 1:
            continue
        if no_wrap:
            findings.append(f"{path.name}: protected token exceeds width budget: {text!r}")
            continue
        if check_only:
            findings.append(f"{path.name}: text requires wrapping into {len(lines)} lines: {text!r}")
            continue
        for child in list(node):
            node.remove(child)
        node.text = None
        x = node.get("x", "0")
        for index, line in enumerate(lines):
            tspan = ET.SubElement(node, f"{{{SVG_NS}}}tspan")
            tspan.set("x", x)
            tspan.set("dy", "0" if index == 0 else "1.2em")
            tspan.text = line
        node.set("data-wrapped", "true")
        changed = True
    if changed:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return findings


def svg_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.svg")))
        elif path.suffix.lower() == ".svg":
            files.append(path)
    return list(dict.fromkeys(files))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply/check token-aware wrapping for PPT Master SVG text")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true", help="report required changes without writing")
    args = parser.parse_args()
    findings: list[str] = []
    for path in svg_files(args.paths):
        findings.extend(process(path, check_only=args.check))
    if findings:
        print("\n".join(findings), file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
