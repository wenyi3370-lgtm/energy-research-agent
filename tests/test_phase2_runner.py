from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from energy_research_agent.cli import synthetic_run


class Phase2RunnerTests(unittest.TestCase):
    def test_synthetic_run_freezes_and_skips_product_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = synthetic_run("示例制造有限公司", Path(temp))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["product_dashboard"], "SKIPPED")
            output = Path(str(result["output_dir"]))
            self.assertTrue((output / "data_freeze.json").exists())
            manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
            product = next(item for item in manifest["artifacts"] if item["type"] == "product_html")
            self.assertEqual(product["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()

