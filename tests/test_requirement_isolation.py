from __future__ import annotations

import hashlib

from energy_research_agent.domain.enums import (
    RunStatus,
    SourceLevel,
    VerificationStatus,
)
from energy_research_agent.domain.models import (
    Claim,
    DataFreeze,
    Entity,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedEvidenceBatch,
    FrozenResearchBundle,
    RunManifest,
    Source,
)
from energy_research_agent.research.claim_validator import ClaimValidator
from energy_research_agent.research.entity_scope import rebind_target_alias_entities
from energy_research_agent.research.normalizer import EvidenceNormalizer, NormalizedEvidence
from energy_research_agent.research.planner import ResearchPlanner
from energy_research_agent.research.publication_relevance import PublicationRelevanceFilter
from energy_research_agent.artifacts.narrative import NarrativeBuilder, ResearchNarrative
from energy_research_agent.validation.publication_quality import ResearchValueValidator


def _claim(claim_id: str, entity_id: str, field: str, value: object, source_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        entity_id=entity_id,
        field_name=field,
        value=value,
        value_type="string",
        source_id=source_id,
        raw_text=str(value),
        context_text=f"{field}: {value}",
        verification_status=VerificationStatus.VERIFIED,
        confidence=0.95,
    )


def test_known_and_unusual_requirements_are_separate_and_complete() -> None:
    requirement = "调查销售渠道、现行政策、主要竞品，以及创始团队独特的技术决策习惯"
    queries = ResearchPlanner().requirement_queries("目标新能源企业", requirement)
    by_topic = {query.topic: query for query in queries}
    assert {"sales_channels", "policy_regulation", "competitive_position", "custom_requirement"} <= set(by_topic)
    assert by_topic["sales_channels"].evidence_lane == "ecosystem"
    assert by_topic["policy_regulation"].subject_role == "public_authority"
    assert by_topic["competitive_position"].evidence_use == "comparison_context"
    assert by_topic["custom_requirement"].goal_domain == "custom_supplement"
    assert all(requirement in query.purpose for query in queries)
    assert all(query.requirement_text == requirement for query in queries)
    assert all("目标新能源企业" in query.query for query in queries)
    for topic in by_topic:
        assert {
            query.collection_round for query in queries if query.topic == topic
        } == {"R1", "R2", "R3"}


def test_target_alias_rebind_never_merges_competitor() -> None:
    target = Entity(
        entity_id="ENT-T", canonical_name="星星充电", registered_name="星星充电",
        verification_status=VerificationStatus.VERIFIED,
    )
    legal = Entity(
        entity_id="ENT-L", canonical_name="万帮星星充电科技有限公司",
        aliases=["星星充电"], verification_status=VerificationStatus.VERIFIED,
    )
    competitor = Entity(
        entity_id="ENT-C", canonical_name="特来电", verification_status=VerificationStatus.VERIFIED,
    )
    evidence = NormalizedEvidence(
        entities=[target, legal, competitor],
        claims=[
            _claim("C-T", "ENT-T", "product_family", "交流充电桩", "S1"),
            _claim("C-L", "ENT-L", "sales_channel", "直营网点", "S1"),
            _claim("C-C", "ENT-C", "market_share", "竞品份额", "S1"),
        ],
    )
    canonical_id = rebind_target_alias_entities(evidence, "ENT-T", "星星充电")
    assert canonical_id == "ENT-T"
    assert {entity.entity_id for entity in evidence.entities} == {"ENT-T", "ENT-C"}
    assert {claim.entity_id for claim in evidence.claims if claim.claim_id in {"C-T", "C-L"}} == {"ENT-T"}
    assert next(claim for claim in evidence.claims if claim.claim_id == "C-C").entity_id == "ENT-C"


