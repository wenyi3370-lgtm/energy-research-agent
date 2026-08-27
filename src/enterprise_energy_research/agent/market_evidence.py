"""Unified evidence layer: overseas market evidence -> main EvidenceStore (§18).

The main repository's EvidenceStore stays the single source of truth. Overseas
ledger rows are mapped to canonical Source + Claim records carrying the five
boundaries (subject_id / goal_id / skill / scope / period) so competitor and
market facts can never pollute the target enterprise's fields (§14/§20/§43).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, HttpUrl

from enterprise_energy_research.domain.enums import SourceLevel, VerificationStatus
from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.domain.models import Claim, Entity, RunManifest, Source, utc_now
from enterprise_energy_research.evidence.store import EvidenceStore

from .models import ResearchGoal, ResearchMission
from .policies import AgentPolicies

TIER_TO_LEVEL = {
    "A": SourceLevel.SOURCE_A, "1": SourceLevel.SOURCE_A, "T1": SourceLevel.SOURCE_A,
    "B": SourceLevel.SOURCE_B, "2": SourceLevel.SOURCE_B, "T2": SourceLevel.SOURCE_B,
    "C": SourceLevel.SOURCE_C, "3": SourceLevel.SOURCE_C, "T3": SourceLevel.SOURCE_C,
}
TIER_TO_CONFIDENCE = {
    "A": 0.9, "1": 0.9, "T1": 0.9,
    "B": 0.75, "2": 0.75, "T2": 0.75,
    "C": 0.55, "3": 0.55, "T3": 0.55,
}
VALID_ROLES = {"SUBJECT", "COMPETITOR", "ECOSYSTEM", "MARKET_CONTEXT", "OTHER"}


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    run_id: str
    rows_seen: int = 0
    sources_created: int = 0
    claims_created: int = 0
    subjects_created: int = 0
    skipped_duplicates: int = 0
    skipped_unsupported: int = 0
    errors: list[str] = []


class MarketEvidenceImporter:
    """Maps overseas structured rows into canonical store records."""

    def __init__(self, store: EvidenceStore, policies: AgentPolicies | None = None) -> None:
        self.store = store
        self.policies = policies or AgentPolicies.load()

    def import_rows(
        self,
        *,
        mission: ResearchMission,
        rows: list[dict[str, Any]],
        goals: list[ResearchGoal],
        originating_skill: str,
    ) -> ImportReport:
        run_id = f"agent-{mission.mission_id}"
        version = mission.evidence_version
        self._ensure_run(mission, run_id)
        report = ImportReport(mission_id=mission.mission_id, run_id=run_id)
        seen: set[tuple[str, ...]] = set()
        known_sources: set[str] = set()
        known_subjects: set[str] = set()
        for goal in goals:
            if self._ensure_subject_entity(mission, goal, run_id, version):
                report.subjects_created += 1
                known_subjects.add(goal.subject_id)
            else:
                known_subjects.add(goal.subject_id)

        for row in rows:
            report.rows_seen += 1
            if not str(row.get("raw_value") or "").strip():
                # A ledger row without an extracted value carries no fact;
                # importing it would create an empty claim.  Source-only rows
                # stay auditable in the ledger itself, never as claims.
                report.skipped_unsupported += 1
                continue
            goal_id = str(row.get("goal_id") or "")
            goal = next((goal for goal in goals if goal.goal_id == goal_id), None)
            if goal is None:
                report.skipped_unsupported += 1
                continue
            value_class = self.policies.map_value_class(str(row.get("value_class") or "pending_verification"))
            if value_class.value in {"MODEL_ESTIMATE", "SIMULATED", "ASSUMPTION"}:
                # Modeling artifacts carry their own audited chain; only
                # observed/derived/confirmed rows become claims here.
                report.skipped_unsupported += 1
                continue
            source_id = str(row.get("source_id") or "").strip() or "ledger"
            key = (goal_id, source_id, str(row.get("evidence_item") or ""), str(row.get("raw_value") or ""))
            if key in seen:
                report.skipped_duplicates += 1
                continue
            seen.add(key)

            # §43 subject isolation: competitor rows bind to a competitor
            # entity, never to the target enterprise's entity.
            role_raw = str(row.get("subject_role") or "").strip().upper()
            subject_role = role_raw if role_raw in VALID_ROLES else "MARKET_CONTEXT"
            competitor_name = str(row.get("subject_name") or row.get("target_brand") or "").strip()
            if subject_role == "COMPETITOR" and competitor_name:
                entity_id = f"competitor:{competitor_name}"
                entity_name = competitor_name
            else:
                entity_id = goal.subject_id
                entity_name = goal.subject_name
            if entity_id not in known_subjects:
                if self._ensure_entity(entity_id, entity_name, mission, run_id, version):
                    report.subjects_created += 1
                known_subjects.add(entity_id)

            if source_id not in known_sources:
                if self._import_source(row, source_id, run_id, version):
                    report.sources_created += 1
                    known_sources.add(source_id)
                elif source_id == "ledger":
                    # Placeholder ledger source already exists or was created.
                    known_sources.add(source_id)

            claim = self._build_claim(
                mission=mission,
                goal=goal,
                row=row,
                source_id=source_id,
                originating_skill=originating_skill,
                entity_id=entity_id,
                subject_role=subject_role,
            )
            try:
                self.store.add(run_id, version, "claim", claim)
                report.claims_created += 1
            except Exception as exc:  # store boundary; import never crashes the agent
                report.errors.append(f"claim {claim.claim_id}: {type(exc).__name__}")

        return report

    # -- helpers ----------------------------------------------------------------

    def _ensure_run(self, mission: ResearchMission, run_id: str) -> None:
        try:
            self.store.get_run(run_id)
            return
        except Exception:
            pass
        from enterprise_energy_research import package_version

        run = RunManifest(
            run_id=run_id,
            request_id=mission.mission_id,
            canonical_entity_id=mission.canonical_entity_id,
            config_hash="agent",
            code_version=package_version(),
            model_gateway={"agent": True},
            evidence_version=mission.evidence_version,
        )
        try:
            self.store.create_run(run)
        except Exception:
            pass

    def _ensure_subject_entity(self, mission: ResearchMission, goal: ResearchGoal, run_id: str, version: int) -> bool:
        """Market subjects exist as entities so claims stay referentially sound."""
        return self._ensure_entity(goal.subject_id, goal.subject_name, mission, run_id, version)

    def _ensure_entity(self, entity_id: str, entity_name: str, mission: ResearchMission, run_id: str, version: int) -> bool:
        if self.store.has_record(run_id, "entity", entity_id):
            return False
        entity = Entity(
            entity_id=entity_id,
            canonical_name=entity_name or entity_id,
            entity_type="other",
            registration_region=str(mission.geographies or "").strip() or None,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        try:
            self.store.add(run_id, version, "entity", entity)
            return True
        except Exception:
            return False

    def _import_source(self, row: dict[str, Any], source_id: str, run_id: str, version: int) -> bool:
        url_raw = str(row.get("source_url") or "").strip()
        placeholder = f"https://ledger.local/{source_id}"
        try:
            canonical_url = HttpUrl(url_raw) if url_raw.startswith("http") else HttpUrl(placeholder)
        except Exception:
            canonical_url = HttpUrl(placeholder)
        domain = str(row.get("root_domain") or "").strip() or canonical_url.host or "ledger.local"
        tier = str(row.get("reliability_tier") or "").strip().upper()
        source = Source(
            source_id=source_id,
            canonical_url=canonical_url,
            source_title=str(row.get("source_title") or row.get("evidence_item") or "") or None,
            source_domain=domain,
            publisher=str(row.get("publisher") or "") or None,
            source_level=TIER_TO_LEVEL.get(tier, SourceLevel.SOURCE_D),
            access_status="blocked" if placeholder in str(canonical_url) else "ok",
            grading_reason=f"overseas market ledger tier={tier or 'unknown'}",
        )
        try:
            self.store.add(run_id, version, "source", source)
            return True
        except Exception:
            return False

    def _build_claim(
        self,
        *,
        mission: ResearchMission,
        goal: ResearchGoal,
        row: dict[str, Any],
        source_id: str,
        originating_skill: str,
        entity_id: str,
        subject_role: str,
    ) -> Claim:
        tier = str(row.get("reliability_tier") or "").strip().upper()
        verification_raw = str(row.get("verification_status") or "").strip().lower()
        verification = VerificationStatus.VERIFIED if verification_raw == "verified" else VerificationStatus.UNVERIFIED
        year_period = str(row.get("year_period") or "").strip()
        as_of = None
        if year_period[:4].isdigit():
            as_of = date(int(year_period[:4]), 1, 1)
        source_url = None
        url_raw = str(row.get("source_url") or "").strip()
        if url_raw.startswith("http"):
            try:
                source_url = HttpUrl(url_raw)
            except Exception:
                source_url = None
        return Claim(
            claim_id=new_sortable_id("CLAIM"),
            entity_id=entity_id,
            field_name=str(row.get("evidence_item") or "market_observation")[:200],
            value=row.get("raw_value"),
            value_type=str(row.get("data_type") or "market"),
            unit=str(row.get("unit") or "") or None,
            currency=str(row.get("currency") or "") or None,
            as_of_date=as_of,
            scope=f"market={row.get('market', '')}; country={row.get('country', '')}".strip("; "),
            qualifier="unknown",
            source_id=source_id,
            raw_text=str(row.get("source_title") or row.get("evidence_item") or "market ledger row")[:500],
            context_text=str(row.get("collection_goal") or goal.goal_description)[:500],
            locator={"ledger_row": str(row.get("record_id") or row.get("source_id") or "")},
            retrieved_at=utc_now(),
            verification_status=verification,
            confidence=TIER_TO_CONFIDENCE.get(tier, 0.4),
            mission_id=mission.mission_id,
            goal_id=goal.goal_id,
            subject_id=entity_id,
            subject_role=subject_role,  # type: ignore[arg-type]
            originating_skill=originating_skill,
            claim_type="market_evidence",
            value_class=self.policies.map_value_class(str(row.get("value_class") or "pending_verification")),
            geography=str(row.get("country") or row.get("global_region") or "") or None,
            source_url=source_url,
            source_type=str(row.get("source_type") or "") or None,
            source_grade=tier or None,
            raw_capture_ref=str(row.get("local_file_path") or row.get("raw_capture_path") or "") or None,
        )
