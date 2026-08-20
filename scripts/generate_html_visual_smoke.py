"""Generate a persistent unified-HTML visual QA artifact from recorded evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from PIL import Image

from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import load_yaml


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "html-visual-unified-smoke"


def main() -> int:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(
            encoding="utf-8"
        )
    )
    company = fixture[0]["entities"][0]["canonical_name"]
    batches = [ExtractedEvidenceBatch.model_validate(item) for item in fixture]
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp:
        temp_root = Path(temp)
        run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
        store = EvidenceStore(temp_root / "evidence.sqlite3")
        store.create_run(
            RunManifest(
                run_id=run_id,
                request_id=request_id,
                status=RunStatus.RUNNING,
                config_hash="html-visual-unified-smoke",
                code_version="0.9.0",
                model_gateway={"mode": "recorded-fixture"},
            )
        )
        state, manifest, _ = Phase3Runner(
            store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")
        ).process_batches(
            ResearchState(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING
            ),
            company,
            batches,
            output_dir=temp_root / "freeze",
        )
        if state.status != RunStatus.PASS or not state.freeze_id or manifest is None:
            raise RuntimeError(f"Recorded HTML smoke freeze failed: {state.status}")

        bundle = FreezeService(store).load_bundle(state.freeze_id)
        prepared_images = []
        for index, image in enumerate(bundle.images):
            asset = temp_root / f"fixture-{index}.png"
            shade = 74 + min(index * 22, 120)
            Image.new("RGB", (image.width, image.height), (shade, shade, shade)).save(
                asset, "PNG"
            )
            prepared_images.append(
                image.model_copy(
                    update={
                        "local_asset_ref": str(asset),
                        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                        "mime_type": "image/png",
                    }
                )
            )
        bundle = bundle.model_copy(update={"images": prepared_images})
        binding = next(
            item
            for item in manifest.artifacts
            if item.type == ArtifactType.ENTERPRISE_HTML
        )
        binding = binding.model_copy(
            update={
                "claim_ids": [claim.claim_id for claim in bundle.claims],
                "image_ids": [image.image_id for image in bundle.images],
            }
        )
        target = OUTPUT / "enterprise_research_dashboard.html"
        result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(
            bundle, binding, target
        )
        if result.status != "published":
            raise RuntimeError(f"HTML publisher failed: {result.diagnostics}")
        print(target.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
