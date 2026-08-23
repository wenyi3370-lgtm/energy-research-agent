from __future__ import annotations

"""Republish Word/Excel/unified HTML from one exported frozen run.

This is intentionally a publication-only path: it reads the exported freeze
and artifact manifest, performs no web or model calls, and leaves evidence
unchanged.  It is useful for layout or publication-language fixes that must be
reproduced without rerunning collection.
"""

import argparse
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from enterprise_energy_research.artifacts.excel import ExcelMasterFrozenPublisher
from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.artifacts.publisher import ArtifactPublicationService
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.domain.enums import ArtifactType
from enterprise_energy_research.domain.models import (
    ArtifactManifest, Claim, ConflictGroup, DataFreeze, DataGap, EnergyProfile,
    EnterpriseEdge, Entity, Factory, FrozenResearchBundle, ImageEvidence,
    Product, Retrieval, RunManifest, Solution, Source,
)


T = TypeVar("T", bound=BaseModel)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path, model: type[T]) -> list[T]:
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _list(path: Path, model: type[T]) -> list[T]:
    payload = _json(path)
    rows = payload if isinstance(payload, list) else [payload]
    return [model.model_validate(row) for row in rows]


def load_exported_bundle(run_dir: Path) -> tuple[FrozenResearchBundle, ArtifactManifest]:
    evidence = run_dir / "01_evidence"
    graph = _json(evidence / "enterprise_graph.json")
    bundle = FrozenResearchBundle(
        freeze=DataFreeze.model_validate(_json(evidence / "data_freeze.json")),
        run_manifest=RunManifest.model_validate(_json(evidence / "run_manifest.json")),
        entities=[Entity.model_validate(row) for row in graph.get("entities", [])],
        factories=[Factory.model_validate(row) for row in graph.get("factories", [])],
        edges=[EnterpriseEdge.model_validate(row) for row in graph.get("edges", [])],
        sources=_jsonl(evidence / "sources.jsonl", Source),
        retrievals=_jsonl(evidence / "retrievals.jsonl", Retrieval),
        claims=_list(evidence / "facts.json", Claim),
        conflicts=_list(evidence / "conflicts.json", ConflictGroup),
        gaps=_list(evidence / "data_gaps.json", DataGap),
        images=_jsonl(evidence / "images.jsonl", ImageEvidence),
        products=_list(evidence / "products.json", Product),
        energy_profiles=_list(evidence / "energy_profile.json", EnergyProfile),
        solutions=_list(evidence / "solutions.json", Solution),
    )
    manifest = ArtifactManifest.model_validate(_json(evidence / "artifact_manifest.json"))
    return bundle, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = (args.output or run_dir / "artifacts").resolve()
    bundle, manifest = load_exported_bundle(run_dir)
    publishers = {
        ArtifactType.EXCEL: ExcelMasterFrozenPublisher(),
        ArtifactType.WORD: FrozenWordPublisher(),
        ArtifactType.ENTERPRISE_HTML: FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML),
    }
    results = ArtifactPublicationService(publishers).publish(bundle, manifest, output)
    payload = [result.model_dump(mode="json") for result in results]
    (run_dir / "republish_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(result.status in {"published", "skipped"} for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
