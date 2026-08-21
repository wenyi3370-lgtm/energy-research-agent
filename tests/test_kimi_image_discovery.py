"""P0-14/15/16 regression: Kimi image goals route to the bridge, Kimi opens
REAL target pages (never only search-result pages), image discovery reads
real image DOM (src/srcset/lazy/picture/background), candidates keep page
context, product/factory images stay bound, zero results are visible, and
verified images reach the archiver.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

from enterprise_energy_research.adapters.base import AdapterHealth, SearchRequest, SearchResultEnvelope
from enterprise_energy_research.domain.enums import EnterpriseComplexity
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Entity, Source
from enterprise_energy_research.research.image_archiver import ImageAssetArchiver
from enterprise_energy_research.research.image_discovery import (
    IMAGE_DISCOVERY_JS, ImageEvidenceBuilder, KimiImageDiscovery, KimiUsageTelemetry,
)
from enterprise_energy_research.research.image_validator import ImageValidator
from enterprise_energy_research.research.planner import ResearchPlanner


def png_bytes(width: int = 600, height: int = 400) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeKimiAdapter:
    name = "kimi_webbridge"

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.navigated: list[dict] = []
        self.evaluations: list[str] = []
        self.requests: list[SearchRequest] = []
        self.evaluate_payload: dict = {}

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name, available=self.available,
            diagnostics=[] if self.available else ["browser extension disconnected"],
        )

    def navigate_to(self, url: str, *, new_tab: bool = False) -> dict:
        self.navigated.append({"url": url, "new_tab": new_tab})
        return {"url": url, "tabId": 1}

    def evaluate(self, code: str) -> dict:
        self.evaluations.append(code)
        return self.evaluate_payload

    def search(self, request: SearchRequest) -> SearchResultEnvelope:
        self.requests.append(request)
        if not self.available:
            return SearchResultEnvelope(adapter=self.name, query_id=request.query_id, status="blocked", diagnostics=["daemon offline"])
        url = request.metadata.get("url") or "https://www.bing.com/search?q=x"
        return SearchResultEnvelope(
            adapter=self.name, query_id=request.query_id, status="ok",
            hits=[{
                "requested_url": url, "final_url": url, "title": "目标页",
                "text": "页面快照", "status": "ok",
                "retrieved_at": "2026-08-20T00:00:00Z",
                "metadata": {"target_page": bool(request.metadata.get("url"))},
            }],
        )


IMAGE_PAYLOAD = {
    "page_title": "ACME 产品中心",
    "page_url": "https://www.acme-corp.com/products",
    "images": [
        {"url": "https://www.acme-corp.com/img/logo.png", "src_attr": "src", "alt": "ACME 标识",
         "title": "logo", "surrounding_text": "公司标识", "link_target": "https://www.acme-corp.com",
         "width": 300, "height": 150},
        {"url": "https://www.acme-corp.com/img/p1.png 1x, https://www.acme-corp.com/img/p1@2x.png 2x",
         "src_attr": "srcset", "alt": "产品图片", "surrounding_text": "储能柜产品", "width": 600, "height": 400},
        {"url": "https://www.acme-corp.com/img/p2.png", "src_attr": "data-src", "alt": "产线图",
         "surrounding_text": "生产线", "width": 500, "height": 300},
        {"url": "https://www.acme-corp.com/img/p3.webp", "src_attr": "picture/source", "alt": "厂区",
         "surrounding_text": "生产基地", "width": 700, "height": 350},
        {"url": "https://www.acme-corp.com/img/bg.png", "src_attr": "background-image", "alt": "",
         "surrounding_text": "背景", "width": 0, "height": 0},
    ],
}


class KimiImageDiscoveryTests(unittest.TestCase):
    def test_image_goal_routes_to_kimi(self) -> None:
        plan = ResearchPlanner().build(
            "RUN-1", "ENT-1", "ACME", EnterpriseComplexity.ENTERPRISE_NORMAL,
            {"max_queries": 6, "max_pages": 20},
        )
        image_queries = [query for query in plan.queries if query.topic == "image_evidence"]
        self.assertTrue(image_queries)
        self.assertTrue(all(query.adapter_preference == "kimi_webbridge" for query in image_queries))

    def test_kimi_visits_target_page_not_only_search_result(self) -> None:
        """Kimi opens the REAL target pages for product-catalog topics — never
        only a search-result page."""
        from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner
        from enterprise_energy_research.domain.models import ResearchQuery
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        runner = AdaptiveResearchRunner(
            {"kimi_webbridge": kimi, "anysearch": FakeKimiAdapter()},
            fetcher=lambda url, referer: png_bytes(),
        )
        query = ResearchQuery.model_validate({
            "query_id": "Q1", "entity_id": "E1", "topic": "products",
            "query": "ACME 产品中心", "purpose": "R1 catalog",
            "collection_round": "R1", "round_goal": "coverage",
            "adapter_preference": "kimi_webbridge", "requires_browser": True,
        })
        envelope = SearchResultEnvelope(
            adapter="anysearch", query_id="Q1", status="ok", topic="products",
            collection_round="R1", round_goal="coverage",
            hits=[{
                "requested_url": "https://www.bing.com/search?q=x",
                "final_url": "https://www.acme-corp.com/products",
                "title": "产品中心", "text": "snippet", "status": "ok",
                "retrieved_at": "2026-08-21T00:00:00Z",
            }],
        )
        telemetry = KimiUsageTelemetry()
        extended = runner._browser_depth_pass([envelope], [query], telemetry)
        deep = [item for item in extended if item.adapter == "kimi_webbridge"]
        self.assertTrue(deep, "Kimi did not open the target product page")
        target_requests = [request for request in kimi.requests if request.metadata.get("url")]
        self.assertTrue(target_requests)
        self.assertTrue(all(
            request.metadata["url"] == "https://www.acme-corp.com/products" for request in target_requests
        ))
        self.assertTrue(all("bing.com" not in request.metadata["url"] for request in target_requests))

    def test_kimi_health_failure_is_visible(self) -> None:
        kimi = FakeKimiAdapter(available=False)
        telemetry = KimiUsageTelemetry()
        candidates = KimiImageDiscovery(kimi, telemetry).discover([{"url": "https://www.acme-corp.com/products"}])
        self.assertEqual(candidates, [])
        self.assertEqual(telemetry.kimi_status, "BLOCKED")
        self.assertEqual(telemetry.image_discovery_status, "BLOCKED")
        self.assertIn("browser extension disconnected", telemetry.reason or "")

    def test_kimi_image_discovery_extracts_src(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        telemetry = KimiUsageTelemetry()
        candidates = KimiImageDiscovery(kimi, telemetry).discover(
            [{"url": "https://www.acme-corp.com/products", "kind": "image"}],
        )
        self.assertIn("src", {candidate.src_attribute for candidate in candidates})
        logo = next(candidate for candidate in candidates if candidate.alt == "ACME 标识")
        self.assertEqual(logo.url, "https://www.acme-corp.com/img/logo.png")
        self.assertEqual(telemetry.image_discovery_status, "OK")
        self.assertGreaterEqual(telemetry.kimi_dom_inspections, 1)

    def test_kimi_extracts_srcset(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products"}],
        )
        srcset = [candidate for candidate in candidates if candidate.src_attribute == "srcset"]
        self.assertTrue(srcset)
        self.assertIn("1x", srcset[0].url)

    def test_kimi_extracts_lazy_loaded_image(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products"}],
        )
        lazy = [candidate for candidate in candidates if candidate.src_attribute == "data-src"]
        self.assertTrue(lazy)
        picture = [candidate for candidate in candidates if candidate.src_attribute == "picture/source"]
        self.assertTrue(picture)
        background = [candidate for candidate in candidates if candidate.src_attribute == "background-image"]
        self.assertTrue(background)

    def test_image_candidate_contains_page_context(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products", "kind": "product", "product_key": "P-1"}],
        )
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate.page_url, "https://www.acme-corp.com/products")
            self.assertEqual(candidate.page_title, "ACME 产品中心")
            self.assertEqual(candidate.product_key, "P-1")

    def test_product_image_links_to_product(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products", "kind": "product", "product_key": "P-1"}],
        )
        builder = ImageEvidenceBuilder(fetcher=lambda url, referer: png_bytes())
        product_candidate = next(candidate for candidate in candidates if candidate.src_attribute == "src")
        image = builder.build(product_candidate, source_id="S1", entity_id="E1", product_id="PROD-1")
        self.assertIsNotNone(image)
        self.assertEqual(image.product_id, "PROD-1")
        self.assertEqual(str(image.source_page_url), "https://www.acme-corp.com/products")

    def test_factory_image_links_to_factory(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/factory", "kind": "factory", "factory_key": "F-1"}],
        )
        builder = ImageEvidenceBuilder(fetcher=lambda url, referer: png_bytes())
        factory_candidate = next(
            candidate for candidate in candidates
            if candidate.surrounding_text and "生产基地" in candidate.surrounding_text
        )
        image = builder.build(factory_candidate, source_id="S1", entity_id="E1", factory_id="FAC-1")
        self.assertIsNotNone(image)
        self.assertEqual(image.factory_id, "FAC-1")
        self.assertEqual(image.image_type, "factory")

    def test_zero_image_result_is_not_silent_pass(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = {"page_title": "无图页", "page_url": "https://www.acme-corp.com/p", "images": []}
        telemetry = KimiUsageTelemetry()
        candidates = KimiImageDiscovery(kimi, telemetry).discover([{"url": "https://www.acme-corp.com/p"}])
        self.assertEqual(candidates, [])
        self.assertEqual(telemetry.image_candidates_found, 0)
        self.assertEqual(telemetry.image_discovery_status, "EMPTY")
        self.assertEqual(telemetry.kimi_dom_inspections, 1)

    def test_decorative_chrome_is_filtered_in_dom(self) -> None:
        """Icons/avatars/QR-code chrome must never become evidence images."""
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = {
            "page_title": "CATL 产品页", "page_url": "https://www.catl.com/products",
            "images": [
                {"url": "https://www.catl.com/static/icon/arrow.png", "src_attr": "src",
                 "alt": "", "surrounding_text": "", "width": 24, "height": 24},
                {"url": "https://www.catl.com/avatar.png", "src_attr": "src",
                 "alt": "", "surrounding_text": "", "width": 60, "height": 60},
                {"url": "https://www.catl.com/qrcode.png", "src_attr": "src",
                 "alt": "", "surrounding_text": "", "width": 200, "height": 200},
                {"url": "https://www.catl.com/upload/product-a.jpg", "src_attr": "src",
                 "alt": "", "surrounding_text": "", "width": 800, "height": 600},
            ],
        }
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.catl.com/products", "kind": "product"}],
        )
        urls = {candidate.url for candidate in candidates}
        self.assertNotIn("https://www.catl.com/static/icon/arrow.png", urls)
        self.assertNotIn("https://www.catl.com/avatar.png", urls)
        self.assertNotIn("https://www.catl.com/qrcode.png", urls)
        self.assertIn("https://www.catl.com/upload/product-a.jpg", urls)

    def test_url_hints_and_size_heuristics_classify_images(self) -> None:
        cases = [
            # (raw, page_kind, expected_type)
            ({"url": "https://x.com/static/logo.png", "alt": "", "surrounding_text": ""}, "factory", "logo"),
            ({"url": "https://x.com/upload/a.png", "alt": "", "surrounding_text": "",
              "width": 100, "height": 100}, "factory", "logo"),  # small square → logo
            ({"url": "https://x.com/upload/b.jpg", "alt": "", "surrounding_text": "",
              "width": 900, "height": 600}, "factory", "factory"),  # scene → page fallback
            ({"url": "https://x.com/upload/c.jpg", "alt": "", "surrounding_text": "",
              "width": 900, "height": 600}, "product", "product"),
            ({"url": "https://x.com/upload/c.jpg", "alt": "", "surrounding_text": "",
              "width": 900, "height": 600}, "image", "other"),
        ]
        for raw, page_kind, expected in cases:
            with self.subTest(raw=raw, page_kind=page_kind):
                self.assertEqual(
                    KimiImageDiscovery._classify(raw, "页面标题", page_kind), expected,
                )

    def test_page_kind_is_carried_on_candidates(self) -> None:
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products", "kind": "product", "product_key": "P-1"}],
        )
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate.page_kind, "product")

    def test_verified_image_reaches_archiver(self) -> None:
        import hashlib
        payload = png_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        kimi = FakeKimiAdapter()
        kimi.evaluate_payload = IMAGE_PAYLOAD
        candidates = KimiImageDiscovery(kimi, KimiUsageTelemetry()).discover(
            [{"url": "https://www.acme-corp.com/products", "kind": "product", "product_key": "P-1"}],
        )

        def fetcher(url: str, referer: str) -> bytes:
            return payload

        builder = ImageEvidenceBuilder(fetcher=fetcher)
        candidate = next(item for item in candidates if item.src_attribute == "src")
        entity = Entity(
            entity_id="E1", canonical_name="ACME科技有限公司",
            official_website="https://www.acme-corp.com",
        )
        source = Source(
            source_id="S1", canonical_url="https://www.acme-corp.com/products",
            source_domain="acme-corp.com", publisher="ACME",
            source_level="SOURCE_A", grading_reason="verified official company source",
            content_type="text/html",
        )
        image = builder.build(candidate, source_id="S1", entity_id="E1")
        self.assertIsNotNone(image)
        validated = ImageValidator().validate([image], [entity], [source])
        self.assertEqual(validated[0].verification_status.value, "VERIFIED")
        with __import__("tempfile").TemporaryDirectory() as temp:
            result = ImageAssetArchiver(fetcher=lambda url, referer: (payload, "image/png")).archive(
                validated, Path(temp),
            )
            self.assertIn(validated[0].image_id, result.archived_image_ids)
            self.assertTrue(validated[0].image_id in [item.image_id for item in result.images if item.local_asset_ref])


if __name__ == "__main__":
    unittest.main()
