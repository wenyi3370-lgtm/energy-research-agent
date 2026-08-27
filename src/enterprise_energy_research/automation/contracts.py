"""Machine-readable input/output contracts for the automation layer (Phase 1).

These models are the stable boundary between external triggers (n8n
webhooks, Feishu forms, future schedulers) and the research pipeline.
Downstream workflow steps must consume :class:`ResearchResult` fields
directly instead of parsing natural-language status text.

The automation :class:`ResearchRequest` is task-level (business user
oriented); it maps onto the existing domain ``ResearchRequest`` consumed
by the research kernel via :meth:`ResearchRequest.to_domain_request`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..domain.enums import ArtifactStatus, ArtifactType, ValidationStatus
from ..domain.models import ResearchRequest as DomainResearchRequest
from ..domain.models import StrictModel, utc_now
from .enums import AdoptionStatus, Priority, ResearchType, ReviewDecision, RiskLevel, TaskStatus


class ResearchRequest(StrictModel):
    """Task-level research request submitted by a business user."""

    schema_version: str = "1.0"
    task_id: str = Field(min_length=1)
    idempotency_key: str | None = None
    requested_by: str = Field(min_length=1)
    country: str | None = None
    region: str | None = None
    company: str | None = None
    product: str | None = None
    research_type: ResearchType
    topics: list[str] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    deadline: datetime | None = None
    language: str = "zh-CN"
    notes: str | None = None

    @field_validator("task_id", "requested_by")
    @classmethod
    def collapse_whitespace(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, value: list[str]) -> list[str]:
        return [" ".join(topic.split()) for topic in value if topic.split()]

    @model_validator(mode="after")
    def require_research_subject(self) -> "ResearchRequest":
        if not (self.company or self.country or self.product):
            raise ValueError(
                "at least one of company, country or product is required"
            )
        return self

    def to_domain_request(self, request_id: str) -> DomainResearchRequest:
        """Map onto the domain ``ResearchRequest`` consumed by the kernel.

        The research kernel is company-centric. For market-level tasks
        without a company (e.g. "Thailand Residential BESS market entry"),
        a synthetic market subject is built from country/region/product so
        the kernel receives a non-blank ``raw_company_name``; the full task
        context is preserved in ``optional_scope``. How the planner and
        query matrix treat market-level subjects is an orchestration
        concern handled in a later phase, not here.
        """
        if self.company:
            subject = self.company
        else:
            parts = [part for part in (self.country, self.region, self.product) if part]
            subject = " ".join(parts) + " market"
        return DomainResearchRequest(
            request_id=request_id,
            raw_company_name=subject,
            locale=self.language,
            optional_scope={
                "task_id": self.task_id,
                "research_type": str(self.research_type),
                "country": self.country,
                "region": self.region,
                "product": self.product,
                "topics": list(self.topics),
                "notes": self.notes,
            },
        )


class CostMetrics(StrictModel):
    """Token/cost accounting for one run; populated by the gateway wrapper."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    search_calls: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class ArtifactRef(StrictModel):
    """Lightweight pointer to a published artifact (Word/Excel/PPT/HTML)."""

    artifact_type: ArtifactType
    status: ArtifactStatus
    location: str | None = None


class ResearchError(StrictModel):
    """Structured failure detail; ``retryable`` drives the retry policy."""

    error_type: str = Field(min_length=1)
    message: str = ""
    failed_step: str | None = None
    retryable: bool = False


class ReviewSubmission(StrictModel):
    """Human review decision submitted at the REVIEW_REQUIRED gate.

    ``original_value``/``modified_value`` carry the before/after of any
    edited field so every human edit is auditable.
    """

    reviewer: str = Field(min_length=1)
    decision: ReviewDecision
    reason: str = ""
    original_value: dict[str, Any] | None = None
    modified_value: dict[str, Any] | None = None

    @model_validator(mode="after")
    def edit_requires_values(self) -> "ReviewSubmission":
        if self.decision == ReviewDecision.EDIT_AND_APPROVE and not self.modified_value:
            raise ValueError("EDIT_AND_APPROVE requires modified_value")
        return self


