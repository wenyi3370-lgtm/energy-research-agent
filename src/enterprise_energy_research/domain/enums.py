from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RunStatus(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    RUNNING = "RUNNING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED = "BLOCKED"
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"


class EnterpriseComplexity(StrEnum):
    GROUP_LARGE = "GROUP_LARGE"
    ENTERPRISE_NORMAL = "ENTERPRISE_NORMAL"
    SMALL_SIMPLE = "SMALL_SIMPLE"
    UNKNOWN = "UNKNOWN"


class SourceLevel(StrEnum):
    SOURCE_A = "SOURCE_A"
    SOURCE_B = "SOURCE_B"
    SOURCE_C = "SOURCE_C"
    SOURCE_D = "SOURCE_D"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    CONFLICTING = "CONFLICTING"
    REJECTED = "REJECTED"
    STALE = "STALE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class StatementType(StrEnum):
    EVIDENCE_SUPPORTED = "EVIDENCE_SUPPORTED"
    ANALYTICAL_INFERENCE = "ANALYTICAL_INFERENCE"
    TO_BE_CONFIRMED = "TO_BE_CONFIRMED"


class ValueClass(StrEnum):
    """Unified evidence value class (Agent integration, §19).

    Superset of the overseas market skill's ledger vocabulary:
    observed -> OBSERVED, derived -> DERIVED, modeled_estimate -> MODEL_ESTIMATE,
    simulated -> SIMULATED, scenario_assumption -> ASSUMPTION,
    pending_verification -> TO_BE_CONFIRMED.
    """

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    MODEL_ESTIMATE = "MODEL_ESTIMATE"
    SIMULATED = "SIMULATED"
    ASSUMPTION = "ASSUMPTION"
    TO_BE_CONFIRMED = "TO_BE_CONFIRMED"


class ValidationStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKER = "BLOCKER"


class ArtifactType(StrEnum):
    EXCEL = "excel"
    WORD = "word"
    ENTERPRISE_HTML = "enterprise_html"
    PRODUCT_HTML = "product_html"
    PPT = "ppt"


class ArtifactStatus(StrEnum):
    PLANNED = "PLANNED"
    SKIPPED = "SKIPPED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ProductDashboardDecision(StrEnum):
    GENERATE = "GENERATE"
    SKIP_PRODUCT_DASHBOARD = "SKIP_PRODUCT_DASHBOARD"
    BLOCKED = "BLOCKED"


class QueryStatus(StrEnum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    RESOLVED = "RESOLVED"
    BLOCKING = "BLOCKING"


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    BLOCKING = "BLOCKING"
