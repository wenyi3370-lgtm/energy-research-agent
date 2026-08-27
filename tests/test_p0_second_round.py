"""P0 second-round architecture acceptance tests (TEST 1–24)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

from energy_research_agent.artifacts.html import FrozenHtmlPublisher
from energy_research_agent.artifacts.narrative import NarrativeBuilder
from energy_research_agent.artifacts.word import FrozenWordPublisher
from energy_research_agent.domain.enums import ArtifactType
from energy_research_agent.research.decision_synthesis import ENERGY_FIELDS
from energy_research_agent.research.opportunity_assessment import OpportunityAssessmentEngine
from energy_research_agent.research.product_detail_frontier import (
    BoundedBrowserWorkerPool, PersistentProductDetailQueue, ProductDetailPageResult,
    normalize_url,
)
from energy_research_agent.validation.consulting_narrative import (
    BrowserExecutionValidator, ConsultingNarrativeValidator,
    PublicationVisibleTextValidator, TOCValidator, cjk_count,
)
from scripts.run_publication_qa import docx_heading_text, inject_static_toc_result
from tests.test_p0_diagram_design_system import _load_bundle


class _FakeBrowser:
    execution_lock = None

    def __init__(self, log: dict, fail: bool = False) -> None:
        self.log = log
        self.fail = fail

    def open_page(self, url: str):
        self.log["active"] += 1
        self.log["maximum"] = max(self.log["maximum"], self.log["active"])
        self.log["opened"].append(url)
        return url

    def wait_and_extract(self, page):
        if self.fail:
            raise TimeoutError("fixture timeout")
        return {"final_url": page, "title": "产品详情", "text": "已提取产品参数"}

    def close_page(self, page):
        self.log["closed"].append(page)
        self.log["active"] -= 1


class SecondRoundP0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.bundle, cls.manifest = _load_bundle(cls.temp.name)
        cls.narrative = NarrativeBuilder().build(cls.bundle)
        cls.word = cls.root / "enterprise_research.docx"
        cls.html = cls.root / "enterprise_research_dashboard.html"
        word_binding = next(item for item in cls.manifest.artifacts if item.type == ArtifactType.WORD)
        html_binding = next(item for item in cls.manifest.artifacts if item.type == ArtifactType.ENTERPRISE_HTML)
        FrozenWordPublisher().publish(cls.bundle, word_binding, cls.word)
        FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(cls.bundle, html_binding, cls.html)
        visible = PublicationVisibleTextValidator()
        cls.word_text = visible.extract_docx(cls.word)
        cls.html_text = visible.extract_html(cls.html)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_01_word_toc_placeholder_zero(self):
        self.assertNotIn("更新域以显示", self.word_text)

    def test_02_word_toc_field_headings_and_page_field(self):
        self.assertEqual(TOCValidator().validate(self.word), [])
        with zipfile.ZipFile(self.word) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
            footer_xml = "".join(archive.read(name).decode("utf-8") for name in archive.namelist() if name.startswith("word/footer") and name.endswith(".xml"))
        self.assertIn("TOC \\o", xml)
        self.assertIn("PAGE", footer_xml)
        self.assertIn("执行摘要与决策建议", self.word_text)
        # Final QA may be safely rerun: rebuilding a LibreOffice-split field
        # must not overwrite the first real Heading 1 paragraph.
        rerun = self.root / "toc-idempotency.docx"
        shutil.copy2(self.word, rerun)
        headings = docx_heading_text(rerun)
        entries = [(heading, index + 3) for index, heading in enumerate(headings)]
        inject_static_toc_result(rerun, entries)
        inject_static_toc_result(rerun, entries)
        self.assertEqual(docx_heading_text(rerun), headings)
        self.assertEqual(TOCValidator().validate(rerun), [])

    def test_03_word_internal_status_zero(self):
        for token in ("requires_site_due_diligence", "SEARCH_FAILED", "NORMALIZED_NOT_VERIFIED"):
            self.assertNotIn(token, self.word_text)

    def test_04_html_internal_status_zero(self):
        for token in ("requires_site_due_diligence", "SEARCH_FAILED", "NORMALIZED_NOT_VERIFIED"):
            self.assertNotIn(token, self.html_text)

    def test_05_publication_raw_energy_keys_zero(self):
        for token in ("electricity_consumption", "transformer_capacity", "load_curve", "roof_area", "operating_schedule"):
            self.assertNotIn(token, self.word_text + self.html_text)

    def test_06_opportunity_is_deduped_before_publication(self):
        solution = self.bundle.solutions[0]
        duplicate = solution.model_copy(update={"solution_id": solution.solution_id + "-DUP"})
        bundle = self.bundle.model_copy(update={"solutions": [solution, duplicate]})
        assessments = OpportunityAssessmentEngine().assess(bundle)
        self.assertEqual(len(assessments), 1)

    def test_07_source_has_one_appendix_owner_and_no_body_chapter(self):
        self.assertIsNone(self.narrative.chapter("sources"))
        self.assertTrue(self.narrative.appendices.source_ledger)
        self.assertEqual(sum(chapter.chapter_id == "sources" for chapter in self.narrative.chapters), 0)

    def test_08_html_source_ledger_once(self):
        self.assertEqual(self.html_text.count("来源索引"), 1)

    def test_09_manufacturing_gwh_never_enters_energy_visual(self):
        claim_by_id = {item.claim_id: item for item in self.bundle.claims}
        for visual in self.narrative.visuals:
            if visual.semantic_domain != "energy":
                continue
            self.assertTrue(all(claim_by_id[cid].field_name in ENERGY_FIELDS for cid in visual.source_claim_ids))

    def test_10_one_year_revenue_is_not_a_trend(self):
        source_claim = self.bundle.claims[0]
        revenue = source_claim.model_copy(update={
            "claim_id": "CLAIM-REV-2025", "field_name": "revenue", "value": 100000000,
            "unit": "元", "as_of_date": date(2025, 12, 31), "period_end": date(2025, 12, 31),
        })
        bundle = self.bundle.model_copy(update={"claims": [*self.bundle.claims, revenue]})
        narrative = NarrativeBuilder().build(bundle)
        self.assertFalse(any(visual.semantic_pattern == "time_series" and "收入" in visual.title for visual in narrative.visuals))
        self.assertIn("不能据此声称长期增长趋势", narrative.chapter("operations").assertion_title)

    def test_11_three_year_revenue_has_trend_and_visual(self):
        source_claim = self.bundle.claims[0]
        rows = [source_claim.model_copy(update={
            "claim_id": f"CLAIM-REV-{year}", "field_name": "revenue", "value": value,
            "unit": "元", "as_of_date": date(year, 12, 31), "period_end": date(year, 12, 31),
        }) for year, value in ((2023, 100000000), (2024, 120000000), (2025, 150000000))]
        narrative = NarrativeBuilder().build(self.bundle.model_copy(update={"claims": [*self.bundle.claims, *rows]}))
        self.assertIn("经营趋势基础", narrative.chapter("operations").assertion_title)
        self.assertTrue(any(visual.semantic_pattern == "time_series" for visual in narrative.visuals))

    def test_12_all_publication_table_headers_are_chinese(self):
        for chapter in self.narrative.chapters:
            for row in chapter.table_rows:
                self.assertTrue(all(cjk_count(str(key)) > 0 or "Go / No-Go" in str(key) for key in row))

    def test_13_executive_summary_has_five_decision_parts(self):
        text = "".join(self.narrative.executive_summary)
        for token in ("企业定位", "经营与战略", "合作建议", "主要限制", "下一步"):
            self.assertIn(token, text)

    def test_14_every_opportunity_has_complete_decision_contract(self):
        for item in self.narrative.opportunity_assessments:
            self.assertTrue(item.strategic_rationale and item.target_scenario and item.our_value_proposition)
            self.assertTrue(item.key_prerequisites and item.first_30_day_action and item.go_no_go_gate)

    def test_15_word_html_overall_judgement_match(self):
        self.assertIn(self.narrative.overall_judgement, self.word_text)
        self.assertIn(self.narrative.overall_judgement, self.html_text)

    def test_16_word_html_opportunity_ranking_match(self):
        for item in self.narrative.opportunity_assessments:
            self.assertIn(item.opportunity_name, self.word_text)
            self.assertIn(item.opportunity_name, self.html_text)

    def test_17_word_html_key_risks_match(self):
        html_payload = self.html.read_text(encoding="utf-8")
        for risk in self.narrative.key_risks:
            self.assertIn(risk, self.word_text)
            self.assertIn(risk, html_payload)

    def test_18_main_body_meets_gate_without_template_padding(self):
        result = ConsultingNarrativeValidator().validate(self.narrative)
        self.assertEqual(result.status, "PASS", [item.model_dump() for item in result.checks if item.status == "FAIL"])
        self.assertGreaterEqual(result.main_body_cjk_char_count, result.threshold)

    def test_19_exact_duplicate_body_paragraphs_zero(self):
        paragraphs = [p.strip() for chapter in self.narrative.chapters for p in chapter.content if p.strip()]
        self.assertFalse([p for p, count in Counter(paragraphs).items() if count > 1])

    def test_20_raw_schema_headers_zero(self):
        self.assertEqual(PublicationVisibleTextValidator().validate_text(self.word_text), [])
        for token in ("catalog_items", "official_product_centers", "{'", '{"'):
            self.assertNotIn(token, self.word_text + self.html_text)
        self.assertEqual(PublicationVisibleTextValidator().validate_text(self.html_text), [])

    def test_21_browser_pool_never_exceeds_configured_workers(self):
        queue = PersistentProductDetailQueue(self.root / "pool.sqlite3")
        for index in range(8):
            queue.enqueue(f"https://example.com/product/{index}", source_page="https://example.com/products")
        log = {"active": 0, "maximum": 0, "opened": [], "closed": []}
        pool = BoundedBrowserWorkerPool(queue, lambda: _FakeBrowser(log), max_workers=3)
        pool.run()
        self.assertLessEqual(pool.metrics.max_active_pages, 3)
        self.assertEqual(BrowserExecutionValidator().validate(pool.metrics), [])

    def test_22_browser_page_closes_after_exception(self):
        queue = PersistentProductDetailQueue(self.root / "cleanup.sqlite3")
        queue.enqueue("https://example.com/product/error", source_page="https://example.com/products")
        log = {"active": 0, "maximum": 0, "opened": [], "closed": []}
        pool = BoundedBrowserWorkerPool(queue, lambda: _FakeBrowser(log, fail=True), max_workers=1, max_attempts=1)
        pool.run()
        self.assertEqual(log["opened"], log["closed"])
        self.assertEqual(BrowserExecutionValidator().validate(pool.metrics), [])

    def test_23_url_normalization_and_deduplication(self):
        variants = [
            "HTTPS://Example.com//product/one/?utm_source=x#spec",
            "https://example.com/product/one",
            "https://example.com/product/one/?fbclid=123",
        ]
        self.assertEqual(len({normalize_url(value) for value in variants}), 1)
        queue = PersistentProductDetailQueue(self.root / "dedupe.sqlite3")
        self.assertTrue(queue.enqueue(variants[0], source_page="https://example.com"))
        self.assertFalse(queue.enqueue(variants[1], source_page="https://example.com"))

    def test_24_persistent_queue_recovers_without_repeating_success(self):
        path = self.root / "recovery.sqlite3"
        queue = PersistentProductDetailQueue(path)
        queue.enqueue("https://example.com/product/done", source_page="https://example.com")
        queue.enqueue("https://example.com/product/pending", source_page="https://example.com")
        interrupted = queue.claim_next()
        self.assertIsNotNone(interrupted)
        recovered = PersistentProductDetailQueue(path)
        self.assertEqual(len(recovered.list("PENDING")), 2)
        log = {"active": 0, "maximum": 0, "opened": [], "closed": []}
        pool = BoundedBrowserWorkerPool(recovered, lambda: _FakeBrowser(log), max_workers=2)
        self.assertEqual(len(pool.run()), 2)
        rerun = BoundedBrowserWorkerPool(PersistentProductDetailQueue(path), lambda: _FakeBrowser(log), max_workers=2)
        self.assertEqual(rerun.run(), [])


if __name__ == "__main__":
    unittest.main()
