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
import json
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

# These phrases expose the internal reasoning template instead of stating a
# business conclusion in ordinary Chinese.  They are forbidden across the
# complete publication DTO because unified HTML embeds that DTO inline.
AI_TONE_PHRASES = (
    "这些事实回答企业靠什么经营",
    "不把企业规模本身等同于合作价值",
    "当前结论为",
    "至少一个合作假设已同时通过",
    "目标问题、合作时点、委托方能力、价值机制和反证条件门槛",
    "机会评估回答目标问题",
    "完整合作假设契约",
    "目标问题、时点和委托方能力缺一不可",
    "30 天回答目标问题是否真实且重要",
    "每一步都允许证伪并停止",
    "不以工作量证明机会成立",
    "关键输出不是资料包或流程台账",
    "价值取决于经核验的现场数据与可审计基线",
    "下一阶段资源仅投向仍未被证伪",
    "不以研究作业是否完成替代业务判断",
    "委托方配置能力无法影响目标问题或无法组织关键关系方",
    "合作假设的证伪门槛",
    "按当前战略优先级验证合作假设",
    "判断企业资源基础时，应把",
    "经营变化应同时观察",
    "该方向进入实质讨论的前提",
    "每个阶段只保留一个明确决策结果",
    "90 天节点不以会议数量衡量",
    "上述信息用于识别研究主体",
    "本章回答的经营问题是",
    "本章小结",
    "经营章节的数据基础为",
    "该补齐工作由定向检索完成",
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
        from energy_research_agent.research.publication_relevance import PublicationRelevanceFilter
        relevant_claims, relevance_report = PublicationRelevanceFilter().filter(bundle)
        # Competitor, customer/supplier and policy-authority evidence is kept
        # for its dedicated chapter but cannot dilute target-enterprise QA.
        # The denominator is therefore the verified canonical/group scope,
        # not every verified claim discovered during broader research.
        target_verified = relevance_report.target_scope_verified
        enterprise_specific_ratio = round(
            len(relevant_claims) / target_verified, 4
        ) if target_verified else 0.0
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
                status=("PASS" if enterprise_specific_ratio > 0.60 else "FAIL" if target_verified >= 20 else "WARN"),
                message=f"目标企业范围内可发布数据占已核验事实 {enterprise_specific_ratio:.1%}（门槛 >60%）", value=enterprise_specific_ratio,
            ),
        ]
        supplemental = list(getattr(narrative, "supplemental_requirements", []) or [])
        pending = [item for item in supplemental if item.get("status") == "pending_retry"]
        checks.append(QualityCheck(
            code="supplemental_requirement_coverage",
            status="FAIL" if pending else "PASS",
            message=(
                "专项要求尚未取得可核验原文证据，必须继续内部补采："
                + "、".join(str(item.get("title") or item.get("topic")) for item in pending)
                if pending else
                "专项要求均已取得可核验证据，或已完成10次补采并保留审计缺口"
            ),
            value=supplemental,
        ))
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


