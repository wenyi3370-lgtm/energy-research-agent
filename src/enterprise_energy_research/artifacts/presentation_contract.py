from __future__ import annotations

from typing import Any

from enterprise_energy_research.artifacts.image_publication import PublicationImage
from enterprise_energy_research.domain.models import ArtifactBinding, FrozenResearchBundle


def build_presentation_contract(
    bundle: FrozenResearchBundle,
    binding: ArtifactBinding,
    publication_images: list[PublicationImage] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entity = next((item for item in bundle.entities if item.entity_id == bundle.run_manifest.canonical_entity_id), bundle.entities[0])
    claim_ids = [claim.claim_id for claim in bundle.claims if claim.claim_id in binding.claim_ids]
    publication_images = publication_images or []

    def placements(types: set[str], maximum: int, role: str) -> list[dict[str, Any]]:
        selected = [image for image in publication_images if image.image_type in types][:maximum]
        return [
            {
                "image_id": image.image_id,
                "image_type": image.image_type,
                "publication_path": image.publication_path,
                "caption": image.caption,
                "source_note": image.source_note,
                "role": role,
                "fit": "contain",
                "crop_policy": "no semantic crop; preserve product/factory identity",
            }
            for image in selected
        ]
    # section, action title, question, evidence themes, visual, kind, layout, so what, bias
    rows = [
        ("封面", f"{entity.canonical_name}：以冻结证据识别产业与能源合作切入点", "本次汇报研究谁、为了什么决策？", ["企业身份", "产业与产品", "能源与合作"], "TYPOGRAPHIC-COVER", "typographic_cover", "cover_hero", "所有结论均以同一冻结版本为边界。", "封面图片仅作已核验主体识别，不作为经营结论。"),
        ("结论先行", "优先从可核验场景启动，未量化收益在现场尽调后决策", "管理层现在可以相信什么、还不能相信什么？", ["高置信事实", "四类机会", "关键缺口"], "FIG-01-EXECUTIVE-DASHBOARD", "approved_chart", "three_column_evidence", "先批准尽调和联合验证，不把公开材料替代工程测量与商务报价。", "冻结证据覆盖不等于现场可行性。"),
        ("研究边界", "三轮检索、冻结与缺口登记共同控制结论边界", "研究如何避免把搜索片段写成事实？", ["来源分级", "主张核验", "缺口登记"], "FIG-02-RESEARCH-FUNNEL", "approved_chart", "full_width_process", "未进入冻结包的材料不得进入正式演示。", "公开资料可能滞后，关键字段仍需企业确认。"),
        ("企业身份", "先锁定法人与集团边界，再解释业务和能源足迹", "哪些主体真正属于本次研究范围？", ["标准主体", "别名与品牌", "区域与官网"], "FIG-03-ENTITY-MAP", "approved_framework", "entity_network", "主体边界未核验的工厂、产品和项目不得归因。", "网络图只展示冻结实体，不推断未核验控制关系。"),
        ("集团结构", "集团复杂度决定检索深度，也决定合作触达路径", "母子公司、经营主体和基地应如何分层？", ["母子关系", "经营主体", "覆盖缺口"], "FIG-03-ENTITY-MAP", "approved_framework", "two_panel_comparison", "商务推进必须绑定到真正拥有资产、工艺或渠道的主体。", "未核验控制边仅作待尽调项。"),
        ("产业布局", "产品目录覆盖比零散关键词更能揭示真实产业能力", "公司实际经营哪些产品族和工艺？", ["产品族", "型号参数", "应用场景"], "FIG-04-PRODUCT-PORTFOLIO", "approved_chart", "full_width_chart", "后续合作应从已核验产品族和工艺需求反推，不从行业标签臆测。", "产品数量是冻结目录计数，不代表市场份额。"),
        ("生产足迹", "基地与工艺足迹决定能源方案可落地的位置和顺序", "哪些基地具备可核验地址、工艺和运营线索？", ["基地清单", "地址", "主要工艺"], "FIG-05-FACTORY-FOOTPRINT", "approved_chart", "footprint_timeline", "优先选择证据完整且现场数据可获得的基地开展试点。", "工艺项数不等于产能或能耗规模。"),
        ("核心产品", "只展示可追溯产品与原图，缺图产品不得用占位图替代", "哪些实体产品、参数和图片可以进入正式材料？", ["实体产品", "参数口径", "原图溯源"], "FIG-04-PRODUCT-PORTFOLIO", "approved_chart", "product_gallery", "产品适配要进入样品、测试方法、批次一致性和认证验证。", "图片仅证明页面关联，不自动证明在售状态或客户适配。"),
        ("经营与项目", "经营数据必须保留时间、范围和冲突口径，不能只留一个数字", "哪些经营与项目数据足以支持合作判断？", ["经营指标", "项目进展", "口径冲突"], "FIG-06-OPERATING-KPIS", "approved_chart", "evidence_scoreboard", "把数据可信度与商业吸引力分开评价。", "不同范围和期间的数值不得直接比较。"),
        ("能源场景", "公开材料只能建立工艺—设备假设，负荷与能耗必须现场测量", "可从哪些工艺和设备识别能源合作场景？", ["主要工艺", "用能设备", "字段状态"], "FIG-07-ENERGY-CHAIN", "approved_framework", "three_column_evidence", "用现场数据把机会从方向判断推进到工程方案。", "设备映射不等于已测负荷。"),
        ("负荷与设施", "变压器、负荷曲线、班次和屋顶条件是方案测算的共同前置项", "哪些设施字段决定方案能否测算？", ["电力接入", "负荷曲线", "空间与班次"], "FIG-A3-GAP-REGISTER", "approved_framework", "gap_matrix", "将缺口清单直接转成现场尽调数据表。", "缺失字段保持缺失，不使用行业均值补齐。"),
        ("EPC机会", "EPC应从可用空间、接入条件和用能基线三项共同验证", "新能源 EPC 的最小可行验证是什么？", ["场址与接入", "方案边界", "商务模式"], "FIG-08-EPC", "approved_framework", "decision_canvas", "先形成可测量的基线和技术边界，再讨论投资与收益。", "未核验资源与电价条件不进入收益承诺。"),
        ("零碳机会", "零碳合作的核心不是口号，而是基线、M&V与碳边界", "节能和零碳项目如何形成可审计收益？", ["能耗基线", "M&V", "碳核算治理"], "FIG-09-ZERO-CARBON", "approved_framework", "value_bridge", "先统一口径和责任，再签订节能量或减排量相关条款。", "公开节能信号不等于项目可核证节能量。"),
        ("储能ODM机会", "储能 ODM 需同时通过产品适配、系统参数与认证责任三道门", "储能合作缺少哪些决定性输入？", ["产品适配", "功率与容量", "认证与质保"], "FIG-10-STORAGE-ODM", "approved_framework", "decision_tree", "以联合定义样品和测试规范替代泛化合作意向。", "材料或业务相关性不等于系统级 ODM 能力。"),
        ("海外机会", "出海合作必须把市场准入、渠道和售后责任放在同一进入模型", "海外市场进入需要哪些证据和责任划分？", ["目标市场", "认证准入", "渠道与售后"], "FIG-11-OVERSEAS", "approved_framework", "market_entry_matrix", "先确定单一目标市场和责任清单，再扩大区域。", "规划项目和意向市场不等于已落地产能或订单。"),
        ("合作路线图", "90天内完成证据补齐、联合验证与商务决策三次闸门", "如何把四类机会转化为可执行行动？", ["0–30天", "31–60天", "61–90天"], "FIG-13-ROADMAP", "approved_framework", "roadmap_timeline", "每个阶段以明确输入、输出和责任人结束。", "路线图为建议节奏，具体日期需双方确认。"),
        ("附录与来源", "来源、冻结哈希与缺口记录使全部结论可以复核和更新", "读者如何追溯本次结论？", ["来源层级", "冻结哈希", "免责声明"], "FIG-A1-SOURCE-MIX", "approved_chart", "evidence_appendix", "新事实必须进入新证据版本并重新发布。", "本材料不替代法律、工程、商务或投资尽调。"),
    ]
    slides: list[dict[str, Any]] = []
    for number, row in enumerate(rows, start=1):
        section, title, question, themes, visual_id, visual_kind, layout, so_what, bias = row
        slide_claims = [] if number == 1 else claim_ids[:12]
        image_placements: list[dict[str, Any]] = []
        if number == 1:
            image_placements = placements({"factory", "production_line", "product", "office", "logo"}, 1, "cover_hero")
        elif number == 4:
            image_placements = placements({"logo", "office", "other"}, 2, "identity_evidence")
        elif number == 6:
            image_placements = placements({"product", "production_line"}, 2, "industry_evidence")
        elif number == 7:
            image_placements = placements({"factory", "production_line", "location"}, 4, "factory_gallery")
        elif number == 8:
            image_placements = placements({"product"}, 4, "product_gallery")
        elif number == 10:
            image_placements = placements({"production_line", "factory"}, 3, "process_evidence")
        elif number == 13:
            image_placements = placements({"certificate"}, 2, "certificate_evidence")
        elif number == 15:
            image_placements = placements({"location", "factory", "product"}, 2, "market_evidence")
        slide_images = [placement["image_id"] for placement in image_placements]
        slides.append({
            "number": number,
            "section": section,
            "action_title": title,
            "question": question,
            "evidence_themes": themes,
            "visual_id": visual_id,
            "visual_kind": visual_kind,
            "layout_family": layout,
            "so_what": so_what,
            "source_ids": slide_claims,
            "image_ids": slide_images,
            "image_placements": image_placements,
            "visual_components": [visual_id, *slide_images],
            "footer": {"source_ids": slide_claims, "as_of": bundle.freeze.created_at.date().isoformat(), "bias_note": bias},
            "geometry_contract": {
                "canvas_px": [1280, 720], "title_baseline_y": 120, "footer_baseline_y": 678,
                "minimum_chart_font_pt": 8, "maximum_overlap_pt": 3,
                "no_wrap_tokens": ["page_number", "badge", "kpi_value_unit", "latin_word", "numeric_string"],
            },
        })
    evidence_map = {
        "schema_version": "1.0",
        "freeze_id": bundle.freeze.freeze_id,
        "slides": [
            {
                "slide": slide["number"], "visual_id": slide["visual_id"], "visual_kind": slide["visual_kind"],
                "claim_ids": slide["source_ids"], "image_ids": slide["image_ids"],
                "layout_family": slide["layout_family"], "source_footer_required": slide["number"] != 1,
            }
            for slide in slides
        ],
        "required_verified_image_ids": list(dict.fromkeys(
            image_id for slide in slides for image_id in slide["image_ids"]
        )),
        "image_placement_count": sum(len(slide["image_placements"]) for slide in slides),
    }
    return slides, evidence_map
