# Enterprise Energy Research v0.9.0 implementation status

`pyproject.toml` is the single version source. Work is organized by quality gates rather than historical phase numbers.

## AGENT — Energy Research Agent fusion (2026-08-25)

- [x] Baseline audit: both repos pinned (enterprise `52d3d14`, overseas `ccc2a18` v1.2.9).
- [x] Overseas skill vendored with commit pin + manifest hashing (24594 files verified).
- [x] ResearchMission / ResearchGoal / dynamic custom goals / MissionParser / GoalPlanner.
- [x] ResearchSkillRouter (LLM classification + code-side boundary enforcement).
- [x] EnterpriseResearchSkill + OverseasMarketResearchAdapter (ResearchSkillPort).
- [x] Orchestrator loop: execute → ingest → evaluate → recovery (executed-round accounting, config-driven cap) → synthesis.
- [x] MarketEvidenceImporter: overseas ledger → unified EvidenceStore with subject isolation.
- [x] CrossDomainSynthesisEngine with traceable findings.
- [x] API + /agent portal + unified mission approval + agent trace store.
- [x] Schemas: research-mission / research-goal / routing-decision / skill-run-result / goal-evaluation / recovery-plan.
- [x] TEST-AGENT-01..15 + hybrid golden (19 offline tests).

## P0 — evidence correctness and saturation

- AnySearch JSON and Markdown parsing paths are reachable and covered by regression tests.
- Research requests decompose into enterprise Goal Families.
- R1 performs official-source coverage; R2 accepts Evidence Gap records; R3 accepts ConflictGroup/critical-claim targets.
- Saturation is evaluated per goal using completed rounds, two final low-yield batches, critical gaps, unexpanded discoveries and triangulation.
- `research_quality.json` exposes coverage, source, verification, catalog, parameter, image, gap, conflict and saturation metrics.

## P1 — formal publication

- Word retains the evidence-first report pipeline and raises the gate to 15 formal figures, five visual families for ten or more visuals, 45% maximum bar-family share and 100% core-chapter visual coverage.
- `visual_manifest.json` carries claim IDs, source IDs, analytical class and Word/HTML/PPT targets.
- `enterprise_research_dashboard.html` combines management overview, report visualization, company/factory gallery and product intelligence database in one offline file.
- Image discovery, evidence and publication manifests remain distinct; publication revalidates local binary hash, MIME and dimensions and deduplicates exact/perceptual matches.

## P2 — QA, eval and deployment

- Recorded research eval and a fixed five-company live-acceptance panel are versioned under `evals/`.
- CI runs unit/integration/fixture tests, automation eval, vendor verification, schema parsing and Docker build.
- HTML QA requires screenshots at 360/768/1440/1920 px; static inspection alone cannot pass.
- Word QA inspects rendered PDF for blank pages, oversized whitespace and clipped blocks.
- PostgreSQL production credentials must come from `.env`/secret injection; n8n uses a pinned image.

## Remaining acceptance condition

A formal release is complete only after a live company run produces all seven output directories and the research, visual, image, validation and cross-artifact reports pass. Adapter unavailability, missing credentials, missing benchmark binaries or unrendered Word/HTML artifacts must be reported as blockers, not converted to success.

## P0 decision-intelligence refactor status

- [x] ClientProfile configuration, status taxonomy and RunManifest snapshot.
- [x] StrategicInterpretation models/engine with evidence lineage and competition/customer/risk gates.
- [x] CooperationHypothesis contract with priority/potential/rejected outcomes.
- [x] Business-led 30/60/90 and single PublicationNarrative 4.0 for Word/HTML.
- [x] Latest valid KPI selection, honest source-grade labels and gap deduplication.
- [x] DecisionIntelligenceValidator and focused regression suite.
- [x] Full recorded regression, recorded eval, render QA and live CATL acceptance passed on 2026-08-23. The final CATL run used direct network mode (proxy variables cleared), froze 227 verified used claims under `FREEZE-01M0Q8T8E4JDTGPMG5JE4FC60K`, published six distinct official-site product images, passed Word/HTML QA with zero errors, and retained only two explicitly disclosed medium-priority evidence gaps.
- [x] Plain-business-language publication pass completed on 2026-08-23: removed framework recitals and abstract gate chains from Word/HTML, added fail-closed AI-tone regression checks, filtered negative/mitigation disclosures from enterprise risks, and separated public factory records from independently verified physical sites.
