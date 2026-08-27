"""Failure Case Library: structured catalog of known Agent failure modes.

Every case is written from real observed incidents (the catalog in
``docs/failure-cases/catalog.yaml`` includes the LLM quota outage, adapter
outages and publisher failures this project actually hit). The library is
read-only documentation + a lookup helper: detection strings and recovery
steps are the operational runbook, not executable automation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from ..domain.models import StrictModel
from ..settings import load_yaml


class FailureCase(StrictModel):
    """One documented failure mode with detection and recovery guidance."""

    case_id: str = Field(min_length=1)
    title: str
    phase: str = ""
    symptom: str = ""
    root_cause: str = ""
    detection: str = ""
    recovery: str = ""
    prevent: str = ""
    tags: list[str] = Field(default_factory=list)


class FailureLibrary:
    """Load and search the failure case catalog."""

    def __init__(self, cases: list[FailureCase]) -> None:
        self.cases = cases

    @staticmethod
    def load(path: Path) -> "FailureLibrary":
        payload = load_yaml(path)
        return FailureLibrary(
            [FailureCase.model_validate(item) for item in payload.get("cases", [])]
        )

    def by_tag(self, tag: str) -> list[FailureCase]:
        return [case for case in self.cases if tag in case.tags]

    def match(self, text: str) -> list[FailureCase]:
        """Best-effort lookup: cases whose tags appear in ``text`` or whose
        detection/root-cause fragments (split on '；'/';;') appear verbatim."""
        lowered = text.lower()
        hits = []
        for case in self.cases:
            needles = list(case.tags) + [
                fragment
                for field in (case.detection, case.root_cause, case.title)
                for fragment in field.replace(";;", "；").split("；")
                if fragment.strip()
            ]
            if any(needle and needle.lower() in lowered for needle in needles):
                hits.append(case)
        return hits

    def summary(self) -> dict[str, Any]:
        return {
            "case_count": len(self.cases),
            "cases": [case.case_id for case in self.cases],
            "tags": sorted({tag for case in self.cases for tag in case.tags}),
        }
