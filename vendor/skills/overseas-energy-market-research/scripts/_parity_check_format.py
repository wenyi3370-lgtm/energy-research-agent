"""格式标记一致性对比：内嵌 CLI vs 官方 CLI（内容无关，只比输出格式骨架）。"""
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

embedded = SCRIPTS_DIR / "anysearch" / "anysearch_cli.py"
official = Path.home() / ".claude" / "skills" / "anysearch" / "scripts" / "anysearch_cli.py"

env = dict(os.environ)
env.setdefault("HTTP_PROXY", "http://127.0.0.1:7897")
env.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")


def format_skeleton(text: str) -> list[str]:
    marks = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if re.match(r"^#{1,6} ", line):
            marks.append("HEADING")
        elif line.startswith("- **") and "**:" in line:
            marks.append("FIELD")
        elif line.startswith("|"):
            marks.append("TABLE")
        elif line.startswith("- `") and "`" in line:
            marks.append("PARAM")
        elif re.match(r"^\*\*.*\*\*$", line):
            marks.append("SECTION")
        else:
            marks.append("TEXT")
    return marks


def main() -> int:
    print("Format-marker parity: embedded CLI vs official CLI (real API, content-agnostic)")
    for args in (
        ["search", "Thailand BESS market 2026", "--max_results", "3"],
        ["get_sub_domains", "--domain", "energy"],
        ["search", "electricity tariff", "--domain", "energy", "--sub_domain", "energy.production", "--sdp", "frequency=annual,keyword=electricity generation", "--max_results", "2"],
    ):
        r_e = subprocess.run([sys.executable, str(embedded), *args], capture_output=True, text=True, timeout=90, env=env)
        r_o = subprocess.run([sys.executable, str(official), *args], capture_output=True, text=True, timeout=90, env=env)
        if r_e.returncode != r_o.returncode:
            print(f"  cmd {args}: exit differs {r_e.returncode} vs {r_o.returncode} -> FAIL")
            return 1
        m_e, m_o = format_skeleton(r_e.stdout), format_skeleton(r_o.stdout)
        same = m_e == m_o
        print(f"  cmd: {' '.join(args)}")
        print(f"    exit {r_e.returncode}/{r_o.returncode} | format skeleton identical: {same}")
        if not same:
            print("    embedded:", m_e)
            print("    official:", m_o)
            return 1
    print("Format-marker parity: PASS (输出格式骨架一致；内容差异来自 API 实时数据，与封装无关)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
