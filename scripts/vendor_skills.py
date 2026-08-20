from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = ROOT / "vendor" / "skills"
MANIFEST_PATH = ROOT / "vendor" / "manifest.json"

COMPONENTS = {
    "anysearch": {
        "source": "Claude Skill snapshot v3.0.1",
        "required": [
            "SKILL.md", "LICENSE", "NOTICE", "scripts/anysearch_cli.py",
            "scripts/anysearch_cli.js", "scripts/anysearch_cli.ps1",
            "scripts/anysearch_cli.sh", "scripts/shared/constants.json",
            "scripts/shared/doc_spec.md",
        ],
    },
    "excel-master": {
        "source": "local Codex Skill snapshot",
        "required": ["SKILL.md", "scripts/make_excel.py", "scripts/chart_layout_guard.py"],
    },
    "ppt-master": {
        "source": "local Agent Skill snapshot",
        "required": [
            "SKILL.md", "references/strategist.md", "references/executor-base.md",
            "scripts/svg_quality_checker.py", "scripts/finalize_svg.py",
            "scripts/svg_to_pptx.py", "templates/design_spec_reference.md",
        ],
    },
    "frontend-design": {
        "source": "local Agent Skill snapshot",
        "required": ["SKILL.md", "LICENSE.txt"],
    },
    "kimi-webbridge": {
        "source": "local Codex Skill snapshot",
        "required": ["SKILL.md", "references/operations.md"],
    },
}

FORBIDDEN_PARTS = {
    ".git", ".venv", ".venv312", "__pycache__", "node_modules",
    "jobs", "playwright-browsers",
}
FORBIDDEN_NAMES = {
    "login_profiles.json", "browser-state-fingerprint.json", "global-context.jsonl", "cache.db",
}
SECRET_PATTERN = re.compile(
    r"(?im)^\s*(?!#)(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|COOKIE)[A-Z0-9_]*\s*=\s*(?!your-|example|changeme|<|\$\{|\{\{|none\b|null\b)[^\s#][^\r\n]*$"
)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def iter_files() -> list[Path]:
    return sorted(
        (
            path for path in VENDOR_ROOT.rglob("*")
            if path.is_file()
            and not (set(path.relative_to(VENDOR_ROOT).parts) & FORBIDDEN_PARTS)
            and path.name not in FORBIDDEN_NAMES
            and path.suffix != ".pyc"
        ),
        key=lambda path: path.relative_to(VENDOR_ROOT).as_posix(),
    )


def safety_findings(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        relative = path.relative_to(VENDOR_ROOT)
        config_like = path.name.startswith(".env") or path.suffix.lower() in {".env", ".ini", ".toml", ".yaml", ".yml"}
        if path.stat().st_size <= 2_000_000 and config_like:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if SECRET_PATTERN.search(text):
                findings.append(f"possible unredacted secret: {relative.as_posix()}")
    return findings


def build_manifest() -> dict:
    files = iter_files()
    findings = safety_findings(files)
    if findings:
        raise ValueError("Unsafe vendor snapshot:\n" + "\n".join(findings))
    components = {}
    for name, metadata in COMPONENTS.items():
        root = VENDOR_ROOT / name
        missing = [relative for relative in metadata["required"] if not (root / relative).is_file()]
        if missing:
            raise ValueError(f"{name} is incomplete: {', '.join(missing)}")
        component_files = [path for path in files if path.is_relative_to(root)]
        components[name] = {
            **metadata,
            "file_count": len(component_files),
            "byte_count": sum(path.stat().st_size for path in component_files),
        }
    workers = min(32, max(4, (len(files) // 500) + 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        hashes = list(executor.map(digest, files))
    return {
        "schema_version": "1.0",
        "policy": {
            "embedded_first": True,
            "private_runtime_state_bundled": False,
            "excluded": sorted(FORBIDDEN_PARTS | FORBIDDEN_NAMES),
        },
        "components": components,
        "files": {
            path.relative_to(VENDOR_ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": file_hash,
            }
            for path, file_hash in zip(files, hashes, strict=True)
        },
    }


def write_manifest() -> int:
    manifest = build_manifest()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "manifest": str(MANIFEST_PATH), "files": len(manifest["files"])}, ensure_ascii=False))
    return 0


def verify_manifest() -> int:
    if not MANIFEST_PATH.is_file():
        print(json.dumps({"status": "blocked", "findings": ["vendor/manifest.json is missing"]}, ensure_ascii=False))
        return 1
    expected = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    try:
        actual = build_manifest()
    except ValueError as exc:
        print(json.dumps({"status": "blocked", "findings": str(exc).splitlines()}, ensure_ascii=False))
        return 1
    findings = []
    if expected != actual:
        expected_files, actual_files = expected.get("files", {}), actual.get("files", {})
        for name in sorted(set(expected_files) | set(actual_files)):
            if expected_files.get(name) != actual_files.get(name):
                findings.append(f"manifest mismatch: {name}")
    status = "pass" if not findings else "blocked"
    print(json.dumps({"status": status, "files": len(actual["files"]), "findings": findings}, ensure_ascii=False))
    return 0 if not findings else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify the embedded Skill supply-chain manifest")
    parser.add_argument("command", choices=("manifest", "verify"))
    args = parser.parse_args()
    return write_manifest() if args.command == "manifest" else verify_manifest()


if __name__ == "__main__":
    sys.exit(main())
