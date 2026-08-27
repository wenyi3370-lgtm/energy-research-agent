from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from check_runtime_dependencies import check


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and verify Python dependencies for the standalone energy-market Skill.")
    parser.add_argument("--install", action="store_true", help="Install requirements into the current Python environment before checking.")
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parents[1]
    if args.install:
        command = [sys.executable, "-m", "pip", "install", "-r", str(skill_root / "requirements.txt")]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode
    report = check()
    print(f"Standalone runtime: {report['status']}")
    if report["missing_python_packages"]:
        print("Missing Python packages: " + ", ".join(report["missing_python_packages"]))
    if report["libreoffice"] == "missing":
        print("LibreOffice is missing; install it or set SOFFICE_PATH.")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
