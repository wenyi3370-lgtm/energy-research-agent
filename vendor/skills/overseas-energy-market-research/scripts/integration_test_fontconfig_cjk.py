# -*- coding: utf-8 -*-
"""v9 optional integration test: real Fontconfig CJK discovery on this host.

SKIP (exit 0, no FAIL) when `fc-match` is unavailable or the system has no
SC CJK font.  On a real Linux/macOS host where
    fc-match "Noto Serif CJK SC"  ->  Noto Serif CJK SC ...NotoSerifCJK-Regular.ttc
the multi-level resolver must resolve the SAME font (never None), otherwise
this test FAILs — that is the exact False Negative the v9 fix closes.

Exit 0 = PASS or SKIP, 1 = FAIL.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import fonts  # noqa: E402

TARGET = "Noto Serif CJK SC"


def fc_match_result(family: str) -> tuple[str, str] | None:
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-f", "%{family}\n%{file}\n", family],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    return lines[0], lines[-1]


def main() -> int:
    print("Integration test: Fontconfig CJK discovery")
    if shutil.which("fc-match") is None:
        print("SKIP: fc-match 不存在（本机非 Fontconfig 环境，如 Windows/部分 macOS）")
        return 0
    m = fc_match_result(TARGET)
    if m is None:
        print("SKIP: fc-match %r 无匹配（本机未安装 Noto Serif CJK SC）" % TARGET)
        return 0
    fam, file_path = m
    print("fc-match result: family=%s file=%s" % (fam, file_path))
    resolved = fonts.resolve_cjk_font()
    if resolved is None:
        print("FAIL: fc-match 能找到 SC 字体，但 resolve_cjk_font() 返回 None（False Negative）")
        return 1
    print("resolve_cjk_font result: family=%s source=%s path=%s"
          % (resolved.family, resolved.source, resolved.path))
    if resolved.family == TARGET and resolved.source == "fontconfig":
        print("Integration test: PASS (fontconfig 发现与解析器一致)")
        return 0
    print("Integration test: PASS (系统可解析 CJK 字体 %s via %s)"
          % (resolved.family, resolved.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
