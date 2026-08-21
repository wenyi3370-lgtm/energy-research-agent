from __future__ import annotations

from enterprise_energy_research.domain.enums import EnterpriseComplexity, SourceLevel
from enterprise_energy_research.domain.ids import RunSequence, new_sortable_id
from enterprise_energy_research.domain.models import ConflictGroup, DataGap, ResearchPlan, ResearchQuery

from .contracts import contract_for


GOAL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("company_identity", "官网 注册主体 曾用名 统一社会信用代码"),
    ("ownership_structure", "股权结构 母公司 实际控制人"),
    ("organization", "组织架构 成员企业 管理层"),
    ("subsidiaries", "子公司 控股公司 参股公司 名录"),
    ("factories", "生产基地 工厂 厂区 地址"),
    ("locations", "总部 园区 基地 地理位置"),
    ("financials", "年报 财务报告 经营数据"),
    ("revenue", "营业收入 营收 年度"),
    ("profit", "净利润 利润总额 年度"),
    ("employees", "员工人数 人员规模 招聘"),
    ("capacity", "产能 年产 技改 投资项目"),
    ("production_lines", "生产线 工艺 设备 环评"),
    ("products", "产品中心 产品分类 产品清单"),
    ("product_series", "产品系列 产品族 分类目录"),
    ("product_models", "产品型号 牌号 series model SKU"),
    ("product_parameters", "技术参数 规格书 datasheet 手册 PDF"),
    ("customers", "核心客户 中标 供应关系 应用案例"),
    ("suppliers", "供应商 采购 招标 供应链"),
    ("certifications", "认证 体系 证书 检测报告"),
    ("technology", "核心技术 研发平台 技术路线"),
    ("patents", "专利 发明专利 知识产权"),
    ("industry_position", "行业地位 市占率 排名 竞争力"),
    ("energy_consumption", "综合能耗 用电量 能源消费"),
    ("energy_equipment", "变压器 锅炉 空压机 冷机 设备"),
    ("electricity_load", "电力负荷 峰谷 需量 负荷曲线"),
    ("natural_gas", "天然气 用气量 燃气锅炉"),
    ("compressed_air", "压缩空气 空压站 空压机"),
    ("heat", "蒸汽 热力 供热 冷热负荷"),
    ("waste_heat", "余热 余压 回收 节能改造"),
    ("roof_area", "屋顶面积 厂房面积 光伏可用面积"),
    ("renewable_energy", "绿色电力 可再生能源 光伏"),
    ("energy_projects", "能源项目 光伏 储能 充电站"),
    ("carbon_projects", "碳盘查 零碳工厂 碳项目"),
    ("EPC_opportunities", "新能源 EPC 综合能源 项目机会"),
    ("energy_saving_opportunities", "节能诊断 节能改造 合同能源管理"),
    ("storage_opportunities", "储能 削峰填谷 需量管理"),
    ("V2G_opportunities", "V2G 车网互动 双向充放电"),
    ("overseas_opportunities", "海外 出口 工厂 经销商 认证"),
    ("risks", "经营风险 合规风险 项目风险"),
    ("image_evidence", "企业logo 总部 厂区 生产线 产品 证书 图片"),
)

# Backward-compatible alias for callers that imported the old symbol.
BASE_TOPICS = list(GOAL_FAMILIES)

ROUND_SUFFIXES = {
    "R1": ("coverage", "候选来源 官方目录 公开披露"),
    "R2": ("depth", "原文 全文 明细 参数 地址 日期 PDF"),
    "R3": ("triangulation", "交叉验证 独立来源 冲突 补漏"),
}

BROWSER_DEPTH_TOPICS = {
    # Kimi WebBridge is reserved for two jobs: IMAGE discovery on real pages,
    # and PRODUCT CATALOG traversal (official product centers are SPA pages
    # that plain HTTP extraction cannot enumerate — P0-17). All other search
    # and text collection runs through AnySearch (search + full-text extract).
    "image_evidence",
    "products", "product_series", "product_models", "product_parameters",
}


