# Data schema

## 1. Schema principles

- Use immutable stable IDs and explicit schema versions.
- Distinguish observed evidence, normalized facts, analysis and publication bindings.
- Store `null` for missing values; publishers render `—`.
- Store value, unit, date, scope and qualifier separately.
- Preserve all conflicting claims and raw contexts.
- Use ISO 8601 timestamps in UTC and record source publication dates separately.

## 2. ID formats

| Object | Format | Example |
|---|---|---|
| Run | `RUN-{date}-{ulid}` | `RUN-20260813-01K...` |
| Entity | `ENT-{ulid}` | `ENT-01K...` |
| Subsidiary | Entity ID + role | Use `ENT-*`, not a duplicate ID namespace |
| Factory | `FAC-{ulid}` | `FAC-01K...` |
| Product | `PROD-{ulid}` | `PROD-01K...` |
| Claim | `CLAIM-{000000}` within run | `CLAIM-000124` |
| Source | `SOURCE-S{000}` within run | `SOURCE-S023` |
| Image | `IMAGE-I{000}` within run | `IMAGE-I008` |
| Chart | `CHART-C{000}` within run | `CHART-C014` |
| Freeze | `FREEZE-{ulid}` | `FREEZE-01K...` |

Keep legacy short citations such as `[S023]` as a display alias of `SOURCE-S023`.

## 3. Core records

### Research request and run

```yaml
ResearchRequest:
  schema_version: "1.0"
  request_id: REQ-...
  raw_company_name: string
  locale: zh-CN
  as_of_date: date|null
  optional_scope: object

RunManifest:
  run_id: RUN-...
  request_id: REQ-...
  created_at: datetime
  completed_at: datetime|null
  status: enum
  canonical_entity_id: ENT-...|null
  complexity: enum|null
  config_hash: sha256
  code_version: string
  model_gateway: {primary_provider, fallback_provider, model_names}
  adapter_versions: object
  evidence_version: integer
  freeze_id: FREEZE-...|null
  validation_status: PASS|PASS_WITH_WARNINGS|BLOCKED|null
```

### Entity and enterprise graph

```yaml
Entity:
  entity_id: ENT-...
  canonical_name: string
  entity_type: company|group|institution|brand|other
  registered_name: string|null
  aliases: [string]
  former_names: [string]
  official_website: uri|null
  registration_region: string|null
  parent_entity_id: ENT-...|null
  actual_controller_entity_id: ENT-...|null
  verification_status: enum
  supporting_claim_ids: [CLAIM-...]

Factory:
  factory_id: FAC-...
  operator_entity_id: ENT-...
  name: string|null
  address: string|null
  geo: {lat: number|null, lon: number|null}
  processes: [string]
  operating_status: string|null
  supporting_claim_ids: [CLAIM-...]

EnterpriseEdge:
  edge_id: EDGE-...
  from_id: string
  relation: ParentCompany|Owns|Subsidiary|OperatesFactory|ProducesProduct|UsesProcess|ConsumesEnergy|HasOpportunity|SuitableForSolution
  to_id: string
  valid_from: date|null
  valid_to: date|null
  verification_status: enum
  confidence: number
  claim_ids: [CLAIM-...]
```

### Sources and retrievals

```yaml
Source:
  source_id: SOURCE-S...
  canonical_url: uri
  source_title: string|null
  source_domain: string
  publisher: string|null
  source_level: SOURCE_A|SOURCE_B|SOURCE_C|SOURCE_D
  publication_date: date|null
  first_retrieved_at: datetime
  last_retrieved_at: datetime
  access_status: ok|redirected|gone|blocked|auth_required|error
  content_type: string|null
  content_sha256: sha256|null
  grading_reason: string

Retrieval:
  retrieval_id: RET-...
  source_id: SOURCE-S...
  adapter: kimi_webbridge|anysearch
  requested_url: uri
  final_url: uri|null
  retrieved_at: datetime
  status_code: integer|null
  raw_store_ref: string|null
  query_id: QUERY-...|null
  diagnostics: object
```

### Evidence claims

