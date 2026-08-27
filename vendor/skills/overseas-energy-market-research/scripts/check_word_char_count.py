#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""机械门禁（2026-08-07 固化）：Word 报告字数校验。

背景：曾因每章仅 2-3 段导致全文约 1.3 万字符，未达 SKILL.md 15,000-30,000 字要求。
本脚本统计 docx 全部文本（正文段 + 表格 + 图题 + 来源注），低于阈值即 FAIL。

用法:
    python check_word_char_count.py <final.docx> [--min 15000] [--json-out <path>]
退出码: 0 = 通过；1 = 不足（FAIL）
"""
import argparse
import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

DEFAULT_MIN = 15000


def collect_text(doc: Document) -> str:
    parts: list[str] = []
    for p in doc.paragraphs:
        parts.append(p.text or "")
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text or "")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Word report character-count gate (min 15,000)")
    ap.add_argument("docx")
    ap.add_argument("--min", type=int, default=DEFAULT_MIN)
    ap.add_argument("--json-out")
    args = ap.parse_args()

    doc = Document(args.docx)
    text = collect_text(doc)
    total = len(text)
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    passed = total >= args.min
    result = {
        "file": args.docx,
        "total_chars": total,
        "cn_chars": cn,
        "min_required": args.min,
        "passed": passed,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    status = "PASS" if passed else "FAIL"
    print(f"char-count gate: {status} | total {total} chars (cn {cn}) | min {args.min}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
