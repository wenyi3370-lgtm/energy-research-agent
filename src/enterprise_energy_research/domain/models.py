from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .enums import (
    ArtifactStatus,
    ArtifactType,
    EnterpriseComplexity,
    ProductDashboardDecision,
    QueryStatus,
    GapStatus,
    ConflictStatus,
    RunStatus,
    Severity,
    SourceLevel,
    StatementType,
    ValidationStatus,
    ValueClass,
    VerificationStatus,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class ResearchRequest(StrictModel):
    schema_version: str = "1.0"
    request_id: str
    raw_company_name: str = Field(min_length=1)
    locale: str = "zh-CN"
    as_of_date: date | None = None
    optional_scope: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("company name must not be blank")
        return value


class Entity(StrictModel):
    entity_id: str
    canonical_name: str = Field(min_length=1)
    entity_type: Literal["company", "group", "institution", "brand", "other"] = "company"
    registered_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    former_names: list[str] = Field(default_factory=list)
    official_website: HttpUrl | None = None
    registration_region: str | None = None
    parent_entity_id: str | None = None
    actual_controller_entity_id: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    supporting_claim_ids: list[str] = Field(default_factory=list)


class CompanyCandidate(StrictModel):
    candidate_id: str
    canonical_name: str
    registered_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    official_website: HttpUrl | None = None
    registration_region: str | None = None
    parent_company: str | None = None
    actual_controller: str | None = None
    business_description: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    supporting_source_ids: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)


class CompanyResolution(StrictModel):
    raw_company_name: str
    candidates: list[CompanyCandidate]
    selected_candidate_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["RESOLVED", "HUMAN_REVIEW", "BLOCKED"]
    rationale: str

    @model_validator(mode="after")
    def validate_resolution(self) -> "CompanyResolution":
        ids = {candidate.candidate_id for candidate in self.candidates}
        if self.status == "RESOLVED" and self.selected_candidate_id not in ids:
            raise ValueError("resolved company requires a selected candidate")
        return self


class ComplexityDecision(StrictModel):
    complexity: EnterpriseComplexity
    score: int
    signals: dict[str, int] = Field(default_factory=dict)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    rationale: str
    is_legal_size_classification: Literal[False] = False


class Factory(StrictModel):
    factory_id: str
    operator_entity_id: str
    name: str | None = None
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    processes: list[str] = Field(default_factory=list)
    operating_status: str | None = None
    supporting_claim_ids: list[str] = Field(default_factory=list)


class EnterpriseEdge(StrictModel):
    edge_id: str
    from_id: str
    relation: Literal[
        "ParentCompany", "Owns", "Subsidiary", "OperatesFactory", "ProducesProduct",
        "UsesProcess", "ConsumesEnergy", "HasOpportunity", "SuitableForSolution",
        # Relationship taxonomy (P0 group boundary): UNKNOWN must never enter
        # an organization/ownership diagram — only VERIFIED structured edges do.
        "SUBSIDIARY", "CONTROLLED_BY", "JOINT_VENTURE", "OWNED_BY",
        "PARTNER", "SUPPLIER", "CUSTOMER", "LICENSEE", "UNKNOWN",
    ]
    to_id: str
    valid_from: date | None = None
    valid_to: date | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(ge=0.0, le=1.0)
    claim_ids: list[str] = Field(default_factory=list)


class Source(StrictModel):
    source_id: str
    canonical_url: HttpUrl
    source_title: str | None = None
    source_domain: str
    publisher: str | None = None
    source_level: SourceLevel
    publication_date: date | None = None
    first_retrieved_at: datetime = Field(default_factory=utc_now)
    last_retrieved_at: datetime = Field(default_factory=utc_now)
    access_status: Literal["ok", "redirected", "gone", "blocked", "auth_required", "error"] = "ok"
    content_type: str | None = None
    content_sha256: str | None = None
    grading_reason: str


