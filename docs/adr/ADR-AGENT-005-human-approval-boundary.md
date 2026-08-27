# ADR-AGENT-005: Human Approval Boundary

## Status

Accepted (2026-08-25)

## Context

The overseas skill requires `00_Research_Approval.csv` before collection; the
host portal required a parse-confirm step before research. An agent that could
approve itself would nullify both gates.

## Decision

One **Unified Research Mission Approval** replaces both. Before execution the
portal/API shows subject, mode, core/custom/market goals, routing, geography,
time scope and deliverables (business language only). Approval is recorded as
`MissionApproval` (never by the agent) and — when the overseas skill runs — the
adapter additionally requires the skill's own approved record
(`00_Research_Approval.csv`); unapproved execution returns BLOCKED/
AUTH_REQUIRED (§27/§28).

Follow-up requests inside an approved mission's scope need no new approval; a
material scope change (new geography / mode change) resets approval to PENDING.

## Consequences

- `parse_and_plan` can never reach execution without an external approver.
- Every approval is durably stored (`MissionStore.approvals`) and auditable.
- TEST-AGENT-08 locks this boundary.
