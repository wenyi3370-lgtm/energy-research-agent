from __future__ import annotations

from datetime import date

from enterprise_energy_research.artifacts.narrative import NarrativeBuilder
from enterprise_energy_research.artifacts.publication_terminology import source_type_label
from enterprise_energy_research.domain.enums import (
    EnterpriseComplexity, RunStatus, SourceLevel, StatementType,
    ValidationStatus, VerificationStatus,
)
from enterprise_energy_research.domain.models import (
    Claim, DataFreeze, DataGap, Entity, FrozenResearchBundle, RunManifest,
    Solution, Source,
)
from enterprise_energy_research.research.client_profile import (
    ClientCapability, ClientCapabilityStatus, ClientProfile, load_client_profile,
)
from enterprise_energy_research.research.cooperation_hypothesis import (
    CooperationHypothesisEngine, CooperationHypothesisStatus,
)
from enterprise_energy_research.research.decision_synthesis import DecisionSynthesisEngine
from enterprise_energy_research.research.research_analysis import ResearchAnalysisEngine
from enterprise_energy_research.research.strategic_interpretation import StrategicInterpretationEngine
from enterprise_energy_research.validation.publication_quality import AI_TONE_PHRASES, DecisionIntelligenceValidator
from enterprise_energy_research.validation.consulting_narrative import narrative_body_text
from enterprise_energy_research.research.vision import parse_vision_text


def claim(claim_id: str, field: str, value, year: int, source_id: str = "SRC-A", confidence: float = 0.9) -> Claim:
    return Claim(
        claim_id=claim_id, entity_id="ENT-1", field_name=field, value=value,
        value_type="number" if isinstance(value, (int, float)) else "text", unit="元" if field in {"revenue", "profit"} else None,
        period_start=date(year, 1, 1), period_end=date(year, 12, 31), scope="公司口径",
        source_id=source_id, raw_text=f"{year} {field} {value}", context_text=f"年度披露 {field}",
        verification_status=VerificationStatus.VERIFIED, confidence=confidence,
    )


def bundle(*, claims: list[Claim] | None = None, gaps: list[DataGap] | None = None, solutions: list[Solution] | None = None, client: ClientProfile | None = None) -> FrozenResearchBundle:
    profile = client or load_client_profile()
    run = RunManifest(
        run_id="RUN-1", request_id="REQ-1", status=RunStatus.PASS,
        canonical_entity_id="ENT-1", complexity=EnterpriseComplexity.ENTERPRISE_NORMAL,
        config_hash="test", code_version="test", model_gateway={"mode": "fixture"},
        client_profile=profile.model_dump(mode="json"), client_profile_hash=profile.stable_hash,
        validation_status=ValidationStatus.PASS, freeze_id="FREEZE-1",
    )
    freeze = DataFreeze(
        freeze_id="FREEZE-1", run_id="RUN-1", evidence_version=1,
        included_record_ids={}, record_hashes={}, root_hash="0" * 64,
        validation_report_id="VAL-1",
    )
    sources = [Source(
        source_id="SRC-A", canonical_url="https://example.com/report", source_domain="example.com",
        source_level=SourceLevel.SOURCE_A, grading_reason="official fixture",
    )]
    return FrozenResearchBundle(
        freeze=freeze, run_manifest=run,
        entities=[Entity(entity_id="ENT-1", canonical_name="样本企业", verification_status=VerificationStatus.VERIFIED)],
        sources=sources, claims=claims or [], gaps=gaps or [], solutions=solutions or [],
    )


def opportunity_solution(claim_ids: list[str]) -> Solution:
    return Solution(
        solution_id="SOL-1", engine="PRODUCT_COOPERATION", target_ids=["ENT-1"],
        opportunity="联合产品验证", proposed_solution="围绕公开技术路线验证产品接口",
        benefit_logic="缩短需求方与技术方确认产品适配性的周期",
        next_step="验证企业责任部门的真实问题", priority="A",
        statement_type=StatementType.EVIDENCE_SUPPORTED, claim_ids=claim_ids,
    )


def test_latest_kpi_uses_latest_completed_verified_period_not_highest_confidence():
    b = bundle(claims=[
        claim("C22", "revenue", 100, 2022, confidence=0.99),
        claim("C23", "revenue", 120, 2023, confidence=0.80),
        claim("C24", "revenue", 150, 2024, confidence=0.85),
    ])
    revenue = next(item for item in ResearchAnalysisEngine().analyze(b).kpis if item.label == "营业收入")
    assert revenue.period == "2024"
    assert revenue.claim_ids == ["C24"]


