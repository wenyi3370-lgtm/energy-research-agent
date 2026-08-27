"""Publication/metrics tests: unified freeze (§37), cross-domain chapter (§38),
agent metrics (§59) and the post-synthesis publish wiring.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from energy_research_agent.agent.evals import compute_agent_metrics
from energy_research_agent.agent.models import (
    AgentCostRecord,
    ApprovalStatus,
    CrossDomainFinding,
    GoalClass,
    GoalStatus,
    MissionApproval,
    MissionStatus,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
    SkillName,
    SkillRunResult,
    SkillRunStatus,
    SubjectType,
)
from energy_research_agent.agent.publication import merge_evidence, publish_unified
from energy_research_agent.artifacts.narrative import NarrativeBuilder, StoryModule
from energy_research_agent.cli import synthetic_run
from energy_research_agent.domain.enums import (
    ArtifactType,
    EnterpriseComplexity,
    RunStatus,
    SourceLevel,
    VerificationStatus,
)
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.domain.models import Entity, Source, Claim, RunManifest, utc_now


def _excel_only_publishers() -> dict:
    """Unit tests exercise the unified plumbing with the Excel publisher only;
    Word/HTML render-QA gates (body length etc.) stay active in production."""
    from energy_research_agent.artifacts.excel import ExcelMasterFrozenPublisher

    return {ArtifactType.EXCEL: ExcelMasterFrozenPublisher()}


def _finding(statement: str, finding_type: str = "MARKET_FIT") -> CrossDomainFinding:
    return CrossDomainFinding(
        finding_id=new_sortable_id("FINDING"),
        finding_type=finding_type,  # type: ignore[arg-type]
        statement=statement,
        enterprise_evidence_refs=["CLAIM-1"],
        market_evidence_refs=["CLAIM-2"],
        assumptions=["电价政策延续"],
        confidence=0.7,
        conditions=["补贴不退坡"],
    )


class TestCrossDomainChapter(unittest.TestCase):
    """§38 chapters 16-19: enterprise-market chapters render from findings."""

    def test_cross_domain_module_renders_findings(self):
        module = NarrativeBuilder()._cross_domain_module(
            None,  # type: ignore[arg-type]  (only findings are consumed)
            [
                _finding("企业A进入德国户储市场适配度中等偏高", "MARKET_FIT"),
                _finding("电价下行构成主要风险", "RISK"),
                _finding("建议通过渠道试点进入", "ENTRY_STRATEGY"),
            ],
        )
        self.assertIsInstance(module, StoryModule)
        self.assertEqual(module.kind, "cross_domain")
        self.assertIn("cross_domain", str(StoryModule.model_fields["kind"].annotation))
        self.assertIn("德国户储市场适配度", module.executive_takeaway)
        self.assertTrue(any("电价下行" in p for p in module.counter_evidence))
        self.assertTrue(any("渠道试点" in p for p in module.recommendations))
        self.assertIn("CLAIM-1", module.claim_ids)
        self.assertIn("CLAIM-2", module.source_ids)


class TestUnifiedPublication(unittest.TestCase):
    """§37: one artifact owner; market evidence merges into one freeze."""

    def _market_store(self, path: Path, mission_id: str) -> tuple[EvidenceStore, str]:
        store = EvidenceStore(path)
        run_id = f"agent-{mission_id}"
        store.create_run(RunManifest(
            run_id=run_id,
            request_id=mission_id,
            config_hash="test",
            code_version="test",
            model_gateway={"agent": True},
        ))
        store.add(run_id, 1, "entity", Entity(
            entity_id="market:spain", canonical_name="西班牙户储市场", entity_type="other",
        ))
        store.add(run_id, 1, "source", Source(
            source_id="MKT-SRC", canonical_url="https://ledger.local/MKT-SRC",
            source_domain="ledger.local", source_level=SourceLevel.SOURCE_B,
            grading_reason="test",
        ))
        store.add(run_id, 1, "claim", Claim(
            claim_id="CLAIM-2",
            entity_id="market:spain",
            field_name="tariff",
            value="0.12",
            value_type="market",
            source_id="MKT-SRC",
            raw_text="market tariff",
            context_text="market evidence",
            retrieved_at=utc_now(),
            confidence=0.8,
            mission_id=mission_id,
            goal_id="GOAL-MKT",
            subject_id="market:spain",
            subject_role="MARKET_CONTEXT",  # type: ignore[arg-type]
            originating_skill="OVERSEAS_MARKET_RESEARCH",
            claim_type="market_evidence",
            value_class="OBSERVED",  # type: ignore[arg-type]
            geography="Spain",
        ))
        return store, run_id

    def _enterprise_run(self, root: Path, label: str) -> tuple[Path, str]:
        """synthetic_run into a dir, then rename it to match the run id
        (production layout: workdir/<run_id>/evidence.sqlite3)."""
        run_dir = root / label
        run_dir.mkdir(parents=True)
        result = synthetic_run("示例制造有限公司", run_dir)
        self.assertEqual(result["status"], "PASS")
        enterprise_store = EvidenceStore(run_dir / "evidence.sqlite3")
        run_id = enterprise_store.connect().execute("SELECT run_id FROM runs").fetchone()[0]
        final_dir = root / run_id
        if run_dir != final_dir:
            run_dir.rename(final_dir)
        return final_dir, run_id

    def test_unified_publish_merges_and_publishes(self):
        with tempfile.TemporaryDirectory(prefix="agent-pub-") as temp:
            root = Path(temp)
            run_dir, enterprise_run_id = self._enterprise_run(root, "RUN-UNIFIED")

            mission_id = new_sortable_id("MISSION")
            market_store, market_run_id = self._market_store(root / "market_evidence.sqlite3", mission_id)

            published = publish_unified(
                workdir=root,
                enterprise_run_id=enterprise_run_id,
                findings=[_finding("示例公司进入西班牙户储市场适配度中等")],
                sub_artifact_refs=["/deliverables/市场调研数据与模型.xlsx"],
                market_evidence_store=market_store,
                market_run_id=market_run_id,
                publishers=_excel_only_publishers(),
            )
            self.assertEqual(published["status"], "OK", published.get("diagnostics"))
            self.assertTrue(published["freeze_id"])
            self.assertEqual(published["findings_count"], 1)
            self.assertGreaterEqual(published["merged"].get("claim", 0), 1, "market claim must merge")
            self.assertTrue(published["artifacts"], "unified artifacts must exist")

            # The manifest references the overseas sub-artifact (§37) and the
            # bundle carries the cross-domain findings for publishers (§38).
            unified = EvidenceStore(run_dir / "unified_evidence.sqlite3")
            row = unified.connect().execute(
                "SELECT payload FROM artifact_manifests WHERE run_id = ?",
                (f"{enterprise_run_id}-unified",),
            ).fetchone()
            self.assertIsNotNone(row)
            import json as _json

            manifest_payload = _json.loads(row[0])
            self.assertIn("/deliverables/市场调研数据与模型.xlsx", manifest_payload.get("sub_artifact_refs", []))
            # §38: findings injected into the frozen bundle flow into the
            # narrative's enterprise-market chapter (what publishers render).
            bundle = __import__("energy_research_agent.evidence.freeze", fromlist=["FreezeService"]).FreezeService(unified).load_bundle(published["freeze_id"])
            bundle.cross_domain_findings = [_finding("示例公司进入西班牙户储市场适配度中等")]
            narrative = NarrativeBuilder().build(bundle)
            self.assertTrue(
                any(chapter.kind == "cross_domain" for chapter in narrative.chapters),
                "cross-domain chapter must render from bundle findings",
            )

    def test_unified_publish_merges_recovery_runs(self):
        """Recovery rounds produce their own run stores; the unified freeze
        must include them (§37), never drop recovery-collected evidence."""
        with tempfile.TemporaryDirectory(prefix="agent-pub-") as temp:
            root = Path(temp)
            run_dir, enterprise_run_id = self._enterprise_run(root, "RUN-REC")
            # A recovery run with one extra claim
            rec_run_id = "REC-ROUND-1"
            rec_dir = root / rec_run_id
            rec_dir.mkdir()
            store = EvidenceStore(rec_dir / "evidence.sqlite3")
            store.create_run(RunManifest(run_id=rec_run_id, request_id="r", config_hash="t", code_version="t", model_gateway={}))
            store.add(rec_run_id, 1, "entity", Entity(entity_id="E2", canonical_name="示例公司2"))
            store.add(rec_run_id, 1, "source", Source(
                source_id="S2", canonical_url="https://example.com/r",
                source_domain="example.com", source_level=SourceLevel.SOURCE_B, grading_reason="t",
            ))
            store.add(rec_run_id, 1, "claim", Claim(
                claim_id="CLAIM-REC", entity_id="E2", field_name="capacity",
                value="20GWh", value_type="string", source_id="S2",
                raw_text="r", context_text="r", retrieved_at=utc_now(),
                confidence=0.7, verification_status=VerificationStatus.VERIFIED,
                goal_family="capacity",
            ))
            published = publish_unified(
                workdir=root,
                enterprise_run_id=enterprise_run_id,
                findings=[],
                sub_artifact_refs=[],
                recovery_run_ids=[rec_run_id],
                publishers=_excel_only_publishers(),
            )
            self.assertEqual(published["status"], "OK", published.get("diagnostics"))
            unified = EvidenceStore(run_dir / "unified_evidence.sqlite3")
            claims = unified.list(f"{enterprise_run_id}-unified", "claim")
            self.assertTrue(
                any(c.claim_id == "CLAIM-REC" for c in claims),
                "recovery-run claims must reach the unified freeze",
            )

    def test_unified_publish_materializes_recovery_image_assets(self):
        """merge_evidence only copies image RECORDS into the unified store; the
        archived byte files stay under each recovery run's outputs dir.  The
        unified publish must materialize those bytes so local_asset_ref resolves
        (otherwise every verified image is dropped -> 0 product images -> the
        image gate blocks the run)."""
        with tempfile.TemporaryDirectory(prefix="agent-pub-") as temp:
            root = Path(temp)
            run_dir, enterprise_run_id = self._enterprise_run(root, "RUN-IMG")
            rec_run_id = "REC-IMG-1"
            rec_assets = root / rec_run_id / "outputs" / "01_evidence" / "assets" / "images"
            rec_assets.mkdir(parents=True)
            (rec_assets / "IMAGE-I022-5c20b4a068d5.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpg")
            store = EvidenceStore(root / rec_run_id / "evidence.sqlite3")
            store.create_run(RunManifest(run_id=rec_run_id, request_id="r", config_hash="t", code_version="t", model_gateway={}))

            published = publish_unified(
                workdir=root,
                enterprise_run_id=enterprise_run_id,
                findings=[],
                sub_artifact_refs=[],
                recovery_run_ids=[rec_run_id],
                publishers=_excel_only_publishers(),
            )
            self.assertEqual(published["status"], "OK", published.get("diagnostics"))
            materialized = run_dir / "outputs" / "01_evidence" / "assets" / "images" / "IMAGE-I022-5c20b4a068d5.jpg"
            self.assertTrue(materialized.is_file(), "recovery-run image bytes must be copied into the unified run")
            self.assertEqual(materialized.read_bytes(), b"\xff\xd8\xff\xe0fakejpg")


    def test_unified_publish_enterprise_only_keeps_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="agent-pub-") as temp:
            root = Path(temp)
            _run_dir, enterprise_run_id = self._enterprise_run(root, "RUN-ENT")
            published = publish_unified(
                workdir=root,
                enterprise_run_id=enterprise_run_id,
                findings=[],
                sub_artifact_refs=[],
                publishers=_excel_only_publishers(),
            )
            self.assertEqual(published["status"], "OK", published.get("diagnostics"))
            self.assertEqual(published["findings_count"], 0)
            self.assertTrue(published["artifacts"])


class TestMergeEvidence(unittest.TestCase):
    """Cross-run merge: per-run sequence ids collide; the merge must namespace
    colliding ids and rewrite references instead of re-binding claims to a
    foreign same-id source (the WEAK_SOURCE_MARKED_VERIFIED root cause)."""

    def _store(self, path: Path, run_id: str) -> EvidenceStore:
        store = EvidenceStore(path)
        store.create_run(RunManifest(
            run_id=run_id, request_id="r", config_hash="t", code_version="t", model_gateway={},
        ))
        return store

    def _source(self, source_id: str, url: str, level: SourceLevel = SourceLevel.SOURCE_A) -> Source:
        return Source(
            source_id=source_id, canonical_url=url, source_domain=url.split("/")[2],
            source_level=level, grading_reason="t",
        )

    def _claim(self, claim_id: str, entity_id: str, source_id: str, raw: str) -> Claim:
        return Claim(
            claim_id=claim_id, entity_id=entity_id, field_name="capacity",
            value=raw, value_type="string", source_id=source_id,
            raw_text=raw, context_text=raw, retrieved_at=utc_now(), confidence=0.5,
        )

    def test_colliding_ids_are_namespaced_and_references_rebound(self):
        with tempfile.TemporaryDirectory(prefix="merge-collide-") as temp:
            root = Path(temp)
            unified = self._store(root / "unified.sqlite3", "U")
            first = self._store(root / "first.sqlite3", "R1")
            first.add("R1", 1, "entity", Entity(entity_id="ENT-1", canonical_name="示例公司"))
            first.add("R1", 1, "source", self._source("SOURCE-S001", "https://a.example/x"))
            first.add("R1", 1, "claim", self._claim("CLAIM-000001", "ENT-1", "SOURCE-S001", "first-pass"))
            # Same per-run ids, different real-world objects (recovery round).
            second = self._store(root / "second.sqlite3", "R2")
            second.add("R2", 1, "entity", Entity(entity_id="ENT-2", canonical_name="示例 公司"))
            second.add("R2", 1, "source", self._source("SOURCE-S001", "https://b.example/y", SourceLevel.SOURCE_D))
            second.add("R2", 1, "claim", self._claim("CLAIM-000001", "ENT-2", "SOURCE-S001", "recovery-pass"))

            merge_evidence(unified, "U", 1, (first, "R1"), (second, "R2"))

            sources = unified.list("U", "source")
            self.assertEqual(len(sources), 2, "different URLs must both survive")
            entities = unified.list("U", "entity")
            self.assertEqual(len(entities), 1, "same-name entity must deduplicate")
            claims = unified.list("U", "claim")
            self.assertEqual(len(claims), 2)
            by_raw = {claim.raw_text: claim for claim in claims}
            for raw, expected_url in (("first-pass", "https://a.example/x"), ("recovery-pass", "https://b.example/y")):
                claim = by_raw[raw]
                self.assertEqual(claim.entity_id, entities[0].entity_id)
                bound = [s for s in sources if s.source_id == claim.source_id]
                self.assertEqual(len(bound), 1)
                self.assertEqual(str(bound[0].canonical_url), expected_url, f"{raw} must stay bound to its own source")
            self.assertNotEqual(by_raw["first-pass"].claim_id, by_raw["recovery-pass"].claim_id)

    def test_same_url_sources_dedup_across_runs(self):
        with tempfile.TemporaryDirectory(prefix="merge-url-") as temp:
            root = Path(temp)
            unified = self._store(root / "unified.sqlite3", "U")
            first = self._store(root / "first.sqlite3", "R1")
            first.add("R1", 1, "entity", Entity(entity_id="ENT-1", canonical_name="示例公司"))
            first.add("R1", 1, "source", self._source("SOURCE-S001", "https://a.example/x"))
            first.add("R1", 1, "claim", self._claim("CLAIM-1", "ENT-1", "SOURCE-S001", "first-pass"))
            second = self._store(root / "second.sqlite3", "R2")
            second.add("R2", 1, "entity", Entity(entity_id="ENT-9", canonical_name="另一公司"))
            second.add("R2", 1, "source", self._source("MKT-SRC", "https://a.example/x"))
            second.add("R2", 1, "claim", self._claim("CLAIM-2", "ENT-9", "MKT-SRC", "market-pass"))

            counts = merge_evidence(unified, "U", 1, (first, "R1"), (second, "R2"))

            sources = unified.list("U", "source")
            self.assertEqual(len(sources), 1, "same-URL source must collapse onto one record")
            self.assertEqual(counts.get("source"), 1)
            claims = {claim.raw_text: claim for claim in unified.list("U", "claim")}
            self.assertEqual(claims["market-pass"].source_id, sources[0].source_id)
            self.assertEqual(claims["market-pass"].source_id, claims["first-pass"].source_id)

    def test_same_url_stronger_grade_never_downgrades(self):
        """One run can declare the same URL twice with different source_kind
        (graded weak and strong); URL dedup must never re-bind VERIFIED claims
        onto the weaker grading."""
        with tempfile.TemporaryDirectory(prefix="merge-rank-") as temp:
            root = Path(temp)
            unified = self._store(root / "unified.sqlite3", "U")
            first = self._store(root / "first.sqlite3", "R1")
            first.add("R1", 1, "entity", Entity(entity_id="ENT-1", canonical_name="示例公司"))
            first.add("R1", 1, "source", self._source("SRC-1", "https://a.example/x", SourceLevel.SOURCE_B))
            first.add("R1", 1, "claim", self._claim("CLAIM-1", "ENT-1", "SRC-1", "first-pass"))
            # Same URL twice in one run: weak grading first, strong second.
            second = self._store(root / "second.sqlite3", "R2")
            second.add("R2", 1, "entity", Entity(entity_id="ENT-2", canonical_name="另一公司"))
            second.add("R2", 1, "source", self._source("SOURCE-S001", "https://b.example/y", SourceLevel.SOURCE_D))
            second.add("R2", 1, "source", self._source("SOURCE-S002", "https://b.example/y", SourceLevel.SOURCE_A))
            second.add("R2", 1, "claim", self._claim("CLAIM-2", "ENT-2", "SOURCE-S001", "weak-pass"))
            second.add("R2", 1, "claim", self._claim("CLAIM-3", "ENT-2", "SOURCE-S002", "strong-pass"))
            # A third run re-discovers the same URL; it must dedup onto the
            # stronger grading, not the weak one registered first.
            third = self._store(root / "third.sqlite3", "R3")
            third.add("R3", 1, "entity", Entity(entity_id="ENT-3", canonical_name="第三公司"))
            third.add("R3", 1, "source", self._source("SRC-9", "https://b.example/y"))
            third.add("R3", 1, "claim", self._claim("CLAIM-4", "ENT-3", "SRC-9", "third-pass"))

            merge_evidence(unified, "U", 1, (first, "R1"), (second, "R2"), (third, "R3"))

            sources = unified.list("U", "source")
            by_url = {}
            for s in sources:
                by_url.setdefault(str(s.canonical_url), []).append(s)
            self.assertEqual(len(by_url["https://a.example/x"]), 1)
            # The twice-declared URL keeps both gradings as separate records.
            self.assertEqual(len(by_url["https://b.example/y"]), 2)
            levels = {s.source_level for s in by_url["https://b.example/y"]}
            self.assertEqual(levels, {SourceLevel.SOURCE_A, SourceLevel.SOURCE_D})
            claims = {claim.raw_text: claim for claim in unified.list("U", "claim")}
            level_of = {s.source_id: s.source_level for s in sources}
            self.assertEqual(level_of[claims["weak-pass"].source_id], SourceLevel.SOURCE_D)
            self.assertEqual(level_of[claims["strong-pass"].source_id], SourceLevel.SOURCE_A)
            # Later same-URL records dedup onto the stronger grading.
            self.assertEqual(level_of[claims["third-pass"].source_id], SourceLevel.SOURCE_A)

    def test_identical_copied_records_deduplicate(self):
        with tempfile.TemporaryDirectory(prefix="merge-copy-") as temp:
            root = Path(temp)
            unified = self._store(root / "unified.sqlite3", "U")
            first = self._store(root / "first.sqlite3", "R1")
            claim = self._claim("CLAIM-7", "ENT-1", "SOURCE-S001", "copied")
            first.add("R1", 1, "entity", Entity(entity_id="ENT-1", canonical_name="示例公司"))
            first.add("R1", 1, "source", self._source("SOURCE-S001", "https://a.example/x"))
            first.add("R1", 1, "claim", claim)
            # A later run re-registers the same rows verbatim (copied store).
            second = self._store(root / "second.sqlite3", "R2")
            second.add("R2", 1, "entity", Entity(entity_id="ENT-1", canonical_name="示例公司"))
            second.add("R2", 1, "source", self._source("SOURCE-S001", "https://a.example/x"))
            second.add("R2", 1, "claim", claim)

            merge_evidence(unified, "U", 1, (first, "R1"), (second, "R2"))

            self.assertEqual(len(unified.list("U", "claim")), 1)
            self.assertEqual(len(unified.list("U", "source")), 1)
            self.assertEqual(len(unified.list("U", "entity")), 1)


class TestAgentMetrics(unittest.TestCase):
    """§59: metrics computed at completion."""

    def test_metrics_computed_from_outcome(self):
        from energy_research_agent.agent.orchestrator import AgentOutcome

        mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request="x", mode=ResearchMode.HYBRID)
        goals = [
            ResearchGoal(
                goal_id=new_sortable_id("GOAL"), goal_name="公司概况", goal_description="d",
                subject_id="e", subject_name="企业", subject_type=SubjectType.ENTERPRISE,
                goal_class=GoalClass.CORE_ENTERPRISE, status=GoalStatus.SATISFIED,
            ),
            ResearchGoal(
                goal_id=new_sortable_id("GOAL"), goal_name="产能与产线", goal_description="d",
                subject_id="e", subject_name="企业", subject_type=SubjectType.ENTERPRISE,
                goal_class=GoalClass.CORE_ENTERPRISE, status=GoalStatus.PARTIAL, recovery_rounds=2,
            ),
            ResearchGoal(
                goal_id=new_sortable_id("GOAL"), goal_name="矿山储能专项", goal_description="d",
                subject_id="e", subject_name="企业", subject_type=SubjectType.CUSTOM,
                goal_class=GoalClass.CUSTOM, status=GoalStatus.SATISFIED, recovery_rounds=1,
            ),
        ]
        outcome = AgentOutcome(
            mission=mission,
            goals=goals,
            skill_results=[
                SkillRunResult(
                    skill_run_id=new_sortable_id("RUN"), skill_name=SkillName.ENTERPRISE_RESEARCH,
                    goal_ids=[], status=SkillRunStatus.OK,
                    coverage_metrics={"evidence_count": 10, "verified_claim_count": 6},
                )
            ],
            cost_records=[AgentCostRecord(stage="agent", input_tokens=100, output_tokens=50)],
            synthesis_findings=[_finding("fit")],
            status=MissionStatus.PARTIAL,
        )
        metrics = compute_agent_metrics(outcome)
        self.assertEqual(metrics["goal_completion_rate"], round(2 / 3, 4))
        self.assertEqual(metrics["core_goal_coverage"], round(0.5, 4))
        self.assertEqual(metrics["dynamic_goal_completion_rate"], 1.0)
        self.assertEqual(metrics["recovery_success_rate"], 0.5)
        self.assertEqual(metrics["valid_evidence_yield"], 0.6)
        self.assertEqual(metrics["agent_token_usage"], 150)
        self.assertEqual(metrics["mode"], "HYBRID")


if __name__ == "__main__":
    unittest.main()
