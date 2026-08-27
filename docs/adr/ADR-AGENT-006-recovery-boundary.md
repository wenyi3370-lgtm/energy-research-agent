# ADR-AGENT-006: Recovery Boundary

## Status

Accepted (2026-08-25)

## Context

Naive retry loops (run the same query N times) waste budget and fake diligence.
First-round "资料有限" conclusions were previously accepted without audit.

## Decision

Recovery is strategy-driven and code-accounted:

1. `RecoveryPlanner` produces a **different** strategy (new source categories
   and new queries) from the previous round's failure, via structured LLM
   output; a deterministic source-lane rotation exists as degraded path.
2. `RecoveryLedger` counts a round only when a genuinely different query set
   actually executed (§24): adapter-level failures (ADAPTER_FAILURE,
   AUTH_REQUIRED) and identical queries consume no round. Three consecutive
   uncounted rounds block the goal instead of spinning.
3. The per-goal cap comes from `config/agent.yaml`
   (`max_recovery_rounds_per_goal`, default 10) — configuration, not a prompt
   constant. Reaching the cap produces an **Auditable Evidence Limitation**
   (`AUDITABLE_EVIDENCE_LIMITATION`), the only permitted end-state for an
   exhausted goal (§25).
4. Mission-level iteration is capped by `max_agent_iterations`.

## Consequences

- No silent data-loss declarations; every limitation carries rounds executed
  and missing evidence.
- TEST-AGENT-09/10/11/12 lock the semantics (recover-then-satisfy, no duplicate
  counting, no adapter-failure counting, config-driven cap).
