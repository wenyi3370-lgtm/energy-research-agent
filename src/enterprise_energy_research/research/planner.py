from __future__ import annotations

from enterprise_energy_research.domain.enums import EnterpriseComplexity, SourceLevel
from enterprise_energy_research.domain.ids import RunSequence, new_sortable_id
from enterprise_energy_research.domain.models import ResearchPlan, ResearchQuery


BASE_TOPICS = [
    ("identity", "官网 注册主体 曾用名 母公司 实际控制人"),
    ("organization", "组织架构 股权 子公司 成员企业"),
    ("factories", "生产基地 工厂 厂区 地址 生产线"),
    ("business", "主营业务 产业布局 核心客户 经营数据"),
    ("product_centers", "官网 产品中心 产品目录 子公司 产品品牌"),
    ("product_catalog", "产品分类 产品系列 产品清单 catalog portfolio"),
    ("product_models", "产品型号 牌号 series model SKU"),
    ("product_parameters", "技术参数 规格书 datasheet 手册 PDF"),
    ("product_applications", "产品应用场景 客户 行业 解决方案"),
    ("product_launches", "新品 发布 迭代 首发 产品矩阵"),
    ("energy", "工艺 设备 用电 天然气 蒸汽 空压 冷冻 变压器"),
    ("green", "绿色工厂 节能 碳 光伏 储能 能评 环评"),
    ("overseas", "出口 海外客户 海外工厂 经销商 认证"),
    ("projects", "招投标 项目 投资 产能 新闻 招聘"),
    ("images", "企业logo 厂区照片 产品照片 生产线"),
]

ROUND_SUFFIXES = {
    "R1": ("coverage", "候选来源 官方目录 公开披露"),
    "R2": ("depth", "原文 全文 明细 参数 地址 日期 PDF"),
    "R3": ("triangulation", "交叉验证 独立来源 冲突 补漏"),
}

BROWSER_DEPTH_TOPICS = {
    "product_centers", "product_catalog", "product_models", "product_parameters",
    "product_applications", "product_launches", "images", "subsidiary_roster",
}


class ResearchPlanner:
    def build(self, run_id: str, entity_id: str, canonical_name: str, complexity: EnterpriseComplexity, budget: dict[str, int]) -> ResearchPlan:
        sequence = RunSequence()
        topics = list(BASE_TOPICS)
        if complexity == EnterpriseComplexity.GROUP_LARGE:
            topics.extend([
                ("subsidiary_roster", "集团成员企业 子公司 名录 组织结构"),
                ("subsidiary_factories", "下属公司 生产基地 工厂 产品 工艺"),
            ])
        elif complexity == EnterpriseComplexity.SMALL_SIMPLE:
            topics = [item for item in topics if item[0] not in {"organization"}]
        max_queries = int(budget.get("max_queries", 80))
        queries: list[ResearchQuery] = []
        seen: set[str] = set()
        for topic, suffix in topics:
            for round_name, (round_goal, round_suffix) in ROUND_SUFFIXES.items():
                query_text = f'"{canonical_name}" {suffix} {round_suffix}'
                normalized = " ".join(query_text.lower().split())
                if normalized in seen or len(queries) >= max_queries:
                    continue
                seen.add(normalized)
                browser_round = topic in BROWSER_DEPTH_TOPICS and round_name in {"R2", "R3"}
                queries.append(ResearchQuery(
                    query_id=sequence.next("query"),
                    entity_id=entity_id,
                    topic=topic,
                    query=query_text,
                    purpose=f"{round_name} {round_goal}: collect {topic} evidence for {canonical_name}",
                    preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                    adapter_preference="kimi_webbridge" if browser_round else "anysearch",
                    max_results=min(10, int(budget.get("max_pages", 120))),
                    requires_browser=browser_round,
                    collection_round=round_name,
                    round_goal=round_goal,
                    high_priority=topic not in {"images", "product_launches"},
                ))
        return ResearchPlan(
            plan_id=new_sortable_id("PLAN"), run_id=run_id, complexity=complexity,
            queries=queries, budget=budget,
            completion_contract=[
                "identity", "organization", "factories", "business", "product_catalog_scope",
                "product_catalog_items", "product_models", "product_parameters", "product_applications",
                "energy", "images",
            ],
        )
