"""Portable Skill archive and incident-fix regression gates."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.package_skill import build, project_files


class SkillPortabilityTests(unittest.TestCase):
    def test_project_files_exclude_secrets_and_runtime_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        relatives = {path.relative_to(root).as_posix() for path in project_files()}
        self.assertIn("SKILL.md", relatives)
        self.assertIn("src/enterprise_energy_research/artifacts/word.py", relatives)
        self.assertIn("src/enterprise_energy_research/research/production_runner.py", relatives)
        self.assertIn("src/enterprise_energy_research/research/deep_retry.py", relatives)
        self.assertIn("scripts/run_product_image_recovery.py", relatives)
        self.assertNotIn(".env", relatives)
        self.assertFalse(any(path.startswith(("build/", "outputs/", ".venv/")) for path in relatives))
        self.assertFalse(any(path.endswith((".sqlite3", ".db", ".log", ".zip")) for path in relatives))

    def test_archive_is_self_contained_without_local_state(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "enterprise-energy-research.zip"
            root = Path(__file__).resolve().parents[1]
            portable_core = [root / "SKILL.md", root / "pyproject.toml", root / "uv.lock"]
            with patch("scripts.package_skill.project_files", return_value=portable_core):
                result = build(target)
            self.assertEqual(result["status"], "pass")
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
            prefix = "enterprise-energy-research/"
            self.assertIn(prefix + "SKILL.md", names)
            self.assertIn(prefix + "pyproject.toml", names)
            self.assertIn(prefix + "uv.lock", names)
            self.assertNotIn(prefix + ".env", names)
            self.assertFalse(any("/build/" in name or "/.venv/" in name for name in names))


if __name__ == "__main__":
    unittest.main()