class Retrieval(StrictModel):
    retrieval_id: str
    source_id: str
    adapter: Literal["kimi_webbridge", "anysearch", "fixture"]
    requested_url: HttpUrl | None = None
    final_url: HttpUrl | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    status_code: int | None = None
    raw_store_ref: str | None = None
    query_id: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class Claim(StrictModel):
    claim_id: str
    entity_id: str
    field_name: str = Field(min_length=1)
    # Canonicalized field name. ``raw_field_name`` preserves the exact
    # field name as extracted from the page before alias normalization.
    raw_field_name: str | None = None
    value: Any = None
    value_type: str
    unit: str | None = None
    currency: str | None = None
    as_of_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    scope: str | None = None
    qualifier: Literal["exact", "approximately", "at_least", "at_most", "range", "unknown"] = "unknown"
    source_id: str
    raw_text: str = Field(min_length=1)
    context_text: str = Field(min_length=1)
    locator: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=utc_now)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(ge=0.0, le=1.0)
    conflict_group_id: str | None = None
    notes: str | None = None
    # Agent integration (§20): goal-family attribution chain —
    # LLM-declared family, else the originating query's topic, else the
    # extraction-contract inverse lookup. Never a fuzzy "looks relevant".
    goal_family: str | None = None
    # Unified evidence-layer extensions (Energy Research Agent). Optional so that
    # enterprise-only evidence stays byte-compatible; populated by the market
    # evidence importer and the agent orchestrator (§19 five-boundary fields).
    mission_id: str | None = None
    goal_id: str | None = None
    subject_id: str | None = None
    subject_role: Literal["SUBJECT", "COMPETITOR", "ECOSYSTEM", "MARKET_CONTEXT", "OTHER"] | None = None
    originating_skill: str | None = None
    claim_type: str | None = None
    value_class: ValueClass | None = None
    geography: str | None = None
    source_url: HttpUrl | None = None
    source_type: str | None = None
    source_grade: str | None = None
    raw_capture_ref: str | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "Claim":
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        if self.verification_status == VerificationStatus.CONFLICTING and not self.conflict_group_id:
            raise ValueError("conflicting claims require conflict_group_id")
        return self


class ConflictGroup(StrictModel):
    conflict_group_id: str
    entity_id: str
    field_name: str
    claim_ids: list[str] = Field(min_length=2)
    analysis: dict[str, Any] = Field(default_factory=dict)
    resolution: Literal["coexist", "select_authoritative", "superseded", "unresolved"] = "unresolved"
    selected_claim_ids: list[str] = Field(default_factory=list)
    rationale: str
    status: ConflictStatus = ConflictStatus.OPEN


class DataGap(StrictModel):
    gap_id: str
    entity_id: str | None = None
    field_name: str
    importance: Literal["critical", "major", "minor"]
    reason: Literal[
        "missing", "conflicting", "stale", "unverifiable", "requires_site_due_diligence",
        # Pipeline-stage taxonomy: a gap must say WHERE the chain stopped,
        # not just that public information is missing.
        "NOT_SEARCHED",
        "SEARCH_FAILED",
        "SEARCHED_NOT_FOUND",
        "FOUND_NOT_RETRIEVED",
        "RETRIEVED_NOT_EXTRACTED",
        "EXTRACTED_NOT_NORMALIZED",
        "NORMALIZED_NOT_VERIFIED",
        "VERIFIED_NOT_SYNTHESIZED",
        "SYNTHESIZED_NOT_PUBLISHED",
        "PUBLIC_EVIDENCE_GAP",
    ]
    attempted_query_ids: list[str] = Field(default_factory=list)
    next_action: str
    status: GapStatus = GapStatus.OPEN


