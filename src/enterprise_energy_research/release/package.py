from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from enterprise_energy_research.adapters.base import ArtifactResult

from .audit import ConsistencyReport


class ReleasePackageBuilder:
    def build(self, report: ConsistencyReport, results: list[ArtifactResult], output_path: Path) -> Path:
        if report.status.value != "PASS":
            raise ValueError("Cannot package artifacts that failed consistency validation")
        files = sorted([Path(item.path) for item in results if item.status == "published" and item.path], key=lambda item: item.name)
        checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        manifest = {
            "freeze_id": report.freeze_id,
            "status": report.status.value,
            "files": checksums,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
            info = zipfile.ZipInfo("release_manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
        return output_path
