from __future__ import annotations

import argparse
import json
from pathlib import Path


PLAN = {
    0: ("fig0_key_numbers", "kpi-cards", "key_numbers.csv", "metric", "value", "关键指标", "数值", "核心结论与证据状态", "澳洲 V2G 关键市场数字", "Road Genius、ARENA、The Driven、本研究建模（2026-08）"),
    1: ("fig1_ev_sales_trend", "line", "ev_sales.csv", "year", "sales", "年份", "EV 销量（辆）", "一、执行摘要与决策问题", "澳洲 EV 年销量（2023-2025）", "Road Genius 澳洲 EV 销量统计（2025 年 6 月）"),
    2: ("fig2_evidence_tiers", "donut", "evidence_tiers.csv", "tier", "count", "来源层级", "数量", "二、调研边界、方法与证据体系", "证据来源层级分布", "来源台账（00_Source_Ledger，2026-08-12）"),
    3: ("fig3_tariff_spread", "scenario-range", "tariff_spread.csv", "period", "price", "时段", "上网电价（c/kWh）", "三、宏观电力环境、政策、电价与市场准入", "NSW 上网电价分时结构", "IPART 2025-26 太阳能上网电价基准报告（2025-05）"),
    4: ("fig4_som_2030", "scenario-range", "som2030.csv", "scenario", "units", "情景", "SOM（台）", "四、市场规模、细分、产业链与增长情景", "2030 年澳洲 V2G 充电器装机规模（SOM）", "本研究建模输出（13_Model_Results，2026-08）"),
    5: ("fig5_user_segments", "scorecards", "segments.csv", "segment", "score", "细分市场", "综合得分（1-5）", "五、用户类型、负荷与应用场景", "细分市场优先级评分", "本研究建模输出（Q3 多准则矩阵，2026-08）"),
    6: ("fig6_power_models", "dot-plot", "power_models.csv", "model", "power_kw", "型号", "功率（kW）", "六、产品系统架构、工程参数与区域合规", "各型号双向功率对比", "各品牌官方产品页与经销商资料（2026-08）"),
    7: ("fig7_pain_scores", "rating-tiles", "pain_scores.csv", "model", "score", "型号", "痛点评分（1低5高）", "七、竞争格局、玩家分类与精确型号对标", "竞品用户痛点评分", "评论语料主题编码（08_Review_Coding，2026-08）"),
    8: ("fig8_charger_price", "dot-plot", "charger_price.csv", "model", "price_aud", "型号", "价格（AUD）", "八、定价、渠道、安装与服务网络", "澳洲 V2G 双向充电器价格带（2026 年 8 月）", "各品牌官网、经销商报价及 Solar Choice（2026）"),
    9: ("fig9_review_themes", "pareto", "themes.csv", "theme", "frequency", "主题", "频次", "九、原始评论、用户痛点与购买驱动", "评论主题频次与累计占比", "评论语料主题编码（2026-08）"),
    10: ("fig10_payback", "decision-cards", "payback.csv", "scenario", "years", "情景", "回收期（年）", "十、经济性、数学模型与敏感性", "V2G 住宅投资回收期（低/基准/高情景）", "本研究建模输出（13_Model_Results，2026-08）"),
    11: ("fig11_pilots", "bubble-ranking", "pilots.csv", "pilot", "scale", "试点项目", "规模（户/辆）", "十一、V2G/V2H、VPP与试点项目", "V2G 试点规模对比", "ARENA、ActewAGL、The Driven（2023-2026）"),
    12: ("fig12_strategy", "lollipop", "segments.csv", "segment", "score", "进入维度", "优先级得分", "十二、产品定义与市场进入策略", "产品进入策略优先级", "本研究策略综合（Q3，2026-08）"),
    13: ("fig13_risks", "risk-tiles", "risks.csv", "risk", "level", "风险项", "风险等级（1-5）", "十三、风险、路线图与行动计划", "主要风险等级评估", "本研究 SWOT 与风险分析（2026-08）"),
    14: ("fig14_sources", "funnel", "source_tiers.csv", "tier", "count", "来源层级", "数量", "十四、来源、假设、证据问题与附录", "来源层级分布", "来源台账（00_Source_Ledger，2026-08-12）"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic UTF-8 figure specs for text-only-model regression.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--spec-dir", default="intermediate/specs_text_only")
    parser.add_argument("--output-dir", default="deliverables/charts_text_only")
    args = parser.parse_args()
    project = Path(args.project_dir).resolve()
    spec_dir = project / args.spec_dir
    spec_dir.mkdir(parents=True, exist_ok=True)
    for chapter, values in PLAN.items():
        figure_id, figure_type, csv_name, category, value, xlabel, ylabel, section, caption, source = values
        spec = {
            "figure_id": figure_id,
            "title": caption,
            "figure_class": "modeling" if chapter in {4, 5, 10, 12} else "market-insight",
            "figure_type": figure_type,
            "archetype": "single-evidence-chart",
            "role": "decision" if chapter in {5, 10, 12, 13} else "discovery",
            "core_claim": caption,
            "claim_confirmed": True,
            "panel_map": {"a": caption},
            "source_data": f"intermediate/chart_data/{csv_name}",
            "data_provenance": "calculated" if chapter in {4, 5, 10, 12} else "observed",
            "visual_intent": figure_type.replace("-", " "),
            "encoding": {"category": category, "value": value, "xlabel": xlabel, "ylabel": ylabel},
            "figsize": [6.1417, 4.2],
            "dpi": 300,
            "minimum_font_size_pt": 8,
            "show_title": False,
            "report_placement": {
                "chapter_number": chapter,
                "section_heading": section,
                "caption": caption,
                "source_note": f"数据来源：{source}。",
            },
            "output_stem": f"{args.output_dir}/{figure_id}",
        }
        (spec_dir / f"{figure_id}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(PLAN)} text-only-safe UTF-8 specs: {spec_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
