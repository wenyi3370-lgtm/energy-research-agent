# -*- coding: utf-8 -*-
"""FIX round-4 P3-16: unit tests for the production requirements parser.

Covers: blank line, comment, normal requirement, version range, PEP 508
environment marker active / inactive, extras, inline marker, specifier
retention. Tests `common.requirements.parse_requirement_line` directly
(production code), not the packaging library in isolation.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common.requirements import parse_requirement_line  # noqa: E402

ENV_310 = {"python_version": "3.10", "python_full_version": "3.10.0"}
ENV_313 = {"python_version": "3.13", "python_full_version": "3.13.0"}


def test_blank_and_comment() -> None:
    if parse_requirement_line("") is not None:
        raise AssertionError("blank line must return None")
    if parse_requirement_line("   ") is not None:
        raise AssertionError("whitespace line must return None")
    if parse_requirement_line("# a comment") is not None:
        raise AssertionError("comment must return None")
    print("  blank line / comment -> None: PASS")


def test_normal_requirement() -> None:
    req = parse_requirement_line("requests>=2.31,<3")
    if req is None or req.name != "requests":
        raise AssertionError("normal requirement not parsed: %r" % req)
    if str(req.specifier) not in (">=2.31,<3", "<3,>=2.31"):
        raise AssertionError("specifier not retained: %r" % req.specifier)
    print("  normal requirement + specifier retention: PASS")


def test_marker_active() -> None:
    req = parse_requirement_line('tomli>=2,<3; python_version < "3.11"', environment=ENV_310)
    if req is None or req.name != "tomli":
        raise AssertionError("marker-active requirement must parse on 3.10")
    print("  PEP 508 marker active (3.10) -> parsed: PASS")


def test_marker_inactive() -> None:
    req = parse_requirement_line('tomli>=2,<3; python_version < "3.11"', environment=ENV_313)
    if req is not None:
        raise AssertionError("marker-inactive requirement must be excluded on 3.13")
    print("  PEP 508 marker inactive (3.13) -> None: PASS")


def test_extras_preserved() -> None:
    req = parse_requirement_line('package[extra]>=1.0; sys_platform == "win32"', environment={"sys_platform": "win32"})
    if req is None or req.name != "package":
        raise AssertionError("extras requirement must parse")
    if "extra" not in (req.extras or set()):
        raise AssertionError("extras not preserved: %r" % req.extras)
    req_other = parse_requirement_line('package[extra]>=1.0; sys_platform == "win32"', environment={"sys_platform": "linux"})
    if req_other is not None:
        raise AssertionError("inline marker must exclude on linux")
    print("  extras preserved + inline marker: PASS")


def test_version_range() -> None:
    req = parse_requirement_line("numpy>=1.26,<3")
    if req is None or "numpy" != req.name:
        raise AssertionError("version-range requirement not parsed")
    print("  version range -> parsed: PASS")


def main() -> int:
    print("Requirements parser unit tests:")
    test_blank_and_comment()
    test_normal_requirement()
    test_marker_active()
    test_marker_inactive()
    test_extras_preserved()
    test_version_range()
    print("Requirements parser unit tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
