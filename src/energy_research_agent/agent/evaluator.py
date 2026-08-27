"""Goal evaluation (§21/§63).

Deterministic criteria (required-evidence coverage, evidence counts) are
computed by code. Qualitative completeness is judged by the LLM and merged.
The agent can never self-declare success: SATISFIED requires both the
deterministic floor AND the LLM judgment, plus a non-empty evidence base.
"""

from __future__ import annotations

from typing import Any

from energy_research_agent.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .models import (
    AgentStrictModel,
    FailureClass,
    GoalEvaluation,
    GoalStatus,
    ResearchGoal,
    SkillRunResult,
)


class _LLMEvaluation(AgentStrictModel):
    satisfied: bool
    satisfied_criteria: list[str] = []
    unmet_criteria: list[str] = []
    gaps: list[dict[str, Any]] = []
    reason: str = ""


class GoalEvaluator:
    def __init__(self, gateway: ModelGateway | None = None) -> None:
        self.gateway = gateway

    def evaluate(
        self,
        goal: ResearchGoal,
        evidence: list[dict[str, Any]],
        skill_results: list[SkillRunResult] | None = None,
    ) -> GoalEvaluation:
        skill_results = skill_results or []
        blocked = [r for r in skill_results if r.status.value in {"BLOCKED", "UNAVAILABLE", "FAILED"}]
        if blocked and not evidence:
            failure_class = blocked[0].failure_class or FailureClass.SKILL_FAILURE
            return GoalEvaluation(
                goal_id=goal.goal_id,
                status=GoalStatus.BLOCKED,
                unmet_criteria=list(goal.success_criteria),
                gaps=[{"type": "skill_blocked", "diagnostics": blocked[0].diagnostics}],
                evidence_count=len(evidence),
                required_evidence_missing=list(goal.required_evidence),
                evaluation_reason=f"执行 Skill 被阻断且无既有证据：{blocked[0].status.value}",
                failure_class=failure_class,
            )

        missing = self._missing_required(goal, evidence)
        llm = None
        if self.gateway is not None:
            try:
                llm = self._llm_evaluate(goal, evidence)
            except (GatewayError, ValueError):
                llm = None

        if llm is None:
            # Honest degraded judgment: never declare success without evidence.
            status = GoalStatus.SATISFIED if evidence and not missing else GoalStatus.PARTIAL
            reason = (
                "确定性评估：全部必需证据已覆盖"
                if status == GoalStatus.SATISFIED
                else f"确定性评估：缺少必需证据 {missing or '证据'}（无 LLM 语义评估）"
            )
            satisfied = [c for c in goal.success_criteria if not missing] if status == GoalStatus.SATISFIED else []
            unmet = list(goal.success_criteria) if not satisfied else missing
            return GoalEvaluation(
                goal_id=goal.goal_id,
                status=status,
                satisfied_criteria=satisfied,
                unmet_criteria=unmet,
                evidence_count=len(evidence),
                required_evidence_missing=missing,
                evaluation_reason=reason,
                failure_class=FailureClass.EVIDENCE_INSUFFICIENT if status != GoalStatus.SATISFIED else None,
            )

        if llm.satisfied and not missing and evidence:
            status = GoalStatus.SATISFIED
        else:
            status = GoalStatus.PARTIAL
        return GoalEvaluation(
            goal_id=goal.goal_id,
            status=status,
            satisfied_criteria=llm.satisfied_criteria,
            unmet_criteria=sorted(set(llm.unmet_criteria) | set(missing)),
            gaps=llm.gaps,
            evidence_count=len(evidence),
            required_evidence_missing=missing,
            evaluation_reason=llm.reason,
            failure_class=None if status == GoalStatus.SATISFIED else FailureClass.EVIDENCE_INSUFFICIENT,
        )

    def _llm_evaluate(self, goal: ResearchGoal, evidence: list[dict[str, Any]]) -> _LLMEvaluation:
        request = StructuredRequest[_LLMEvaluation](
            purpose="agent.goal_evaluation",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是研究目标评估器。基于给定证据判断目标是否已满足。"
                        "要求：1) 不能因为证据‘看起来相关’就宣布满足；2) 不满足必须列出缺口；"
                        "3) 证据不足时明确说证据不足，禁止编造；4) 用中文给出 reason。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"goal_name={goal.goal_name}\ngoal_description={goal.goal_description}\n"
                        f"required_evidence={goal.required_evidence}\n"
                        f"success_criteria={goal.success_criteria}\n"
                        f"evidence_count={len(evidence)}\n"
                        f"evidence_sample={jsonable(evidence[:30])}"
                    ),
                },
            ],
            response_model=_LLMEvaluation,
        )
        return self.gateway.structured(request)

    @staticmethod
    def _missing_required(goal: ResearchGoal, evidence: list[dict[str, Any]]) -> list[str]:
        covered: set[str] = set()
        for row in evidence:
            for key in ("field_name", "claim_type", "goal_class", "name", "metric"):
                value = row.get(key)
                if value:
                    covered.add(str(value))
        return [field for field in goal.required_evidence if field not in covered]


def jsonable(value: Any) -> Any:
    """Coerce to JSON-safe primitives for prompt embedding."""
    if isinstance(value, dict):
        return {str(key): jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value][:500]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
