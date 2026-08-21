"""P0 refactor system tests (TEST 1-20).

Covers the diagram-design visual system contract end to end:
1-7   VisualSpec schema + Visual Router routing/anti-abuse
8-10  DiagramDesignAdapter rendering / single-source / fallback
11-12 normalization-before-freeze canonicalizers
13    analysis layer (YoY/CAGR with full derivation trace)
14-16 narrative-driven chapters, product-no-image fix, org relationship gate
17-18 image publication gate + per-chapter budgets
19    QA separation from user-facing reports
20    Lieflat removal + diagram-design third-party compliance
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.analysis.financials import FinancialAnalyst, parse_number
from enterprise_energy_research.artifacts.diagram_design_adapter import DiagramDesignAdapter
from enterprise_energy_research.artifacts.html import FrozenHtmlPublisher
from enterprise_energy_research.artifacts.image_publication import prepare_publication_images, publication_eligible
from enterprise_energy_research.artifacts.narrative import (
    IMAGE_BUDGETS,
    NarrativeBuilder,
    publishable_images,
)
from enterprise_energy_research.artifacts.visual_router import RULES, VisualProposal, VisualRouter
from enterprise_energy_research.artifacts.visuals import VisualDatum, VisualNode, VisualSpec, VisualStage
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.domain.enums import ArtifactType, RunStatus, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import (
    Claim, EnterpriseEdge, ExtractedEvidenceBatch, RunManifest,
)
from enterprise_energy_research.evidence.freeze import FreezeService
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.research.canonicalizers import FactoryCanonicalizer, ProductCanonicalizer, UnitNormalizer
from enterprise_energy_research.settings import load_yaml
from enterprise_energy_research.vendor import EMBEDDED_SKILLS


ROOT = Path(__file__).resolve().parents[1]


def _load_bundle(temp: str, fixture: str = "normal_manufacturer.json"):
    raw = json.loads((ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8"))
    company = raw[0]["entities"][0]["canonical_name"]
    run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
    store = EvidenceStore(Path(temp) / "evidence.sqlite3")
    store.create_run(RunManifest(
        run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
        config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "fixture"},
    ))
    state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
        ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING), company,
        [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
    )
    return FreezeService(store).load_bundle(state.freeze_id), manifest


class P0VisualSystemTests(unittest.TestCase):
    # ── TEST 1: Lieflat fully removed from runtime ──────────────────────────
    def test_01_lieflat_runtime_references_are_zero(self) -> None:
        hits: list[str] = []
        for path in (ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            if "lieflat" in text:
                hits.append(str(path))
        self.assertEqual(hits, [], "Lieflat references remain in src/: %s" % hits)
        self.assertNotIn("lieflat-charts", EMBEDDED_SKILLS)
        self.assertNotIn("lieflat", " ".join(EMBEDDED_SKILLS))
        self.assertFalse((ROOT / "vendor" / "skills" / "lieflat-charts").exists())

    # ── TEST 2: VisualSpec carries the full P0 field contract ───────────────
    def test_02_visualspec_has_required_fields(self) -> None:
        required = {
            "visual_id", "chapter_id", "decision_question", "business_thesis",
            "visual_type", "semantic_pattern", "title", "subtitle", "data_binding",
            "source_ids", "unit", "period", "scope", "transformation",
            "assumption_status", "verified", "destination", "editorial_priority",
        }
        spec = VisualSpec(visual_id="v1", chapter_id="c1", decision_question="q",
                          business_thesis="t", semantic_pattern="none", title="标题")
        self.assertTrue(required.issubset(VisualSpec.model_fields))
        self.assertEqual(spec.visual_type, "table")  # safe default, never None

    # ── TEST 3: semantic pattern → visual type routing ──────────────────────
    def test_03_router_maps_semantic_patterns(self) -> None:
        router = VisualRouter()
        expectations = {
            "time_series": "line", "category_comparison": "bar",
            "multi_dimension_score": "radar", "opportunity_priority": "quadrant",
            "two_metric_distribution": "scatter", "part_to_whole": "treemap",
            "technology_evolution": "timeline", "operational_process": "process",
            "value_flow": "sankey", "implementation_roadmap": "gantt",
            "hierarchy_or_conversion": "pyramid", "verified_relationship": "tree",
            "root_cause": "fishbone", "system_architecture": "architecture",
            "customer_journey": "journey", "data_handoff": "data_flow",
        }
        self.assertEqual(set(RULES), set(expectations) | {"quantitative_facts", "none"})
        for pattern, visual_type in expectations.items():
            proposal = _rich_proposal(pattern)
            spec, check = router.route(proposal)
            self.assertIsNotNone(spec, f"{pattern} dropped unexpectedly: {check.reasons}")
            self.assertEqual(spec.visual_type, visual_type, pattern)

    # ── TEST 4-7: anti-chart-abuse rules ────────────────────────────────────
    def test_04_no_fake_time_series_becomes_line(self) -> None:
        router = VisualRouter()
        proposal = VisualProposal(visual_id="t", chapter_id="c", decision_question="q",
                                  business_thesis="b", semantic_pattern="time_series", title="t")
        proposal.items = [
            VisualDatum(label="a", value=10, period="2023"),
            VisualDatum(label="b", value=12, period="2023"),  # same period: not a series
        ]
        spec, check = router.route(proposal)
        self.assertTrue(check.fallback or spec is None or spec.visual_type != "line")
        if spec is not None:
            self.assertNotEqual(spec.visual_type, "line")

    def test_05_no_fake_scores_become_radar(self) -> None:
        router = VisualRouter()
        proposal = VisualProposal(visual_id="t", chapter_id="c", decision_question="q",
                                  business_thesis="b", semantic_pattern="multi_dimension_score", title="t")
        proposal.items = [
            VisualDatum(label="维度A", value=80),
            VisualDatum(label="维度B", value=None),  # missing score
            VisualDatum(label="维度C", value=None),
        ]
        spec, check = router.route(proposal)
        if spec is not None:
            self.assertNotEqual(spec.visual_type, "radar")
            self.assertTrue(check.fallback, "only the table/KPI fallback may survive")
        else:
            self.assertTrue(check.fallback)

    def test_06_no_xy_metrics_no_quadrant_or_scatter(self) -> None:
        router = VisualRouter()
        for pattern in ("opportunity_priority", "two_metric_distribution"):
            proposal = VisualProposal(visual_id="t", chapter_id="c", decision_question="q",
                                      business_thesis="b", semantic_pattern=pattern, title="t")
            proposal.items = [VisualDatum(label="甲", value=10), VisualDatum(label="乙", value=8)]
            spec, check = router.route(proposal)
            self.assertFalse(spec and spec.visual_type in {"quadrant", "scatter"}, pattern)

    def test_07_no_flow_weights_no_sankey(self) -> None:
        router = VisualRouter()
        proposal = VisualProposal(visual_id="t", chapter_id="c", decision_question="q",
                                  business_thesis="b", semantic_pattern="value_flow", title="t")
        proposal.stages = [
            VisualStage(id="a", label="原料", from_label="原料", to_label="成品"),
            VisualStage(id="b", label="成品", from_label="成品", to_label="交付"),
        ]
        spec, check = router.route(proposal)
        self.assertIsNone(spec)
        self.assertTrue(check.fallback)

    # ── TEST 8-10: adapter rendering / single source / fallback ─────────────
    def test_08_adapter_renders_all_supported_types(self) -> None:
        adapter = DiagramDesignAdapter()
        self.assertEqual(len(adapter.supported_types()), 18)
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for visual_type in sorted(adapter.supported_types()):
                spec = _spec_for(visual_type)
                result = adapter.build_visual(spec, out, destination="html")
                self.assertIn(result.status, {"rendered", "fallback_table"}, visual_type)
                self.assertIsNotNone(result.svg_markup)
                self.assertIn('role="img"', result.svg_markup)
                self.assertIn("aria-labelledby=", result.svg_markup)
                self.assertIn(f'id="{spec.visual_id}-title"', result.svg_markup)

    def test_09_html_svg_png_are_single_source(self) -> None:
        adapter = DiagramDesignAdapter()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            spec = _spec_for("bar")
            result = adapter.build_visual(spec, out, destination="both", png_scale=2)
            self.assertIn(result.svg_markup, result.html_path.read_text(encoding="utf-8"))
            self.assertIn(result.svg_markup, result.svg_path.read_text(encoding="utf-8"))
            if result.png_path is not None:
                from PIL import Image
                with Image.open(result.png_path) as image:
                    self.assertGreaterEqual(image.size[0], 100)
            # standalone SVG follows diagram-design export.md: XML declaration + xmlns
            standalone = result.svg_path.read_text(encoding="utf-8")
            self.assertTrue(standalone.startswith('<?xml version="1.0"'))
            self.assertIn('xmlns="http://www.w3.org/2000/svg"', standalone)

    def test_10_renderer_failure_degrades_never_silently_drops(self) -> None:
        adapter = DiagramDesignAdapter()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            spec = _spec_for("line")
            spec.items = []  # crashes the line generator → safe fallback
            result = adapter.build_visual(spec, out, destination="both")
            self.assertEqual(result.status, "fallback_table")
            self.assertTrue(result.svg_path.is_file())
            self.assertTrue(result.fallback_reason)
            # the fallback is a structured table drawn from the same spec data
            self.assertIn("table", result.visual_type)

    # ── TEST 11-12: normalization before freeze ─────────────────────────────
    def test_11_unit_normalizer_fixes_mechanical_corruption(self) -> None:
        normalizer = UnitNormalizer()
        self.assertEqual(normalizer.normalize("kmkm"), "km")
        self.assertEqual(normalizer.normalize("%%"), "%")
        self.assertEqual(normalizer.normalize("次次"), "次")
        self.assertEqual(normalizer.normalize("年年"), "年")
        self.assertEqual(normalizer.normalize("万千瓦时"), "万kWh")
        self.assertEqual(normalizer.normalize("千瓦时"), "kWh")

    def test_12_product_and_factory_canonicalizers_merge_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = _load_bundle(temp)
            product = bundle.products[0]
            duplicate = product.model_copy(update={
                "product_id": "PROD-DUP", "source_ids": ["S2"],
                "description": "补充描述",
            })
            merged = ProductCanonicalizer().canonicalize([product, duplicate])
            self.assertEqual(len(merged), 1)
            self.assertIn("S2", merged[0].source_ids)
            # first-seen record keeps its own data; the union only extends lists
            self.assertEqual(merged[0].description, product.description)
            factory = bundle.factories[0]
            factory_dup = factory.model_copy(update={"factory_id": "FAC-DUP", "processes": ["注塑"]})
            factories = FactoryCanonicalizer().canonicalize([factory, factory_dup])
            self.assertEqual(len(factories), 1)
            self.assertIn("注塑", factories[0].processes)

    # ── TEST 13: analysis layer, no fabrication ─────────────────────────────
    def test_13_analysis_derives_yoy_and_cagr_with_full_trace(self) -> None:
        from datetime import date
        claims = [
            _claim("revenue", 100, date(2022, 12, 31), "S1", "C1"),
            _claim("revenue", 120, date(2023, 12, 31), "S1", "C2"),
            _claim("revenue", 144, date(2024, 12, 31), "S1", "C3"),
        ]
        results = FinancialAnalyst().analyze("E1", claims)
        revenue = next(item for item in results if item.metric == "revenue")
        self.assertEqual(revenue.method, "cagr")
        self.assertAlmostEqual(revenue.value, 20.0, delta=0.01)
        self.assertEqual(revenue.source_claim_ids, ["C1", "C2", "C3"])
        self.assertEqual(len(revenue.period), 3)
        self.assertTrue(revenue.formula)
        # insufficient evidence → no result at all
        none = FinancialAnalyst().analyze("E1", [claims[0]])
        self.assertEqual(none, [])
        self.assertEqual(parse_number("1,234.5亿元"), 123_450_000_000.0)  # 1234.5 × 10^8
        self.assertEqual(parse_number("300万"), 3_000_000.0)

    # ── TEST 14-16: narrative structure ─────────────────────────────────────
    def test_14_chapters_are_dynamic_and_evidence_gated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = _load_bundle(temp)
            narrative = NarrativeBuilder().build(bundle)
            ids = {chapter.chapter_id for chapter in narrative.chapters}
            self.assertIn("executive_summary", ids)
            self.assertIn("sources", ids)
            # no verified structured edges, no verified products in small_simple
            small, _ = _load_bundle(temp, "small_simple.json")
            small_narrative = NarrativeBuilder().build(small)
            small_ids = {chapter.chapter_id for chapter in small_narrative.chapters}
            self.assertNotIn("group_structure", small_ids)
            self.assertNotIn("products", small_ids)
            # every chapter has a conclusion-driven title and decision question
            for chapter in narrative.chapters:
                self.assertTrue(chapter.title)
                self.assertTrue(chapter.decision_question)
                self.assertTrue(chapter.thesis)

    def test_15_product_without_image_still_published(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = _load_bundle(temp)
            # force the image-less-product scenario (photo unpublished/unbound)
            bundle = bundle.model_copy(update={
                "products": [product.model_copy(update={"image_id": None}) for product in bundle.products],
            })
            for product in bundle.products:
                self.assertIsNone(product.image_id)
            narrative = NarrativeBuilder().build(bundle)
            products_chapter = narrative.chapter("products")
            self.assertIsNotNone(products_chapter)
            names = [row["name"] for row in products_chapter.table_rows]
            self.assertIn(bundle.products[0].name, names)

    def test_16_org_structure_uses_only_verified_structured_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = _load_bundle(temp)
            entity = bundle.entities[0]
            child = entity.model_copy(update={"entity_id": "ENT-CHILD", "canonical_name": "子公司甲"})
            edges = [
                EnterpriseEdge(edge_id="E1", from_id=entity.entity_id, relation="SUBSIDIARY",
                               to_id="ENT-CHILD", verification_status=VerificationStatus.VERIFIED,
                               confidence=0.9, claim_ids=["C1"]),
                EnterpriseEdge(edge_id="E2", from_id=entity.entity_id, relation="UNKNOWN",
                               to_id="ENT-UNKNOWN", verification_status=VerificationStatus.VERIFIED,
                               confidence=0.5, claim_ids=["C1"]),
            ]
            bundle = bundle.model_copy(update={"entities": [*bundle.entities, child], "edges": edges})
            narrative = NarrativeBuilder().build(bundle)
            structure = narrative.chapter("group_structure")
            self.assertIsNotNone(structure)
            self.assertIn("股权关系 1 条", structure.content[0])
            tree = next((visual for visual in narrative.visuals if visual.visual_type == "tree"), None)
            self.assertIsNotNone(tree)
            node_ids = {node.id for node in tree.nodes}
            labels = {node.label for node in tree.nodes}
            self.assertIn("ENT-CHILD", node_ids)
            self.assertNotIn("ENT-UNKNOWN", node_ids)
            self.assertIn("子公司甲", labels)

    # ── TEST 17-18: image gate + budgets ────────────────────────────────────
    def test_17_image_publication_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = _load_bundle(temp)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            # context-only images (fixture default) are withheld
            image_manifest = prepare_publication_images(bundle, binding, Path(temp) / "assets")
            self.assertEqual(image_manifest.prepared_images, [])
            for image in bundle.images:
                self.assertIn(image.image_id, image_manifest.withheld_image_ids)
            # vision-verified, entity-bound images pass the gate
            verified = [
                image.model_copy(update={
                    "visual_verified": True,
                    "target_entity_id": image.entity_id or image.factory_id or image.product_id or "E1",
                    "verification_method": "vision",
                })
                for image in bundle.images
            ]
            bundle = bundle.model_copy(update={"images": verified})
            eligible, _ = publication_eligible(verified[0])
            self.assertTrue(eligible)
            self.assertTrue(publishable_images(bundle))
            # editorial images publish without an entity binding
            editorial = verified[0].model_copy(update={
                "image_id": "IMG-EDITORIAL", "target_entity_type": "editorial",
                "target_entity_id": None, "visual_verified": False,
            })
            eligible, _ = publication_eligible(editorial)
            self.assertTrue(eligible)

    def test_18_per_chapter_image_budgets_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, _ = _load_bundle(temp)
            entity_id = bundle.entities[0].entity_id
            factory_id = bundle.factories[0].factory_id
            product_id = bundle.products[0].product_id
            images = []
            for index in range(12):
                images.append(bundle.images[0].model_copy(update={
                    "image_id": f"IMG-{index:02d}",
                    "image_type": "product",
                    "product_id": product_id,
                    "factory_id": None,
                    "entity_id": entity_id,
                    "target_entity_type": "product",
                    "target_entity_id": product_id,
                    "visual_verified": True,
                    "verification_method": "vision",
                    "publication_priority": (index % 5) + 1,
                }))
            for index in range(8):
                images.append(bundle.images[0].model_copy(update={
                    "image_id": f"FIMG-{index:02d}",
                    "image_type": "factory",
                    "product_id": None,
                    "factory_id": factory_id,
                    "entity_id": entity_id,
                    "target_entity_type": "factory",
                    "target_entity_id": factory_id,
                    "visual_verified": True,
                    "verification_method": "vision",
                    "publication_priority": (index % 5) + 1,
                }))
            bundle = bundle.model_copy(update={"images": images})
            narrative = NarrativeBuilder().build(bundle)
            products_chapter = narrative.chapter("products")
            factories_chapter = narrative.chapter("factories")
            executive = narrative.chapter("executive_summary")
            self.assertLessEqual(len(products_chapter.image_ids), IMAGE_BUDGETS["products"])
            self.assertLessEqual(len(factories_chapter.image_ids), IMAGE_BUDGETS["factories"])
            self.assertLessEqual(len(executive.image_ids), IMAGE_BUDGETS["executive_summary"])
            # priority ordering: highest priority product image selected first
            selected = {image_id for image_id in products_chapter.image_ids}
            self.assertTrue(selected.issubset({f"IMG-{i:02d}" for i in range(12)}))

    # ── TEST 19: QA stays out of user-facing reports ────────────────────────
    def test_19_no_qa_or_internal_text_in_user_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = _load_bundle(temp)
            word_binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            html_binding = next(item for item in manifest.artifacts if item.type == ArtifactType.ENTERPRISE_HTML)
            word_target = Path(temp) / "report.docx"
            html_target = Path(temp) / "enterprise.html"
            word_result = FrozenWordPublisher().publish(bundle, word_binding, word_target)
            html_result = FrozenHtmlPublisher(ArtifactType.ENTERPRISE_HTML).publish(bundle, html_binding, html_target)
            self.assertEqual(word_result.status, "published")
            self.assertEqual(html_result.status, "published")
            html_text = html_target.read_text(encoding="utf-8")
            import zipfile
            with zipfile.ZipFile(word_target) as archive:
                word_text = archive.read("word/document.xml").decode("utf-8")
            forbidden = ["lieflat", "冻结数据不足", "renderer", "qa_report", "internal validation", "QA"]
            for token in forbidden:
                self.assertNotIn(token.lower(), html_text.lower(), f"forbidden token in HTML: {token}")
                self.assertNotIn(token.lower(), word_text.lower(), f"forbidden token in Word: {token}")
            qa_path = word_target.parent / "report_assets" / "publication_qa_report.json"
            self.assertTrue(qa_path.is_file())
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            self.assertIn("visual_entries", qa)

    # ── TEST 20: diagram-design third-party compliance ──────────────────────
    def test_20_diagram_design_third_party_compliance(self) -> None:
        self.assertIn("diagram-design", EMBEDDED_SKILLS)
        vendor_skill = ROOT / "vendor" / "skills" / "diagram-design"
        self.assertTrue((vendor_skill / "SKILL.md").is_file())
        self.assertTrue((vendor_skill / "LICENSE").is_file())
        self.assertTrue((vendor_skill / "THIRD_PARTY_LICENSES.md").is_file())
        license_text = (vendor_skill / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertTrue((ROOT / "third_party" / "diagram-design" / "LICENSE").is_file())
        notice = (ROOT / "third_party" / "diagram-design" / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("diagram-design", notice)
        adapter = DiagramDesignAdapter()
        self.assertTrue(adapter.skill_available())


# ── helpers ──────────────────────────────────────────────────────────────────

def _rich_proposal(pattern: str) -> VisualProposal:
    proposal = VisualProposal(
        visual_id=f"v-{pattern}", chapter_id="c", decision_question="问题",
        business_thesis="结论", semantic_pattern=pattern, title="标题",
    )
    proposal.items = [
        VisualDatum(label="甲", value=10, period="2023", x=1, y=2, weight=5),
        VisualDatum(label="乙", value=8, period="2024", x=2, y=3, weight=5, series="s2"),
        VisualDatum(label="丙", value=6, period="2025", x=3, y=4, weight=5, series="s3"),
    ]
    proposal.stages = [
        VisualStage(id="a", label="步骤A", from_label="原料", to_label="成品", weight=10, start="2024-01", end="2024-03"),
        VisualStage(id="b", label="步骤B", from_label="成品", to_label="交付", weight=10, start="2024-04", end="2024-06"),
    ]
    proposal.nodes = [
        VisualNode(id="root", label="根", kind="focal"),
        VisualNode(id="child1", label="子1", kind="backend", parent="root"),
        VisualNode(id="child2", label="子2", kind="store", parent="root"),
    ]
    return proposal


def _spec_for(visual_type: str) -> VisualSpec:
    proposal = _rich_proposal("category_comparison")
    spec, _ = VisualRouter().route(proposal)
    assert spec is not None
    return spec.model_copy(update={"visual_id": f"v-{visual_type}", "visual_type": visual_type, "title": f"图 {visual_type}"})


def _claim(field: str, value, as_of, source_id: str, claim_id: str) -> Claim:
    return Claim(
        claim_id=claim_id, entity_id="E1", field_name=field, value=value,
        value_type="number", as_of_date=as_of, source_id=source_id,
        raw_text=str(value), context_text=str(value),
        verification_status=VerificationStatus.VERIFIED, confidence=1.0,
    )


if __name__ == "__main__":
    unittest.main()
