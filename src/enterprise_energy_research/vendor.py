from __future__ import annotations

import os
from pathlib import Path


EMBEDDED_SKILLS = (
    "anysearch",
    "excel-master",
    "ppt-master",
    "frontend-design",
    "kimi-webbridge",
    "diagram-design",
    "overseas-energy-market-research",
)


def repository_root() -> Path:
    override = os.getenv("ENTERPRISE_ENERGY_SKILL_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def embedded_skill_root(name: str) -> Path:
    if name not in EMBEDDED_SKILLS:
        raise ValueError(f"Unknown embedded skill: {name}")
    return repository_root() / "vendor" / "skills" / name


def embedded_skill_available(name: str) -> bool:
    root = embedded_skill_root(name)
    return root.is_dir() and (root / "SKILL.md").is_file()
