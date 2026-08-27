# ADR-AGENT-004: Unified Evidence Ownership

## Status

Accepted (2026-08-25)

## Context

Two evidence vocabularies existed: the host's Claim/Source store and the
overseas skill's CSV ledger (`value_class`: observed/derived/modeled_estimate/
scenario_assumption/simulated/pending_verification). Without a single owner,
HYBRID reports would stitch two incompatible evidence sets and cross-domain
conclusions would be untraceable.

## Decision

The host `EvidenceStore` is the single evidence plane. `Claim` gained additive,
optional unified fields (mission_id/goal_id/subject_id/subject_role/
originating_skill/claim_type/value_class/geography/source_url/source_type/
source_grade/raw_capture_ref). The value-class map lives in
`config/agent.yaml` (observed→OBSERVED, derived→DERIVED,
modeled_estimate→MODEL_ESTIMATE, simulated→SIMULATED,
scenario_assumption→ASSUMPTION, pending_verification→TO_BE_CONFIRMED; anything
unknown imports as TO_BE_CONFIRMED, never dropped).

Five-boundary subject isolation (§14): evidence binds to a goal only via
explicit `goal_id`; competitor rows bind to `competitor:<name>` entities and
carry `subject_role=COMPETITOR`, so they can never pollute target-enterprise
facts. Conflicts are preserved as separate records — nothing auto-overwrites.

## Consequences

- Existing enterprise evidence stays byte-compatible (all new fields optional).
- Cross-domain synthesis reads only VERIFIED claims with resolvable refs.
- Modeling artifacts (MODEL_ESTIMATE/SIMULATED/ASSUMPTION) keep their own
  audited chain and are not duplicated as claims.
