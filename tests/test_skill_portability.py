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
        self.assertIn("src/energy_research_agent/artifacts/word.py", relatives)
        self.assertIn("src/energy_research_agent/research/production_runner.py", relatives)
        self.assertIn("src/energy_research_agent/research/deep_retry.py", relatives)
        self.assertIn("scripts/run_product_image_recovery.py", relatives)
        self.assertNotIn(".env", relatives)
        self.assertFalse(any(path.startswith(("build/", "outputs/", ".venv/")) for path in relatives))
        self.assertFalse(any(path.endswith((".sqlite3", ".db", ".log", ".zip")) for path in relatives))

    def test_archive_is_self_contained_without_local_state(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "energy-research-agent.zip"
            root = Path(__file__).resolve().parents[1]
            portable_core = [root / "SKILL.md", root / "pyproject.toml", root / "uv.lock"]
            with patch("scripts.package_skill.project_files", return_value=portable_core):
                result = build(target)
            self.assertEqual(result["status"], "pass")
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
            prefix = "energy-research-agent/"
            self.assertIn(prefix + "SKILL.md", names)
            self.assertIn(prefix + "pyproject.toml", names)
            self.assertIn(prefix + "uv.lock", names)
            self.assertNotIn(prefix + ".env", names)
            self.assertFalse(any("/build/" in name or "/.venv/" in name for name in names))

    def test_new_agent_identity_has_no_previous_project_residue(self):
        root = Path(__file__).resolve().parents[1]
        previous_tokens = (
            "enterprise" + "-energy-research",
            "enterprise" + "_energy_research",
            "E" + "ER_",
        )
        text_suffixes = {
            ".bat", ".cjs", ".css", ".html", ".ini", ".js", ".json",
            ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
        }
        violations: list[str] = []
        for path in project_files():
            relative = path.relative_to(root).as_posix()
            if any(token in relative for token in previous_tokens):
                violations.append(relative)
                continue
            if path.suffix.lower() not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in previous_tokens):
                violations.append(relative)
        self.assertEqual(violations, [])

    def test_readme_documents_portable_agent_installation(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Energy Research Agent", readme)
        self.assertIn("energy_research_agent", readme)
        self.assertIn("ERA_", readme)
        self.assertIn("docker compose up -d --build", readme)
        self.assertIn("~/.agents/skills/energy-research-agent", readme)

    def test_intelligence_catchup_defaults_on_everywhere(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (root / ".env.example").read_text(encoding="utf-8")
        app = (
            root / "src/energy_research_agent/automation/api/app.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "ERA_INTELLIGENCE_CATCHUP: ${ERA_INTELLIGENCE_CATCHUP:-on}",
            compose,
        )
        self.assertIn("ERA_INTELLIGENCE_CATCHUP=on", env_example)
        self.assertIn(
            'os.environ.get("ERA_INTELLIGENCE_CATCHUP", "on")',
            app,
        )


if __name__ == "__main__":
    unittest.main()
