"""Focused fifth-round fail-closed publication regressions."""

from __future__ import annotations

import unittest
from pathlib import Path

from enterprise_energy_research.artifacts.publication_boilerplate import (
    HTML_ZERO_PHRASES,
    PublicationBoilerplateFilter,
)
from enterprise_energy_research.artifacts.qa_report import QAFinding, new_qa_report
from enterprise_energy_research.artifacts.visual_router import VisualDatum, VisualProposal, VisualRouter
from enterprise_energy_research.artifacts.word import FrozenWordPublisher
from enterprise_energy_research.domain.models import Entity
from enterprise_energy_research.research.deep_retry import exact_product_key
from enterprise_energy_research.research.production_runner import AdaptiveResearchRunner


class FifthRoundP0Tests(unittest.TestCase):
    def test_publication_filter_removes_every_html_zero_phrase_recursively(self):
        payload = {"a": list(HTML_ZERO_PHRASES), "b": {"c": "；".join(HTML_ZERO_PHRASES)}}
        filtered = PublicationBoilerplateFilter().filter_value(payload)
        self.assertTrue(all(value == 0 for value in PublicationBoilerplateFilter.zero_phrase_counts(filtered).values()))

    def test_error_finding_changes_qa_status_to_fail(self):
        report = new_qa_report("RUN-1", "FREEZE-1", "ART-1")
        report.record_finding(QAFinding(code="gate", severity="error", message="blocked"))
        self.assertEqual(report.status, "fail")

    def test_map_and_dual_axis_routes_require_real_shapes(self):
        router = VisualRouter()
        map_proposal = VisualProposal(
            visual_id="map", chapter_id="factories", decision_question="where",
            business_thesis="distribution", semantic_pattern="spatial_distribution",
            semantic_domain="manufacturing", title="map",
            items=[VisualDatum(label="宁德", x=119.3, y=26.08, value=1)],
        )
        map_spec, _ = router.route(map_proposal)
        self.assertEqual(map_spec.visual_type, "map")

        dual = VisualProposal(
            visual_id="dual", chapter_id="operations", decision_question="change",
            business_thesis="two series", semantic_pattern="dual_metric_time_series",
            semantic_domain="financial", title="dual",
            items=[
                VisualDatum(label="2023", period="2023", series="收入", value=100),
                VisualDatum(label="2024", period="2024", series="收入", value=120),
                VisualDatum(label="2023", period="2023", series="利润", value=10),
                VisualDatum(label="2024", period="2024", series="利润", value=15),
            ],
        )
        dual_spec, _ = router.route(dual)
        self.assertEqual(dual_spec.visual_type, "dual_axis")

    def test_word_compacts_prose_heavy_six_column_tables(self):
        due_rows = [{
            "当前尚不能判断的关键事项": "典型日/全年负荷曲线",
            "为什么重要": "决定测算边界",
            "影响判断": "项目经济性",
            "建议获取资料": "小时级负荷曲线",
            "获取时点": "预可研阶段",
            "是否阻断决策": "是",
        }] * 20
        compact_due = FrozenWordPublisher._compact_table_rows(due_rows)
        self.assertEqual(list(compact_due[0]), ["关键事项", "重要性与影响", "建议获取资料", "时点与门槛"])
        self.assertEqual(len(compact_due), 1, "duplicate due-diligence rows must not bloat the body table")

        product_rows = [{
            "名称": "神行电池", "品牌": "CATL", "型号": "Pro",
            "产品族": "动力电池", "系列": "神行", "核心参数": "公开参数",
        }]
        compact_product = FrozenWordPublisher._compact_table_rows(product_rows)
        self.assertEqual(list(compact_product[0]), ["产品 / 型号", "产品族 / 系列", "核心参数"])
        self.assertIn("神行电池", compact_product[0]["产品 / 型号"])

    def test_word_compact_table_presets_fill_portrait_width(self):
        for columns in (
            ["关键事项", "重要性与影响", "建议获取资料", "时点与门槛"],
            ["产品 / 型号", "产品族 / 系列", "核心参数"],
            ["合作方向 / 优先级", "切入场景", "公开依据与决策门槛"],
        ):
            self.assertEqual(sum(FrozenWordPublisher._table_widths(columns)), 9360)

    def test_image_owner_is_canonical_not_first_co_mentioned_entity(self):
        supplier = Entity(entity_id="ENT-SUPPLIER", canonical_name="供应商公司")
        canonical = Entity(entity_id="ENT-CANONICAL", canonical_name="目标公司")
        selected = AdaptiveResearchRunner._select_image_owner(
            [supplier, canonical], "ENT-CANONICAL",
        )
        self.assertEqual(selected.entity_id, "ENT-CANONICAL")
        self.assertIsNone(
            AdaptiveResearchRunner._select_image_owner([supplier, canonical], None),
            "multiple entities must never fall back to list position",
        )

    def test_shared_catalog_page_has_no_random_product_binding(self):
        self.assertEqual(exact_product_key({"PROD-1"}), "PROD-1")
        self.assertIsNone(exact_product_key({"PROD-1", "PROD-2"}))
        self.assertIsNone(exact_product_key(set()))

    def test_portable_runtime_has_no_developer_machine_absolute_paths(self):
        root = Path(__file__).resolve().parents[1]
        targets = [*sorted((root / "src").rglob("*.py"))]
        targets.extend([
            root / "scripts" / "run_live_acceptance.py",
            root / "scripts" / "run_product_image_recovery.py",
            root / "scripts" / "run_publication_qa.py",
        ])
        banned = ("C:\\Users\\", "/Users/", "/home/")
        violations = []
        for path in targets:
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in banned):
                violations.append(str(path.relative_to(root)))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
