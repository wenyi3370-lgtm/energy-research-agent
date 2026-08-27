from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from _common import write_json
from build_executive_presentation import build
from create_page_contact_sheet import build_contact_sheets
from libreoffice_render import convert_to_pdf, prepend_bundled_runtime_bin, render_pdf_pages
from register_ppt_delivery import main as _register_main  # imported to prove the module remains loadable
from resolve_presentation_images import resolve
from validate_ppt_delivery import validate


def make_figure(path: Path) -> None:
    years = [2025, 2026, 2027, 2028, 2029, 2030]
    values = [1.0, 1.22, 1.50, 1.82, 2.15, 2.48]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(years, values, color="#0033A0", linewidth=2.6, marker="o", markersize=5)
    ax.fill_between(years, values, [0.9] * len(years), color="#2E5BFF", alpha=0.08)
    ax.set_title("Addressable market expands only after policy and economics gates", loc="left", fontsize=12, weight="bold")
    ax.set_ylabel("Index (2025=1.0)")
    ax.set_xticks(years)
    ax.grid(axis="y", color="#D0D3D9", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, facecolor="white")
    plt.close(fig)


def make_cover_fixture(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.set_facecolor("#0B1F4B")
    ax.add_patch(plt.Rectangle((0.46, 0.12), 0.18, 0.56, color="#2E5BFF", alpha=0.95))
    ax.add_patch(plt.Rectangle((0.67, 0.25), 0.18, 0.43, color="#147D64", alpha=0.95))
    ax.plot([0.12, 0.46, 0.67, 0.88], [0.28, 0.48, 0.52, 0.76], color="white", linewidth=3, alpha=0.85)
    ax.scatter([0.12, 0.46, 0.67, 0.88], [0.28, 0.48, 0.52, 0.76], s=150, color="#D7DEEA", edgecolor="#2E5BFF", linewidth=2)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, facecolor="#0B1F4B", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def sample_plan(figure_path: str) -> dict:
    source = "SRC-OFFICIAL-01；SRC-INDUSTRY-02；模型结果 MR-01"
    bias = "测试数据用于回归；正式项目必须替换为R1/R2/R3证据与已确认模型口径"
    return {
        "deck": {
            "title": "目标国户用储能市场深度研究",
            "subtitle": "增长并不自动转化为利润：进入节奏必须由政策与单位经济性共同决定",
            "eyebrow": "ENERGY MARKET & PRODUCT INTELLIGENCE",
            "meta": "三轮饱和采集 · 竞争与经济性联合判断",
            "update_date": "2026-08-09",
            "confidentiality": "内部使用",
        },
        "slides": [
            {"slide_id": "S01", "layout": "cover", "title": "目标国户用储能市场深度研究"},
            {
                "slide_id": "S02", "layout": "executive_summary", "section": "EXECUTIVE SUMMARY",
                "title": "增长窗口已经出现，但只有轻资产试点能够同时控制政策与需求误判风险", "answer_first": True,
                "items": [
                    {"title": "市场", "text": "未来五年需求保持两位数增长，但可服务市场集中在高电价、光伏渗透和备电需求同时成立的区域。"},
                    {"title": "经济性", "text": "基准回收期仍受峰谷价差和补贴影响，不能用全国平均电价替代目标客群的真实负荷曲线。"},
                    {"title": "进入", "text": "先用渠道合作和软件能力验证转化率，再决定是否配置本地库存、安装网络及售后团队。"},
                ],
                "kpis": [{"value": "2.48×", "label": "2030年可服务需求指数"}, {"value": "3个", "label": "必须同时满足的商业化门槛"}, {"value": "12月", "label": "首轮试点验证周期"}, {"value": "≤5年", "label": "目标客群回收期门槛"}],
                "takeaway": "建议批准可逆的渠道试点，不建议在经济性验证前形成重资产承诺。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S03", "layout": "figure", "section": "MARKET",
                "title": "政策与电价门槛打开后，可服务市场到2030年扩大至2025年的2.48倍", "answer_first": True,
                "figure_path": figure_path,
                "items": [{"title": "增长来源", "text": "分布式光伏、电价上涨和备电韧性共同提高储能价值。"}, {"title": "非线性约束", "text": "并网规则或补贴退坡会改变增长斜率，不能把单一CAGR当作确定预测。"}, {"title": "优先区域", "text": "高电价、独立住宅占比高且安装商网络成熟的区域优先。"}],
                "takeaway": "市场规模是必要条件，政策可执行性和客户现金流才是进入门槛。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S04", "layout": "timeline", "section": "POLICY",
                "title": "监管开放分三步推进，商业化资源应在并网与聚合规则明确后集中投入", "answer_first": True,
                "items": [
                    {"period": "2025", "title": "技术试点", "text": "验证设备安全、并网响应与数据接口，规模小且商业收益有限。"},
                    {"period": "2026", "title": "规则成型", "text": "明确并网认证、计量结算与聚合商责任，是渠道签约的前置条件。"},
                    {"period": "2027", "title": "区域放量", "text": "重点地区形成可复制套餐，安装与售后能力开始决定份额。"},
                    {"period": "2028+", "title": "平台化", "text": "通过虚拟电厂和动态电价叠加收益，软件能力成为差异化核心。"},
                ],
                "takeaway": "以规则落地而非新闻发布时间作为资源投入触发器。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S05", "layout": "segments", "section": "CUSTOMER",
                "title": "高电价独立住宅客群贡献最清晰的首批需求，应作为渠道试点唯一主目标", "answer_first": True,
                "items": [
                    {"title": "高电价独立住宅", "text": "已有光伏、白天发电富余且晚间负荷高，对自发自用和备电价值感知最强。", "barrier": "安装合规与回收期透明", "metric": "优先级：高"},
                    {"title": "新建住宅项目", "text": "可在设计阶段联合配置，但项目周期长、开发商议价强且交付节奏不稳定。", "barrier": "地产合作与项目认证", "metric": "优先级：中"},
                    {"title": "租赁与公寓客群", "text": "产权、空间和并网约束明显，除非存在共享储能机制，否则近期可服务性有限。", "barrier": "产权与公共区域审批", "metric": "优先级：低"},
                ],
                "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S06", "layout": "matrix", "section": "COMPETITION",
                "title": "主流品牌集中在高价高能力区，中等容量与强本地服务仍存在定位空白", "answer_first": True,
                "quadrants": ["高价值/低门槛", "高价值/高门槛", "低价值/低门槛", "低价值/高门槛"],
                "points": [{"label": "品牌A", "x": 0.72, "y": 0.82}, {"label": "品牌B", "x": 0.64, "y": 0.70}, {"label": "品牌C", "x": 0.32, "y": 0.48}, {"label": "目标定位", "x": 0.55, "y": 0.76}],
                "items": [{"title": "空白带", "text": "不是最低价格，而是安装、保修和能源管理体验的组合。"}, {"title": "反证", "text": "如果渠道服务成本高于毛利空间，空白带并不等于可盈利机会。"}],
                "takeaway": "先验证服务成本，再锁定价格带。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S07", "layout": "comparison", "section": "PRODUCT",
                "title": "标准化硬件加本地化软件服务，比追求最大容量更能形成首发产品优势", "answer_first": True,
                "items": [
                    {"title": "建议方案", "headline": "10–15 kWh", "text": "覆盖核心晚间负荷，保留模块化扩容；开放主流逆变器和能源管理接口。", "metric": "优先：安装效率+软件体验"},
                    {"title": "高端竞品", "headline": "15–20 kWh", "text": "品牌与生态能力强，但价格高、渠道封闭，对非核心客群形成预算压力。", "metric": "优势：品牌与集成"},
                    {"title": "低价竞品", "headline": "5–10 kWh", "text": "初始价格低，但本地认证、质保和售后覆盖可能成为成交阻力。", "metric": "优势：入门价格"},
                ],
                "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S08", "layout": "figure", "section": "ECONOMICS",
                "title": "只有峰谷价差、光伏富余和补贴同时达到门槛，五年内回收才可能成立", "answer_first": True,
                "image_request_id": "use_case_illustration",
                "diagram_title": "户用储能价值闭环",
                "diagram_steps": ["光伏富余", "电池充放", "峰谷优化", "账单与备电价值"],
                "items": [{"title": "基准", "text": "以目标客群逐时负荷和当地电价计算，不使用全国平均家庭替代。"}, {"title": "敏感项", "text": "利用小时、价差、设备成本和电池衰减共同决定回收期。"}, {"title": "止损线", "text": "若试点回收期持续高于五年，应转向软件或渠道合作模式。"}],
                "takeaway": "经济性不成立时保留数据与平台能力，不扩大硬件库存。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S09", "layout": "swot", "section": "STRATEGY",
                "title": "机会来自增长与服务空白，主要风险则集中在规则变化和本地履约成本", "answer_first": True,
                "items": [
                    {"title": "优势", "text": "模块化产品、能源管理算法和供应链成本控制可形成组合优势。"},
                    {"title": "劣势", "text": "本地品牌认知、安装商关系与售后网点尚未形成规模。"},
                    {"title": "机会", "text": "高电价区域增长、存量光伏改造和聚合服务带来分层机会。"},
                    {"title": "威胁", "text": "认证变化、补贴退坡、渠道排他与价格战可能侵蚀毛利。"},
                ],
                "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S10", "layout": "roadmap", "section": "ENTRY ROADMAP",
                "title": "先验证渠道与单位经济性、再配置本地履约能力，可将不可逆投入推迟十二个月", "answer_first": True,
                "items": [
                    {"period": "0–3个月", "title": "证据闭环", "text": "完成认证路线、目标客群访谈、渠道成本和逐时经济性复核。", "gate": "关键参数覆盖率≥90%"},
                    {"period": "4–9个月", "title": "小规模试点", "text": "与两类渠道完成真实安装、转化率和售后成本验证。", "gate": "回收期≤5年且NPS达标"},
                    {"period": "10–18个月", "title": "选择性扩张", "text": "只在通过门槛的区域配置库存、认证与服务网络。", "gate": "贡献毛利覆盖本地履约"},
                ],
                "takeaway": "每阶段都设置退出条件，避免把增长预测误当成确定订单。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S11", "layout": "decision", "section": "DECISIONS",
                "title": "管理层当前只需批准三项可逆决策，无需提前承诺重资产进入", "answer_first": True,
                "items": [
                    {"title": "批准目标客群", "text": "聚焦高电价独立住宅，不在首轮覆盖公寓与低价地区。", "owner": "市场｜2周", "gate": "访谈与订单意向闭环"},
                    {"title": "批准渠道试点", "text": "选择安装商和能源服务商各一类伙伴完成真实交付。", "owner": "渠道｜3个月", "gate": "获客与安装成本达标"},
                    {"title": "批准产品验证", "text": "冻结10–15 kWh模块化方案和本地化软件最小范围。", "owner": "产品｜6个月", "gate": "认证、可靠性与毛利达标"},
                    {"title": "保留退出权", "text": "政策延期或回收期超门槛时暂停库存与团队扩张。", "owner": "管理层｜季度", "gate": "证据审计触发复核"},
                ],
                "takeaway": "所有投入均绑定明确责任人、时间和可测量通过门槛。", "source": source, "bias_note": bias,
            },
            {
                "slide_id": "S12", "layout": "closing", "section": "NEXT STEP",
                "title": "以小规模验证换取下一阶段选择权",
                "items": [{"title": "补齐证据", "text": "关闭政策、价格与安装成本的高风险缺口。"}, {"title": "验证交易", "text": "用真实客户和渠道数据检验转化率与回收期。"}, {"title": "条件扩张", "text": "仅在门槛通过后增加库存、认证与本地团队。"}],
                "source": "内部决策材料｜以最终证据审计为准",
            },
        ],
    }


def render(pptx_path: Path, qa_dir: Path) -> None:
    prepend_bundled_runtime_bin()
    qa_dir.mkdir(parents=True, exist_ok=True)
    pdf = convert_to_pdf(pptx_path, qa_dir, 120)
    render_pdf_pages(pdf, qa_dir, 120)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the embedded presentation end-to-end regression.")
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    work_dir = Path(args.work_dir).resolve()
    project_dir = work_dir / "project"
    deliverables = project_dir / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    figure_path = project_dir / "deliverables" / "charts" / "fig1_market_trend.png"
    make_figure(figure_path)

    requests_path = project_dir / "presentation_image_requests.json"
    write_json(
        requests_path,
        {
            "requests": [
                {"request_id": "cover_hero", "role": "cover", "prompt": "Residential solar, home battery, inverter and grid ecosystem on the right side", "output_format": "png"},
                {"request_id": "use_case_illustration", "role": "body", "prompt": "A household energy flow from rooftop solar through a battery to evening appliances", "output_format": "png"},
            ]
        },
    )
    resolve(project_dir, requests_path, offline_reason="insufficient_balance:Regression fixture for the EWO no-balance path")
    acquisition_path = project_dir / "presentation_project" / "image_acquisition_manifest.json"

    plan_path = project_dir / "presentation_plan.json"
    plan = sample_plan(str(figure_path.relative_to(project_dir)).replace("\\", "/"))
    plan["slides"][4]["title"] += "，首轮不应同时覆盖产权复杂、安装受限且支付意愿尚未验证的边缘客群"
    write_json(plan_path, plan)
    first_pptx = deliverables / "presentation_first_render.pptx"
    build(project_dir, plan_path, acquisition_path, first_pptx)
    render(first_pptx, project_dir / "presentation_project" / "qa_first")

    plan["slides"][4]["title"] = "高电价独立住宅客群贡献最清晰的首批需求，应作为渠道试点唯一主目标"
    write_json(plan_path, plan)
    final_pptx = deliverables / "市场调研内部宣讲PPT.pptx"
    build(project_dir, plan_path, acquisition_path, final_pptx)
    qa_dir = project_dir / "presentation_project" / "qa"
    render(final_pptx, qa_dir)
    build_contact_sheets(qa_dir, qa_dir / "contact", columns=4, rows=3, thumb_width=300)

    issues = validate(project_dir, final_pptx, qa_dir, mode="final")
    fails = [issue for issue in issues if issue.level == "fail"]
    if fails:
        raise AssertionError("PPT regression validation failed: " + "; ".join(f"{item.row}/{item.field}: {item.message}" for item in fails[:20]))

    import sys

    original = sys.argv
    try:
        sys.argv = [
            "register_ppt_delivery.py", "--project-dir", str(project_dir), "--pptx", str(final_pptx),
            "--qa-render-dir", str(qa_dir), "--pages-inspected", "12", "--confirm-all-pages-inspected",
            "--visual-fix-cycle-count", "1", "--visual-inspection-notes",
            "First render showed excessive title density on slide 5; shortened the answer-first title and rerendered all 12 slides.",
            "--fallback-reason", "Regression fixture intentionally exercises the Python-native fallback renderer.",
        ]
        _register_main()
    finally:
        sys.argv = original

    # Path A smoke: use a local raster fixture to test format/hash/embed gates without spending EWO balance.
    path_a_project = work_dir / "path_a_project"
    path_a_project.mkdir(parents=True, exist_ok=True)
    cover_fixture = path_a_project / "presentation_project" / "images" / "cover_hero.png"
    make_cover_fixture(cover_fixture)
    from presentation_production import sha256_file

    path_a_acquisition = path_a_project / "presentation_project" / "image_acquisition_manifest.json"
    write_json(
        path_a_acquisition,
        {
            "cover_decision": {"default_path": "A_ai_image", "path_taken": "A_ai_image", "ai_image_request_id": "cover_hero", "fallback_reason": {}},
            "requests": [{"request_id": "cover_hero", "role": "cover", "status": "generated", "path": "presentation_project/images/cover_hero.png", "format": "png", "sha256": sha256_file(cover_fixture), "provider": "test_fixture"}],
        },
    )
    path_a_plan = path_a_project / "presentation_plan.json"
    write_json(path_a_plan, sample_plan(str(figure_path)))
    path_a_pptx = path_a_project / "path_a_smoke.pptx"
    build(path_a_project, path_a_plan, path_a_acquisition, path_a_pptx)
    path_a_fails = [item for item in validate(path_a_project, path_a_pptx, path_a_project / "qa", mode="draft") if item.level == "fail"]
    if path_a_fails:
        raise AssertionError("Path A smoke failed: " + "; ".join(f"{item.row}/{item.field}: {item.message}" for item in path_a_fails))
    print("Presentation delivery regression: PASS")
    print(final_pptx)
    print(qa_dir / "contact" / "contact-1.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