def test_competitor_evidence_does_not_dilute_target_publication_ratio() -> None:
    target = Entity(
        entity_id="ENT-T", canonical_name="目标企业",
        verification_status=VerificationStatus.VERIFIED,
    )
    competitor = Entity(
        entity_id="ENT-C", canonical_name="竞品企业",
        verification_status=VerificationStatus.VERIFIED,
    )
    source = Source(
        source_id="S1", canonical_url="https://example.com/report",
        source_domain="example.com", source_level=SourceLevel.SOURCE_A,
        grading_reason="official_announcement",
    )
    claims = [
        _claim("T1", "ENT-T", "product_family", "储能系统", "S1"),
        _claim("T2", "ENT-T", "sales_channel", "直销", "S1"),
        *[
            _claim(f"X{index}", "ENT-C", "market_share", f"竞品口径{index}", "S1")
            for index in range(8)
        ],
    ]
    manifest = RunManifest(
        run_id="RUN-T", request_id="REQ-T", status=RunStatus.RUNNING,
        canonical_entity_id="ENT-T", config_hash="x", code_version="test",
        model_gateway={"mode": "test"},
    )
    bundle = FrozenResearchBundle(
        freeze=DataFreeze(
            freeze_id="FREEZE-T", run_id="RUN-T", evidence_version=1,
            included_record_ids={}, record_hashes={}, root_hash="0" * 64,
            validation_report_id="VAL-T",
        ),
        run_manifest=manifest,
        entities=[target, competitor], sources=[source], claims=claims,
    )
    body, report = PublicationRelevanceFilter().filter(bundle)
    assert report.total_verified == 10
    assert report.target_scope_verified == 2
    assert {claim.entity_id for claim in body} == {"ENT-T"}


def test_conflicts_are_isolated_by_entity_and_period_scope() -> None:
    source = Source(
        source_id="S1", canonical_url="https://example.com/report",
        source_domain="example.com", source_level=SourceLevel.SOURCE_A,
        grading_reason="official_announcement",
    )
    claims = [
        _claim("T1", "ENT-T", "revenue", 100, "S1"),
        _claim("C1", "ENT-C", "revenue", 300, "S1"),
    ]
    _, conflicts = ClaimValidator().validate(claims, [source])
    assert conflicts == []


def test_normalizer_persists_requirement_routing_on_claim() -> None:
    batch = ExtractedEvidenceBatch(
        source_url="https://example.com/channel",
        source_kind="official_company",
        entities=[ExtractedEntity(entity_key="target", canonical_name="目标企业")],
        claims=[ExtractedClaim(
            entity_key="target", field_name="sales_channel", value="直营网点",
            value_type="string", raw_text="销售采用直营网点", context_text="公司销售采用直营网点",
        )],
        extraction_method="model_structured",
        origin_query_id="Q-CHANNEL",
        origin_topic="sales_channels",
        goal_domain="commercial_channels",
        subject_role="ecosystem_party",
        evidence_lane="ecosystem",
        evidence_use="relationship_context",
        requirement_text="调查销售渠道",
    )
    evidence = EvidenceNormalizer().normalize([batch])
    routing = evidence.claims[0].locator["_routing"]
    assert routing["origin_query_id"] == "Q-CHANNEL"
    assert routing["topic"] == "sales_channels"
    assert routing["requirement_text"] == "调查销售渠道"


def _supplement_bundle(*, attempts: int, with_claim: bool) -> FrozenResearchBundle:
    target = Entity(
        entity_id="ENT-T", canonical_name="目标企业",
        verification_status=VerificationStatus.VERIFIED,
    )
    source = Source(
        source_id="S1", canonical_url="https://example.com/channel",
        source_domain="example.com", source_level=SourceLevel.SOURCE_A,
        grading_reason="official_company",
    )
    claims = []
    if with_claim:
        claims.append(_claim("T1", "ENT-T", "sales_channel", "直营网点", "S1").model_copy(update={
            "locator": {"_routing": {
                "topic": "sales_channels", "goal_domain": "commercial_channels",
                "subject_role": "ecosystem_party", "evidence_lane": "ecosystem",
                "evidence_use": "relationship_context", "requirement_text": "调查销售渠道",
            }}
        }))
    requirement_key = hashlib.sha256("调查销售渠道".encode("utf-8")).hexdigest()
    manifest = RunManifest(
        run_id="RUN-S", request_id="REQ-S", status=RunStatus.RUNNING,
        canonical_entity_id="ENT-T", config_hash="x", code_version="test",
        model_gateway={"mode": "test"},
        research_scope={
            "requirements": "调查销售渠道",
            "supplemental_requirement_key": requirement_key,
            "supplemental_attempts": attempts,
            "supplemental_attempt_history": [
                {
                    "requirement_key": requirement_key,
                    "round": index,
                    "execution_status": "completed",
                    "queried_topics": ["sales_channels"],
                    "active_topics": ["sales_channels"],
                }
                for index in range(1, attempts + 1)
            ],
            "requirement_routes": [{
                "topic": "sales_channels", "goal_domain": "commercial_channels",
                "subject_role": "ecosystem_party", "evidence_lane": "ecosystem",
                "evidence_use": "relationship_context",
            }],
        },
    )
    return FrozenResearchBundle(
        freeze=DataFreeze(
            freeze_id="FREEZE-S", run_id="RUN-S", evidence_version=1,
            included_record_ids={}, record_hashes={}, root_hash="0" * 64,
            validation_report_id="VAL-S",
        ),
        run_manifest=manifest, entities=[target], sources=[source], claims=claims,
    )


