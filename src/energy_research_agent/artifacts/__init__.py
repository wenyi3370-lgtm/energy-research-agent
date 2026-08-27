"""Artifact public API with lazy imports.

Publishers depend on the narrative/validation layer, so importing every
publisher eagerly here creates a cycle for clean CLI entry points. PEP 562
lazy attributes preserve the public API without executing unrelated modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ArtifactPlanner": (".planner", "ArtifactPlanner"),
    "ArtifactPublicationService": (".publisher", "ArtifactPublicationService"),
    "ExcelMasterFrozenPublisher": (".excel", "ExcelMasterFrozenPublisher"),
    "FrozenHtmlPublisher": (".html", "FrozenHtmlPublisher"),
    "FrozenWordPublisher": (".word", "FrozenWordPublisher"),
    "PptMasterFrozenPublisher": (".ppt", "PptMasterFrozenPublisher"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