class ImageEvidence(StrictModel):
    image_id: str
    entity_id: str | None = None
    factory_id: str | None = None
    product_id: str | None = None
    source_url: HttpUrl
    source_page_url: HttpUrl
    source_id: str
    source_domain: str
    source_title: str | None = None
    image_type: Literal[
        "logo", "headquarters", "factory", "workshop", "office", "production_line",
        "product", "product_application", "equipment", "location", "certificate", "project", "other",
    ]
    retrieved_at: datetime = Field(default_factory=utc_now)
    sha256: str
    phash: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: str
    alt_text: str | None = None
    surrounding_text: str | None = None
    entity_match_signals: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(ge=0.0, le=1.0)
    local_asset_ref: str | None = None
    # P0 image-pipeline fields: candidate discovery → technical validation →
    # semantic verification → exact entity binding → editorial ranking → publish.
    # ``visual_verified`` is ONLY set by a vision-capable verifier looking at
    # the actual pixels; context signals alone never promote an image.
    target_entity_type: Literal[
        "factory", "product", "headquarters", "logo", "production_line",
        "workshop", "office", "equipment", "certificate", "project", "editorial", "other",
    ] | None = None
    target_entity_id: str | None = None
    visual_verified: bool = False
    semantic_score: float = Field(default=0.0, ge=0.0, le=1.0)
    visual_description: str | None = None
    publication_priority: int = Field(default=3, ge=1, le=5)
    verification_method: Literal["vision", "context", "none"] = "none"


class ProductParameter(StrictModel):
    name: str
    value: Any = None
    unit: str | None = None
    claim_ids: list[str] = Field(default_factory=list)


class Product(StrictModel):
    product_id: str
    entity_id: str
    name: str
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    # Distinct catalog level below category: one family can ship several series.
    series: str | None = None
    description: str | None = None
    parameters: list[ProductParameter] = Field(default_factory=list)
    # Real business fields; never replaced by empty placeholders.
    applications: list[str] = Field(default_factory=list)
    customer_segment: str | None = None
    commercial_status: str | None = None
    image_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class ProductDetection(StrictModel):
    has_physical_products: bool
    product_confidence: float = Field(ge=0.0, le=1.0)
    product_count: int = Field(ge=0)
    qualifying_product_ids: list[str] = Field(default_factory=list)
    dashboard_decision: ProductDashboardDecision
    reason: str
    coverage_status: Literal["COMPLETE", "PARTIAL", "NOT_ASSESSED"] = "NOT_ASSESSED"
    catalog_scope_verified: bool = False
    catalog_item_count: int = Field(default=0, ge=0)
    matched_catalog_items: list[str] = Field(default_factory=list)
    unresolved_catalog_items: list[str] = Field(default_factory=list)
    catalog_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    verified_product_count: int = Field(default=0, ge=0)
    model_level_product_count: int = Field(default=0, ge=0)
    parameterized_product_count: int = Field(default=0, ge=0)
    coverage_reason: str = "Product catalog coverage was not assessed"

    @model_validator(mode="after")
    def validate_route(self) -> "ProductDetection":
        if self.product_count != len(self.qualifying_product_ids):
            raise ValueError("product_count must match qualifying_product_ids")
        if self.dashboard_decision == ProductDashboardDecision.GENERATE and not self.has_physical_products:
            raise ValueError("product dashboard cannot be generated without physical products")
        if self.catalog_item_count != len(self.matched_catalog_items) + len(self.unresolved_catalog_items):
            raise ValueError("catalog_item_count must match resolved and unresolved catalog items")
        if self.coverage_status == "COMPLETE" and (not self.catalog_scope_verified or self.unresolved_catalog_items):
            raise ValueError("complete product coverage requires a verified catalog scope and no unresolved items")
        return self


class EnergyProfile(StrictModel):
    energy_profile_id: str
    entity_id: str
    factory_id: str | None = None
    processes: list[str] = Field(default_factory=list)
    operating_schedule: dict[str, Any] | None = None
    electricity_equipment: list[str] = Field(default_factory=list)
    gas_equipment: list[str] = Field(default_factory=list)
    steam_heat: dict[str, Any] | None = None
    compressed_air: dict[str, Any] | None = None
    chilled_water_hvac: dict[str, Any] | None = None
    transformer_load: dict[str, Any] | None = None
    roof: dict[str, Any] | None = None
    load_shape: dict[str, Any] | None = None
    field_status: dict[str, Literal["observed", "inferred", "missing", "requires_on_site_due_diligence"]] = Field(default_factory=dict)
    claim_ids: list[str] = Field(default_factory=list)


