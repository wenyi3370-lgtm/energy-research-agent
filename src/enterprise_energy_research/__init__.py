"""Evidence-first enterprise research and decision intelligence platform."""

from importlib import metadata
from pathlib import Path


def package_version() -> str:
    """Read pyproject.toml as the repository's single version source."""
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        in_project = False
        for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("["):
                in_project = line == "[project]"
            elif in_project and line.startswith("version") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"\'')
    try:
        return metadata.version("enterprise-energy-research")
    except metadata.PackageNotFoundError:
        return "0+unknown"


__version__ = package_version()