def test_supplemental_requirement_gets_its_own_evidence_bound_chapter() -> None:
    bundle = _supplement_bundle(attempts=0, with_claim=True)
    narrative = ResearchNarrative(
        run_id="RUN-S", freeze_id="FREEZE-S", entity_name="目标企业",
    )
    modules = NarrativeBuilder()._supplemental_modules(bundle, narrative)
    assert len(modules) == 1
    assert modules[0].title == "专项补充：销售渠道"
    assert modules[0].claim_ids == ["T1"]
    assert narrative.supplemental_requirements[0]["status"] == "satisfied"


def test_supplemental_gap_is_blocking_until_ten_attempts_are_audited() -> None:
    pending_bundle = _supplement_bundle(attempts=8, with_claim=False)
    pending = ResearchNarrative(
        run_id="RUN-S", freeze_id="FREEZE-S", entity_name="目标企业",
    )
    NarrativeBuilder()._supplemental_modules(pending_bundle, pending)
    pending_checks = ResearchValueValidator().validate(pending, pending_bundle)
    assert next(item for item in pending_checks if item.code == "supplemental_requirement_coverage").status == "FAIL"

    exhausted_bundle = _supplement_bundle(attempts=10, with_claim=False)
    exhausted = ResearchNarrative(
        run_id="RUN-S", freeze_id="FREEZE-S", entity_name="目标企业",
    )
    NarrativeBuilder()._supplemental_modules(exhausted_bundle, exhausted)
    exhausted_checks = ResearchValueValidator().validate(exhausted, exhausted_bundle)
    assert next(item for item in exhausted_checks if item.code == "supplemental_requirement_coverage").status == "PASS"
    assert exhausted.supplemental_requirements[0]["status"] == "exhausted_gap"


def test_blocked_search_rounds_never_masquerade_as_public_evidence_exhaustion() -> None:
    bundle = _supplement_bundle(attempts=10, with_claim=False)
    scope = dict(bundle.run_manifest.research_scope)
    scope["supplemental_attempt_history"] = [
        {**item, "execution_status": "blocked", "active_topics": []}
        for item in scope["supplemental_attempt_history"]
    ]
    bundle = bundle.model_copy(update={
        "run_manifest": bundle.run_manifest.model_copy(update={"research_scope": scope})
    })
    narrative = ResearchNarrative(
        run_id="RUN-S", freeze_id="FREEZE-S", entity_name="目标企业",
    )
    NarrativeBuilder()._supplemental_modules(bundle, narrative)
    checks = ResearchValueValidator().validate(narrative, bundle)
    assert next(item for item in checks if item.code == "supplemental_requirement_coverage").status == "FAIL"
    assert narrative.supplemental_requirements[0]["status"] == "pending_retry"


def test_extraction_failed_rounds_never_count_toward_evidence_exhaustion() -> None:
    bundle = _supplement_bundle(attempts=10, with_claim=False)
    scope = dict(bundle.run_manifest.research_scope)
    scope["supplemental_attempt_history"] = [
        {**item, "execution_status": "extraction_failed"}
        for item in scope["supplemental_attempt_history"]
    ]
    bundle = bundle.model_copy(update={
        "run_manifest": bundle.run_manifest.model_copy(update={"research_scope": scope})
    })
    narrative = ResearchNarrative(
        run_id="RUN-S", freeze_id="FREEZE-S", entity_name="目标企业",
    )
    NarrativeBuilder()._supplemental_modules(bundle, narrative)
    assert narrative.supplemental_requirements[0]["status"] == "pending_retry"
    assert narrative.supplemental_requirements[0]["completed_recovery_rounds"] == 0
