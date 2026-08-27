"""Change detection between two evidence runs for monitored fields (Phase 14).

Compares claim-level evidence of a previous run and a newer run for the
same subject. Only claims are compared (structured values); sources are
referenced by their ids. Detection is a pure function over evidence rows,
so it is testable without the full pipeline.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ...domain.models import Claim, StrictModel


class Change(StrictModel):
    kind: str  # changed | added | removed
    field_name: str
    old_value: Any | None = None
    new_value: Any | None = None
    old_source_id: str | None = None
    new_source_id: str | None = None
    note: str = ""


class ChangeReport(StrictModel):
    subject: str
    changes: list[Change] = Field(default_factory=list)

    @property
    def changed_fields(self) -> list[str]:
        return [change.field_name for change in self.changes]

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


class ChangeDetector:
    """Diff claims of two runs on the monitored fields."""

    def detect(
        self,
        subject: str,
        old_claims: list[Claim],
        new_claims: list[Claim],
        fields: list[str] | None = None,
    ) -> ChangeReport:
        old_by_field = {claim.field_name: claim for claim in old_claims}
        new_by_field = {claim.field_name: claim for claim in new_claims}
        scope = fields or sorted(set(old_by_field) | set(new_by_field))
        changes: list[Change] = []
        for field_name in scope:
            old_claim = old_by_field.get(field_name)
            new_claim = new_by_field.get(field_name)
            if old_claim is None and new_claim is None:
                continue
            if old_claim is None:
                changes.append(Change(
                    kind="added",
                    field_name=field_name,
                    new_value=new_claim.value,
                    new_source_id=new_claim.source_id,
                    note="new evidence appeared for a monitored field",
                ))
                continue
            if new_claim is None:
                changes.append(Change(
                    kind="removed",
                    field_name=field_name,
                    old_value=old_claim.value,
                    old_source_id=old_claim.source_id,
                    note="monitored field no longer backed by evidence",
                ))
                continue
            if old_claim.value != new_claim.value:
                changes.append(Change(
                    kind="changed",
                    field_name=field_name,
                    old_value=old_claim.value,
                    new_value=new_claim.value,
                    old_source_id=old_claim.source_id,
                    new_source_id=new_claim.source_id,
                    note="monitored field value changed between runs",
                ))
        return ChangeReport(subject=subject, changes=changes)
