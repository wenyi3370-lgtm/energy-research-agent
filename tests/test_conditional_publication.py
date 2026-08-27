"""Conditional publication regression tests.

Evidence-absent targets must still get a deliverable: a report built only
from frozen verified evidence with a visible caveat banner, plus machine
readable blocking-gap records.
"""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.automation.contracts import DeepResearchPayload

from tests.test_office_image_publication import OfficeImagePublicationTests


class ConditionalPayloadTests(unittest.TestCase):
    def test_publish_conditional_defaults_on(self) -> None:
        payload = DeepResearchPayload(requirements="补充产品与产能证据")
        self.assertTrue(payload.publish_conditional)

    def test_publish_conditional_can_be_disabled(self) -> None:
        payload = DeepResearchPayload(requirements="补充产品与产能证据", publish_conditional=False)
        self.assertFalse(payload.publish_conditional)


class ConditionalBannerTests(unittest.TestCase):
    def _conditional_bundle(self, temp: str):
        base = OfficeImagePublicationTests()
        bundle, word_binding, html_binding = base._bundle_and_bindings(temp)
        from enterprise_energy_research.domain.enums import ArtifactType
        html_binding = html_binding.model_copy(update={"type": ArtifactType.ENTERPRISE_HTML})
        scope = dict(bundle.run_manifest.research_scope or {})
        scope["publication_mode"] = "conditional"
        bundle = bundle.model_copy(update={"run_manifest": bundle.run_manifest.model_copy(
            update={"research_scope": scope},
        )})
        return bundle, word_binding, html_binding

    def test_word_renders_conditional_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, word_binding, _ = self._conditional_bundle(temp)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, word_binding, target)
            self.assertEqual(result.status, "published")
            with zipfile.ZipFile(target) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("【条件发布】", xml)
            self.assertIn("覆盖缺口", xml)

    def test_word_without_conditional_mode_has_no_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = OfficeImagePublicationTests()
            bundle, word_binding, _ = base._bundle_and_bindings(temp)
            target = Path(temp) / "report.docx"
            result = FrozenWordPublisher().publish(bundle, word_binding, target)
            self.assertEqual(result.status, "published")
            with zipfile.ZipFile(target) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
            self.assertNotIn("【条件发布】", xml)

    def test_html_renders_conditional_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _, html_binding = self._conditional_bundle(temp)
            target = Path(temp) / "dashboard.html"
            result = FrozenHtmlPublisher(html_binding.type).publish(bundle, html_binding, target)
            self.assertEqual(result.status, "published")
            raw = target.read_text(encoding="utf-8")
            self.assertIn("【条件发布】", raw)


class PublishConditionallyHelperTests(unittest.TestCase):
    def test_helper_marks_run_manifest_and_calls_conditional_freeze(self) -> None:
        from unittest.mock import MagicMock, patch

        from enterprise_energy_research.research import deep_retry

        store = MagicMock()
        manifest = MagicMock()
        manifest.research_scope = {"mode": "full_enterprise_plus_supplements"}
        store.get_run.return_value = manifest
        # AdaptiveResearchRunner is imported lazily inside the helper, so the
        # patch must target the defining module.
        with patch("enterprise_energy_research.research.production_runner.AdaptiveResearchRunner") as runner_cls:
            runner_cls.return_value._freeze_and_publish.return_value = ("FREEZE-1", [])
            result = deep_retry.publish_conditionally(
                store, "RUN-1", Path("/tmp/out"),
                reason="evidence_absent_converged",
                blocking_gaps=["coverage-revenue"],
            )
        self.assertTrue(result["published"])
        self.assertEqual(result["publication_mode"], "conditional")
        # run manifest marked BEFORE freeze so the frozen bundle carries the
        # conditional mode for the Word/HTML banners
        scope = store.replace_run_manifest.call_args[0][0].research_scope
        self.assertEqual(scope["publication_mode"], "conditional")
        self.assertEqual(scope["blocking_gaps"], ["coverage-revenue"])
        self.assertEqual(scope["publication_mode_reason"], "evidence_absent_converged")
        args = runner_cls.return_value._freeze_and_publish.call_args
        self.assertTrue(args.kwargs.get("conditional"))


if __name__ == "__main__":
    unittest.main()
