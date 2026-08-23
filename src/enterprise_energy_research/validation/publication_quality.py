"""Publication quality validators (P0 third round).

Beyond exact-duplicate detection, a formal report is now measured for
REAL research value:

  * PublicationBoilerplateValidator — counts self-referential AI/methodology
    boilerplate phrases in the body text;
  * ParagraphSimilarityValidator — normalized n-gram skeleton similarity to
    catch template repetition that is not an exact duplicate;
  * ResearchValueValidator — quantitative facts, unique metrics, time-series
    metrics, meaningful visuals, product images, enterprise-specific vs
    boilerplate sentence ratios, and visual density;
  * ProductImageCoverageValidator — product-photo coverage vs. verified
    products.

Thresholds are evidence-adjusted: a thin evidence set must not be padded,
and a rich set must not hide behind prose.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from pydantic import BaseModel, Field

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
SENTENCE_SPLIT_RE = re.compile(r"[。；！？!?；\n]+")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")

BOILERPLATE_PHRASES = (
    "该信息用于",
    "后续评审应",
    "本节判断由",
    "证据强度用于",
    "当前冻结的公开事实",
    "下一道决策门",
    "不用于制造确定性",
    "现有证据可归纳为",
    "资料能够证明的范围必须与结论范围一致",
    "该记录用于限定本节结论范围",
    "任何超出来源范围的外推",
    "事实链尚未闭合",
    "若新资料改变口径",
    "应同步重算",
    "管理层应把本报告当作",
    "资源配置边界",
    "不能用上一层数量替代下一层判断",
    "So What：",
)

DECISION_DENSITY_PHRASES = (
    "Go / No-Go", "决策门", "30 / 60 / 90", "阻断条件", "预可研",
)

# Allowed decision-language chapters (consulting layer only).
DECISION_CHAPTERS = {"executive_summary", "opportunities", "action_plan", "risks_evidence"}


class QualityCheck(BaseModel):
    code: str
    status: str = "PASS"  # PASS | WARN | FAIL
    message: str
    value: Any = None


def _narrative_body(narrative: Any) -> str:
    chunks: list[str] = []
    for chapter in narrative.chapters:
        chunks.extend([
            chapter.assertion_title, chapter.executive_takeaway,
            *chapter.context_paragraphs, *chapter.analysis_paragraphs,
            *chapter.implications, *chapter.recommendations,
            *chapter.counter_evidence, *chapter.limitations, *chapter.action_items,
        ])
    return "\n".join(filter(None, chunks))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if len(part.strip()) >= 12]


def _skeleton(sentence: str) -> str:
    """Remove numbers and latin identifiers -> comparable sentence skeleton."""
    without_numbers = NUMBER_RE.sub("＃", sentence)
    without_entities = ENTITY_RE.sub("＠", without_numbers)
    return "".join(without_entities.split())


def _ngrams(skeleton: str, n: int = 3) -> set[str]:
    return {skeleton[index:index + n] for index in range(max(0, len(skeleton) - n + 1))}


def _similarity(left: str, right: str) -> float:
    left_grams, right_grams = _ngrams(left, 3), _ngrams(right, 3)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


class PublicationBoilerplateValidator:
    """Count self-referential boilerplate phrases in the final body text."""

    def validate(self, narrative: Any) -> list[QualityCheck]:
        body = _narrative_body(narrative)
        counts = {phrase: body.count(phrase) for phrase in BOILERPLATE_PHRASES if phrase in body}
        zero_required = {"后续评审应", "本节判断由", "证据强度用于", "当前冻结的公开事实", "该信息用于", "下一道决策门", "不用于制造确定性", "So What："}
        checks: list[QualityCheck] = []
        for phrase in zero_required:
            count = body.count(phrase)
            checks.append(QualityCheck(
                code="boilerplate_zero", status="PASS" if count == 0 else "FAIL",
                message=f'"{phrase}" 出现 {count} 次', value=count,
            ))
        existing = body.count("现有证据可归纳为")
        checks.append(QualityCheck(
            code="boilerplate_evidence_summary", status="PASS" if existing <= 1 else "FAIL",
            message=f'"现有证据可归纳为" 出现 {existing} 次（允许 ≤1）', value=existing,
        ))
        return checks + [QualityCheck(
            code="boilerplate_total", status="PASS" if not counts else "WARN",
            message=f"命中模板短语 {sum(counts.values())} 次" if counts else "未命中模板短语",
            value=counts,
        )]

    def decision_density(self, narrative: Any) -> list[QualityCheck]:
        """Decision-gate language may appear only in the consulting chapters."""
        violations: dict[str, list[str]] = {}
        for chapter in narrative.chapters:
            if chapter.chapter_id in DECISION_CHAPTERS:
                continue
            text = "\n".join([
                chapter.assertion_title, chapter.executive_takeaway,
                *chapter.context_paragraphs, *chapter.analysis_paragraphs,
            ])
            hits = [phrase for phrase in DECISION_DENSITY_PHRASES if phrase in text]
            if hits:
                violations[chapter.chapter_id] = hits
        return [QualityCheck(
            code="decision_language_scoped", status="PASS" if not violations else "FAIL",
            message="决策门语言越界" if violations else "决策门语言仅出现在咨询章节",
            value=violations,
        )]


class ParagraphSimilarityValidator:
    """Catch near-duplicate template paragraphs (skeleton similarity > 0.80)."""

    def validate(self, narrative: Any, threshold: float = 0.80) -> list[QualityCheck]:
        paragraphs: list[tuple[str, str]] = []
        for chapter in narrative.chapters:
            for text in [
                *chapter.context_paragraphs, *chapter.analysis_paragraphs,
                *chapter.implications, *chapter.recommendations,
                *chapter.limitations, *chapter.action_items,
            ]:
                stripped = text.strip()
                if len(stripped) >= 40:
                    paragraphs.append((chapter.chapter_id, stripped))
        duplicates: list[dict] = []
        for index, (_, left) in enumerate(paragraphs):
            for other_index in range(index + 1, len(paragraphs)):
                _, right = paragraphs[other_index]
                score = _similarity(_skeleton(left), _skeleton(right))
                if score > threshold:
                    duplicates.append({"a": left[:40], "b": right[:40], "similarity": round(score, 3)})
                    break
        return [QualityCheck(
            code="boilerplate_duplicate", status="PASS" if not duplicates else "FAIL",
            message=f"模板重复段落 {len(duplicates)} 对" if duplicates else "无模板重复段落",
            value=duplicates[:5],
        )]


class ResearchValueValidator:
    """Quantify research value instead of raw length."""

    def validate(self, narrative: Any, bundle: Any) -> list[QualityCheck]:
        body = _narrative_body(narrative)
        sentences = _sentences(body)
        quantitative_facts = len(re.findall(r"\d+(?:\.\d+)?(?:%|亿|万|万元|亿元|GWh|MWh|MW|GW|kWh|吨|处|项|个|人)", body))
        metric_mentions: set[str] = set()
        for token in ("营业收入", "净利润", "毛利率", "净利率", "研发投入", "研发费用率", "装机量", "市场份额", "产能", "员工人数", "现金流"):
            if token in body:
                metric_mentions.add(token)
        time_series_metrics = sum(
            1 for visual in narrative.visuals
            if visual.semantic_pattern == "time_series"
            and len([item for item in visual.items if isinstance(item.value, (int, float))]) >= 2
        )
        meaningful_visuals = sum(
            1 for visual in narrative.visuals
            if len([item for item in visual.items if isinstance(item.value, (int, float))]) >= 2
            or len(visual.stages) >= 2 or len(visual.nodes) >= 2
        )
        product_image_count = int(narrative.counts.get("product_image_count", 0))
        boilerplate = sum(1 for sentence in sentences if any(phrase in sentence for phrase in BOILERPLATE_PHRASES))
        decision_sentences = sum(
            1 for sentence in sentences
            if any(phrase in sentence for phrase in DECISION_DENSITY_PHRASES)
        )
        boilerplate_ratio = round(boilerplate / len(sentences), 4) if sentences else 1.0
        from enterprise_energy_research.research.publication_relevance import PublicationRelevanceFilter
        relevant_claims, relevance_report = PublicationRelevanceFilter().filter(bundle)
        enterprise_specific_ratio = round(
            len(relevant_claims) / relevance_report.total_verified, 4
        ) if relevance_report.total_verified else 0.0
        main_body = int(narrative.counts.get("main_body_cjk_char_count", 0))
        checks: list[QualityCheck] = [
            QualityCheck(code="quantitative_fact_count", status="PASS", message="正文量化事实数", value=quantitative_facts),
            QualityCheck(code="unique_metric_count", status="PASS", message="正文独立指标数", value=len(metric_mentions)),
            QualityCheck(code="time_series_metric_count", status="PASS", message="真实时间序列图数", value=time_series_metrics),
            QualityCheck(code="meaningful_visual_count", status="PASS", message="有信息价值的图/表模块数", value=meaningful_visuals),
            QualityCheck(code="product_image_count", status="PASS", message="产品图片数", value=product_image_count),
            QualityCheck(
                code="boilerplate_sentence_ratio",
                status="PASS" if boilerplate_ratio < 0.15 else "FAIL",
                message=f"模板句占比 {boilerplate_ratio:.1%}（门槛 <15%）", value=boilerplate_ratio,
            ),
            QualityCheck(
                code="enterprise_specific_data_ratio",
                status=("PASS" if enterprise_specific_ratio > 0.60 else "FAIL" if relevance_report.total_verified >= 20 else "WARN"),
                message=f"企业特异性数据占已核验事实 {enterprise_specific_ratio:.1%}（门槛 >60%）", value=enterprise_specific_ratio,
            ),
        ]
        if main_body > 15_000 and meaningful_visuals < 5:
            checks.append(QualityCheck(
                code="insufficient_visual_density", status="WARN",
                message=f"正文 {main_body} 字但有效图表仅 {meaningful_visuals} 个（建议 ≥5）",
                value={"main_body": main_body, "meaningful_visuals": meaningful_visuals},
            ))
        verified_products = int(narrative.counts.get("verified_products", 0))
        if verified_products >= 5 and product_image_count < 5:
            checks.append(QualityCheck(
                code="product_image_coverage_failure", status="FAIL",
                message=f"已核验产品 {verified_products} 项但正式产品图片仅 {product_image_count} 张，需重试至至少 5 张",
                value={"verified_products": verified_products, "product_images": product_image_count},
            ))
        return checks


class ProductImageCoverageValidator:
    def validate(self, narrative: Any) -> list[QualityCheck]:
        verified_products = int(narrative.counts.get("verified_products", 0))
        product_images = int(narrative.counts.get("product_image_count", 0))
        if verified_products < 5:
            return [QualityCheck(code="product_image_coverage", status="PASS", message="产品不足 5 项，无图片覆盖门槛")]
        if product_images < 5:
            return [QualityCheck(
                code="product_image_coverage_failure", status="FAIL",
                message=f"verified_products={verified_products}，正式产品图片={product_images}（门槛 ≥5）", value=verified_products,
            )]
        return [QualityCheck(code="product_image_coverage", status="PASS", message=f"{product_images} 张产品图片", value=product_images)]
