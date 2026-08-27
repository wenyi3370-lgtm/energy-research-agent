"""Cross-domain synthesis (§35/§36).

Connects enterprise capability evidence with market demand/policy/competition
evidence into traceable findings. Only VERIFIED/VALIDATED evidence may feed in;
every finding must carry its evidence refs and counter-evidence — a bare LLM
opinion is rejected by the code guardrail.
"""

from __future__ import annotations

from typing import Any

from enterprise_energy_research.domain.ids import new_sortable_id
from enterprise_energy_research.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .models import (
    AgentStrictModel,
    CrossDomainFinding,
    ResearchGoal,
    ResearchMission,
    ResearchMode,
)


class _LLMSynthesis(AgentStrictModel):
    findings: list[CrossDomainFinding]


class CrossDomainSynthesisEngine:
    """Reads only verified evidence; code-validates every produced finding."""

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        self.gateway = gateway

    def synthesize(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        enterprise_evidence: list[dict[str, Any]],
        market_evidence: list[dict[str, Any]],
    ) -> list[CrossDomainFinding]:
        if mission.mode == ResearchMode.ENTERPRISE:
            return []
        verified_enterprise = [row for row in enterprise_evidence if row.get("verification_status") in {"VERIFIED", "verified"}]
        verified_market = [row for row in market_evidence if row.get("verification_status") in {"VERIFIED", "verified"}]
        refs = {
            **{str(row.get("claim_id")): row for row in verified_enterprise if row.get("claim_id")},
            **{str(row.get("claim_id")): row for row in verified_market if row.get("claim_id")},
        }
        if self.gateway is None:
            return []
        try:
            batch = self._llm_synthesize(mission, goals, verified_enterprise, verified_market)
        except (GatewayError, ValueError):
            return []
        findings: list[CrossDomainFinding] = []
        for finding in batch.findings:
            all_refs = (
                list(finding.enterprise_evidence_refs)
                + list(finding.market_evidence_refs)
                + list(finding.counter_evidence_refs)
            )
            if not all_refs or not all(ref_id in refs for ref_id in all_refs):
                # §36: conclusions must be traceable; drop untraceable ones.
                continue
            findings.append(finding)
        return findings

    def _llm_synthesize(
        self,
        mission: ResearchMission,
        goals: list[ResearchGoal],
        enterprise_evidence: list[dict[str, Any]],
        market_evidence: list[dict[str, Any]],
    ) -> _LLMSynthesis:
        from .evaluator import jsonable

        request = StructuredRequest[_LLMSynthesis](
            purpose="agent.cross_domain_synthesis",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是企业—市场跨域综合引擎。基于已验证证据产出可追溯结论。"
                        "规则：1) 每个 finding 必须携带 enterprise_evidence_refs / "
                        "market_evidence_refs / counter_evidence_refs（claim_id 列表），"
                        "引用必须真实存在于输入证据；2) 结论类型限 MARKET_FIT / PRODUCT_FIT / "
                        "CHANNEL_FIT / TIMING / RISK / OPPORTUNITY / COOPERATION_POTENTIAL / "
                        "ENTRY_STRATEGY；3) 无证据支持的宏大判断禁止出现；4) 语言中文，咨询级表述。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"mission={mission.raw_request}\nmode={mission.mode.value}\n"
                        f"decision_question={mission.decision_question or ''}\n"
                        f"goals={jsonable([{'goal_id': g.goal_id, 'name': g.goal_name} for g in goals])}\n"
                        f"enterprise_evidence={jsonable(enterprise_evidence[:80])}\n"
                        f"market_evidence={jsonable(market_evidence[:80])}"
                    ),
                },
            ],
            response_model=_LLMSynthesis,
        )
        return self.gateway.structured(request)

    @staticmethod
    def finding(
        *,
        finding_type: str,
        statement: str,
        enterprise_refs: list[str] | None = None,
        market_refs: list[str] | None = None,
        counter_refs: list[str] | None = None,
        assumptions: list[str] | None = None,
        confidence: float = 0.5,
        conditions: list[str] | None = None,
    ) -> CrossDomainFinding:
        """Deterministic helper used by tests and degraded paths."""
        return CrossDomainFinding(
            finding_id=new_sortable_id("FINDING"),
            finding_type=finding_type,  # type: ignore[arg-type]
            statement=statement,
            enterprise_evidence_refs=enterprise_refs or [],
            market_evidence_refs=market_refs or [],
            counter_evidence_refs=counter_refs or [],
            assumptions=assumptions or [],
            confidence=confidence,
            conditions=conditions or [],
        )
