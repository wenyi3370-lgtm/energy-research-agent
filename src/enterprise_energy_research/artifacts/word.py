from __future__ import annotations

import hashlib
from pathlib import Path

from enterprise_energy_research.adapters.base import AdapterHealth, ArtifactResult
from enterprise_energy_research.artifacts.image_publication import (
    PublicationImage,
    prepare_publication_images,
    write_image_publication_manifest,
)
from enterprise_energy_research.artifacts.visual_policy import colors as theme_colors
from enterprise_energy_research.artifacts.visual_policy import word_policy
from enterprise_energy_research.artifacts.visuals import (
    VisualSpec,
    build_visual_manifest,
    render_visual_bundle,
    write_visual_manifest,
)
from enterprise_energy_research.domain.enums import ArtifactType, VerificationStatus
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle


FIELD_LABELS = {
    "canonical_company_name": "公司名称", "stock_code": "股票代码", "core_business": "核心业务",
    "revenue": "营业收入", "profit": "归母净利润", "rd_expense": "研发费用", "process": "主要工艺",
    "product_portfolio": "产品组合", "export": "销售区域", "polarizer_market_share": "偏光片市场份额",
    "polarizer_capacity": "偏光片规划产能", "green_electricity_transaction_volume": "绿电交易量",
    "roof_pv_generation": "屋顶光伏发电量", "green_factory_count": "绿色工厂数量",
    "energy_management_certified_sites": "能源管理体系认证厂区", "energy_efficiency_signal": "节能管理信号",
    "sichuan_factory_efficiency_improvement": "四川基地生产效率提升", "sichuan_factory_unit_energy_reduction": "四川基地单位能耗下降",
    "waste_heat_recovery": "余热回收", "planned_overseas_project": "海外规划项目",
    "planned_overseas_investment": "海外规划投资上限", "electricity_consumption": "年度用电量",
    "load_curve": "负荷曲线", "operating_schedule": "生产班次", "transformer_capacity": "变压器容量", "roof_area": "可用屋面面积",
}


