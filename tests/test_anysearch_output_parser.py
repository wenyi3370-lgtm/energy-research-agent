from __future__ import annotations

import json
import unittest

from enterprise_energy_research.adapters.anysearch import AnySearchCliAdapter


class AnySearchOutputParserRegressionTests(unittest.TestCase):
    def test_anysearch_json_output_parses(self) -> None:
        hits = AnySearchCliAdapter._parse_output(json.dumps({
            "results": [{"title": "Official", "url": "https://example.com/a", "content": "full text"}]
        }))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "Official")
        self.assertEqual(hits[0].metadata["format"], "json")

    def test_anysearch_markdown_output_parses(self) -> None:
        hits = AnySearchCliAdapter._parse_output(
            "## Search Results\n\n### 1. Example\n- **URL**: https://example.com\nMaterial body"
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].final_url, "https://example.com")
        self.assertEqual(hits[0].metadata["format"], "markdown")

    def test_anysearch_empty_output(self) -> None:
        self.assertEqual(AnySearchCliAdapter._parse_output("  \n"), [])

    def test_anysearch_invalid_json_falls_back(self) -> None:
        hits = AnySearchCliAdapter._parse_output('{"results": broken')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].status, "partial")
        self.assertEqual(hits[0].metadata["format"], "markdown")

    def test_anysearch_multiple_hits(self) -> None:
        hits = AnySearchCliAdapter._parse_output(json.dumps({"data": {"hits": [
            {"name": "A", "link": "https://a.example", "snippet": "a"},
            {"name": "B", "link": "https://b.example", "description": "b"},
        ]}}))
        self.assertEqual([item.title for item in hits], ["A", "B"])

    def test_anysearch_extract_json(self) -> None:
        hits = AnySearchCliAdapter._parse_output(
            json.dumps({"content": "extracted page body"}), requested_url="https://example.com/page"
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].final_url, "https://example.com/page")
        self.assertIn("extracted page", hits[0].text or "")


if __name__ == "__main__":
    unittest.main()