class EnterpriseGraph(StrictModel):
    entities: list[Entity] = Field(default_factory=list)
    factories: list[Factory] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    edges: list[EnterpriseEdge] = Field(default_factory=list)


class ResearchQuery(StrictModel):
    query_id: str
    entity_id: str
    topic: str
    query: str
    purpose: str
    preferred_source_levels: list[SourceLevel] = Field(default_factory=list)
    adapter_preference: Literal["anysearch", "kimi_webbridge"] = "anysearch"
    max_results: int = Field(default=5, ge=1, le=100)
    recursion_depth: int = Field(default=0, ge=0)
    requires_browser: bool = False
    collection_round: Literal["R1", "R2", "R3", "R4"] = "R1"
    round_goal: Literal["coverage", "depth", "triangulation"] = "coverage"
    high_priority: bool = True
    raw_capture_required: bool = True
    trigger: Literal["baseline", "official_discovery", "catalog_enumeration", "gap", "conflict", "triangulation", "coverage", "user_requirement"] = "baseline"
    target_gap_ids: list[str] = Field(default_factory=list)
    target_conflict_ids: list[str] = Field(default_factory=list)
    target_claim_ids: list[str] = Field(default_factory=list)
    # Three-dimensional requirement routing. Defaults keep older fixtures and
    # serialized plans compatible; planners fill all four fields explicitly.
    goal_domain: str = "general_enterprise_research"
    subject_role: Literal[
        "target_enterprise", "group_member", "competitor",
        "ecosystem_party", "public_authority", "market_context",
    ] = "target_enterprise"
    evidence_lane: Literal[
        "target", "enterprise_group", "comparison", "ecosystem", "policy_context",
    ] = "target"
    evidence_use: Literal[
        "target_fact", "target_context", "comparison_context", "relationship_context",
        "policy_context", "visual_support",
    ] = "target_fact"
    # Exact user requirement carried independently from the human-readable
    # purpose string.  Internal readiness/coverage searches leave this empty,
    # which prevents their evidence from leaking into a supplemental chapter.
    requirement_text: str | None = None
    # P0-2: goal context declared at planning time so extraction never loses it.
    canonical_company_name: str | None = None
    canonical_company_aliases: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)
    interpretation_goal: str | None = None
    evidence_patterns: list[str] = Field(default_factory=list)
    counter_evidence_patterns: list[str] = Field(default_factory=list)
    time_scope: str | None = None
    comparison_required: bool = False
    historical_required: bool = False
    status: QueryStatus = QueryStatus.PLANNED