class DecisionIntelligenceValidator:
    """Hard publication gates for management-useful decision intelligence."""

    PROCESS_TERMS = (
        "资料清单", "数据清洗", "补数", "预可研", "检索失败", "检索流程",
        "报告生成", "问题台账", "资料齐套率", "完成报告", "证据收集流程",
    )
    GAP_TERMS = (
        "数据缺口", "资料缺失", "未找到资料", "尚未检索", "检索失败",
        "待补充资料", "公开资料不足", "现场数据缺失",
    )
    GENERIC_OPPORTUNITY = "提供场景诊断、数据边界梳理、技术适配与预可研服务"

    def validate(self, narrative: Any, bundle: Any) -> list[QualityCheck]:
        body = _narrative_body(narrative)
        sentences = _sentences(body)
        denominator = max(1, len(sentences))
        process = [sentence for sentence in sentences if any(term in sentence for term in self.PROCESS_TERMS)]
        gaps = [sentence for sentence in sentences if any(term in sentence for term in self.GAP_TERMS)]
        process_ratio = len(process) / denominator
        gap_ratio = len(gaps) / denominator
        verified_count = sum(getattr(claim, "verification_status", None).value == "VERIFIED" for claim in bundle.claims)
        gap_threshold = 0.05 if verified_count >= 80 else 0.10
        strategic = getattr(narrative, "strategic_interpretation", None)
        has_historical_inputs = any(
            getattr(trend, "year_count", 0) >= 3
            for trend in __import__(
                "energy_research_agent.research.research_analysis",
                fromlist=["ResearchAnalysisEngine"],
            ).ResearchAnalysisEngine().analyze(bundle).trends
        )
        trajectory_ok = bool(strategic and strategic.trajectories) if has_historical_inputs else True
        comparative_claims = [
            claim for claim in bundle.claims
            if claim.field_name in {"competitor", "comparison", "market_share", "industry_rank"}
            and getattr(claim.verification_status, "value", claim.verification_status) == "VERIFIED"
        ]
        competition_ok = not (strategic and strategic.competitive_positions) or bool(comparative_claims)
        hypotheses = list(getattr(narrative, "cooperation_hypotheses", []))
        bad_priority = [
            item.hypothesis_id for item in hypotheses
            if getattr(item.status, "value", item.status) == "PRIORITY_OPPORTUNITY"
            and (not item.target_problem or not item.why_now or not item.client_capability_match
                 or not item.value_creation_logic or not item.target_department
                 or not item.disconfirming_conditions
                 or "UNKNOWN_CLIENT_CAPABILITY" in item.client_capability_statuses)
        ]
        generic = [item.hypothesis_id for item in hypotheses if self.GENERIC_OPPORTUNITY in item.value_creation_logic]
        executive = narrative.chapter("executive_summary")
        exec_text = "\n".join([*(executive.context_paragraphs if executive else []), *(executive.analysis_paragraphs if executive else [])])
        exec_process = [term for term in self.PROCESS_TERMS if term in exec_text]
        enterprise_chapters = [chapter for chapter in narrative.chapters if chapter.claim_ids]
        enterprise_ratio = len(enterprise_chapters) / max(1, len(narrative.chapters))
        full_payload = json.dumps(narrative.model_dump(mode="json"), ensure_ascii=False)
        ai_tone_hits = {phrase: full_payload.count(phrase) for phrase in AI_TONE_PHRASES if phrase in full_payload}
        checks = [
            QualityCheck(code="decision_process_language_ratio", status="PASS" if process_ratio < 0.05 else "FAIL", message=f"流程语言句占比 {process_ratio:.1%}（门槛 <5%）", value=process[:5]),
            QualityCheck(code="decision_gap_narrative_ratio", status="PASS" if gap_ratio < gap_threshold else "FAIL", message=f"缺口叙事句占比 {gap_ratio:.1%}（门槛 <{gap_threshold:.0%}）", value=gaps[:5]),
            QualityCheck(code="strategic_trajectory_required", status="PASS" if trajectory_ok else "FAIL", message="存在三年可比数据时必须形成战略轨迹", value=bool(strategic and strategic.trajectories) if strategic else False),
            QualityCheck(code="competition_evidence_gate", status="PASS" if competition_ok else "FAIL", message="竞争位置必须由具名可比或量化竞争证据打开", value=[claim.claim_id for claim in comparative_claims]),
            QualityCheck(code="cooperation_hypothesis_contract", status="PASS" if not bad_priority else "FAIL", message="优先合作假设必须满足 Need/Why Now/委托方能力/价值机制/责任部门/反证条件", value=bad_priority),
            QualityCheck(code="generic_opportunity_rejection", status="PASS" if not generic else "FAIL", message="不得使用通用预可研服务模板生成正式机会", value=generic),
            QualityCheck(code="executive_summary_process_language", status="PASS" if not exec_process else "FAIL", message="执行摘要不得以研究流程作为结论", value=exec_process),
            QualityCheck(code="enterprise_specific_chapter_ratio", status="PASS" if enterprise_ratio > 0.70 else "WARN", message=f"企业事实绑定章节占比 {enterprise_ratio:.1%}（目标 >70%）", value=enterprise_ratio),
            QualityCheck(code="management_usefulness", status="PASS" if executive and len(narrative.executive_summary) == 5 and bool(getattr(narrative, "client_profile", None)) else "FAIL", message="执行摘要须回答企业本质、变化、委托方含义、风险反证与资源决定"),
            QualityCheck(
                code="plain_business_language",
                status="PASS" if not ai_tone_hits else "FAIL",
                message="公开表达应直接陈述业务事实、建议和条件，不得复述内部推理框架",
                value=ai_tone_hits,
            ),
        ]
        return checks
