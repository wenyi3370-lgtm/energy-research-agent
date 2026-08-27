from __future__ import annotations

from collections import defaultdict

from energy_research_agent.domain.enums import Severity, SourceLevel, ValidationStatus, VerificationStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import ValidationFinding, ValidationReport
from energy_research_agent.evidence.store import EvidenceStore, EvidenceStoreError


class CoreValidator:
    """Core structural validator; source, image, and render checks run separately."""

    def __init__(
        self,
        store: EvidenceStore,
        resolved_conflict_ids: frozenset[str] | None = None,
    ) -> None:
        self.store = store
        # Legacy externally resolved conflict IDs remain supported for old
        # evidence stores. New runs persist automatic RESOLVED conflicts.
        self.resolved_conflict_ids = resolved_conflict_ids or frozenset()

    def validate(self, run_id: str, evidence_version: int) -> ValidationReport:
        findings: list[ValidationFinding] = []
        try:
            self.store.assert_referential_integrity(run_id, evidence_version)
        except EvidenceStoreError as exc:
            findings.append(self._finding("SchemaValidator", Severity.BLOCKER, "REFERENTIAL_INTEGRITY", str(exc)))

        sources = {item.source_id: item for item in self.store.list(run_id, "source", up_to_version=evidence_version)}
        claims = self.store.list(run_id, "claim", up_to_version=evidence_version)
        for claim in claims:
            source = sources.get(claim.source_id)
            if not source:
                continue
            if claim.verification_status == VerificationStatus.VERIFIED and source.source_level in {
                SourceLevel.SOURCE_C, SourceLevel.SOURCE_D
            }:
                findings.append(self._finding(
                    "EvidenceValidator", Severity.ERROR, "WEAK_SOURCE_MARKED_VERIFIED",
                    f"{claim.claim_id} is VERIFIED from {source.source_level}", [claim.claim_id, source.source_id],
                ))
            if source.source_level == SourceLevel.SOURCE_D and "snippet" in source.grading_reason.lower():
                findings.append(self._finding(
                    "EvidenceValidator", Severity.WARNING, "SEARCH_SNIPPET_DISCOVERY_ONLY",
                    f"{source.source_id} is discovery-only", [source.source_id],
                ))

        conflicts: dict[str, list[str]] = defaultdict(list)
        for claim in claims:
            if claim.conflict_group_id:
                conflicts[claim.conflict_group_id].append(claim.claim_id)
        for group_id, claim_ids in conflicts.items():
            if len(claim_ids) < 2:
                findings.append(self._finding(
                    "EvidenceValidator", Severity.ERROR, "SINGLETON_CONFLICT_GROUP",
                    f"{group_id} contains only one claim", claim_ids,
                ))

        for conflict in self.store.list(run_id, "conflict", up_to_version=evidence_version):
            if conflict.conflict_group_id in self.resolved_conflict_ids:
                continue
            if conflict.status.value == "BLOCKING":
                findings.append(self._finding(
                    "EvidenceValidator", Severity.BLOCKER, "UNRESOLVED_CORE_CONFLICT",
                    f"{conflict.conflict_group_id} remains blocking for {conflict.field_name}", conflict.claim_ids,
                ))

        images = self.store.list(run_id, "image", up_to_version=evidence_version)
        for image in images:
            if image.verification_status.value == "REJECTED":
                findings.append(self._finding(
                    "ImageValidator", Severity.WARNING, "IMAGE_REJECTED",
                    f"{image.image_id} was rejected and cannot be used in formal artifacts", [image.image_id],
                ))

        for gap in self.store.list(run_id, "gap", up_to_version=evidence_version):
            if gap.status.value == "OPEN" and gap.field_name.startswith("product_"):
                findings.append(self._finding(
                    "EvidenceValidator", Severity.WARNING, "INCOMPLETE_PRODUCT_COVERAGE",
                    f"{gap.field_name} remains open; the product section must not be described as complete",
                    [gap.gap_id],
                ))

        if any(item.severity in {Severity.BLOCKER, Severity.ERROR} for item in findings):
            status = ValidationStatus.BLOCKED
        elif findings:
            status = ValidationStatus.PASS_WITH_WARNINGS
        else:
            status = ValidationStatus.PASS
        return ValidationReport(
            validation_report_id=new_sortable_id("VAL"),
            run_id=run_id,
            status=status,
            findings=findings,
        )

    @staticmethod
    def _finding(
        validator: str,
        severity: Severity,
        code: str,
        message: str,
        record_ids: list[str] | None = None,
    ) -> ValidationFinding:
        return ValidationFinding(
            finding_id=new_sortable_id("FIND"),
            validator=validator,
            severity=severity,
            code=code,
            message=message,
            record_ids=record_ids or [],
            remediation="Correct the evidence record and create a new evidence version.",
        )
