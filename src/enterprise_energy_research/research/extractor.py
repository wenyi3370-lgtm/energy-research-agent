from __future__ import annotations

import json
from typing import Any

from enterprise_energy_research.adapters.base import SearchResultEnvelope
from enterprise_energy_research.domain.models import ExtractedEvidenceBatch
from enterprise_energy_research.gateway.base import GatewayError, ModelGateway, StructuredRequest


class EvidenceExtractor:
    """Turn adapter output into typed extraction batches without treating snippets as facts."""

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
            prompt = (
                "Extract only explicit company facts from the supplied page. "
                "Return ONE JSON object matching exactly the following JSON Schema "
                "(strict: no extra keys, no missing required keys, empty lists stay empty):\n"
                f"{json.dumps(ExtractedEvidenceBatch.model_json_schema(), ensure_ascii=False)}\n\n"
                "Example of a valid object (use this shape, replace values with page facts):\n"
                f"{json.dumps(self.EXEMPLAR_BATCH, ensure_ascii=False)}\n\n"
                "Do not infer missing values. raw_text and context_text must quote the supplied page. "
                "Treat search-result snippets as discovery-only.\n\n"
                f"URL: {hit.final_url}\nTITLE: {hit.title or ''}\nCONTENT:\n{hit.text[:60000]}"
            )
            try:
                batch = self.gateway.structured(StructuredRequest[
                    ExtractedEvidenceBatch
                ](
                    purpose="enterprise_evidence_extraction",
                    messages=[{"role": "user", "content": prompt}],
                    response_model=ExtractedEvidenceBatch,
                    temperature=0.0,
                    metadata={"query_id": result.query_id, "adapter": result.adapter},
                ))
            except GatewayError as exc:
                # One bad page must not sink the whole run: record it and
                # keep going. The orchestrator surfaces these diagnostics.
                self.last_failures.append(
                    f"{result.query_id} {hit.final_url}: {str(exc)[:160]}"
                )
                continue
            batch = self._sanitize_batch(batch, result.query_id, hit.final_url)
            if batch is not None:
                batches.append(batch)
        return batches

    def _sanitize_batch(self, batch: ExtractedEvidenceBatch, query_id: str, url: str) -> ExtractedEvidenceBatch | None:
        """Drop records whose references point at undeclared keys (抽取一致性清洗).

        The LLM occasionally writes a fact into ``entity_key`` (e.g. a claim
        whose entity_key is a phrase like "global_largest_..._production_base")
        while the entity itself is missing from ``entities``. The kernel
        normalizer rejects those hard, which would sink the whole run.
        Instead, drop the dangling records here and surface the drop, so the
        run continues with the clean records (宁缺毋滥, never fabricate).
        """
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
        batch.images = [i for i in batch.images if keep(i, ("entity_key", "factory_key"))]
        if dropped:
            self.last_failures.append(
                f"{query_id} {url}: dropped {len(dropped)} dangling record(s): {', '.join(dropped[:3])}"
            )
        if not batch.entities and not batch.claims:
            return None  # nothing usable left on this page
        return batch

