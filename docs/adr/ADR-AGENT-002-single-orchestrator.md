# ADR-AGENT-002: Why a Single Orchestrator

## Status

Accepted (2026-08-25)

## Context

Multi-agent designs (planner agent, critic agent, writer agent, reviewer agent
conversing) add coordination failure modes, unbounded token loops and
non-deterministic control flow without adding research capability. The two
capability packs are deterministic workflows, not reasoning partners.

## Decision

Exactly one `ResearchOrchestratorAgent` exists. Professional capability is
provided through `ResearchSkillPort` implementations (ENTERPRISE_RESEARCH,
OVERSEAS_MARKET_RESEARCH), which return structured `SkillRunResult` records —
never free text, never agent-to-agent conversation.

## Consequences

- No agent-to-agent message loops; all coordination is code (the orchestrator).
- Adding a domain capability means adding a port implementation, not an agent.
- The 30-iteration / 10-round budgets are enforceable in one place.
