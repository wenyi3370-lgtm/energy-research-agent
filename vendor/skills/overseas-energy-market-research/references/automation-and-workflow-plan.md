# Automation And Workflow Plan

## Architecture

Use four layers:

1. Skill: role, routing, integrity rules, and stage order.
2. Workflow: inputs, outputs, approval gates, and stop conditions.
3. Templates: evidence, assumptions, model results, and Office shells.
4. Validators: approval, sources, identifiers, reviews, parameters, models, and deliverables.

## Standard Project Files

```text
project/
  project_manifest.json
  policy_snapshot/
    collection_quantity_policy.yaml
    archive/
      v<version>_<hash>.yaml
  stage_status.json
  00_Research_Approval.csv
  00_Source_Ledger.csv
  01_Market_Scan.csv
  02_Web_Collection_Tasks.csv
  02_Competitor_List.csv
  03_Model_Identifier_Check.csv
  04_Product_Parameters.csv
  05_Pricing_Channel.csv
  06_Channel_Service.csv
  07_Raw_Reviews.csv
  08_Review_Coding.csv
  09_Integrated_Matrix.csv
  10_SWOT_Opportunity.csv
  11_Evidence_Issues.csv
  12_Model_Assumptions.csv
  13_Model_Results.csv
  14_Simulated_Modeling_Data.csv
  15_Collection_Record_Registry.csv
  stage_brief.md
  research_outline.md
  raw/
  intermediate/
    market-insight/
      market_insight_report.md
  deliverables/
```

`11_Evidence_Issues.csv` and `15_Collection_Record_Registry.csv` are internal and must not appear as visible final Excel sheets.

## Main Commands

Initialize:

```text
python scripts/run_workflow.py --project-dir <dir> --region <region> --category <category> --init
```

Record the outline and obtain explicit human approval before collection. Set the approval row to the current outline version.

Check one stage:

```text
python scripts/validate_stage_gate.py --project-dir <dir> --stage <n> --mode draft
```

Final:

```text
python scripts/run_workflow.py --project-dir <dir> --stages 0-8 --check --audit --mode final --strict-final-files
```

## Validators

- `validate_outline_approval.py`: current outline version is explicitly approved.
- `validate_collection_tasks.py`: validates the frozen quantity-policy identity, AnySearch/Kimi WebBridge task routing, three-round collection fields, and identifier requirements.
- `upgrade_collection_policy.py`: applies the current skill policy to an existing project only with explicit confirmation and an identified human approver; archives the previous YAML read-only and records version/SHA256/archive history.
- `validate_source_ledger.py`: URL/local-path traceability and derived-insight evidence IDs.
- `validate_model_identifiers.py`: exact ASIN/SKU/model/variant match.
- `validate_parameter_sources.py`: local-file priority and web-source reason.
- `validate_review_corpus.py`: raw reviews precede coding.
- `validate_collection_tasks.py`: under frozen policy v4+, a review `platform_limit` is accepted only through a project-local structured JSON that reconciles all accessible review rows, platform counts, retrieval attempts, raw captures, three-round closure, and human approval.
- `validate_collection_tasks.py`: under frozen policy v5+, every counted record must be owned by the current task in `15_Collection_Record_Registry.csv`; the registry recomputes substantive-content SHA256, blocks cross-task/file duplication, and permits later-round reuse only as verified material enrichment.
- `validate_collection_tasks.py`: under frozen policy v6+, derives source-type/platform sets from source-ledger rows actually linked by current-task records, rejects declaration mismatches and unused-source padding, and verifies review-row platform identity.
- `validate_source_ledger.py`: under frozen policy v6+, validates controlled `platform_id`, one-platform-per-root-domain, and canonical derivative platform inheritance.
- `validate_source_ledger.py`: under frozen policy v7+, validates every source type/reliability-tier combination and requires Tier 0 local evidence to resolve to a real file.
- `validate_collection_tasks.py`: under frozen policy v7+, derives the complete task-qualified primary-source set and rejects extra, missing, derivative, unverified, or incorrectly tiered declarations.
- `validate_collection_tasks.py`: under frozen policy v8+, requires each critical claim to have unique hashed text and at least two same-task registered evidence bindings with real substantive fields and an exact source-union match.
- `validate_model_integrity.py`: assumptions/results contain value class, formulas, inputs, units, sources, and checks.
- `validate_market_insight.py`: embedded Five Views method, required sections, outline version, evidence anchors, implications, and final placeholder checks.
- `validate_deliverables.py`: required stage artifacts and final Office files.

