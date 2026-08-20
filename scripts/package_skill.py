from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "vendor" / "manifest.json"
EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "node_modules", "outputs"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def project_files() -> list[Path]:
    vendor_root = ROOT / "vendor" / "skills"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    trusted_vendor = {vendor_root / name for name in manifest["files"]}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if set(relative.parts) & EXCLUDED_PARTS or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.is_relative_to(vendor_root) and path not in trusted_vendor:
            continue
        if relative.parts[:2] == ("vendor", "skills") and path not in trusted_vendor:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def build(output: Path) -> dict:
    output = output.resolve()
    files = [path for path in project_files() if path.resolve() != output]
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = "enterprise-energy-research/"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            name = prefix + path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"status": "pass", "path": str(output), "files": len(files), "bytes": output.stat().st_size, "sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic self-contained Skill archive")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