class FeishuFormPayload(StrictModel):
    """Feishu form / Bitable row mapped to a research task trigger (Phase 7).

    Field names are the ones n8n/Feishu webhooks are expected to send; the
    mapping into a full :class:`ResearchRequest` is explicit so the trigger
    path is auditable end to end.
    """

    requested_by: str = Field(min_length=1)
    country: str | None = None
    region: str | None = None
    company: str | None = None
    product: str | None = None
    research_type: ResearchType = ResearchType.MARKET_ENTRY
    topics: list[str] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    deadline: datetime | None = None
    language: str = "zh-CN"
    notes: str | None = None
    task_id: str | None = None

    def to_research_request(self) -> ResearchRequest:
        from ..domain.ids import new_sortable_id

        return ResearchRequest(
            task_id=self.task_id or new_sortable_id("TASK"),
            idempotency_key=None,
            requested_by=self.requested_by,
            country=self.country,
            region=self.region,
            company=self.company,
            product=self.product,
            research_type=self.research_type,
            topics=self.topics,
            priority=self.priority,
            deadline=self.deadline,
            language=self.language,
            notes=self.notes,
        )


class FeedbackPayload(StrictModel):
    """Requester feedback submitted after delivery (Phase 11 ROI input)."""

    submitted_by: str = Field(min_length=1)
    adoption_status: AdoptionStatus | None = None
    user_rating: int | None = Field(default=None, ge=1, le=5)
    manual_baseline_minutes: float | None = Field(default=None, ge=0.0)
    human_review_minutes: float | None = Field(default=None, ge=0.0)
    human_edit_count: int | None = Field(default=None, ge=0)
    comment: str | None = None


class ConflictResolutionPayload(StrictModel):
    """Human adjudication of a BLOCKING evidence conflict (冲突裁决).

    ``decision`` mirrors ``ConflictGroup.resolution``: coexist (keep both),
    select_authoritative (pick one claim) or superseded (both replaced by
    later evidence). ``select_authoritative`` requires ``selected_claim_id``.
    """

    reviewer: str = Field(min_length=1)
    decision: Literal["coexist", "select_authoritative", "superseded"]
    rationale: str = ""
    selected_claim_id: str | None = None


class NaturalLanguagePrompt(StrictModel):
    """自然语言调研需求（AI 解析为结构化 ResearchRequest）。"""

    prompt: str = Field(min_length=4)
    requested_by: str = Field(default="portal-user", min_length=1)


class DeepResearchPayload(StrictModel):
    """继续深度研究：在已有报告上补充/修改，完善报告、HTML 与 Excel 数据。

    ``requirements`` 直接使用自然语言（分条写更好）；系统按关键词路由
    到财务/产品/基地/能源/图片等主题并定向检索。

    ``run_dir`` 可选：指向该 run 的产物目录（如
    ``build/live_acceptance/宁德时代-20260822-r3``）；缺省时在自动化
    workdir 与 live_acceptance 中按 run_id 自动定位最新的证据库。

    ``save_to_desktop``：完成后把 Word/HTML/Excel 复制到宿主机桌面
    （容器需挂载 /desktop，见 docker-compose.yml）。

    ``notify_feishu``：完成后推送飞书（文本 + 成果文件），与主调查
    流程一致；未配置 EER_FEISHU_* 时自动降级为不推送。
    """

    requirements: str = Field(min_length=2, max_length=4000)
    requested_by: str = Field(default="portal-user", min_length=1)
    run_dir: str | None = None
    company: str | None = None
    include_images: bool = True
    save_to_desktop: bool = False
    notify_feishu: bool = True
    # Wall-clock budget for the whole recovery loop.  Evidence-absent gaps
    # can stall the loop for hours; the budget guarantees a graceful
    # terminal state (time_budget_exhausted) with all evidence retained.
    time_budget_minutes: int = Field(default=90, ge=5, le=1440)
    # When the recovery loop ends without passing the formal-publication
    # gate (evidence absent from public channels / budget exhausted),
    # publish a CONDITIONAL report from the verified evidence with a
    # prominent caveat banner and the blocking-gap register, instead of
    # leaving the run BLOCKED with no deliverables.  No fabricated facts:
    # every published claim still comes from frozen, verified evidence.
    publish_conditional: bool = True


class NaturalResearchRequest(StrictModel):
    """LLM 从自然语言解析出的调研参数（全部可选，由解析器兜底）。"""

    company: str | None = None
    country: str | None = None
    region: str | None = None
    product: str | None = None
    research_type: ResearchType | None = None
    topics: list[str] = Field(default_factory=list)
    priority: Priority | None = None
    notes: str | None = None


class ResearchResult(StrictModel):
    """Structured run outcome consumed by n8n / Feishu / API callers."""

    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: TaskStatus
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    validation_status: ValidationStatus | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: RiskLevel | None = None
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    gap_count: int = Field(default=0, ge=0)
    artifact_manifest: list[ArtifactRef] = Field(default_factory=list)
    cost_metrics: CostMetrics = Field(default_factory=CostMetrics)
    error: ResearchError | None = None
