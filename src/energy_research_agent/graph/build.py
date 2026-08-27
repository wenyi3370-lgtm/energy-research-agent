from __future__ import annotations

from typing import Any, TypedDict


class GraphDependencyError(RuntimeError):
    pass


class LangGraphState(TypedDict, total=False):
    run_id: str
    request_id: str
    status: str
    current_node: str
    canonical_entity_id: str | None
    complexity: str
    evidence_version: int
    freeze_id: str | None
    artifact_manifest_id: str | None
    blocking_findings: list[str]


def build_langgraph(nodes: dict[str, Any]) -> Any:
    """Build the explicit Agent graph when LangGraph is installed.

    Required nodes: preflight, input_normalizer, company_resolver, classifier,
    research_planner, validate, freeze, artifact_plan. Phase 3 will replace boundary stubs.
    """
    required = {
        "preflight", "input_normalizer", "company_resolver", "classifier",
        "research_planner", "validate", "freeze", "artifact_plan",
    }
    missing = required.difference(nodes)
    if missing:
        raise ValueError(f"Missing graph nodes: {', '.join(sorted(missing))}")
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise GraphDependencyError("LangGraph is not installed; install the 'orchestration' optional dependency") from exc

    graph = StateGraph(LangGraphState)
    for name in required:
        graph.add_node(name, nodes[name])
    def route_preflight(state: LangGraphState) -> str:
        return "blocked" if state.get("status") == "BLOCKED" else "continue"

    def route_identity(state: LangGraphState) -> str:
        return "review" if state.get("status") == "HUMAN_REVIEW" else "continue"

    def route_validation(state: LangGraphState) -> str:
        return "blocked" if state.get("status") == "BLOCKED" else "continue"

    graph.add_edge(START, "preflight")
    graph.add_conditional_edges("preflight", route_preflight, {"continue": "input_normalizer", "blocked": END})
    graph.add_edge("input_normalizer", "company_resolver")
    graph.add_conditional_edges("company_resolver", route_identity, {"continue": "classifier", "review": END})
    graph.add_edge("classifier", "research_planner")
    graph.add_edge("research_planner", "validate")
    graph.add_conditional_edges("validate", route_validation, {"continue": "freeze", "blocked": END})
    graph.add_edge("freeze", "artifact_plan")
    graph.add_edge("artifact_plan", END)
    return graph.compile()