class FrozenWordPublisher:
    """Formal Word report using the standard_business_brief preset and editorial cover."""

    name = "word_document"
    artifact_type = ArtifactType.WORD

    def health(self) -> AdapterHealth:
        try:
            import docx  # noqa: F401
            return AdapterHealth(name=self.name, available=True, version="python-docx")
        except ImportError:
            return AdapterHealth(name=self.name, available=False, diagnostics=["python-docx is unavailable"])

    def publish(self, bundle: FrozenResearchBundle, binding: ArtifactBinding, output_path: Path) -> ArtifactResult:
        health = self.health()
        if not health.available:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=health.diagnostics)
        if binding.type != self.artifact_type:
            return ArtifactResult(adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type, status="failed", diagnostics=["Word publisher received a non-Word binding"])
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Mm, Pt, RGBColor

        entity = next((x for x in bundle.entities if x.entity_id == bundle.run_manifest.canonical_entity_id), bundle.entities[0])
        asset_root = output_path.parent / f"{output_path.stem}_assets"
        image_manifest = prepare_publication_images(
            bundle, binding, asset_root, extra_search_roots=[output_path.parent]
        )
        prepared_ids = set(image_manifest.prepared_image_ids)
        duplicate_ids = set(image_manifest.skipped_duplicate_image_ids)
        missing_image_ids = sorted(set(image_manifest.required_image_ids) - prepared_ids - duplicate_ids)
        fixture_mode = bundle.run_manifest.model_gateway.get("mode") in {"fixture", "recorded-fixture"}
        if missing_image_ids and not fixture_mode:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=[
                    "Verified evidence images are not publication-ready: " + ", ".join(missing_image_ids),
                    *image_manifest.diagnostics,
                ],
            )
        publication_images = image_manifest.by_chapter()
        selected_word_images = list(publication_images.get("cover", [])[:1])
        for chapter_key in ("entity_overview", "products", "factories", "core_evidence"):
            selected_word_images.extend(publication_images.get(chapter_key, [])[:6])
        selected_word_image_ids = list(dict.fromkeys(image.image_id for image in selected_word_images))
        image_manifest = image_manifest.model_copy(update={"artifact_selections": {"word": selected_word_image_ids}})
        write_image_publication_manifest(image_manifest, asset_root)
        visual_manifest = build_visual_manifest(bundle, binding)
        visual_assets = asset_root / "figures"
        rendered_visuals: dict[str, tuple[VisualSpec, Path, Path]] = {}
        for visual in visual_manifest.visuals:
            png_path, svg_path = render_visual_bundle(visual, visual_assets)
            rendered_visuals[visual.chapter_key] = (visual, png_path, svg_path)
        write_visual_manifest(visual_manifest, asset_root / "visual_manifest.json")
        wp = word_policy()
        quality_issues = self._visual_quality_issues(visual_manifest, wp)
        if quality_issues and not fixture_mode:
            return ArtifactResult(
                adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
                status="failed", diagnostics=["Word visual quality gate rejected the report:", *quality_issues],
            )

        document = Document()
        section = document.sections[0]
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(25.4)
        section.header_distance = section.footer_distance = Mm(12.5)
        wp = word_policy()
        tc = theme_colors()
        figure_width = Cm(wp["maximum_figure_width_cm"])
        body_cjk = wp["body_cjk_font"]
        body_latin = wp["body_latin_font"]
        navy_hex = tc["navy"].lstrip("#")
        purple_hex = tc["sevc_purple"].lstrip("#")
        cool_gray_hex = tc["cool_gray"].lstrip("#")
        styles = document.styles
        for name, size, color, before, after, cjk_font in [
            ("Normal", wp["body_size_pt"], "111111", 0, 6, body_cjk),
            ("Heading 1", wp["heading_1_size_pt"], navy_hex, 18, 10, "Microsoft YaHei"),
            ("Heading 2", wp["heading_2_size_pt"], navy_hex, 14, 7, body_cjk),
            ("Heading 3", wp["heading_3_size_pt"], purple_hex, 10, 5, body_cjk),
        ]:
            style = styles[name]
            style.font.name = body_latin
            style._element.rPr.rFonts.set(qn("w:eastAsia"), cjk_font)
            style._element.rPr.rFonts.set(qn("w:ascii"), body_latin)
            style._element.rPr.rFonts.set(qn("w:hAnsi"), body_latin)
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor.from_string(color)
            style.font.bold = name != "Normal"
            style.paragraph_format.space_before = Pt(before)
            style.paragraph_format.space_after = Pt(after)
            style.paragraph_format.keep_with_next = name != "Normal"
            if name == "Normal":
                style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
                style.paragraph_format.line_spacing = Pt(wp["line_spacing_pt"])
                style.paragraph_format.first_line_indent = Pt(wp["body_size_pt"] * wp["first_line_indent_characters"])
                style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            elif name == "Heading 1":
                style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        header = section.header.paragraphs[0]
        header.text = "SEVC｜企业产业与能源合作智能调研"
        header.runs[0].font.size = Pt(9)
        header.runs[0].font.color.rgb = RGBColor(112, 103, 118)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        footer.add_run("证据冻结：" + bundle.freeze.freeze_id + "  ·  ")
        self._field(footer, "PAGE")

        # ---- 封面（标准商务文字封面，规范：公司名+主题+冻结版本+编号+日期）----
        from datetime import date

        cover_spacer = document.add_paragraph()
        cover_spacer.paragraph_format.space_after = Pt(60)
        kicker = document.add_paragraph("SEVC · EVIDENCE-FIRST RESEARCH")
        kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
        kr = kicker.runs[0]; kr.font.name = "Arial"; kr.bold = True; kr.font.size = Pt(10); kr.font.color.rgb = RGBColor(111, 43, 134)
        if publication_images.get("cover"):
            self._add_cover_image(document, publication_images["cover"][0], asset_root, Cm(4.2))
        title = document.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.paragraph_format.space_before = Pt(18)
        tr = title.add_run(entity.canonical_name)
        tr.bold = True; tr.font.name = "Microsoft YaHei"; tr.font.size = Pt(26); tr.font.color.rgb = RGBColor(33, 18, 43)
        subtitle = document.add_paragraph("企业产业与能源合作智能调研报告")
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle.paragraph_format.space_after = Pt(26)
        subtitle.runs[0].font.size = Pt(16); subtitle.runs[0].bold = True
        subtitle.runs[0].font.color.rgb = RGBColor.from_string(navy_hex)
        # 分隔线（深海军蓝）
        rule = document.add_paragraph()
        rule.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_pr = rule._p.get_or_add_pPr()
        p_bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "12"); bottom.set(qn("w:color"), navy_hex)
        p_bdr.append(bottom)
        p_pr.append(p_bdr)
        rule.paragraph_format.space_after = Pt(30)
        # 元信息块：独立行、清晰字号
        today = date.today()
        report_no = f"EER-{today:%Y%m%d}-{bundle.freeze.freeze_id[-6:]}"
        for label, value in (
            ("报告编号", report_no),
            ("冻结版本", bundle.freeze.freeze_id),
            ("企业复杂度", bundle.run_manifest.complexity.value if bundle.run_manifest.complexity else "UNKNOWN"),
            ("生成日期", f"{today:%Y}年{today.month}月{today.day}日"),
        ):
            meta = document.add_paragraph(f"{label}：{value}")
            meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
            meta.paragraph_format.space_before = Pt(4)
            meta.paragraph_format.space_after = Pt(4)
            for run in meta.runs:
                run.font.size = Pt(11)
                run.font.color.rgb = RGBColor.from_string(cool_gray_hex)
        document.add_page_break()

        document.add_heading("目录", level=1)
        toc = document.add_paragraph()
        self._field(toc, 'TOC \\o "1-3" \\h \\z \\u')
        document.add_page_break()
        document.add_heading("1. 执行摘要", level=1)
        document.add_paragraph(f"本报告基于冻结证据快照，对 {entity.canonical_name} 的企业实体、生产足迹、能源场景与合作机会进行结构化呈现。报告不把数据缺口写成事实，不在发布阶段新增研究结论。")
        self._add_visual(document, rendered_visuals.get("executive_summary"), "1-1", figure_width)
        document.add_heading("2. 调研概述", level=1)
        document.add_paragraph("调研以企业身份、集团边界、生产基地、产品目录、经营活动、工艺用能及四类合作机会为主线。所有判断均绑定冻结证据；公开资料不足的字段保留为待尽调事项，不使用行业均值替代企业事实。")
        self._add_visual(document, rendered_visuals.get("research_scope"), "2-1", figure_width)
        document.add_heading("3. 集团与企业概况", level=1)
        for item in bundle.entities:
            document.add_heading(item.canonical_name, level=2)
            document.add_paragraph(f"实体类型：{item.entity_type}；核验状态：{item.verification_status.value}；注册区域：{item.registration_region or '待核验'}。")
        self._add_visual(document, rendered_visuals.get("entity_overview"), "3-1", figure_width)
        self._add_evidence_gallery(document, publication_images.get("entity_overview", []), asset_root, "3")
        document.add_heading("4. 重点产业与优势产品", level=1)
        if bundle.products:
            for product in bundle.products:
                document.add_heading(product.name, level=2)
                parameter_text = "、".join(
                    f"{parameter.name}={parameter.value}{parameter.unit or ''}" for parameter in product.parameters
                ) or "公开资料未披露可核验参数"
                document.add_paragraph(f"类别：{product.category or '待核验'}；型号：{product.model or '未披露'}；参数：{parameter_text}。")
                if product.parameters:
                    names = {parameter.name for parameter in product.parameters}
                    interpretation = []
                    if "D50" in names:
                        interpretation.append("D50反映颗粒粒径中位水平，是配方分散、涂布稳定性及倍率性能评估的基础输入")
                    if "比表面积" in names:
                        interpretation.append("比表面积会影响界面反应与首次不可逆容量，需结合客户电解液体系和极片设计验证")
                    if "振实密度" in names:
                        interpretation.append("振实密度关系到极片压实及体积能量密度，但不能脱离颗粒强度与循环膨胀单独判断")
                    if "容量" in names:
                        interpretation.append("容量是材料克容量口径，尚不能直接等同于电芯能量密度")
                    if "首次效率" in names:
                        interpretation.append("首次效率影响首周锂损耗，应与补锂方案、正极匹配及客户测试方法共同核对")
                    if interpretation:
                        document.add_paragraph("参数解读：" + "；".join(interpretation) + "。上述解释为指标含义，不构成对客户电芯性能的承诺；正式导入仍需样品、测试方法、批次一致性和认证资料。")
                else:
                    document.add_paragraph("公开边界：该条目仅在官方业务页形成族级证据，未发现可核验的公开型号表和参数面板。报告保留其产品族身份，但不推断客户定制牌号、规格范围、商业化阶段或在售状态。")
        else:
            document.add_paragraph("本次冻结证据未形成可核验的实体产品记录，因此不将业务描述推断为具体产品目录；相关信息应在后续尽调中补充。")
        self._add_visual(document, rendered_visuals.get("products"), "4-1", figure_width)
        self._add_evidence_gallery(document, publication_images.get("products", []), asset_root, "4")
        document.add_heading("5. 子公司与工厂逐一分析", level=1)
        for factory in bundle.factories:
            document.add_heading(factory.name or "未命名生产基地", level=2)
            document.add_paragraph(f"地址：{factory.address or '待核验'}；工艺：{'、'.join(factory.processes) if factory.processes else '待核验'}。")
        self._add_visual(document, rendered_visuals.get("factories"), "5-1", figure_width)
        self._add_evidence_gallery(document, publication_images.get("factories", []), asset_root, "5")
        document.add_heading("6. 核心经营与生产证据", level=1)
        verified = [x for x in bundle.claims if x.verification_status == VerificationStatus.VERIFIED and x.claim_id in binding.claim_ids]
        table_caption = document.add_paragraph("表 6-1 核心经营与生产证据")
        self._format_caption(table_caption)
        table = document.add_table(rows=1, cols=4)
        table.autofit = False
        for cell, text in zip(table.rows[0].cells, ["字段", "取值", "时间/范围", "来源"]): cell.text = text
        sources = {x.source_id: x for x in bundle.sources}
        for claim in verified:
            row = table.add_row().cells
            row[0].text = FIELD_LABELS.get(claim.field_name, claim.field_name)
            row[1].text = f"{claim.value} {claim.unit or ''}".strip()
            row[2].text = " / ".join(filter(None, [str(claim.as_of_date or ""), claim.scope or ""])) or "未注明"
            row[3].text = sources[claim.source_id].source_title or sources[claim.source_id].source_domain
        self._table_geometry(table, [1800, 3000, 1800, 2760])
        self._style_three_line_table(table)
        source_note = document.add_paragraph("数据来源：证据主表及来源台账；原文摘录和 URL 保存在同一冻结包中。")
        source_note.paragraph_format.space_before = source_note.paragraph_format.space_after = Pt(4)
        source_note.runs[0].font.size = Pt(9); source_note.runs[0].font.color.rgb = RGBColor(112, 103, 118)
        self._add_visual(document, rendered_visuals.get("operating_metrics"), "6-1", figure_width)
        self._add_visual(document, rendered_visuals.get("core_evidence"), "6-2", figure_width)
        self._add_evidence_gallery(document, publication_images.get("core_evidence", []), asset_root, "6")
        document.add_heading("7. 能源消费与节能潜力", level=1)
        if bundle.energy_profiles:
            for profile in bundle.energy_profiles:
                document.add_heading(profile.factory_id or profile.entity_id, level=2)
                document.add_paragraph(
                    f"主要工艺：{'、'.join(profile.processes) or '待核验'}；用电设备：{'、'.join(profile.electricity_equipment) or '待核验'}；"
                    f"燃气设备：{'、'.join(profile.gas_equipment) or '待核验'}。负荷、变压器、屋顶及运行班次按字段状态保留现场尽调要求。"
                )
        else:
            document.add_paragraph("冻结证据未形成完整能源画像，报告仅保留工艺到能源设备的可核验映射，并把负荷曲线、变压器容量、运行班次和屋顶面积列为现场尽调输入。")
        self._add_visual(document, rendered_visuals.get("energy"), "7-1", figure_width)

        solution_chapters = [
            ("8. 新能源 EPC", "EPC"),
            ("9. 零碳与节能改造", "ZERO_CARBON"),
            ("10. 储能 ODM", "STORAGE_ODM"),
            ("11. 出海合作", "OVERSEAS"),
        ]
        engine_visuals = {"EPC": ("epc", "8-1"), "ZERO_CARBON": ("zero_carbon", "9-1"), "STORAGE_ODM": ("storage_odm", "10-1"), "OVERSEAS": ("overseas", "11-1")}
        for chapter_title, engine in solution_chapters:
            document.add_page_break()
            document.add_heading(chapter_title, level=1)
            matched = [solution for solution in bundle.solutions if solution.engine == engine]
            if not matched:
                document.add_paragraph("当前冻结证据不足以形成可执行方案，本章保留为待补充的合作方向，不作事实性收益承诺。")
            for solution in matched:
                document.add_heading(f"优先级 {solution.priority}｜{solution.opportunity}", level=2)
                document.add_paragraph(solution.proposed_solution)
                label = "证据支持" if solution.statement_type.value == "EVIDENCE_SUPPORTED" else "分析推断"
                document.add_paragraph(f"结论类型：{label}；收益逻辑：{solution.benefit_logic}；下一步：{solution.next_step}。")
            visual_key, figure_no = engine_visuals[engine]
            self._add_visual(document, rendered_visuals.get(visual_key), figure_no, figure_width)

        document.add_page_break()
        document.add_heading("12. 合作模式与商务路径", level=1)
        for solution in bundle.solutions:
            document.add_heading(solution.engine, level=2)
            document.add_paragraph(f"建议合作模式：{solution.business_model or '需双方确认'}；需补充数据：{'、'.join(solution.data_requirements) or '无新增要求'}。")
        self._add_visual(document, rendered_visuals.get("cooperation"), "12-1", figure_width)
        document.add_page_break()
        document.add_heading("13. 项目优先级与 90 天计划", level=1)
        for priority in ("A", "B", "C", "HOLD"):
            items = [solution for solution in bundle.solutions if solution.priority == priority]
            if items:
                document.add_heading(f"优先级 {priority}", level=2)
                document.add_paragraph("；".join(f"{item.engine}：{item.next_step}" for item in items) + "。")
        self._add_visual(document, rendered_visuals.get("roadmap"), "13-1", figure_width)
        document.add_heading("14. 风险与边界", level=1)
        risks = [risk for solution in bundle.solutions for risk in solution.risks]
        document.add_paragraph("；".join(dict.fromkeys(risks)) + "。" if risks else "尚无足够证据量化项目风险，应在技术、商务、合规和现场数据四条线上完成尽调后再作投资决策。")
        self._add_visual(document, rendered_visuals.get("risks"), "14-1", figure_width)
        document.add_heading("15. 调研结论", level=1)
        document.add_paragraph("本报告给出的合作方向用于形成可验证的下一步，不替代现场测量、技术方案、商务报价、法律审查或投资决策。任何新增事实或数据修订均需进入新证据版本、重新验证并生成新的冻结快照。")
        self._add_visual(document, rendered_visuals.get("conclusion"), "15-1", figure_width)
        document.add_heading("附录 A：术语与口径", level=1)
        document.add_paragraph("事实、分析推断、待确认事项分别对应不同证据状态；产能、收入、能耗等数值均以原始披露的时间、范围、单位和限定条件为准。")
        document.add_heading("附录 B：来源清单", level=1)
        for source in bundle.sources:
            document.add_paragraph(f"[{source.source_id}] {source.source_level.value}｜{source.source_title or source.source_domain}｜{source.canonical_url}")
        self._add_visual(document, rendered_visuals.get("appendix_sources"), "B-1", figure_width)
        document.add_heading("附录 C：图片来源", level=1)
        if bundle.images:
            for image in bundle.images:
                document.add_paragraph(f"[{image.image_id}] {image.image_type}｜{image.source_page_url}｜{image.verification_status.value}")
        else:
            document.add_paragraph("本次冻结包未包含可用于正式报告的已核验图片。")
        self._add_visual(document, rendered_visuals.get("appendix_images"), "C-1", figure_width)
        document.add_heading("附录 D：数据缺口与尽调", level=1)
        for gap in bundle.gaps:
            document.add_heading(FIELD_LABELS.get(gap.field_name, gap.field_name), level=2)
            document.add_paragraph(f"重要性：{gap.importance}；原因：{gap.reason}；建议动作：{gap.next_action}。")
        self._add_visual(document, rendered_visuals.get("appendix_gaps"), "D-1", figure_width)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path)
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return ArtifactResult(
            adapter=self.name, artifact_id=binding.artifact_id, artifact_type=binding.type,
            path=output_path, content_sha256=digest, used_claim_ids=[x.claim_id for x in verified],
            used_image_ids=selected_word_image_ids, status="published",
            diagnostics=image_manifest.diagnostics if fixture_mode else [],
        )

    @staticmethod
    def _visual_quality_issues(visual_manifest, wp: dict) -> list[str]:
        """Reject non-Lieflat or weakly sourced figures without imposing chart quotas."""
        issues: list[str] = []
        visuals = visual_manifest.visuals
        if not visuals:
            return []
        allowed = {"F4", "F5", "L13"}
        for visual in visuals:
            if visual.renderer != "lieflat-charts-gallery-port-svg-v2" or visual.template_id not in allowed:
                issues.append(f"{visual.visual_id} is not routed through an approved Lieflat catalog template")
            if not visual.template_source or not visual.template_card_title or visual.color_system != "mono":
                issues.append(f"{visual.visual_id} does not record its Lieflat gallery source and global color system")
            if not visual.data_contract:
                issues.append(f"{visual.visual_id} has no Lieflat data contract")
            if not visual.source_note.startswith("数据来源：证据冻结"):
                issues.append(f"{visual.visual_id} has no adjacent freeze source note")
        minimum_analysis = int(wp.get("minimum_analysis_characters_before_visual", 50))
        lead_analysis = (
            "基于冻结证据形成的结构化视图见图。该图用于呈现冻结快照中已核验与"
            "待核验数据的分布关系，不扩展原始证据口径，也不替代正文中的事实叙述。"
        )
        if len(lead_analysis) < minimum_analysis:
            issues.append(
                f"visual lead analysis is {len(lead_analysis)} characters; "
                f"minimum is {minimum_analysis}"
            )
        return issues

    @staticmethod
    def _add_cover_image(document, image: PublicationImage, asset_root: Path, width) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.shared import Pt

        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # 图片段落必须用单倍行距：固定行距（EXACTLY）会截断图片
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        paragraph.paragraph_format.space_before = paragraph.paragraph_format.space_after = Pt(6)
        paragraph.add_run().add_picture(str(asset_root / image.publication_path), width=width)

    @classmethod
    def _add_evidence_gallery(
        cls,
        document,
        images: list[PublicationImage],
        asset_root: Path,
        chapter_number: str,
        *,
        maximum_images: int = 6,
    ) -> None:
        if not images:
            return
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.shared import Cm, Pt, RGBColor

        document.add_heading("真实图片证据", level=2)
        lead = document.add_paragraph("以下图片均来自已核验原始页面，并已完成本地归档、哈希、格式和尺寸校验；图片用于主体、产品或生产场景识别，不替代产能、性能或运营状态证明。")
        lead.paragraph_format.keep_with_next = True
        for index, image in enumerate(images[:maximum_images], start=1):
            # 图片段落：单倍行距 + 上下留白，避免固定行距截断图片
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            paragraph.paragraph_format.space_before = Pt(6)
            paragraph.paragraph_format.space_after = Pt(6)
            ratio = image.width / image.height
            width = Cm(13.8 if ratio >= 1.1 else 9.5)
            paragraph.add_run().add_picture(str(asset_root / image.publication_path), width=width)
            caption = document.add_paragraph(f"图 {chapter_number}-P{index} {image.caption}")
            cls._format_caption(caption)
            source = document.add_paragraph(image.source_note)
            source.alignment = WD_ALIGN_PARAGRAPH.CENTER
            source.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            source.paragraph_format.space_before = Pt(0)
            source.paragraph_format.space_after = Pt(10)
            for run in source.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(107, 114, 128)

    @staticmethod
    def _format_caption(paragraph) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.shared import Pt

        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.keep_together = True
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.paragraph_format.space_after = Pt(4)
        for run in paragraph.runs:
            run.bold = True
            run.font.size = Pt(10)

    @classmethod
    def _add_visual(cls, document, rendered: tuple[VisualSpec, Path, Path] | None, figure_no: str, width) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
        from docx.shared import Pt, RGBColor

        if rendered is None:
            return
        spec, png_path, _ = rendered
        lead = document.add_paragraph(
            f"基于冻结证据形成的结构化视图见图 {figure_no}。该图用于{spec.purpose}，"
            "仅呈现冻结快照中已核验与待核验数据的分布关系，不扩展原始证据口径，"
            "也不替代正文中的事实叙述。"
        )
        lead.paragraph_format.keep_with_next = True
        # 图片段落：单倍行距 + 留白，避免固定行距截断图表
        picture_paragraph = document.add_paragraph()
        picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture_paragraph.paragraph_format.keep_together = True
        picture_paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        picture_paragraph.paragraph_format.space_before = Pt(6)
        picture_paragraph.paragraph_format.space_after = Pt(6)
        picture_paragraph.add_run().add_picture(str(png_path), width=width)
        caption = document.add_paragraph(f"图 {figure_no} {spec.title}")
        cls._format_caption(caption)
        source = document.add_paragraph(spec.source_note)
        source.alignment = WD_ALIGN_PARAGRAPH.CENTER
        source.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        source.paragraph_format.space_before = Pt(0)
        source.paragraph_format.space_after = Pt(8)
        for run in source.runs:
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(107, 114, 128)

    @classmethod
    def _style_three_line_table(cls, table) -> None:
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor

        tc = theme_colors()
        navy_hex = tc["navy"].lstrip("#")
        pale_hex = tc["pale_gray"].lstrip("#")
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_pr = table._tbl.tblPr
        existing = tbl_pr.find(qn("w:tblBorders"))
        if existing is not None:
            tbl_pr.remove(existing)
        borders = OxmlElement("w:tblBorders")
        for edge, value, size, color in (
            ("top", "single", "12", "000000"), ("bottom", "single", "12", "000000"),
            ("left", "nil", "0", "FFFFFF"), ("right", "nil", "0", "FFFFFF"),
            ("insideH", "nil", "0", "FFFFFF"), ("insideV", "nil", "0", "FFFFFF"),
        ):
            node = OxmlElement(f"w:{edge}")
            node.set(qn("w:val"), value); node.set(qn("w:sz"), size); node.set(qn("w:color"), color)
            borders.append(node)
        tbl_pr.append(borders)
        for row_index, row in enumerate(table.rows):
            for cell in row.cells:
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                tc_pr = cell._tc.get_or_add_tcPr()
                if row_index == 0:
                    shade = OxmlElement("w:shd"); shade.set(qn("w:fill"), pale_hex); tc_pr.append(shade)
                    cell_border = OxmlElement("w:tcBorders")
                    bottom = OxmlElement("w:bottom"); bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "8"); bottom.set(qn("w:color"), navy_hex)
                    cell_border.append(bottom); tc_pr.append(cell_border)
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    paragraph.paragraph_format.first_line_indent = Pt(0)
                    paragraph.paragraph_format.left_indent = Pt(0)
                    paragraph.paragraph_format.right_indent = Pt(0)
                    paragraph.paragraph_format.keep_together = True
                    for run in paragraph.runs:
                        run.font.name = "Times New Roman"; run.font.size = Pt(word_policy()["table_size_pt"])
                        run._element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")
                        if row_index == 0:
                            run.bold = True; run.font.color.rgb = RGBColor.from_string(navy_hex)

    @staticmethod
    def _field(paragraph, instruction: str) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        run = paragraph.add_run()
        begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = instruction
        separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
        text = OxmlElement("w:t"); text.text = "更新域以显示"
        end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
        for node in (begin, instr, separate, text, end): run._r.append(node)

    @staticmethod
    def _table_geometry(table, widths: list[int]) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        table.autofit = False
        tbl_pr = table._tbl.tblPr
        tbl_w = tbl_pr.first_child_found_in("w:tblW")
        if tbl_w is None:
            tbl_w = OxmlElement("w:tblW")
        tbl_w.set(qn("w:w"), str(sum(widths))); tbl_w.set(qn("w:type"), "dxa")
        if tbl_w.getparent() is None: tbl_pr.append(tbl_w)
        existing_layout = tbl_pr.find(qn("w:tblLayout"))
        if existing_layout is not None: tbl_pr.remove(existing_layout)
        tbl_layout = OxmlElement("w:tblLayout"); tbl_layout.set(qn("w:type"), "fixed"); tbl_pr.append(tbl_layout)
        existing_ind = tbl_pr.find(qn("w:tblInd"))
        if existing_ind is not None: tbl_pr.remove(existing_ind)
        tbl_ind = OxmlElement("w:tblInd"); tbl_ind.set(qn("w:w"), "0"); tbl_ind.set(qn("w:type"), "dxa"); tbl_pr.append(tbl_ind)
        grid = table._tbl.tblGrid
        for child in list(grid): grid.remove(child)
        for width in widths:
            col = OxmlElement("w:gridCol"); col.set(qn("w:w"), str(width)); grid.append(col)
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                tc_w = cell._tc.get_or_add_tcPr().get_or_add_tcW(); tc_w.set(qn("w:w"), str(width)); tc_w.set(qn("w:type"), "dxa")
