# ADR-AGENT-001: Why Agentic Workflow

## Status

Accepted (2026-08-25)

## Context

The repository grew two production loops (`OrchestratingExecutor.research_and_validate`,
`AdaptiveResearchRunner.run`) and a keyword/if-chain patch debt (see
`docs/agent/PATCH_DEBT_AUDIT.md`). Every new user requirement (competition, policy,
channel, continuation, custom goals) had to be anticipated as a code branch. User
requests that did not match a branch degraded silently. Two separate capability
repositories (enterprise research, overseas market research) could not be combined
without a new mega-workflow.

## Decision

Add a single **Research Orchestrator Agent** control layer (`src/enterprise_energy_research/agent/`)
that owns understanding, goal decomposition, skill routing, gap reasoning, recovery
planning and cross-domain synthesis, while deterministic skills own execution, gates,
budgets, IDs and audits.

The invariant is: **LLM owns uncertainty; code owns determinism.**

## Consequences

- New request shapes become data (goals), not code branches.
- Every agent decision is structured (Pydantic/JSON Schema via ModelGateway) and auditable.
- Risks: higher token cost (measured via CountingGateway/AgentCostRecord); LLM routing
  errors are mitigated by code-side boundary overrides (subject integrity) and
  deterministic fallbacks that are explicitly marked `keyword_fallback`.
