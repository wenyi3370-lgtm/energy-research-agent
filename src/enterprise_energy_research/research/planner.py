from __future__ import annotations

from enterprise_energy_research.domain.enums import EnterpriseComplexity, SourceLevel
from enterprise_energy_research.domain.ids import RunSequence, new_sortable_id
from enterprise_energy_research.domain.models import ConflictGroup, DataGap, ResearchPlan, ResearchQuery

from .contracts import contract_for
from .requirement_routing import route_for_topic


GOAL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("company_identity", "官网 注册主体 曾用名 统一社会信用代码"),
    ("ownership_structure", "股权结构 母公司 实际控制人"),
    ("organization", "组织架构 成员企业 管理层"),
    ("subsidiaries", "子公司 控股公司 参股公司 名录"),
    ("factories", "生产基地 工厂 厂区 地址"),
    ("locations", "总部 园区 基地 地理位置"),
    ("financials", "最近5年 年报 财务报告 营业收入 归母净利润 毛利率 研发投入 研发费用率 分业务收入"),
    ("revenue", "最近5年 营业收入 分业务收入 年度 可比口径"),
    ("profit", "最近5年 归母净利润 毛利率 研发投入 研发费用率 年度 可比口径"),
    ("employees", "员工人数 人员规模 招聘"),
    ("capacity", "产能 年产 技改 投资项目"),
    ("production_lines", "生产线 工艺 设备 环评"),
    ("products", "产品中心 产品分类 产品清单"),
    ("product_series", "产品系列 产品族 分类目录"),
    ("product_models", "产品型号 牌号 series model SKU"),
    ("product_parameters", "技术参数 规格书 datasheet 手册 PDF"),
    ("customers", "核心客户 中标 供应关系 应用案例"),
    ("sales_channels", "销售渠道 经销商 直销 分销 代理商 渠道结构"),
    ("suppliers", "供应商 采购 招标 供应链"),
    ("certifications", "认证 体系 证书 检测报告"),
    ("technology", "核心技术 研发平台 技术路线"),
    ("patents", "专利 发明专利 知识产权"),
    ("industry_position", "行业地位 市占率 排名 竞争力"),
    ("strategic_trajectory", "最近5年 战略变化 业务重心 投资 产能 技术路线 转折"),
    ("business_drivers", "增长驱动 利润驱动 需求变化 政策 客户 技术路线"),
    ("customer_market_proof", "具名客户 合同 订单 市场份额 应用证明 时间"),
    ("competitive_position", "同口径 市场份额 排名 可比企业 竞争位置"),
    ("policy_regulation", "产业政策 监管规则 补贴 准入 标准 政府文件"),
    ("enterprise_risks", "年报 风险因素 监管 客户集中 供应链 减值"),
    ("cooperation_timing", "战略优先级 当前时点 资源投向 合作窗口 反证"),
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

RECOVERY_STRATEGIES = (
    "企业官网 原始公告 官方目录",
    "政府网站 监管文件 招投标 环评",
    "年度报告 审计报告 工商及债券披露",
    "产品手册 规格书 认证机构 原始PDF",
    "客户公告 中标合同 应用案例",
    "销售渠道 经销商名录 区域代理 官方合作",
    "产线基地 产能 投资备案 投产进度",
    "行业协会 权威数据库 同口径统计",
    "历史版本 最近五年 时间序列 口径变化",
    "英文名称 别名 区域官网 海外披露 交叉验证",
)

BROWSER_DEPTH_TOPICS = {
    # Kimi WebBridge is reserved for two jobs: IMAGE discovery on real pages,
    # and PRODUCT CATALOG traversal (official product centers are SPA pages
    # that plain HTTP extraction cannot enumerate — P0-17). All other search
    # and text collection runs through AnySearch (search + full-text extract).
    "image_evidence",
    "products", "product_series", "product_models", "product_parameters",
}


def discovery_adapter_for(topic: str) -> str:
    """Choose the search-discovery adapter, not the later page renderer."""
    return "kimi_webbridge" if topic == "image_evidence" else "anysearch"

