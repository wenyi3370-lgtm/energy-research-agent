from __future__ import annotations

import json
from typing import Any

from enterprise_energy_research.adapters.base import SearchResultEnvelope
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch
from enterprise_energy_research.gateway.base import GatewayError, ModelGateway, StructuredRequest

from .contracts import contract_for

GOAL_PROMPT_TEMPLATE = """CURRENT RESEARCH GOAL:
{goal_family}

RESEARCH QUESTION:
{business_question}

EXPECTED FIELDS:
{expected_fields}

PRIORITY:
优先提取与本研究问题直接有关的明确事实。

SECONDARY:
页面中存在其他重大企业事实时也允许提取。

RULE:
不得推测页面未明确披露的信息。

PERIOD RULE（重要）：
对营业收入、归母净利润、毛利率、研发投入、研发费用率、经营现金流等
财务类字段，若页面明确写出"2023年度""2024年"等报告期间，
必须在 Claim 的 period_start / period_end 中按"YYYY-01-01"与
"YYYY-12-31"写明该报告年度（日历年度口径）；无法判断具体年度的
才允许留空。单点营销数字（服务热线、服务站数量、页面计数等）
不是财务事实，不得提取为财务字段。
"""


class EvidenceExtractor:
    """Turn adapter output into typed extraction batches without treating snippets as facts.

    Every extraction call receives the planner's research goal (topic, purpose,
    round, gap/conflict targets, expected fields) so the model knows WHY the
    page was retrieved — never a bare "extract company facts" instruction.
    """

    # Few-shot exemplar matching ExtractedEvidenceBatch exactly. extraction_method
    # is "model_structured" (NOT recorded_fixture) so real batches never fall
    # into the fixture-mode quality backdoor.
    EXEMPLAR_BATCH = {
        "source_url": "https://example.com/company/about",
        "source_title": "示例公司简介",
        "publisher": "示例公司",
        "source_kind": "official_company",
        "extraction_method": "model_structured",
        "retrieval_adapter": "anysearch",
        "is_search_snippet": False,
        "entities": [{
            "entity_key": "acme",
            "canonical_name": "示例公司",
            "entity_type": "company",
            "official_website": "https://example.com",
            "registration_region": "中国广东省深圳市",
        }],
        "claims": [{
            "entity_key": "acme",
            "field_name": "founded_date",
            "value": "2011年",
            "value_type": "string",
            "raw_text": "原文中写明的成立时间",
            "context_text": "原文中的一句完整引用",
            "qualifier": "exact",
        }],
        "factories": [],
        "products": [],
        "images": [],
    }

    IDENTITY_CLAIM_EXAMPLE = {
        "entity_key": "acme",
        "field_name": "canonical_company_name",
        "value": "页面写明的公司全称",
        "value_type": "string",
        "raw_text": "原文中写明公司全称的句子",
        "context_text": "包含公司全称的完整原文引用",
        "qualifier": "exact",
    }

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        self.gateway = gateway
        # Per-call diagnostics: pages whose structured extraction failed.
        # Failures are surfaced (never silently dropped) by the orchestrator
        # via ExecutionOutcome.review_reasons.
        self.last_failures: list[str] = []

    def extract(self, result: SearchResultEnvelope) -> list[ExtractedEvidenceBatch]:
        self.last_failures = []
        batches: list[ExtractedEvidenceBatch] = []
        for hit in result.hits:
            recorded = hit.metadata.get("evidence_batch")
            if recorded:
                batches.append(ExtractedEvidenceBatch.model_validate(recorded))
                continue
            if not hit.final_url or not hit.text or self.gateway is None:
                continue
            prompt = self._build_prompt(result, hit)
            try:
                batch = self.gateway.structured(StructuredRequest[
                    ExtractedEvidenceBatch
                ](
                    purpose="enterprise_evidence_extraction",
                    messages=[{"role": "user", "content": prompt}],
                    response_model=ExtractedEvidenceBatch,
                    temperature=0.0,
                    metadata={
                        "query_id": result.query_id,
                        "adapter": result.adapter,
                        "topic": result.topic,
                        "collection_round": result.collection_round,
                    },
                ))
            except GatewayError as exc:
                # One bad page must not sink the whole run: record it and
                # keep going. The orchestrator surfaces these diagnostics.
                self.last_failures.append(
                    f"{result.query_id} {hit.final_url}: {str(exc)[:160]}"
                )
                continue
            except Exception as exc:  # noqa: BLE001 - structured schema edge cases
                from pydantic import ValidationError as _ValidationError
                if not isinstance(exc, _ValidationError):
                    raise
                self.last_failures.append(
                    f"{result.query_id} {hit.final_url}: schema validation: {str(exc)[:160]}"
                )
                continue
            batch = self._sanitize_batch(batch, result.query_id, hit.final_url)
            if batch is not None:
                # Snippet status is ADAPTER metadata, not model judgement:
                # the model must never upgrade a snippet to a page, nor
                # downgrade an extracted full page to a snippet.
                batch = batch.model_copy(update={"is_search_snippet": bool(hit.metadata.get("snippet"))})
                batches.append(batch)
        return batches

    def _build_prompt(self, result: SearchResultEnvelope, hit) -> str:
        contract = contract_for(result.topic or "")
        goal_block = GOAL_PROMPT_TEMPLATE.format(
            goal_family=contract.goal_family,
            business_question=contract.business_question,
            expected_fields="\n".join(result.expected_fields or contract.expected_fields),
        )
        identity_rule = ""
        if (result.topic or "") in {"company_identity", "ownership_structure"}:
            identity_rule = (
                "IDENTITY RULE: 若页面明确写明公司全称，必须生成 canonical_company_name Claim"
                "（示例见下）；若页面写明注册名称、统一社会信用代码、总部、成立时间、母公司或"
                "实际控制人，分别生成 registered_name / registration_identifier / headquarters / "
                "founded_date / parent_company / actual_controller Claim。"
                "不得把输入的公司简称直接当成注册全称。\n"
                f"Identity claim example:\n{json.dumps(self.IDENTITY_CLAIM_EXAMPLE, ensure_ascii=False)}\n"
            )
        return (
            "从提供的页面中提取企业事实。页面是为以下研究目标检索的：\n\n"
            f"{goal_block}\n"
            f"{identity_rule}"
            "source_kind 必须从以下固定词表中选择其一（不得自创）："
            "government, sasac, annual_report, official_manual, official_announcement, "
            "official_company, industry_association, university, research_institute, "
            "certification_body, recruitment, commercial_database, marketplace, channel, "
            "social_media, forum, ordinary_media。\n"
            "Return ONE JSON object matching exactly the following JSON Schema "
            "(strict: no extra keys, no missing required keys, empty lists stay empty):\n"
            f"{json.dumps(ExtractedEvidenceBatch.model_json_schema(), ensure_ascii=False)}\n\n"
            "Example of a valid object (use this shape, replace values with page facts):\n"
            f"{json.dumps(self.EXEMPLAR_BATCH, ensure_ascii=False)}\n\n"
            "Do not infer missing values. raw_text and context_text must quote the supplied page. "
            "Treat search-result snippets as discovery-only.\n\n"
            f"URL: {hit.final_url}\nTITLE: {hit.title or ''}\nCONTENT:\n{hit.text[:60000]}"
        )

    def _sanitize_batch(self, batch: ExtractedEvidenceBatch, query_id: str, url: str) -> ExtractedEvidenceBatch | None:
        """Drop records whose references point at undeclared keys (抽取一致性清洗).

        The LLM occasionally writes a fact into ``entity_key`` (e.g. a claim
        whose entity_key is a phrase like "global_largest_..._production_base")
        while the entity itself is missing from ``entities``. The kernel
        normalizer rejects those hard, which would sink the whole run.
        Instead, drop the dangling records here and surface the drop, so the
        run continues with the clean records (宁缺毋滥, never fabricate).

        ``source_kind`` is also pinned to the fixed vocabulary — free-text
        kinds are normalized conservatively, never upgraded.
        """
        from enterprise_energy_research.research.source_grader import normalize_source_kind
        batch = batch.model_copy(update={"source_kind": normalize_source_kind(batch.source_kind)})
        declared = {item.entity_key for item in batch.entities}
        declared.update(item.factory_key for item in batch.factories)
        declared.update(item.product_key for item in batch.products)
        dropped: list[str] = []

        def keep(record, reference_attrs) -> bool:
            for attr in reference_attrs:
                value = getattr(record, attr, None)
                if value and value not in declared:
                    dropped.append(f"{type(record).__name__}.{attr}={value}")
                    return False
            return True

        batch.claims = [c for c in batch.claims if keep(c, ("entity_key",))]
        batch.factories = [f for f in batch.factories if keep(f, ("operator_entity_key",))]
        batch.products = [p for p in batch.products if keep(p, ("entity_key",))]
        batch.images = [i for i in batch.images if keep(i, ("entity_key", "factory_key"))]
        if dropped:
            self.last_failures.append(
                f"{query_id} {url}: dropped {len(dropped)} dangling record(s): {', '.join(dropped[:3])}"
            )
        if not batch.entities and not batch.claims:
            return None  # nothing usable left on this page
        return batch


def extract_goal_context(result: SearchResultEnvelope) -> dict[str, Any]:
    """Expose the research-goal context carried by an envelope (P0-2 contract)."""
    return {
        "query_id": result.query_id,
        "topic": result.topic,
        "purpose": result.purpose,
        "collection_round": result.collection_round,
        "round_goal": result.round_goal,
        "trigger": result.trigger,
        "target_gap_ids": result.target_gap_ids,
        "target_conflict_ids": result.target_conflict_ids,
        "target_claim_ids": result.target_claim_ids,
        "canonical_company_name": result.canonical_company_name,
        "expected_fields": result.expected_fields,
    }
