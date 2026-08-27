# ADR-AGENT-003: Overseas Skill Remains a Capability Pack

## Status

Accepted (2026-08-25)

## Context

The overseas market research skill is a complete, gated domain pipeline (stage
gates 0-8, source ledger, modeling chain, Word/Excel/PPT). Re-implementing it
inside the host repository would create a second monster workflow and break its
regression suite. A naive "copy all Python files into src/" merge (§5) is
explicitly forbidden.

## Decision

The skill is vendored under `vendor/skills/overseas-energy-market-research/`
with a pinned commit (`ccc2a18…`, v1.2.9), LICENSE + THIRD_PARTY_NOTICES +
`VENDOR_INFO.md`, and every file SHA-256-hashed in `vendor/manifest.json`
(verified by `scripts/vendor_skills.py verify`). It is reached exclusively
through `OverseasMarketResearchAdapter`, which reads structured artifacts
(ledger, journal, stage status, gap log) and maps them to `SkillRunResult` and,
via `MarketEvidenceImporter`, into the unified EvidenceStore.

Upstream files are only patched when necessary; the single applied patch
(`resolve_presentation_images.py` statement-order fix) is recorded in
`VENDOR_INFO.md`.

## Consequences

- Upstream regression suite keeps running unmodified (14/14 offline).
- Domain rules (market routing, modeling gates) stay with the domain owner.
- Upgrade path: re-vendor a newer commit, drop recorded patches if upstream fixed them, regenerate the manifest.
