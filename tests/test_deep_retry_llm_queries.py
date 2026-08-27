"""Deep-research (t3) LLM recovery-query generation (ported from t1).

Every t3 round previously searched the same deterministic keyword family
regardless of which fields were actually missing. The port feeds the current
coverage-audit gaps + user requirement to the gateway and executes the
returned texts VERBATIM via ``ResearchPlanner.direct_recovery_queries`` (R4).
The LLM is an enrichment: any failure degrades to the template floor.
"""

from enterprise_energy_research.gateway.base import GatewayError
from enterprise_energy_research.research.data_coverage import CoverageGap
from enterprise_energy_research.research.deep_retry import (
    _DeepRecoveryQueries,
    _llm_recovery_queries,
)


def _gap(code: str, hint: str = "环评 建设项目") -> CoverageGap:
    return CoverageGap(
        gap_code=code,
        field_name=code.replace("coverage-", ""),
        description=f"缺少 {code} 有效证据",
        requirement="≥ 1 条",
        found="",
        severity="high",
        retry_hint=hint,
    )


class _FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def structured(self, request):
        self.requests.append(request)
        if isinstance(self.payload, Exception):
            raise self.payload
        return _DeepRecoveryQueries.model_validate(self.payload)


def test_schema_accepts_common_llm_synonyms_and_caps() -> None:
    plan = _DeepRecoveryQueries.model_validate({
        "reason": "财务缺口",
        "queries": [f"查询{i}" for i in range(9)] + ["", "   ", None],
        "unknown_field": "drop me",
    })
    assert plan.analysis == "财务缺口"
    assert len(plan.new_queries) == 6
    assert all(query.strip() for query in plan.new_queries)


def test_schema_coerces_single_string_query() -> None:
    plan = _DeepRecoveryQueries.model_validate({"queries": "单条查询"})
    assert plan.new_queries == ["单条查询"]


def test_llm_queries_returned_verbatim_deduplicated() -> None:
    gateway = _FakeGateway({
        "analysis": "缺口集中在新建项目",
        "queries": [
            "昀冢电子 环评批复 新建项目",
            "  昀冢电子   环评批复 新建项目  ",
            "昀冢电子 投产公告 产能",
        ],
    })
    texts = _llm_recovery_queries(
        gateway, "苏州昀冢电子科技股份有限公司", "新建项目环评与产能",
        [_gap("coverage-projects")],
        previous_hints=["环评 建设项目"], recovery_round=2,
    )
    assert texts == ["昀冢电子 环评批复 新建项目", "昀冢电子 投产公告 产能"]
    request = gateway.requests[0]
    assert request.response_model is _DeepRecoveryQueries
    assert request.purpose == "deep_retry.recovery_queries"
    user_content = request.messages[-1]["content"]
    assert "company=苏州昀冢电子科技股份有限公司" in user_content
    assert "coverage-projects" in user_content
    assert "环评 建设项目" in user_content  # previous hints carried


def test_llm_failures_degrade_to_empty_floor() -> None:
    gaps = [_gap("coverage-revenue")]
    # gateway absent -> template floor
    assert _llm_recovery_queries(None, "公司", "需求", gaps,
                                  previous_hints=[], recovery_round=1) == []
    # no gaps -> nothing to plan
    assert _llm_recovery_queries(_FakeGateway({}), "公司", "需求", [],
                                 previous_hints=[], recovery_round=1) == []
    # provider failure -> template floor, never raise
    gateway = _FakeGateway(GatewayError("provider down"))
    assert _llm_recovery_queries(gateway, "公司", "需求", gaps,
                                 previous_hints=[], recovery_round=1) == []
    # garbage payload tolerated by schema (non-list coerced to []) -> floor
    gateway = _FakeGateway({"queries": 123})
    assert _llm_recovery_queries(gateway, "公司", "需求", gaps,
                                 previous_hints=[], recovery_round=1) == []
