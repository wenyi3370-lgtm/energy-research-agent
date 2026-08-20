from __future__ import annotations

from pathlib import Path

from enterprise_energy_research.adapters.base import ArtifactAdapter, ArtifactResult
from enterprise_energy_research.domain.enums import ArtifactStatus, ArtifactType
from enterprise_energy_research.domain.models import ArtifactManifest, FrozenResearchBundle


DEFAULT_FILENAMES = {
    ArtifactType.EXCEL: "enterprise_research.xlsx",
    ArtifactType.WORD: "enterprise_research.docx",
    ArtifactType.ENTERPRISE_HTML: "enterprise_dashboard.html",
    ArtifactType.PRODUCT_HTML: "product_dashboard.html",
    ArtifactType.PPT: "enterprise_research.pptx",
}


class ArtifactPublicationService:
    """Dispatch frozen bindings to approved publishers; skipped bindings remain skipped."""

    def __init__(self, adapters: dict[ArtifactType, ArtifactAdapter]) -> None:
        self.adapters = adapters

    def publish(self, bundle: FrozenResearchBundle, manifest: ArtifactManifest, output_dir: Path) -> list[ArtifactResult]:
        if manifest.freeze_id != bundle.freeze.freeze_id:
            raise ValueError("Artifact manifest and frozen bundle do not match")
        results: list[ArtifactResult] = []
        for binding in manifest.artifacts:
            if binding.status == ArtifactStatus.SKIPPED:
                results.append(ArtifactResult(
                    adapter="orchestrator", artifact_id=binding.artifact_id, artifact_type=binding.type,
                    status="skipped", diagnostics=[binding.skip_reason or "Skipped by artifact manifest"],
                ))
                continue
            adapter = self.adapters.get(binding.type)
            if adapter is None:
                results.append(ArtifactResult(
                    adapter="orchestrator", artifact_id=binding.artifact_id, artifact_type=binding.type,
                    status="failed", diagnostics=[f"Approved publisher is not configured for {binding.type.value}"],
                ))
                continue
            results.append(adapter.publish(bundle, binding, output_dir / DEFAULT_FILENAMES[binding.type]))
        return results