def test_carbon_report_title_is_not_misread_as_energy_consumption_value():
    report = claim("E23", "energy_consumption", "2023年度碳排放核算报告", 2023)
    b = bundle(claims=[report])
    analysis = ResearchAnalysisEngine().analyze(b)
    assert analysis.own_energy_metrics == []
    narrative = NarrativeBuilder().build(b)
    energy = narrative.chapter("energy_profile")
    assert energy is not None
    payload = energy.model_dump_json()
    assert "综合能源消费量 2023年度碳排放核算报告" not in payload
    assert "标题本身没有给出综合能源消费量的数值" in payload
    assert "不支持直接进行容量设计或商业报价" in payload
    assert "v-energy-own-kpis" not in energy.visual_ids


def test_unit_bearing_energy_measurement_remains_publishable():
    measurement = Claim(
        claim_id="E24", entity_id="ENT-1", field_name="electricity_consumption",
        value=1200, value_type="number", unit="MWh", period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31), scope="公司口径", source_id="SRC-A",
        raw_text="2024年度用电量1200MWh", context_text="年度能源披露",
        verification_status=VerificationStatus.VERIFIED, confidence=0.9,
    )
    analysis = ResearchAnalysisEngine().analyze(bundle(claims=[measurement]))
    assert [(item.field_name, item.value, item.unit) for item in analysis.own_energy_metrics] == [
        ("electricity_consumption", 1200.0, "MWh")
    ]


def test_source_grade_publication_mapping_is_honest():
    assert source_type_label(SourceLevel.SOURCE_A) == "核心一级证据"
    assert source_type_label(SourceLevel.SOURCE_B) == "高质量辅助证据"
    assert source_type_label(SourceLevel.SOURCE_C) == "线索型来源"
    assert source_type_label(SourceLevel.SOURCE_D) == "弱证据/舆情线索"


def test_gap_dedupe_merges_same_entity_field_and_affected_decision():
    gaps = [
        DataGap(gap_id="G1", entity_id="ENT-1", field_name="load_curve", importance="critical", reason="missing", next_action="ask"),
        DataGap(gap_id="G2", entity_id="ENT-1", field_name="load_curve", importance="critical", reason="SEARCHED_NOT_FOUND", next_action="ask again"),
    ]
    result = DecisionSynthesisEngine()._due_diligence(gaps)
    assert len(result) == 1
    assert result[0].source_gap_ids == ["G1", "G2"]


def test_gap_dedupe_merges_different_schema_fields_with_same_public_label():
    gaps = [
        DataGap(gap_id="G1", entity_id="ENT-1", field_name="unmapped_alpha", importance="major", reason="missing", next_action="ask"),
        DataGap(gap_id="G2", entity_id="ENT-1", field_name="unmapped_beta", importance="major", reason="SEARCHED_NOT_FOUND", next_action="ask again"),
    ]
    result = DecisionSynthesisEngine()._due_diligence(gaps)
    assert len(result) == 1
    assert result[0].item == "其他公开披露事项"


def test_product_signal_alone_is_not_priority_opportunity():
    claims = [claim("P1", "product_family", "储能产品", 2024)]
    b = bundle(claims=claims, solutions=[opportunity_solution(["P1"])])
    strategic = StrategicInterpretationEngine().interpret(b)
    hypothesis = CooperationHypothesisEngine().build(b, strategic)[0]
    assert hypothesis.status == CooperationHypothesisStatus.POTENTIAL_HYPOTHESIS
    assert any("未显示对方提出具体合作需求" in item for item in hypothesis.rejection_reasons)


def test_unknown_client_capability_cannot_support_priority():
    client = ClientProfile(client_id="unknown", client_name="未知委托方", role="未知", capabilities=[
        ClientCapability(capability_id="u", name="未知能力", status=ClientCapabilityStatus.UNKNOWN_CLIENT_CAPABILITY, applicable_opportunity_types=["PRODUCT_COOPERATION"]),
    ])
    claims = [
        claim("R1", "risk", "产品适配周期过长", 2023),
        claim("S1", "strategic_priority", "联合技术验证", 2024),
    ]
    b = bundle(claims=claims, solutions=[opportunity_solution(["R1", "S1"])], client=client)
    result = CooperationHypothesisEngine().build(b, StrategicInterpretationEngine().interpret(b), client)[0]
    assert result.status != CooperationHypothesisStatus.PRIORITY_OPPORTUNITY
    assert "UNKNOWN_CLIENT_CAPABILITY" in result.client_capability_statuses


def test_competition_analysis_is_gated_and_never_invents_competitors():
    empty = StrategicInterpretationEngine().interpret(bundle(claims=[claim("B1", "core_business", "电池", 2024)]))
    assert empty.competitive_positions == []
    comparative = StrategicInterpretationEngine().interpret(bundle(claims=[claim("M1", "market_share", "全球份额30%", 2024)]))
    assert len(comparative.competitive_positions) == 1
    assert comparative.competitive_positions[0].named_comparables == []


