from __future__ import annotations

from pathlib import Path

from energy_research_agent.domain.enums import ArtifactType
from energy_research_agent.domain.models import ArtifactBinding, FrozenResearchBundle

from .base import AdapterError, AdapterHealth, ArtifactResult, SearchRequest, SearchResultEnvelope


class UnconfiguredSearchAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def health(self) -> AdapterHealth:
        return AdapterHealth(name=self.name, available=False, diagnostics=[f"{self.name} is not configured"])

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        raise AdapterError(f"{self.name} is not configured; research cannot continue")


class UnconfiguredArtifactAdapter:
    def __init__(self, name: str, artifact_type: ArtifactType) -> None:
        self.name = name
        self.artifact_type = artifact_type

    def health(self) -> AdapterHealth:
        return AdapterHealth(name=self.name, available=False, diagnostics=[f"{self.name} is not configured"])

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        raise AdapterError(f"{self.name} is not configured; {binding.artifact_id} was not published")