## Builders

- `build_deliverable_package.py`: copy Office shells.
- `build_stage1_market_scan_docx.py`: draft market-scan package.
- `render_charts.py`: draft evidence charts.
- `sync_csv_to_excel.py`: sync final workbook sheets with sources last.
- `build_final_report_package.py`: draft integrated files.

Builders do not replace the embedded Excel pipeline, the embedded Five Views branch, `embedded-word-production-v1`, the modeling chain, the embedded single-owner figure route (`embedded-market-figure-v1` / `embedded-modeling-figure-v1`), the formal `embedded-pptmaster-svg-v1` handwritten-SVG route, or final rendering checks. `embedded-presentation-production-v1` remains a fallback renderer only.

## Stop Conditions

- Stop collection if outline approval is missing or stale.
- Stop model-level collection if exact identifier is unresolved.
- Stop review synthesis if raw corpus is absent.
- Stop final handoff if formulas/units/sources fail or Office files do not pass visual/structural QA.

## Audit-Gap Closing Loop (v1.2.6)

When the final audit (`run_workflow.py --stages 0-8 --check --audit --mode final --strict-final-files`)
exposes tasks below their round floors:

1. Verify the shortfall is a genuine absence of public evidence: R1/R2/R3 tasks
   are completed, each has a count-evidence JSON in `audits/count_evidence/`,
   and raw captures exist.  `generate_collection_audits.py` prints `[WARN]`
   diagnostics for empty round segments instead of silently writing empty audits.
2. Register one `market_evidence_gap` row per scoped goal in
   `11_Evidence_Issues.csv` (template `assets/templates/csv/data_gaps_template.csv`),
   linking the same-scope R1/R2/R3 task IDs, `rounds_completed=1;2;3`, the three
   count-evidence JSON paths, and `remaining_high_priority_count=0`.
3. Author `audits/market_gap/GAP-xxx.json` (template
   `assets/templates/json/market_gap_evidence_template.json`) with per-round
   `attempted_queries` / `attempted_source_ids` / `failure_reasons` /
   `raw_capture_refs` — every field must reflect real collection attempts.
4. Obtain named, date-stamped human approval
   (`exception_approval_status=approved` + `exception_approved_by` /
   `exception_approval_date` / `exception_approval_message`).
5. Link the task rows in `02_Web_Collection_Tasks.csv`
   (`quantity_exception_type=market_gap`, `quantity_exception_refs=GAP-xxx`),
   re-run `generate_collection_audits.py`, then re-run the final audit.
6. R3 critical claims: under an approved market_gap exception with documented
   R3 failure reasons and zero remaining high-priority discoveries, a
   **verified saturation claim** (gap-confirmation statement) satisfies the R3
   claim gate instead of a dual-sourced triangulation claim (v1.2.6 controlled
   exemption).  This does not relax source-type/platform/primary floors — those
   must still be met with real records.

The `platform_limit` exception (reviews corpus) is separate: its evidence JSON
(`audits/platform_limit_reviews.json`) must cover **every** counted review
record of the R2 task, with per-platform URLs that exactly match source-ledger
rows and unique raw-capture references.

## Estimation Policy

Only inaccessible market observations may be kept in `11_Evidence_Issues.csv`, with `data_domain=market`. Under frozen quantity-policy v3+, a row can justify a `market_gap` quantity exception only when it links completed R1/R2/R3 tasks and their three count-audit JSON files; supplies a project-relative gap JSON with per-round queries, attempted source IDs, failure reasons, and raw captures; leaves zero high-priority discoveries; completes reason, decision impact, resolution path, owner, status, and source context; and carries named, date-stamped human approval. If a mathematical model lacks a required input:

1. Calibrate the most realistic feasible simulation from analogous official/primary evidence and physical/business constraints.
2. Create a low/base/high or quantile-based input in `12_Model_Assumptions.csv` with `value_class=simulated`.
3. Record calibration sources, method/process, parameters, bounds, correlation/time structure, fixed seed, sample size, generator code, generated data, validation, and sensitivity in `14_Simulated_Modeling_Data.csv`.
4. Keep the generated dataset at the recorded project-relative path and calculate outputs with formulas/code.
5. Obtain human approval for material calibration and simplifying assumptions.

Never silently substitute simulated data for an observation, and never label it `observed`.