```yaml
Claim:
  claim_id: CLAIM-...
  entity_id: ENT-...
  field_name: string
  value: scalar|object|array|null
  value_type: string
  unit: string|null
  currency: string|null
  as_of_date: date|null
  period_start: date|null
  period_end: date|null
  scope: string|null
  qualifier: exact|approximately|at_least|at_most|range|unknown
  source_id: SOURCE-S...
  raw_text: string
  context_text: string
  locator: {page: integer|null, section: string|null, selector: string|null}
  retrieved_at: datetime
  verification_status: UNVERIFIED|VERIFIED|CONFLICTING|REJECTED|STALE
  confidence: number
  conflict_group_id: CONFLICT-...|null
  notes: string|null
```

Core fields may be represented by multiple claims. A derived `FactView` selects or groups them only after validation and retains the source claim IDs.

### Conflicts and gaps

```yaml
ConflictGroup:
  conflict_group_id: CONFLICT-...
  entity_id: ENT-...
  field_name: string
  claim_ids: [CLAIM-...]
  analysis: {period_difference, scope_difference, definition_difference, source_rank_difference}
  resolution: coexist|select_authoritative|superseded|unresolved
  selected_claim_ids: [CLAIM-...]
  rationale: string
  status: OPEN|RESOLVED|BLOCKING

DataGap:
  gap_id: GAP-...
  entity_id: ENT-...|null
  field_name: string
  importance: critical|major|minor
  reason: missing|conflicting|stale|unverifiable|requires_site_due_diligence
  attempted_query_ids: [QUERY-...]
  next_action: string
  status: OPEN|ACCEPTED|RESOLVED|BLOCKING
```

### Images

```yaml
ImageEvidence:
  image_id: IMAGE-I...
  entity_id: ENT-...|null
  factory_id: FAC-...|null
  product_id: PROD-...|null
  source_url: uri
  source_page_url: uri
  source_id: SOURCE-S...
  source_domain: string
  source_title: string|null
  image_type: logo|factory|office|production_line|product|location|certificate|other
  retrieved_at: datetime
  sha256: sha256
  phash: string
  width: integer
  height: integer
  mime_type: string
  alt_text: string|null
  surrounding_text: string|null
  entity_match_signals: [string]
  verification_status: UNVERIFIED|VERIFIED|REJECTED|REVIEW_REQUIRED
  confidence: number
  local_asset_ref: string|null
```

`local_asset_ref` is a run-relative path to an archived binary, not a remote URL. It is mandatory for every image bound to a formal product dashboard. The resolved file must exist inside the run/package boundary and its bytes must reproduce the ledger `sha256`, `mime_type`, `width` and `height`; otherwise the image remains evidence-only and is not artifact-ready.

### Products

```yaml
Product:
  product_id: PROD-...
  entity_id: ENT-...
  name: string
  brand: string|null
  model: string|null
  category: string|null
  description: string|null
  parameters:
    - {name: string, value: scalar|null, unit: string|null, claim_ids: [CLAIM-...]}
  image_id: IMAGE-I...|null
  source_ids: [SOURCE-S...]
  verification_status: enum

ProductDetection:
  has_physical_products: boolean
  product_confidence: number
  product_count: integer
  qualifying_product_ids: [PROD-...]
  dashboard_decision: GENERATE|SKIP_PRODUCT_DASHBOARD|BLOCKED
  reason: string
  coverage_status: COMPLETE|PARTIAL|NOT_ASSESSED
  catalog_scope_verified: boolean
  catalog_item_count: integer
  matched_catalog_items: [string]
  unresolved_catalog_items: [string]
  catalog_coverage_ratio: number
  verified_product_count: integer
  model_level_product_count: integer
  parameterized_product_count: integer
  coverage_reason: string
```

For a formal product dashboard, `qualifying_product_ids` may include only products whose `image_id` resolves to a `VERIFIED` image with a valid `local_asset_ref`. Dashboard image coverage is therefore 100% by construction; remote-only image evidence produces a gap or `BLOCKED` decision.

Represent the catalog boundary as a verified `Claim(field_name="product_catalog_scope")` containing `official_product_centers`, `enumerated`, `enumerated_at`, `enumeration_method` and `catalog_items`. Product-center navigation establishes the inventory boundary; detail pages establish model and parameter evidence.

