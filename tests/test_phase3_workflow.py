from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enterprise_energy_research.domain.enums import (
    EnterpriseComplexity,
    ProductDashboardDecision,
    RunStatus,
    VerificationStatus,
)
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch, RunManifest
from enterprise_energy_research.evidence.store import EvidenceStore
from enterprise_energy_research.graph.phase3_runner import Phase3Runner
from enterprise_energy_research.graph.state import ResearchState
from enterprise_energy_research.settings import Settings, load_yaml


ROOT = Path(__file__).resolve().parents[1]


class Phase3WorkflowTests(unittest.TestCase):
    def _load(self, fixture: str) -> tuple[str, list[ExtractedEvidenceBatch]]:
        payload = json.loads((ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8"))
        return payload[0]["entities"][0]["canonical_name"], [
            ExtractedEvidenceBatch.model_validate(item) for item in payload
        ]

    def _run(self, fixture: str, temp: str):
        company, batches = self._load(fixture)
        request_id = new_sortable_id("REQ")
        run_id = new_sortable_id("RUN")
        settings = Settings(output_root=Path(temp) / "outputs")
        store = EvidenceStore(Path(temp) / "evidence.sqlite3")
        store.create_run(RunManifest(
            run_id=run_id,
            request_id=request_id,
            status=RunStatus.RUNNING,
            config_hash=settings.config_hash(),
            code_version="0.3.0",
            model_gateway={"mode": "recorded-fixture"},
        ))
        state = ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING)
        result = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
            state,
            company,
            batches,
            output_dir=Path(temp) / "outputs" / run_id,
        )
        return store, result

    def test_normal_manufacturer_generates_product_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store, (state, manifest, detection) = self._run("normal_manufacturer.json", temp)
            self.assertEqual(state.status, RunStatus.PASS)
            self.assertEqual(state.complexity, EnterpriseComplexity.ENTERPRISE_NORMAL)
            self.assertEqual(detection.dashboard_decision, ProductDashboardDecision.GENERATE)
            self.assertEqual(len(store.list(state.run_id, "energy_profile")), 1)
            self.assertEqual(len(store.list(state.run_id, "solution")), 4)
            self.assertTrue(all(item.verification_status == VerificationStatus.VERIFIED for item in store.list(state.run_id, "image")))
            product_artifact = next(item for item in manifest.artifacts if item.type.value == "product_html")
            self.assertEqual(product_artifact.status.value, "PLANNED")

    def test_company_alias_resolves_to_canonical_entity(self) -> None:
        _, batches = self._load("normal_manufacturer.json")
        entity = batches[0].entities[0]
        batches[0] = batches[0].model_copy(update={
            "entities": [entity.model_copy(update={"aliases": ["示例能源"]})],
        })
        with tempfile.TemporaryDirectory() as temp:
            request_id, run_id = new_sortable_id("REQ"), new_sortable_id("RUN")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.6.1", model_gateway={"mode": "fixture"},
            ))
            state, manifest, _ = Phase3Runner(
                store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")
            ).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                "示例能源", batches, output_dir=Path(temp) / "outputs",
            )
            self.assertEqual(state.status, RunStatus.PASS)
            self.assertIsNotNone(manifest)

    def test_large_group_uses_large_workflow_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, (state, manifest, detection) = self._run("large_group.json", temp)
            self.assertEqual(state.status, RunStatus.PASS)
            self.assertEqual(state.complexity, EnterpriseComplexity.GROUP_LARGE)
            self.assertEqual(detection.dashboard_decision, ProductDashboardDecision.SKIP_PRODUCT_DASHBOARD)
            self.assertIsNotNone(manifest)

    def test_small_service_company_uses_simple_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, (state, _, detection) = self._run("small_simple.json", temp)
            self.assertEqual(state.status, RunStatus.PASS)
            self.assertEqual(state.complexity, EnterpriseComplexity.SMALL_SIMPLE)
            self.assertEqual(detection.dashboard_decision, ProductDashboardDecision.SKIP_PRODUCT_DASHBOARD)

    def test_ambiguous_identity_routes_to_human_review_without_ingest(self) -> None:
        _, batches = self._load("normal_manufacturer.json")
        first = batches[0]
        rival = first.model_copy(update={
            "source_url": "https://rival.example.com/about",
            "entities": [first.entities[0].model_copy(update={
                "entity_key": "rival",
                "official_website": "https://rival.example.com",
            })],
            "claims": [],
            "factories": [],
            "products": [],
            "images": [],
        })
        with tempfile.TemporaryDirectory() as temp:
            request_id, run_id = new_sortable_id("REQ"), new_sortable_id("RUN")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.3.0", model_gateway={"mode": "fixture"},
            ))
            state, manifest, detection = Phase3Runner(
                store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")
            ).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                first.entities[0].canonical_name,
                [first, rival],
                output_dir=Path(temp) / "outputs",
            )
            self.assertEqual(state.status, RunStatus.HUMAN_REVIEW)
            self.assertIsNone(manifest)
            self.assertIsNone(detection)
            self.assertEqual(store.list(run_id, "entity"), [])

    def test_core_field_conflict_blocks_freeze(self) -> None:
        company, batches = self._load("normal_manufacturer.json")
        first = batches[0]
        revenue_claim = first.claims[0].model_copy(update={
            "field_name": "revenue",
            "value": 100,
            "value_type": "number",
            "unit": "CNY million",
            "as_of_date": "2025-12-31",
            "scope": "consolidated",
            "raw_text": "2025年营业收入100百万元",
            "context_text": "公司2025年合并营业收入100百万元。",
        })
        second_claim = revenue_claim.model_copy(update={
            "value": 120,
            "raw_text": "2025年营业收入120百万元",
            "context_text": "监管披露显示2025年合并营业收入120百万元。",
        })
        batches[0] = first.model_copy(update={"claims": [*first.claims, revenue_claim]})
        batches.append(first.model_copy(update={
            "source_url": "https://filing.example.gov.cn/acme-2025",
            "source_title": "监管披露",
            "publisher": "示例监管机构",
            "source_kind": "government",
            "claims": [second_claim],
            "factories": [],
            "products": [],
            "images": [],
        }))
        with tempfile.TemporaryDirectory() as temp:
            request_id, run_id = new_sortable_id("REQ"), new_sortable_id("RUN")
            store = EvidenceStore(Path(temp) / "evidence.sqlite3")
            store.create_run(RunManifest(
                run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
                config_hash="fixture", code_version="0.3.0", model_gateway={"mode": "fixture"},
            ))
            state, manifest, _ = Phase3Runner(
                store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")
            ).process_batches(
                ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING),
                company,
                batches,
                output_dir=Path(temp) / "outputs",
            )
            self.assertEqual(state.status, RunStatus.BLOCKED)
            self.assertIsNone(manifest)
            self.assertIn("UNRESOLVED_CORE_CONFLICT", state.blocking_findings)
            self.assertEqual(store.list(run_id, "conflict")[0].status.value, "BLOCKING")


if __name__ == "__main__":
    unittest.main()
