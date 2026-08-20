from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from enterprise_energy_research.domain.models import ArtifactManifest, FrozenResearchBundle


def _json_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _jsonl_bytes(records: Iterable[BaseModel]) -> bytes:
    lines = [json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for record in records]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def export_bundle(bundle: FrozenResearchBundle, manifest: ArtifactManifest, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "facts.json": _json_bytes([claim.model_dump(mode="json") for claim in bundle.claims]),
        "sources.jsonl": _jsonl_bytes(bundle.sources),
        "images.jsonl": _jsonl_bytes(bundle.images),
        "retrievals.jsonl": _jsonl_bytes(bundle.retrievals),
        "enterprise_graph.json": _json_bytes({
            "entities": [item.model_dump(mode="json") for item in bundle.entities],
            "factories": [item.model_dump(mode="json") for item in bundle.factories],
            "edges": [item.model_dump(mode="json") for item in bundle.edges],
        }),
        "conflicts.json": _json_bytes([item.model_dump(mode="json") for item in bundle.conflicts]),
        "data_gaps.json": _json_bytes([item.model_dump(mode="json") for item in bundle.gaps]),
        "products.json": _json_bytes([item.model_dump(mode="json") for item in bundle.products]),
        "energy_profile.json": _json_bytes([item.model_dump(mode="json") for item in bundle.energy_profiles]),
        "solutions.json": _json_bytes([item.model_dump(mode="json") for item in bundle.solutions]),
        "run_manifest.json": _json_bytes(bundle.run_manifest),
        "data_freeze.json": _json_bytes(bundle.freeze),
        "artifact_manifest.json": _json_bytes(manifest),
    }
    checksums: dict[str, str] = {}
    for name, content in files.items():
        path = output_dir / name
        path.write_bytes(content)
        checksums[name] = hashlib.sha256(content).hexdigest()
    (output_dir / "checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
    return checksums