ANALYTICAL_TOPICS = {
    "strategic_trajectory", "business_drivers", "customer_market_proof",
    "competitive_position", "enterprise_risks", "cooperation_timing",
}
ANALYTICAL_FIELDS = {
    field_name
    for topic in ANALYTICAL_TOPICS
    for field_name in contract_for(topic).expected_fields
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
            + [topic for topic in GOAL_FAMILIES if topic[0] == "company_identity"]
            + [topic for topic in GOAL_FAMILIES if topic[0] in ANALYTICAL_TOPICS]
            + [topic for topic in GOAL_FAMILIES if topic[0] not in set(browser_priority) | ANALYTICAL_TOPICS | {"company_identity"}]
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
                adapter = discovery_adapter_for(topic)
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
                    **route_for_topic(topic).model_updates(),
                    canonical_company_name=canonical_name,
                    expected_fields=list(contract_for(topic).expected_fields),
                    interpretation_goal=contract_for(topic).interpretation_goal,
                    evidence_patterns=list(contract_for(topic).evidence_patterns),
                    counter_evidence_patterns=list(contract_for(topic).counter_evidence_patterns),
                    time_scope=contract_for(topic).time_scope,
                    comparison_required=contract_for(topic).comparison_required,
                    historical_required=contract_for(topic).historical_required,
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
                adapter_preference=discovery_adapter_for(family),
                max_results=10, requires_browser=family in BROWSER_DEPTH_TOPICS,
                collection_round="R2", round_goal="depth", high_priority=gap.importance != "minor",
                trigger="gap", target_gap_ids=[gap.gap_id],
                **route_for_topic(family).model_updates(),
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
                **route_for_topic(family).model_updates(),
                target_claim_ids=list(conflict.claim_ids),
                canonical_company_name=canonical_name,
                expected_fields=list(contract_for(family).expected_fields),
            ))
        return queries

    def coverage_queries(
        self, canonical_name: str, gaps: list, *, retry_round: int = 1
    ) -> list[ResearchQuery]:
        """Generate R4 targeted searches for high-value DATA COVERAGE gaps.

        Coverage gaps come from ResearchDataCoverageValidator (P0 third
        round): e.g. a listed company with only one year of revenue needs
        annual-report targeting, and a product-rich company with zero
        product photos needs an image pass over official product pages.
        """
        queries: list[ResearchQuery] = []
        strategy = RECOVERY_STRATEGIES[(max(1, retry_round) - 1) % len(RECOVERY_STRATEGIES)]
        for gap in gaps:
            if not getattr(gap, "searchable", False):
                continue
            family = (
                "image_evidence" if gap.gap_code == "coverage-product-images"
                else self._family_for_field(gap.field_name)
            )
            queries.append(ResearchQuery(
                query_id=new_sortable_id("QRY-COVERAGE"), entity_id="UNKNOWN", topic=family,
                query=f'"{canonical_name}" {gap.retry_hint} {strategy}',
                purpose=f"R4 coverage retry round {retry_round} for {gap.gap_code}: {gap.description}（现有：{gap.found}）; strategy={strategy}",
                preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                adapter_preference=discovery_adapter_for(family),
                max_results=10, requires_browser=family in BROWSER_DEPTH_TOPICS,
                collection_round="R4", round_goal="coverage", high_priority=gap.severity != "low",
                trigger="coverage",
                **route_for_topic(family).model_updates(),
                canonical_company_name=canonical_name,
                expected_fields=list(contract_for(family).expected_fields),
            ))
        return queries

    # Whole-sentence semantic routing for user requirements.  This catalogue
    # deliberately maps one sentence to *all* matching goal families.  It does
    # not depend on punctuation, conjunctions, or an LLM deciding where a
    # clause ends.  Specific concepts precede broader concepts only to make
    # the generated search focus clearer; matches are de-duplicated by family.
    REQUIREMENT_TOPIC_KEYWORDS = (
        ("company_identity", ("主营业务", "主要业务", "业务范围", "企业定位", "公司概况", "基本情况")),
        ("ownership_structure", ("股权结构", "实际控制人", "实控人", "控股股东", "母公司")),
        ("organization", ("组织架构", "管理层", "部门设置")),
        ("subsidiaries", ("子公司", "成员企业", "控股公司", "参股公司")),
        ("factories", ("生产基地", "制造基地", "工厂", "厂区", "基地布局")),
        ("locations", ("总部地址", "地理位置", "园区", "区域布局")),
        ("capacity", ("产能", "年产", "产量", "扩产", "技改")),
        ("production_lines", ("生产线", "产品线", "产线", "制造工艺", "生产工艺", "设备")),
        ("product_parameters", ("技术参数", "产品参数", "规格书", "数据手册", "datasheet")),
        ("product_models", ("产品型号", "型号", "牌号", "SKU")),
        ("product_series", ("产品系列", "产品族", "系列")),
        ("products", ("产品矩阵", "产品清单", "产品中心", "产品分类", "产品")),
        ("image_evidence", ("产品图片", "工厂图片", "产线图片", "图片", "照片", "实景", "logo")),
        ("revenue", ("营业收入", "营收", "收入")),
        ("profit", ("归母净利润", "净利润", "利润", "毛利率")),
        ("financials", ("财务", "年报", "现金流", "研发投入", "分红", "业绩")),
        ("employees", ("员工人数", "人员规模", "员工")),
        ("customers", ("核心客户", "客户", "订单", "中标", "应用案例", "合作方")),
        ("sales_channels", ("销售渠道", "渠道结构", "经销渠道", "分销渠道", "经销商", "代理商", "直销", "分销")),
        ("customer_market_proof", ("市场证明", "市场接受度", "客户案例", "合同订单", "客户结构")),
        ("suppliers", ("供应商", "采购", "供应链")),
        ("technology", ("核心技术", "技术路线", "研发平台")),
        ("certifications", ("认证", "证书", "检测报告")),
        ("industry_position", ("市场份额", "市占率", "行业地位", "排名", "竞争力")),
        ("competitive_position", ("竞争情况", "竞争格局", "竞争对手", "竞品", "竞争位置", "同业对比")),
        ("policy_regulation", ("政策", "产业政策", "监管", "法规", "补贴", "准入", "行业标准", "政府文件")),
        ("energy_consumption", ("用电量", "综合能耗", "能耗", "能源消费")),
        ("electricity_load", ("电力负荷", "峰谷", "需量", "负荷曲线")),
        ("energy_equipment", ("变压器", "锅炉", "空压机", "冷机", "能源设备")),
        ("renewable_energy", ("绿电", "可再生能源", "分布式光伏")),
        ("energy_projects", ("能源项目", "光伏项目", "储能项目", "充电站")),
        ("carbon_projects", ("碳盘查", "零碳工厂", "碳项目", "碳排放")),
        ("storage_opportunities", ("储能合作", "储能机会", "削峰填谷", "需量管理")),
        ("V2G_opportunities", ("V2G", "车网互动", "双向充放电")),
        ("overseas_opportunities", ("海外工厂", "出海", "出口", "海外市场", "经销商")),
        ("enterprise_risks", ("经营风险", "合规风险", "风险因素", "诉讼", "减值")),
    )

    @classmethod
    def requirement_intents(cls, requirements: str) -> list[tuple[str, str]]:
        """Return every goal family expressed anywhere in a full sentence.

        The focus label is the longest matching phrase for that family.  The
        complete original requirement is still carried into every query, so
        conjunction-heavy input and input with no separator lose no context.
        """
        text = " ".join((requirements or "").split())
        folded = text.casefold()
        matches: list[tuple[int, int, str, str]] = []
        for family_index, (family, keywords) in enumerate(cls.REQUIREMENT_TOPIC_KEYWORDS):
            hits = [keyword for keyword in keywords if keyword.casefold() in folded]
            if not hits:
                continue
            focus = max(hits, key=len)
            matches.append((folded.find(focus.casefold()), family_index, family, focus))
        if not text:
            return []
        routed = [(family, focus) for _, _, family, focus in sorted(matches)]
        # Open requirement lane: the complete user sentence is always kept as
        # its own contract. Known families get precise searches; genuinely new
        # or unusual requirements still receive a dedicated query/chapter
        # instead of being misclassified as company identity.
        routed.append(("custom_requirement", text[:160]))
        return routed

    def requirement_queries(
        self,
        canonical_name: str,
        requirements: str,
        *,
        recovery_round: int = 0,
    ) -> list[ResearchQuery]:
        """Turn a user's deep-research requirement text into targeted queries.

        The entire sentence is parsed for every expressed business intent;
        punctuation is optional and never controls completeness.
        """
        complete_requirement = " ".join((requirements or "").split())
        queries: list[ResearchQuery] = []
        recovery_strategy = (
            RECOVERY_STRATEGIES[(recovery_round - 1) % len(RECOVERY_STRATEGIES)]
            if recovery_round > 0 else ""
        )
        for family, focus in self.requirement_intents(complete_requirement):
            contract = contract_for(family)
            # A portal/deep-research requirement receives the SAME three
            # collection layers as a fixed Goal Family.  One broad result
            # page is not accepted as a completed supplemental investigation:
            # R1 finds primary/official coverage, R2 opens detailed originals,
            # and R3 seeks an independent source or counter-evidence.
            for round_name, (round_goal, round_suffix) in ROUND_SUFFIXES.items():
                source_focus = {
                    "R1": "官网 企业公告 政府 监管 原始来源",
                    "R2": "全文 明细 期间 单位 口径 PDF 详情页",
                    "R3": "独立来源 交叉验证 反证 同口径比较",
                }[round_name]
                # Keep the complete requirement in the extraction contract
                # (purpose/requirement_text), not redundantly in every search
                # string. Long conjunction-heavy sentences caused search
                # engines to ignore the company and return unrelated pages.
                # Known routes search the precise focus; the open custom route
                # searches the exact request once (bounded for provider limits).
                search_focus = (
                    complete_requirement[:240]
                    if family == "custom_requirement" else focus
                )
                queries.append(ResearchQuery(
                    query_id=new_sortable_id("QRY-REQ"), entity_id="UNKNOWN", topic=family,
                    query=(f'"{canonical_name}" 新能源产业企业 {search_focus} '
                           f'{source_focus} {round_suffix} '
                           f'{recovery_strategy}').strip(),
                    purpose=(f"supplemental {round_name} {round_goal} for {canonical_name}; "
                             f"focus={focus}; full requirement={complete_requirement}; "
                             f"recovery_round={recovery_round or 'initial'}"),
                    preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                    adapter_preference=discovery_adapter_for(family),
                    max_results=10, requires_browser=family in BROWSER_DEPTH_TOPICS,
                    collection_round=round_name, round_goal=round_goal, high_priority=True,
                    trigger="user_requirement",
                    **route_for_topic(family).model_updates(),
                    requirement_text=complete_requirement,
                    canonical_company_name=canonical_name,
                    expected_fields=list(contract.expected_fields),
                    interpretation_goal=contract.interpretation_goal or contract.business_question,
                    evidence_patterns=list(contract.evidence_patterns),
                    counter_evidence_patterns=list(contract.counter_evidence_patterns),
                    time_scope=contract.time_scope,
                    comparison_required=contract.comparison_required,
                    historical_required=contract.historical_required,
                ))
        return queries

    def direct_recovery_queries(
        self,
        canonical_name: str,
        recovery_texts: list[str],
        *,
        recovery_round: int = 1,
        entity_id: str = "UNKNOWN",
    ) -> list[ResearchQuery]:
        """Execute agent-supplied recovery queries VERBATIM (§22).

        Recovery queries are planned by the agent's LLM (or its deterministic
        fallback) for exactly this round's gap. Re-routing them through the
        keyword template engine regenerated the same dead searches every
        round (observed live: 90 minutes of recovery rounds with zero new
        evidence), so the exact text is searched as planned — only anchored
        with the subject name when the planner omitted it.
        """
        queries: list[ResearchQuery] = []
        for text in recovery_texts:
            text = " ".join(str(text).split())
            if not text:
                continue
            if canonical_name and canonical_name not in text:
                text = f'"{canonical_name}" {text}'
            families = [
                family for family, _focus in self.requirement_intents(text)
                if family != "custom_requirement"
            ]
            family = families[0] if families else "custom_requirement"
            queries.append(ResearchQuery(
                query_id=new_sortable_id("QRY-RECDIR"), entity_id=entity_id, topic=family,
                query=text,
                purpose=f"R4 recovery round {recovery_round}: agent query executed verbatim",
                preferred_source_levels=[SourceLevel.SOURCE_A, SourceLevel.SOURCE_B],
                adapter_preference=discovery_adapter_for(family),
                max_results=10, requires_browser=family in BROWSER_DEPTH_TOPICS,
                collection_round="R4", round_goal="coverage", high_priority=True,
                trigger="coverage",
                **route_for_topic(family).model_updates(),
                canonical_company_name=canonical_name,
                expected_fields=list(contract_for(family).expected_fields),
            ))
        return queries

    def targeted_plan(
        self,
        run_id: str,
        canonical_name: str,
        requirements: str,
        *,
        entity_id: str = "UNKNOWN",
        max_queries: int = 120,
        max_pages: int = 60,
        direct_recovery_texts: list[str] = (),
        recovery_round: int = 0,
    ) -> ResearchPlan:
        """Build the isolated additive plan used by both portal paths."""
        queries = self.requirement_queries(canonical_name, requirements)
        if direct_recovery_texts:
            queries = queries + self.direct_recovery_queries(
                canonical_name, list(direct_recovery_texts),
                recovery_round=max(1, recovery_round), entity_id=entity_id,
            )
        queries = [query.model_copy(update={"entity_id": entity_id}) for query in queries]
        effective_query_budget = max(max_queries, len(queries))
        return ResearchPlan(
            plan_id=new_sortable_id("PLAN-REQ"), run_id=run_id,
            complexity=EnterpriseComplexity.UNKNOWN, queries=queries,
            budget={
                "max_queries": max(1, effective_query_budget),
                "max_pages": max(max_pages, len(queries) * 3),
            },
            completion_contract=list(dict.fromkeys(query.topic for query in queries)),
            scoped_goal_families=list(dict.fromkeys(query.topic for query in queries)),
            requires_catalog_enumeration=any(query.topic in BROWSER_DEPTH_TOPICS for query in queries),
            canonical_company_name=canonical_name,
        )

    @staticmethod
    def _family_for_field(field_name: str) -> str:
        normalized = field_name.lower()
        for family, _ in GOAL_FAMILIES:
            if family.lower() in normalized or normalized in family.lower():
                return family
        aliases = {"identity": "company_identity", "factory": "factories", "product": "products", "energy": "energy_consumption"}
        return next((family for token, family in aliases.items() if token in normalized), "risks")
