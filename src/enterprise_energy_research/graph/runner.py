from __future__ import annotations

from pathlib import Path

from enterprise_energy_research.artifacts.planner import ArtifactPlanner
from enterprise_energy_research.domain.enums import RunStatus, ValidationStatus
from enterprise_energy_research.domain.models import ArtifactManifest, ProductDetection
from enterprise_energy_research.evidence.exports import export_bundle
from enterprise_energy_research.evidence.freeze import FreezeError, FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore, canonical_json
from enterprise_energy_research.validation.core import CoreValidator

from .state import ResearchState


class Phase2Runner:
    """Deterministic foundation runner.

    It starts after synthetic/externally prepared evidence has been stored. Research nodes are
    intentionally not implemented until Phase 3.
    """

    def __init__(
        self,
        store: EvidenceStore,
        resolved_conflict_ids: frozenset[str] | None = None,
    ) -> None:
        self.store = store
        self.validator = CoreValidator(store, resolved_conflict_ids=resolved_conflict_ids)
        self.freeze_service = FreezeService(store)
        self.planner = ArtifactPlanner()

    def finalize_evidence(
        self,
        state: ResearchState,
        *,
        output_dir: Path,
        product_detection: ProductDetection | None = None,
    ) -> tuple[ResearchState, ArtifactManifest | None]:
        state.transition("VALIDATE", status=RunStatus.RUNNING)
        report = self.validator.validate(state.run_id, state.evidence_version)
        state.validation_status = report.status
        if report.status == ValidationStatus.BLOCKED:
            state.blocking_findings = [finding.code for finding in report.findings if finding.severity.value in {"ERROR", "BLOCKER"}]
            state.transition("BLOCKED", status=RunStatus.BLOCKED)
            return state, None

        state.transition("FREEZE")
        try:
            freeze = self.freeze_service.create(state.run_id, state.evidence_version, report)
        except FreezeError as exc:
            state.blocking_findings.append(str(exc))
            state.transition("BLOCKED", status=RunStatus.BLOCKED)
            return state, None
        state.freeze_id = freeze.freeze_id

        run = self.store.get_run(state.run_id)
        run.freeze_id = freeze.freeze_id
        run.validation_status = report.status
        run.status = RunStatus.PASS_WITH_WARNINGS if report.status == ValidationStatus.PASS_WITH_WARNINGS else RunStatus.PASS
        self.store.replace_run_manifest(run)

        state.transition("ARTIFACT_PLAN")
        bundle = self.freeze_service.load_bundle(freeze.freeze_id)
        manifest = self.planner.plan(bundle, product_detection)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO artifact_manifests(artifact_manifest_id, run_id, freeze_id, payload) VALUES (?, ?, ?, ?)",
                (manifest.artifact_manifest_id, state.run_id, freeze.freeze_id, canonical_json(manifest)),
            )
        state.artifact_manifest_id = manifest.artifact_manifest_id

        state.transition("EXPORT")
        export_bundle(bundle, manifest, output_dir)
        final_status = RunStatus.PASS_WITH_WARNINGS if report.status == ValidationStatus.PASS_WITH_WARNINGS else RunStatus.PASS
        state.transition("EVIDENCE_READY", status=final_status)
        return state, manifest
