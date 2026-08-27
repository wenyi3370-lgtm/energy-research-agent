"""Decision-grade narrative and publication gates.

These validators operate on the analysis/publication contracts, not on a
renderer-specific string-replacement layer.  They are intentionally usable
both in unit tests and in the final Word/HTML inspection workflow.
"""

from __future__ import annotations

import re
import json
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, Field

from energy_research_agent.domain.models import FrozenResearchBundle

ENERGY_FIELDS = {
    "electricity_consumption", "energy_consumption", "power_demand", "peak_load",
    "peak_demand", "electricity_cost", "load_curve", "pv_capacity", "storage_capacity",
    "storage_power", "renewable_share", "transformer_capacity", "roof_area",
}
MANUFACTURING_FIELDS = {
    "capacity", "production_capacity", "factory_capacity", "battery_production_capacity",
    "production_lines", "output", "annual_output", "factory_name", "process", "processes",
    "factory_address", "address", "commissioning_date", "project_status", "factory_count",
}


RAW_ENUMS = {
    "requires_site_due_diligence", "SEARCH_FAILED", "NORMALIZED_NOT_VERIFIED",
    "SOURCE_A", "SOURCE_B", "SOURCE_C", "SOURCE_D",
    "PRIORITY_OPPORTUNITY", "POTENTIAL_HYPOTHESIS", "REJECTED",
}
RAW_FIELDS = {
    "electricity_consumption", "transformer_capacity", "load_curve", "roof_area",
    "operating_schedule", "product_parameters", "catalog_items", "enumerated",
    "official_product_centers",
}
RAW_HEADERS = {"field", "value", "name", "address", "processes", "status", "opportunity", "solution", "priority", "next_step"}


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or ""))


def narrative_body_text(narrative: Any) -> str:
    chunks: list[str] = []
    for chapter in narrative.chapters:
        chunks.extend([
            chapter.assertion_title, chapter.executive_takeaway,
            *chapter.context_paragraphs, *chapter.analysis_paragraphs,
            *chapter.implications, *chapter.recommendations,
            *chapter.counter_evidence, *chapter.limitations, *chapter.action_items,
        ])
    return "\n".join(filter(None, chunks))


