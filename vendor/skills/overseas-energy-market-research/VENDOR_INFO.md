# Vendored Capability Pack — overseas-energy-market-research-skill

- **Origin**: https://github.com/wenyi3370-lgtm/overseas-energy-market-research-skill
- **Pinned commit**: `ccc2a18b484efad919031a6b935021e67a0cb8f2` (tag/release marker: v1.2.9, 2026-08-12)
- **License**: Apache License 2.0 (see `LICENSE`); third-party components documented in `THIRD_PARTY_NOTICES.md`
- **Vendored by**: Energy Research Agent integration (`energy-research-agent`), 2026-08-25
- **Integrity**: every file in this snapshot is SHA-256 hashed in `vendor/manifest.json`;
  run `python scripts/vendor_skills.py verify` from the repository root to verify.

## Role

Domain Capability Pack for overseas energy market research: market sizing, policy, tariffs,
certification, channels, competition, product benchmarking, economics (NPV/IRR/Payback),
Five Views, modeling chain, and Word/Excel/PPT deliverables. Executed by the Agent layer
through `OverseasMarketResearchAdapter` (see `src/energy_research_agent/agent/tools/`),
never mutated by the host except as documented below.

## Applied patches (do not remove without re-checking)

| File | Upstream defect | Patch | Reason |
|---|---|---|---|
| `scripts/resolve_presentation_images.py` | `output_manifest` referenced before assignment (UnboundLocalError at manifest build) | Reorder two statements: assign `output_manifest` before building the manifest dict | The skill's own `regression_test_ppt_delivery.py` cannot pass in any environment without this fix. Pure ordering fix, no behavior change. |

When upgrading this snapshot to a newer upstream commit, re-run the skill's 14 offline
regression scripts (`scripts/regression_test_*.py`) and drop this patch if upstream fixed it.

## Runtime notes

- No bundled secrets; external services (AnySearch API, Kimi WebBridge daemon, LibreOffice,
  EWO image service) remain outside the snapshot.
- `scripts/anysearch/` text files are stored with LF line endings; Windows checkouts must not
  convert them to CRLF or the embedded-CLI hash regression will fail (see integration baseline).