class ResearchPlan(StrictModel):
    plan_id: str
    run_id: str
    complexity: EnterpriseComplexity
    queries: list[ResearchQuery]
    budget: dict[str, int]
    completion_contract: list[str]
    scoped_goal_families: list[str] = Field(default_factory=list)
    requires_catalog_enumeration: bool = True
    canonical_company_name: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def unique_query_ids(self) -> "ResearchPlan":
        ids = [query.query_id for query in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("research query IDs must be unique")
        if len(self.queries) > self.budget.get("max_queries", len(self.queries)):
            raise ValueError("research plan exceeds max_queries budget")
        return self


class ExtractedClaim(StrictModel):
    entity_key: str
    field_name: str
    value: Any = None
    value_type: str
    raw_text: str
    context_text: str
    unit: str | None = None
    currency: str | None = None
    as_of_date: date | None = None
    # Annual series fields (P0 third round): financial facts must carry the
    # exact reporting period so trend analysis stays claim-bound and honest.
    period_start: date | None = None
    period_end: date | None = None
    scope: str | None = None
    qualifier: Literal["exact", "approximately", "at_least", "at_most", "range", "unknown"] = "unknown"
    locator: dict[str, Any] = Field(default_factory=dict)
    # Agent integration (§20): the extraction LLM names the goal family this
    # claim belongs to, chosen from the planner's goal-family vocabulary. The
    # binding layer validates it against the plan contract deterministically.
    goal_family: str | None = None


class ExtractedEntity(StrictModel):
    entity_key: str
    canonical_name: str
    entity_type: Literal["company", "group", "institution", "brand", "other"] = "company"
    aliases: list[str] = Field(default_factory=list)
    official_website: HttpUrl | None = None
    registration_region: str | None = None
    parent_entity_key: str | None = None
    # Identity fields below may ONLY be filled when the page states them.
    registered_name: str | None = None
    headquarters: str | None = None
    founded_date: str | None = None
    parent_company: str | None = None
    actual_controller: str | None = None
    registration_identifier: str | None = None


class ExtractedFactory(StrictModel):
    factory_key: str
    operator_entity_key: str
    name: str | None = None
    address: str | None = None
    processes: list[str] = Field(default_factory=list)


class ExtractedProduct(StrictModel):
    product_key: str
    entity_key: str
    name: str
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    series: str | None = None
    description: str | None = None
    parameters: list[ProductParameter] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    customer_segment: str | None = None
    commercial_status: str | None = None
    image_key: str | None = None


class ExtractedImage(StrictModel):
    image_key: str
    entity_key: str | None = None
    factory_key: str | None = None
    product_key: str | None = None
    source_url: HttpUrl
    image_type: Literal["logo", "headquarters", "factory", "office", "production_line", "product", "location", "certificate", "project", "other"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: str
    sha256: str
    phash: str
    alt_text: str | None = None
    surrounding_text: str | None = None


class ExtractedEvidenceBatch(StrictModel):
    source_url: HttpUrl
    source_title: str | None = None
    publisher: str | None = None
    publication_date: date | None = None
    source_kind: str
    claims: list[ExtractedClaim] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    factories: list[ExtractedFactory] = Field(default_factory=list)
    products: list[ExtractedProduct] = Field(default_factory=list)
    images: list[ExtractedImage] = Field(default_factory=list)
    extraction_method: Literal["deterministic", "model_structured", "recorded_fixture"]
    retrieval_adapter: Literal["anysearch", "kimi_webbridge"] = "anysearch"
    is_search_snippet: bool = False
    # Filled by the executor after model extraction; never trusted from page
    # content. These fields provide claim-level routing lineage.
    origin_query_id: str | None = None
    origin_topic: str | None = None
    goal_domain: str | None = None
    subject_role: str | None = None
    evidence_lane: str | None = None
    evidence_use: str | None = None
    requirement_text: str | None = None


class Solution(StrictModel):
    solution_id: str
    engine: Literal[
        "EPC", "ZERO_CARBON", "STORAGE_ODM", "OVERSEAS",
        # Evidence-driven Opportunity Registry types (P0-20). Legacy values
        # above remain valid for previously frozen runs.
        "PV_EPC", "STORAGE", "V2G", "CHARGING", "ENERGY_EFFICIENCY",
        "COMPRESSED_AIR", "WASTE_HEAT", "HVAC", "GREEN_POWER",
        "ENERGY_MANAGEMENT", "CARBON_MANAGEMENT", "ZERO_CARBON_FACTORY",
        "MICROGRID", "ENERGY_DIGITALIZATION", "PRODUCT_COOPERATION",
        "JOINT_RND", "SUPPLY_CHAIN", "ODM", "CHANNEL", "OTHER",
    ]
    target_ids: list[str]
    opportunity: str
    proposed_solution: str
    business_model: str | None = None
    benefit_logic: str
    data_requirements: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_step: str
    priority: Literal["A", "B", "C", "HOLD"]
    statement_type: StatementType
    claim_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_traceability(self) -> "Solution":
        if self.statement_type == StatementType.EVIDENCE_SUPPORTED and not self.claim_ids:
            raise ValueError("evidence-supported solution requires claim_ids")
        if self.statement_type == StatementType.ANALYTICAL_INFERENCE and not self.assumptions:
            raise ValueError("analytical inference requires assumptions")
        return self


class ValidationFinding(StrictModel):
    finding_id: str
    validator: str
    severity: Severity
    code: str
    message: str
    record_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    expected: Any = None
    actual: Any = None
    remediation: str


class ValidationReport(StrictModel):
    validation_report_id: str
    run_id: str
    freeze_id: str | None = None
    status: ValidationStatus
    findings: list[ValidationFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def status_matches_findings(self) -> "ValidationReport":
        severities = {finding.severity for finding in self.findings}
        if Severity.BLOCKER in severities and self.status != ValidationStatus.BLOCKED:
            raise ValueError("blocker findings require BLOCKED status")
        if not self.findings and self.status != ValidationStatus.PASS:
            raise ValueError("empty findings require PASS status")
        return self


class DataFreeze(StrictModel):
    freeze_id: str
    run_id: str
    schema_version: str = "1.0"
    created_at: datetime = Field(default_factory=utc_now)
    evidence_version: int = Field(ge=1)
    included_record_ids: dict[str, list[str]]
    record_hashes: dict[str, str]
    root_hash: str
    validation_report_id: str
    immutable: Literal[True] = True


class ArtifactBinding(StrictModel):
    artifact_id: str
    type: ArtifactType
    status: ArtifactStatus = ArtifactStatus.PLANNED
    skip_reason: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    chart_ids: list[str] = Field(default_factory=list)
    section_bindings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_skip_reason(self) -> "ArtifactBinding":
        if self.status == ArtifactStatus.SKIPPED and not self.skip_reason:
            raise ValueError("skipped artifacts require skip_reason")
        return self


class ArtifactManifest(StrictModel):
    artifact_manifest_id: str
    run_id: str
    freeze_id: str
    artifacts: list[ArtifactBinding]
    # §37: validated sub-artifacts (e.g. overseas market Excel models, Five
    # Views reports) referenced — never re-published — by the unified plane.
    sub_artifact_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"


class RunManifest(StrictModel):
    run_id: str
    request_id: str
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.PREFLIGHT
    canonical_entity_id: str | None = None
    complexity: EnterpriseComplexity | None = None
    config_hash: str
    code_version: str
    model_gateway: dict[str, Any]
    adapter_versions: dict[str, str] = Field(default_factory=dict)
    evidence_version: int = Field(default=1, ge=1)
    freeze_id: str | None = None
    validation_status: ValidationStatus | None = None
    client_profile: dict[str, Any] | None = None
    client_profile_hash: str | None = None
    # User-request scope is separate from the commissioning client's
    # capability profile. It drives supplemental chapters and audit routing.
    research_scope: dict[str, Any] = Field(default_factory=dict)


class FrozenResearchBundle(StrictModel):
    freeze: DataFreeze
    run_manifest: RunManifest
    entities: list[Entity] = Field(default_factory=list)
    factories: list[Factory] = Field(default_factory=list)
    edges: list[EnterpriseEdge] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    retrievals: list[Retrieval] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[ConflictGroup] = Field(default_factory=list)
    gaps: list[DataGap] = Field(default_factory=list)
    images: list[ImageEvidence] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    energy_profiles: list[EnergyProfile] = Field(default_factory=list)
    solutions: list[Solution] = Field(default_factory=list)
    # Agent cross-domain findings (§35/§36). Populated by the unified publisher
    # before artifact rendering; publishers consume them unchanged.
    cross_domain_findings: list["CrossDomainFinding"] = Field(default_factory=list)


class CrossDomainFinding(StrictModel):
    """Traceable cross-domain conclusion (§36). Never a bare LLM opinion.

    Lives in the domain plane because the frozen bundle and narrative consume
    it; the agent layer imports and re-exports this model.
    """

    finding_id: str
    finding_type: Literal[
        "MARKET_FIT", "PRODUCT_FIT", "CHANNEL_FIT", "TIMING", "RISK",
        "OPPORTUNITY", "COOPERATION_POTENTIAL", "ENTRY_STRATEGY",
    ]
    statement: str = Field(min_length=1)
    enterprise_evidence_refs: list[str] = Field(default_factory=list)
    market_evidence_refs: list[str] = Field(default_factory=list)
    counter_evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    conditions: list[str] = Field(default_factory=list)
