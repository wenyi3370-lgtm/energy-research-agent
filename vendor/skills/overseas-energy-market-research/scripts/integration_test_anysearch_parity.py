# -*- coding: utf-8 -*-
"""FIX-01: Official parity / integration test for Embedded AnySearch.

Compares the BUNDLED AnySearch CLI against the OFFICIAL AnySearch Skill CLI:
- CLI SHA256
- `doc` output (zero-diff)
- `--help` command surface

This is an integration test: when the official AnySearch Skill is NOT
installed it returns SKIP (exit 0) — business capability is intact, only the
comparison reference is missing (false-negative guard). Self-contained,
offline, deterministic.

Usage:
    python integration_test_anysearch_parity.py [--official PATH]

Exit 0 = PASS or SKIP; 1 = parity FAIL (real mismatch); 2 = environment error.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_collection import anysearch_backend as backend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--official", help="Explicit path to the official anysearch_cli.py")
    args = parser.parse_args()

    embedded = backend.embedded_cli_path()
    official = backend.official_cli_path(explicit=args.official)
    if not embedded.is_file():
        print("FAIL: embedded anysearch CLI missing:", embedded)
        return 2
    if official is None:
        print("SKIP: Official AnySearch Skill is not installed.")
        print("Embedded AnySearch regression remains valid.")
        return 0

    failures: list[str] = []

    def run(cli: Path, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(cli), *argv],
                              capture_output=True, text=True, timeout=60)

    emb_sha = backend.cli_sha256(embedded)
    off_sha = backend.cli_sha256(official)
    if emb_sha == off_sha:
        print("  [1/4] CLI SHA256 identical: PASS")
    else:
        failures.append("CLI SHA256 differs (embedded %s vs official %s)" % (emb_sha[:16], off_sha[:16]))

    emb_doc = run(embedded, "doc")
    off_doc = run(official, "doc")
    if emb_doc.returncode or off_doc.returncode:
        failures.append("doc command failed (embedded rc=%s official rc=%s)" % (emb_doc.returncode, off_doc.returncode))
    elif emb_doc.stdout == off_doc.stdout:
        print("  [2/4] doc output zero-diff: PASS")
    else:
        failures.append("doc output differs from official (diff != 0)")

    for cmd in ("--help", "search --help", "extract --help", "batch_search --help"):
        emb = run(embedded, *cmd.split())
        off = run(official, *cmd.split())
        if emb.returncode or off.returncode:
            failures.append("command surface %r failed" % cmd)
        elif emb.stdout == off.stdout:
            print("  [%s] %s surface identical: PASS" % ("3/4" if cmd == "--help" else "4/4", cmd))
        else:
            failures.append("command surface %r differs from official" % cmd)

    if failures:
        print("AnySearch parity: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("AnySearch parity: PASS (embedded == official)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