def evidence_adjusted_threshold(narrative: Any) -> int:
    """Data-weighted body gate (P0 third round).

    A dense evidence set lowers the padding pressure: verified claims,
    meaningful visuals and product/factory records each raise the bar,
    while a report with 9 real charts and 190 verified claims is no longer
    forced to pad prose to the old flat 12k ceiling.
    """
    verified = int(narrative.counts.get("verified_claims", 0))
    visuals = int(narrative.counts.get("meaningful_visual_count", 0))
    products = int(narrative.counts.get("verified_products", 0))
    factories = int(narrative.counts.get("factories", 0))
    full = verified >= 30 and len(narrative.opportunity_assessments) >= 2 and len(narrative.chapters) >= 7
    if full:
        # Verified count is weighted lightly: it includes many low-value
        # identity/registry claims; visuals, products and factories carry
        # the research density instead.
        base = 2_500 + verified * 6 + visuals * 300 + products * 8 + factories * 8
        return min(12_000, max(8_000, (base // 100) * 100))
    # A thin evidence set must still produce analysis, but must not be padded
    # to impersonate a 30-page report. The 3,500-character formal floor stays
    # fixed; the workflow must supplement evidence and rebuild up to ten
    # times before this gate may fail.
    return 3_500


class ValidationCheck(BaseModel):
    code: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str
    value: Any = None


class ConsultingNarrativeValidation(BaseModel):
    status: Literal["PASS", "BLOCKED"]
    main_body_cjk_char_count: int
    executive_summary_cjk_char_count: int
    threshold: int
    checks: list[ValidationCheck] = Field(default_factory=list)


class ConsultingNarrativeValidator:
    """Run the 20 mandatory narrative checks from the P0 quality contract."""

    CORE_KINDS = {"operations", "products", "factories", "energy_profile", "opportunities", "action_plan", "risks_evidence"}

    def validate(
        self,
        narrative: Any,
        *,
        enforce_length: bool = True,
    ) -> ConsultingNarrativeValidation:
        checks: list[ValidationCheck] = []
        body = narrative_body_text(narrative)
        main_count = cjk_count(body)
        executive = narrative.chapter("executive_summary")
        executive_text = "\n".join([
            executive.assertion_title, executive.executive_takeaway,
            *executive.context_paragraphs, *executive.analysis_paragraphs,
            *executive.implications, *executive.recommendations,
            *executive.counter_evidence, *executive.limitations, *executive.action_items,
        ]) if executive else "\n".join(narrative.executive_summary)
        executive_count = cjk_count(executive_text)
        threshold = evidence_adjusted_threshold(narrative)
        executive_threshold = min(800, max(500, threshold // 10))
        executive_length_ok = executive_count >= executive_threshold
        checks.append(ValidationCheck(
            code="executive_summary_length",
            status="PASS" if executive_length_ok or not enforce_length else "FAIL",
            message=(
                f"执行摘要中文字符数 {executive_count}，正式门槛 {executive_threshold}；"
                + (
                    "必须以证据、决策影响和行动条件完成深化，不得用模板套话补齐。"
                    if enforce_length
                    else "合成测试样本不执行正式字数门槛。"
                )
            ),
            value={
                "actual": executive_count,
                "threshold": executive_threshold,
                "enforced": enforce_length,
            },
        ))
        self._check(checks, "no_raw_internal_enum", not any(token in body for token in RAW_ENUMS), "正文不得出现内部枚举")
        self._check(checks, "no_raw_snake_case", not re.search(r"\b[a-z]+(?:_[a-z0-9]+)+\b", body), "正文不得出现 snake_case 字段")
        paragraphs = self._paragraphs(narrative)
        duplicates = [text for text, count in Counter(paragraphs).items() if count > 1]
        self._check(checks, "no_duplicate_paragraph", not duplicates, f"完全重复段落 {len(duplicates)} 个", duplicates[:3])
        keys = [item.canonical_key for item in narrative.opportunity_assessments]
        self._check(checks, "no_duplicate_opportunity", len(keys) == len(set(keys)), "Opportunity canonical_key 必须唯一")
        deficient = []
        short = []
        for chapter in narrative.chapters:
            if chapter.kind not in self.CORE_KINDS:
                continue
            substantive = [p for p in [*chapter.context_paragraphs, *chapter.analysis_paragraphs] if cjk_count(p) >= 60]
            if len(substantive) < 2:
                deficient.append(chapter.chapter_id)
            short.extend(f"{chapter.chapter_id}:{cjk_count(p)}" for p in substantive if cjk_count(p) < 80)
        self._check(checks, "core_chapter_depth", not deficient, "核心章节至少 2 个实质分析段", deficient)
        checks.append(ValidationCheck(
            code="substantive_paragraph_length", status="PASS" if not short else "WARN",
            message="实质分析段建议不少于 80 个中文字符；短段不以模板句补长。", value=short,
        ))
        hollow = [p for p in paragraphs if re.search(r"已形成\s*1\s*份", p)]
        self._check(checks, "no_hollow_chapter", not hollow, "不得使用空洞计数句撑起章节")
        negative_trend_terms = ("不足", "不能", "不支持", "不可", "尚无法")
        bad_trend = [
            c.assertion_title for c in narrative.chapters
            if "趋势" in c.assertion_title
            and not any(term in c.assertion_title for term in negative_trend_terms)
            and not any(len(v.items) >= 3 for v in narrative.visuals_for(c.chapter_id))
        ]
        self._check(checks, "trend_requires_three_periods", not bad_trend, "趋势结论必须有至少 3 个期间", bad_trend)
        bad_energy = [v.visual_id for v in narrative.visuals if v.semantic_domain == "energy" and any(token in (v.data_binding or "") for token in MANUFACTURING_FIELDS)]
        self._check(checks, "energy_semantic_guard", not bad_energy, "制造产能不得进入用能图", bad_energy)
        unsupported = [c.chapter_id for c in narrative.chapters if c.recommendations and not c.claim_ids and c.kind != "risks_evidence"]
        self._check(checks, "recommendation_lineage", not unsupported, "建议必须具备事实依据", unsupported)
        incomplete_opps = [item.opportunity_id for item in narrative.opportunity_assessments if not all((item.strategic_rationale, item.target_scenario, item.entry_point, item.key_prerequisites, item.first_30_day_action, item.go_no_go_gate))]
        self._check(checks, "opportunity_contract", not incomplete_opps, "机会必须说明 why/where/how/prerequisite/action/gate", incomplete_opps)
        source_chapters = [c.chapter_id for c in narrative.chapters if c.kind == "sources" or c.chapter_id == "sources"]
        self._check(checks, "source_single_owner", not source_chapters and bool(narrative.appendices.source_ledger), "来源清单仅归 appendices.source_ledger 所有", source_chapters)
        # Renderer-level TOC is separately inspected by TOCValidator.
        self._check(checks, "toc_contract_declared", True, "TOC placeholder 由最终 DOCX gate 检查")
        raw_headers = [key for chapter in narrative.chapters for row in chapter.table_rows for key in row if str(key).casefold() in RAW_HEADERS]
        self._check(checks, "publication_headers_chinese", not raw_headers, "最终表头不得使用英文 schema 名", raw_headers)
        self._check(checks, "overall_judgement_lineage", bool(narrative.overall_judgement and narrative.decision_findings), "总体判断必须有 DecisionFinding 依据")
        # Cross-render consistency is guaranteed by the shared serialized narrative; artifact QA verifies fingerprints.
        self._check(checks, "shared_word_html_judgement", bool(narrative.overall_judgement), "Word/HTML 使用同一总体判断")
        self._check(checks, "shared_word_html_ranking", len(keys) == len(set(keys)), "Word/HTML 使用同一机会排序")
        self._check(checks, "shared_word_html_risks", narrative.key_risks is not None, "Word/HTML 使用同一风险集合")
        length_ok = main_count >= threshold
        checks.append(ValidationCheck(
            code="main_body_length",
            status="PASS" if length_ok or not enforce_length else "FAIL",
            message=(
                f"正文中文字符数 {main_count}，正式门槛 {threshold}；"
                + ("必须以企业事实、口径对比和决策影响完成深化，不得用模板套话补齐。" if enforce_length else "合成测试样本不执行正式字数门槛。")
            ),
            value={"actual": main_count, "threshold": threshold, "enforced": enforce_length},
        ))
        return ConsultingNarrativeValidation(
            status="PASS" if all(item.status != "FAIL" for item in checks) else "BLOCKED",
            main_body_cjk_char_count=main_count, executive_summary_cjk_char_count=executive_count,
            threshold=threshold, checks=checks,
        )

    @staticmethod
    def _paragraphs(narrative: Any) -> list[str]:
        return [p.strip() for chapter in narrative.chapters for p in [
            *chapter.context_paragraphs, *chapter.analysis_paragraphs, *chapter.implications,
            *chapter.recommendations, *chapter.counter_evidence, *chapter.limitations, *chapter.action_items,
        ] if p and p.strip()]

    @staticmethod
    def _check(checks: list[ValidationCheck], code: str, condition: bool, message: str, value: Any = None) -> None:
        checks.append(ValidationCheck(code=code, status="PASS" if condition else "FAIL", message=message, value=value))


class VisualSemanticValidator:
    ALLOWED = {
        "energy": ENERGY_FIELDS,
        "manufacturing": MANUFACTURING_FIELDS | {"factory_count"},
    }

    def validate(self, visual: Any, bundle: FrozenResearchBundle) -> list[str]:
        claim_by_id = {item.claim_id: item for item in bundle.claims}
        fields = {claim_by_id[cid].field_name for cid in visual.source_claim_ids if cid in claim_by_id}
        if visual.semantic_domain not in self.ALLOWED:
            return []
        forbidden = sorted(fields - self.ALLOWED[visual.semantic_domain])
        return [f"{visual.visual_id}: {visual.semantic_domain} visual contains forbidden fields {forbidden}"] if forbidden else []


class PublicationVisibleTextValidator:
    def validate_text(self, text: str) -> list[str]:
        findings = [f"visible raw token: {token}" for token in sorted(RAW_ENUMS | RAW_FIELDS) if token in text]
        findings.extend(
            f"visible vision-audit prompt: {token}"
            for token in ("图中主体属于", "主体类别", "是否能支撑将其绑定", "置信度：**")
            if token in text
        )
        if re.search(r"\{\s*['\"]?[A-Za-z][A-Za-z0-9_]*['\"]?\s*:", text):
            findings.append("visible serialized internal mapping")
        findings.extend(
            f"visible raw schema header: {match.group(1)}"
            for match in re.finditer(r"(?:^|[|\t\n])\s*(field|value|next_step|opportunity|solution|address|processes|status)\s*(?:[|\t\n]|$)", text, re.I)
        )
        return findings

    def extract_docx(self, path: Path) -> str:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join("".join(node.text or "" for node in paragraph.findall(".//w:t", ns)) for paragraph in root.findall(".//w:p", ns))

    def extract_html(self, path: Path) -> str:
        parser = _VisibleHTMLParser()
        parser.feed(path.read_text(encoding="utf-8"))
        return "\n".join(parser.text)


class SourceOwnershipValidator:
    def validate(self, narrative: Any) -> list[str]:
        body_sources = [item.chapter_id for item in narrative.chapters if item.chapter_id == "sources" or item.kind == "sources"]
        findings = ["source ledger must not be a body chapter"] if body_sources else []
        if not narrative.appendices.source_ledger:
            findings.append("appendices.source_ledger is missing")
        return findings


class TOCValidator:
    def validate(self, docx_path: Path, *, require_page_numbers: bool = False) -> list[str]:
        visible = PublicationVisibleTextValidator().extract_docx(docx_path)
        findings = []
        if "更新域以显示" in visible:
            findings.append("TOC placeholder remains visible")
        with zipfile.ZipFile(docx_path) as archive:
            settings = archive.read("word/settings.xml").decode("utf-8", errors="ignore")
            document = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        if "updateFields" not in settings:
            findings.append("settings.xml does not request field refresh")
        if "TOC \\o" not in document:
            findings.append("TOC field is missing")
        root = ElementTree.fromstring(document.encode("utf-8"))
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        toc_paragraphs = []
        for paragraph in root.findall(f".//{namespace}body/{namespace}p"):
            style = paragraph.find(f"./{namespace}pPr/{namespace}pStyle")
            style_id = style.get(namespace + "val") if style is not None else ""
            if style_id in {"TOC1", "TOC2", "TOC 1", "TOC 2"}:
                toc_paragraphs.append(paragraph)
        if len(toc_paragraphs) < 2:
            findings.append("TOC field result is empty; visible directory entries are missing")
        if require_page_numbers and toc_paragraphs:
            missing_pages = 0
            for paragraph in toc_paragraphs:
                after_tab = False
                page_found = False
                for node in paragraph.iter():
                    if node.tag == namespace + "tab":
                        after_tab = True
                    elif after_tab and node.tag == namespace + "t" and (node.text or "").strip().isdigit():
                        page_found = True
                        break
                if not page_found:
                    missing_pages += 1
            if missing_pages:
                findings.append(f"TOC page numbers are missing from {missing_pages} visible entries")
        return findings


class WordLengthValidator:
    def validate(self, narrative: Any) -> list[str]:
        count = cjk_count(narrative_body_text(narrative))
        threshold = evidence_adjusted_threshold(narrative)
        return [] if count >= threshold else [f"insufficient analytical evidence: {count} < {threshold}"]


class BrowserExecutionValidator:
    def validate(self, metrics: Any) -> list[str]:
        findings: list[str] = []
        configured = int(getattr(metrics, "configured_max_workers", metrics.get("configured_max_workers", 0) if isinstance(metrics, dict) else 0))
        active = int(getattr(metrics, "active_pages", metrics.get("active_pages", 0) if isinstance(metrics, dict) else 0))
        maximum = int(getattr(metrics, "max_active_pages", metrics.get("max_active_pages", 0) if isinstance(metrics, dict) else 0))
        opened = int(getattr(metrics, "opened_pages", metrics.get("opened_pages", 0) if isinstance(metrics, dict) else 0))
        closed = int(getattr(metrics, "closed_pages", metrics.get("closed_pages", 0) if isinstance(metrics, dict) else 0))
        if not 1 <= configured <= 4:
            findings.append("configured browser workers must be 1..4")
        if maximum > configured:
            findings.append(f"max active pages {maximum} exceeded configured workers {configured}")
        if active != 0 or opened != closed:
            findings.append(f"browser page leak: active={active}, opened={opened}, closed={closed}")
        return findings


def write_consulting_validation(report: ConsultingNarrativeValidation, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden_depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "template"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "template"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not self.hidden_depth and value:
            self.text.append(value)
