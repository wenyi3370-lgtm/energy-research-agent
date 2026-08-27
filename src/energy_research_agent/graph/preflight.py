from __future__ import annotations

from collections.abc import Iterable

from energy_research_agent.adapters.base import AdapterHealth


def preflight(health_checks: Iterable[AdapterHealth], *, require_external: bool) -> list[str]:
    diagnostics: list[str] = []
    for item in health_checks:
        if not item.available:
            diagnostics.extend(item.diagnostics or [f"{item.name} unavailable"])
    if require_external and diagnostics:
        return diagnostics
    return []