class ResearchPlanner:
    def build(self, run_id: str, entity_id: str, canonical_name: str, complexity: EnterpriseComplexity, budget: dict[str, int], *, only_topics: list[str] | None = None) -> ResearchPlan:
        sequence = RunSequence()
        # Browser-reserved goals are planned FIRST so they always receive a
        # query slot: image discovery (P0-15) and product-catalog traversal
        # (P0-17) are mandatory Kimi jobs, and a query budget must never
        # silently starve them (live runs showed products getting 0 queries).
        # image_evidence keeps its absolute first slot; the product families
        # follow, then everything else in GOAL_FAMILIES order.
        browser_priority = ("image_evidence", "products", "product_series", "product_models", "product_parameters")
        families = (
            [topic for topic in GOAL_FAMILIES if topic[0] == "image_evidence"]
            + [topic for topic in GOAL_FAMILIES if topic[0] in browser_priority[1:]]
            + [topic for topic in GOAL_FAMILIES if topic[0] not in browser_priority]
        )
        if only_topics is not None:
            allowed = set(only_topics)
            families = [topic for topic in families if topic[0] in allowed]
        topics = families
        max_queries = int(budget.get("max_queries", 80))
        queries: list[ResearchQuery] = []
        seen: set[str] = set()
        for topic, suffix in topics:
            if len(queries) + len(ROUND_SUFFIXES) > max_queries:
                break
            for round_name, (round_goal, round_suffix) in ROUND_SUFFIXES.items():
                official_hint = "官网 官方 年报 政府" if round_name == "R1" else ""
                query_text = f'"{canonical_name}" {suffix} {official_hint} {round_suffix}'.strip()
                normalized = " ".join(query_text.lower().split())
                if normalized in seen or len(queries) >= max_queries:
                    continue
                seen.add(normalized)
                browser_round = topic in BROWSER_DEPTH_TOPICS
                # Product-catalog topics DISCOVER via AnySearch, then Kimi
                # opens the REAL official product pages (SPA) in the depth
                # pass. Only image goals run their own search on the bridge.
                adapter = "kimi_webbridge" if topic == "image_evidence" else "anysearch"
                queries.append(ResearchQuery(
                    query_id=sequence.next("query"),
                    entity_id=entity_id,
                    topic=topic,
                    query=query_text,
                    purpose=f"{round_name} {round_goal}: collect {topic} evidence for {canonical_name}",
                    preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                    adapter_preference=adapter,
                    max_results=min(int(budget.get("max_results_per_query", 10)), int(budget.get("max_pages", 120))),
                    requires_browser=browser_round,
                    collection_round=round_name,
                    round_goal=round_goal,
                    high_priority=topic != "image_evidence",
                    trigger=("official_discovery" if round_name == "R1" else "catalog_enumeration" if topic in {"products", "product_series", "product_models", "product_parameters"} else "triangulation" if round_name == "R3" else "baseline"),
                    canonical_company_name=canonical_name,
                    expected_fields=list(contract_for(topic).expected_fields),
                ))
        return ResearchPlan(
            plan_id=new_sortable_id("PLAN"), run_id=run_id, complexity=complexity,
            queries=queries, budget=budget,
            completion_contract=[name for name, _ in GOAL_FAMILIES],
            scoped_goal_families=[name for name, _ in GOAL_FAMILIES],
            requires_catalog_enumeration=True,
            canonical_company_name=canonical_name,
        )

    def gap_queries(self, plan: ResearchPlan, canonical_name: str, gaps: list[DataGap]) -> list[ResearchQuery]:
        """Generate R2 searches from real Evidence Gap records, never generic retry text."""
        queries: list[ResearchQuery] = []
        for gap in gaps:
            family = self._family_for_field(gap.field_name)
            query_text = f'"{canonical_name}" {gap.field_name} {gap.next_action} 原文 明细 PDF'
            queries.append(ResearchQuery(
                query_id=new_sortable_id("QRY-GAP"), entity_id=gap.entity_id or "UNKNOWN", topic=family,
                query=query_text, purpose=f"R2 gap-driven search for {gap.gap_id}: {gap.reason}",
                preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                adapter_preference="kimi_webbridge" if family in BROWSER_DEPTH_TOPICS else "anysearch",
                max_results=10, requires_browser=family in BROWSER_DEPTH_TOPICS,
                collection_round="R2", round_goal="depth", high_priority=gap.importance != "minor",
                trigger="gap", target_gap_ids=[gap.gap_id],
                canonical_company_name=canonical_name,
                expected_fields=list(contract_for(family).expected_fields),
            ))
        return queries

    def conflict_queries(self, plan: ResearchPlan, canonical_name: str, conflicts: list[ConflictGroup]) -> list[ResearchQuery]:
        """Generate R3 independent-origin searches for unresolved conflicting claims."""
        queries: list[ResearchQuery] = []
        for conflict in conflicts:
            if conflict.resolution != "unresolved":
                continue
            family = self._family_for_field(conflict.field_name)
            queries.append(ResearchQuery(
                query_id=new_sortable_id("QRY-CONFLICT"), entity_id=conflict.entity_id, topic=family,
                query=f'"{canonical_name}" {conflict.field_name} 公告 政府 年报 交叉验证',
                purpose=f"R3 conflict-driven triangulation for {conflict.conflict_group_id}",
                preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                adapter_preference="anysearch", max_results=10,
                collection_round="R3", round_goal="triangulation", high_priority=True,
                trigger="conflict", target_conflict_ids=[conflict.conflict_group_id],
                target_claim_ids=list(conflict.claim_ids),
                canonical_company_name=canonical_name,
                expected_fields=list(contract_for(family).expected_fields),
            ))
        return queries

    @staticmethod
    def _family_for_field(field_name: str) -> str:
        normalized = field_name.lower()
        for family, _ in GOAL_FAMILIES:
            if family.lower() in normalized or normalized in family.lower():
                return family
        aliases = {"identity": "company_identity", "factory": "factories", "product": "products", "energy": "energy_consumption"}
        return next((family for token, family in aliases.items() if token in normalized), "risks")