### Energy and solutions

```yaml
EnergyProfile:
  entity_id: ENT-...
  factory_id: FAC-...|null
  processes: []
  operating_schedule: object|null
  electricity_equipment: []
  gas_equipment: []
  steam_heat: object|null
  compressed_air: object|null
  chilled_water_hvac: object|null
  transformer_load: object|null
  roof: object|null
  load_shape: object|null
  field_status: object
  claim_ids: [CLAIM-...]

Solution:
  solution_id: SOL-...
  engine: EPC|ZERO_CARBON|STORAGE_ODM|OVERSEAS
  target_ids: [string]
  opportunity: string
  proposed_solution: string
  business_model: string|null
  benefit_logic: string
  data_requirements: [string]
  risks: [string]
  next_step: string
  priority: A|B|C|HOLD
  statement_type: EVIDENCE_SUPPORTED|ANALYTICAL_INFERENCE|TO_BE_CONFIRMED
  claim_ids: [CLAIM-...]
  assumptions: [string]
```

### Freeze and artifact manifest

```yaml
DataFreeze:
  freeze_id: FREEZE-...
  run_id: RUN-...
  schema_version: "1.0"
  created_at: datetime
  evidence_version: integer
  included_record_ids: object
  record_hashes: object
  root_hash: sha256
  validation_report_id: VAL-...
  immutable: true

ArtifactManifest:
  artifact_manifest_id: AM-...
  run_id: RUN-...
  freeze_id: FREEZE-...
  artifacts:
    - artifact_id: ART-...
      type: excel|word|enterprise_html|product_html|ppt
      status: PLANNED|SKIPPED|PUBLISHED|FAILED
      skip_reason: string|null
      claim_ids: [CLAIM-...]
      image_ids: [IMAGE-I...]
      chart_ids: [CHART-C...]
      section_bindings: object
```

## 4. Collection saturation audit

```yaml
CollectionAttemptSummary:
  goal_family: string
  round: R1|R2|R3
  batch_id: string
  attempted_queries: integer
  unique_sources: integer
  source_types: [string]
  fulltext_captures: integer
  material_records: integer
  critical_claim_count: integer
  independently_verified_critical_claim_count: integer
  authoritative_critical_claim_count: integer
  inspected_sources: integer
  new_high_priority_ids: [string]
  raw_capture_refs: [path]
  failure_reasons: [string]

SaturationAssessment:
  status: SATURATED|PARTIAL|BLOCKED
  marginal_high_priority_yield: number
  missing_rounds: object
  findings: [string]
```

The attempt journal and assessment are internal audit records. The final artifact may summarize disclosed gaps, but must not expose operational credentials or browser state.

## 5. Export contract

Export deterministic UTF-8 files with stable ordering:

- `facts.json`: validated fact views plus source claim IDs;
- `sources.jsonl`: one source per line;
- `images.jsonl`: one image ledger record per line;
- `enterprise_graph.json`: entities and edges;
- `products.json`, `energy_profile.json`, `solutions.json`;
- `run_manifest.json`, `artifact_manifest.json`;
- `validation_report.json`.

Never export credentials, session cookies, raw authorization headers or unrestricted personal data.

## Decision-intelligence DTOs

- `RunManifest.client_profile/client_profile_hash`: frozen commissioning-party configuration.
- `ClientProfile -> ClientCapability[]`: capability status is VERIFIED, CONFIGURED, ASSUMED or UNKNOWN; verified capabilities require evidence refs.
- `StrategicInterpretation`: trajectories, turning points, drivers, priorities, competitive positions, customer/market proof, dependencies, enterprise risks, scenarios and decision saturation.
- `InterpretationLineage`: claim/source IDs, reasoning and counterevidence claim IDs for every interpretation.
- `CooperationHypothesis`: target problem, why now, client capability match/status, value logic, target department, recommended action, evidence/counterevidence, assumptions, disconfirming conditions, rejection reasons and status.
- `ResearchNarrative` 4.0 is the shared PublicationNarrative. Full `DueDiligenceRequirement[]` remains appendix-owned; the body may show only decision-changing unknowns.