def test_data_gap_never_becomes_enterprise_risk():
    b = bundle(gaps=[DataGap(gap_id="G", entity_id="ENT-1", field_name="load_curve", importance="critical", reason="missing", next_action="ask")])
    strategic = StrategicInterpretationEngine().interpret(b)
    assert strategic.enterprise_risks == []


def test_negative_or_mitigation_disclosures_are_not_published_as_risks():
    engine = StrategicInterpretationEngine()
    assert not engine._is_substantive_risk_text("公司报告期未发生重大诉讼、仲裁事项")
    assert not engine._is_substantive_risk_text("公司成立风控小组以控制风险")
    assert not engine._is_substantive_risk_text("不存在按照境外会计准则与中国会计准则披露的净资产差异")
    assert engine._is_substantive_risk_text("市场竞争加剧风险")


def test_three_year_series_requires_strategic_trajectory():
    b = bundle(claims=[claim("R22", "revenue", 100, 2022), claim("R23", "revenue", 130, 2023), claim("R24", "revenue", 180, 2024)])
    assert StrategicInterpretationEngine().interpret(b).trajectories


def test_publication_narrative_contains_client_strategy_and_shared_decision_model():
    claims = [claim("R22", "revenue", 100, 2022), claim("R23", "revenue", 130, 2023), claim("R24", "revenue", 180, 2024)]
    narrative = NarrativeBuilder().build(bundle(claims=claims))
    assert narrative.client_profile.client_name == "四川动力电池产业创新中心"
    assert narrative.strategic_interpretation.trajectories
    assert narrative.chapter("strategic_interpretation") is not None
    assert len(narrative.executive_summary) == 5


def test_publication_narrative_localizes_hypothesis_statuses():
    b = bundle(claims=[claim("P1", "product_family", "储能产品", 2024)], solutions=[opportunity_solution(["P1"])])
    text = narrative_body_text(NarrativeBuilder().build(b))
    assert "备选方向" in text
    assert "POTENTIAL_HYPOTHESIS" not in text


def test_decision_intelligence_validator_rejects_process_dominated_copy():
    b = bundle(claims=[claim("B1", "core_business", "电池", 2024)])
    narrative = NarrativeBuilder().build(b)
    for chapter in narrative.chapters:
        chapter.analysis_paragraphs = [
            "本阶段以资料清单、数据清洗、预可研、补数和报告生成为主要工作内容。",
            "后续继续进行资料收集、数据清洗和报告制作。",
        ]
    checks = {item.code: item for item in DecisionIntelligenceValidator().validate(narrative, b)}
    assert checks["decision_process_language_ratio"].status == "FAIL"


def test_executive_summary_uses_business_outcomes_not_process_language():
    b = bundle(claims=[claim("R22", "revenue", 100, 2022), claim("R23", "revenue", 130, 2023), claim("R24", "revenue", 180, 2024)])
    narrative = NarrativeBuilder().build(b)
    checks = {item.code: item for item in DecisionIntelligenceValidator().validate(narrative, b)}
    assert checks["executive_summary_process_language"].status == "PASS"


def test_publication_payload_uses_plain_business_language():
    claims = [
        claim("R1", "risk", "产品适配周期过长", 2023),
        claim("S1", "strategic_priority", "联合技术验证", 2024),
    ]
    narrative = NarrativeBuilder().build(bundle(claims=claims, solutions=[opportunity_solution(["R1", "S1"])]))
    payload = narrative.model_dump_json()
    assert not [phrase for phrase in AI_TONE_PHRASES if phrase in payload]
    action = narrative.chapter("action_plan")
    assert action is not None
    assert "确认需求" in action.executive_takeaway
    assert "明确技术指标" in "".join(action.analysis_paragraphs)


def test_plain_business_language_gate_rejects_internal_framework_recital():
    b = bundle(claims=[claim("B1", "core_business", "电池", 2024)])
    narrative = NarrativeBuilder().build(b)
    narrative.chapters[0].analysis_paragraphs.append("关键输出不是资料包或流程台账，而是逐项检验内部假设。")
    checks = {item.code: item for item in DecisionIntelligenceValidator().validate(narrative, b)}
    assert checks["plain_business_language"].status == "FAIL"


def test_rejected_candidates_do_not_receive_high_priority():
    b = bundle(claims=[claim("P1", "product_family", "储能产品", 2024)], solutions=[opportunity_solution(["P1"])])
    assessment = NarrativeBuilder().opportunity_engine.assess(b)[0]
    assert assessment.priority not in {"A", "B"}


def test_vision_markdown_score_is_parsed_from_real_provider_shape():
    verdict = parse_vision_text(
        "1) 图中主体属于：**产品**\n\n2) 图中是一个蓝色集装箱。\n\n"
        "3) 绑定到目标实体（类型：product）的置信度：**1.0**（主体明确）。"
    )
    assert verdict.verified is True
    assert verdict.score == 1.0
