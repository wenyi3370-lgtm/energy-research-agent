## v1.2.9 — 2026-08-12（PPT 高密度正文页三栏版式固化）

- **PPT 正文页密度升级**：数据密集型页面默认采用三栏高密度布局——左证据栏
  （x=60 w=290，2 组主题 + 证据行号要点）+ 中图栏（嵌入 Word 已验收图表，
  x=380 w=520）+ 右要点栏（x=930 w=290），图下 1-2 行数据注，SO WHAT 横幅 +
  双栏页脚不变；变体覆盖政策页（左时间线+右全高图）与竞争页（双图+图下速览）。
- **坐标规范**写入 `references/ppt-style-prompts.md` §1.4（含密度纪律：每页
  2-4 个证据主题、要点绑定证据行、数学符号用文字、内容区 ≥2/3 画布）；
  `references/text-only-chart-and-slide-design.md` 新增 §6 密度契约与清单项。
- **端到端验证**：澳洲 V2G 管理宣讲 12 页重绘（12 种版式家族、嵌入 10 张已验收
  图表），`verify_ppt_render_geometry` 0 重叠 0 越界（修复页 9 数学符号 ∝ 渲染
  重叠 → 改文字），`validate_high_fidelity_ppt_delivery --mode final` OK
  （0 fail 0 warn），最终审计 OK。

## v1.2.8 — 2026-08-12（表题去重 + 单图型最多两次）

- Word 表题由全局“编号存在即可”改为逐表结构归一化：每张正文表格正前方只保留一个
  有效表题，删除连续或游离的通用表题，按章重新编号；最终验证增加一表一题、紧邻和
  编号唯一门禁。
- 图表生产增加标准化类型配额：任一图型全篇最多 2 次，别名归一化后计数；生成第三张
  同型图时立即失败，最终组合验证再次统计，防止通过人工复制或改名绕过。
- 回归新增重复表题反例、自动修复断言和第三张同型图阻断断言。

## v1.2.7 — 2026-08-12（Word 图表可见性 + 语义图型 + PPT 证据地图）

### 交付质量修复

- **Word 内联图表裁切**：`Figure Image` 样式及每个含 drawing 的段落统一改为
  single/auto 1.0 行距，禁止 exact 固定行高；模板、构建器、后处理器和最终验证器
  四层同时修复。真实澳洲 V2G 报告从 16 个裁切问题降为 0，LibreOffice/PyMuPDF
  重渲染后 15 张图完整显示。
- **图表语义路由与美化**：声明式生成器新增 lollipop、diverging bar、waterfall、
  donut、funnel、timeline、risk matrix，并按 `visual_intent` / evidence relationship
  对 text-only 模型的 `auto` 或泛化 `bar` 请求做确定性路由。配色扩充为深蓝、蓝、
  teal、gold 与冷灰，文字下限统一 8 pt，图内标题关闭，标签避让继续强制。
- **图表组合门禁**：最终图表数 ≥6 时，柱状图家族占比不得超过 60%，实际图型不得
  少于 3 类；避免“一章一张同色柱状图”的低质量退化。
- **PPT 证据地图**：新增 `build_presentation_evidence_map.py` 与
  `references/text-only-chart-and-slide-design.md`，把证据→结论→问题→2–4 主题→
  SO WHAT→版式家族固化为 JSON。正式高保真 PPT 至少 4 种版式家族，禁止同一版式
  连续 3 页，并由最终验证器检查 evidence map 与 SVG 页数一致。
- **回归覆盖**：新增固定 12pt 行高的反例断言和 text-only 图型路由断言；Word、
  图表生成/注册/嵌入回归均通过。

## v1.2.6 — 2026-08-12（跨项目硬编码可配置化 + PPT 多目录探测 + R3 受控豁免）

### P1 修复

- **P1-1 生成器跨项目硬编码全部可配置化**：`generate_collection_audits.py`
  的 registry `market="Spain"`、`created_date="2026-01-01"`、URL→来源提示表
  （西班牙域）、06 渠道品牌→来源映射、04 表 technology_performance 分类关键字、
  08 编码主题→评论继承映射，全部改为读取冻结策略快照的 `generator_overrides`
  段（模板默认保留原行为，向后兼容）。跨市场项目用
  `upgrade_collection_policy.py --confirm-policy-upgrade --approved-by <人> --overrides <yaml>`
  注入（`_merge_overrides`：顶层键替换 + 嵌套 dict 逐键合并），生成器自动写入
  正确 registry（澳洲项目验证：476 行 market 全部为 Australia，不再手工修补）。
- **P1-2 生成器空分段静默写空审计**：R2/R3 段无池记录时只写空 count-evidence
  JSON 并标记 completed，最终审计才暴露。修复：空段打印 `[WARN]` 诊断
  （任务 ID/家族/池规模/建议补录或登记例外）；docstring 同步修正
  （`audits/platform_limit_reviews.json` 非本脚本产出）。
- **P1-3 生成器真实崩溃**：R3 claim 生成 bindings fallback 处
  `for f, i in recs[:2]` 对 5 元组解包崩溃（`too many values to unpack`），
  补录记录场景必现；修复为 `for f, i, *_ in recs[:2]`。
- **P1-4 PPT 管线硬编码单层目录**：`validate/register_high_fidelity_ppt_delivery.py`、
  `audit_cover_compliance.py`、`verify_ppt_render_geometry.py`、
  `resolve_presentation_images.py`、`wrap_slide_text.py` 全部硬编码
  `<project>/presentation_project`。修复：`_common.find_presentation_project()`
  自动探测（优先 `presentation_project/`，其次单层扫描含 design_spec.md +
  svg_output 的子目录，兼容 `init` 的 `<name>_ppt169_<YYYYMMDD>/`），并新增
  可选 `--presentation-project` 显式覆盖；找不到时列出候选目录。
- **P1-5 R3 关键声明消息-代码不一致**：错误消息声称支持
  "verified saturation claim" 但代码无该分支。修复为受控豁免：任务有有效
  market_gap 例外 + count-evidence 无遗留高优发现 + gap 审计 JSON 的 R3 轮
  含真实 failure_reasons 时，允许缺口验证声明替代双源三角验证；消息同步
  明确化（无豁免时提示两种可行路径）。
- **P1-6 Excel 同步后公式缓存失效**：`sync_csv_to_excel.py` 完成后自动调用
  `recalculate_excel.py`（LibreOffice 可用时；`--skip-recalc` 可关闭；缺
  LibreOffice 时打印明确提示），消除 `excel_delivery.formula_cache` 审计失败。

### P2 修复

- **P2-7 SKILL.md/parity/automation/deliverables 文档契约漂移**：修正
  `doctor` 不产出文件、`init` 真实目录命名、validate/register 的 required
  参数、Excel recalc 步骤、例外闭环流程（审计暴露缺口 → 登记
  `data_gaps_template.csv` + `market_gap_evidence_template.json` → 人工批准 →
  挂接 02 表 → 重跑生成器 → 重审计）、generator_overrides 配置说明；
  `references/embedded-pptmaster-parity.md` 示例对齐自动探测。
- **P2-8 新增回归测试**：`scripts/regression_test_collection_audits.py`
  覆盖默认模板行为（Spain/2026-01-01）、项目覆盖（Australia/2026-08-12）、
  tech_keywords 覆盖 + 空段 `[WARN]` 诊断、`_merge_overrides` 合并语义，
  全部 PASS。

### Remaining Issues（更新后）

- `01_Market_Scan` 分段关键字与 04 表分类关键字同为中文项目特有词，尚未
  移入 `generator_overrides`（本次不阻断；跨语言市场项目若分类漂移，按 P1-1
  同模式扩展 `market_scan_keywords` 键）。
- R3 受控豁免不覆盖 source_type/platform/primary 下限——这些仍须真实记录
  满足（研究质量底线）。

## v1.2.3 — 2026-08-12（Reliability Final 收口：Gate 全链 fail-fast + PEP 508 落地）

### P1 修复

- **P1-1 Pre-collection gate FAIL 后立即阻断**：`--all` 的 check 段改为显式
  `precheck_entry = step(...)` + `_handle_gate`（不再依赖 run_step 的隐式 raise）；
- **P1-2 Final Report build FAIL 后阻断 Evidence Audit**：build 段同样显式 gate，
  audit 不再对失败的最终交付物执行；
- **P1-3 真实 Bug 修复**：`_handle_gate` 此前只认 `entry["status"]`，而 step 型 entry
  只有 returncode（无 status）→ 永远返回 None → check/build gate 形同虚设。
  修复：无 status 时按 returncode 推导 PASS/FAIL（Case 12 模块级 mock 实证抓到
  audit 在 build FAIL 后仍执行，修复后正确阻断）。
- **P1-4 Workflow regression 12/12**：新增 Case 11（precheck FAIL → collect 不执行，
  断言 workflow summary 不出现 + exit≠0）、Case 12（build FAIL → audit 不执行，
  模块级 mock 记录步骤序列断言 audit_called=False）。

### P2 修复

- **P2-5/6/7 PEP 508 真正落地**：审计发现上一轮"PEP 508 化"实际未写入文件
  （`common/requirements.py` 仍是手工 `split(";")`）——本轮重写为
  `parse_requirement_line()`（packaging.Requirement + marker.evaluate(environment)，
  保真 name/specifier/extras/marker）与 `core_packages(environment=None)` /
  `optional_packages(environment=None)`；Python 3.10 → tomli 要求、
  3.13 → 排除（Fault C/D 实证）。
- **P2-9/10/11 Doctor regression 隔离化**：每个 case 先注入"全 healthy"基线
  （_pkg/_libreoffice/resolve_cjk_font/_writable/_probe_service 全部 healthy），
  只注入目标故障，宿主机缺失状态不再污染结果；Case 1/2 改为直接测生产
  parser `core_packages(environment=...)`（不再只测 packaging 库本身）。
- **P2-14/15 packaging 显式依赖**：`requirements.txt` 加入 `packaging>=24,<26`，
  `constraints-tested.txt` 固定 `packaging==25.0`（不再依赖 pip/setuptools 间接提供）。
- **P3-16 新增 `test_requirements_parser.py`**（6 项 unit test）：blank/comment、
  普通依赖+specifier 保真、marker 生效（3.10）、marker 不生效（3.13）、extras+inline
  marker、版本范围——全部直接测生产 parser。

### 测试与故障注入（全部 PASS）

- compileall 全量编译 OK；回归 16/16（anysearch/word/figure/excel/workflow 12 项/
  modeling/final_report_package/doctor 6 项/web_collection/ppt/parity/
  source_independence 100 例/requirements parser 6 项/svg self-test）；
- 故障注入：Fault A（precheck FAIL → collect_called=False + exit≠0）、Fault B
  （build FAIL → audit_called=False + exit≠0）、Fault C（3.13 tomli absent）、
  Fault D（3.10 tomli present）、Fault E（仅 optional 服务不可达 → WARN 且
  READY，其他能力全 healthy 隔离验证）；
- 四副本（.claude/.codex/.openclaw×2）同步，关键文件哈希一致。

## v1.2.4 — 2026-08-12（跨平台字体发现收口：CJK Font Discovery False Negative 修复）

### 核心 Bug

- **TTC False Negative**：Linux/macOS 已安装 SC 中文字体（常在 `.ttc` 集合内，如
  `/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc`），Fontconfig 能解析
  `Noto Serif CJK SC`，但 Matplotlib font cache 只暴露集合的另一个 face（通常
  是 `Noto Serif CJK JP`）→ `findfont("...SC")` False Negative →
  误报 "No supported Chinese font was found"。修复原则：
  `字体发现 ≠ 字体语义选择`、`系统字体存在 ≠ Matplotlib cache 认识该 family`。

### 修复内容

- **`common/fonts.py` 重写为多级发现 + `ResolvedFont` 结果对象**（family/path/
  source/regional_variant）：
  1. Level 1 Matplotlib 原生发现（`findfont(fallback_to_default=False)`，最轻路径）；
  2. Level 2 Fontconfig（`fc-match -f '%{family}\n%{file}\n'`，subprocess timeout=3s、
     禁 shell、捕获 stderr、无 fc-match 时静默跳过——macOS 不依赖 fc-match）；
     必须验证返回文件存在 + family 与请求合理匹配（拒绝 DejaVu Sans 等无关
     fallback），TTC 多 face 场景允许；
  3. Level 3 文件系统兜底（平台字体目录扫描 SC 专用文件，不硬编码固定文件、
     不靠无关文件名猜 family）。
- **SC-first 策略**：JP/KR/TC/HK 区域变体不得静默冒充 SC；`require_simplified_
  chinese=False` 是显式 opt-in（返回 `regional_variant=True` 标记）；生产渲染
  默认不使用 JP。新增 API：`resolve_cjk_font()` / `resolve_cjk_font_family()` /
  `resolve_cjk_font_path()` / `require_cjk_font()` / `register_font_for_matplotlib()`
  / `find_regional_variant()` / `is_approved_cjk_family()`；平台优先级
  Windows(SimSun→YaHei) / macOS(STSong→Noto Serif SC→Source Han Serif SC) /
  Linux(Noto Serif CJK SC→Noto Serif SC→Source Han Serif SC)。
- **`register_font_for_matplotlib()` 存在性与使用分离**：`addfont(TTC)` 在不同
  matplotlib/FreeType 版本下行为不同，绝不假定注册成功——注册后必须实际验证
  SC face 是否可解析（Case 7 实证：仅暴露 JP face 时诚实返回 False）。
- **Doctor 字体检查区分三态**：Case B（matplotlib 找不到但 fontconfig 找到 SC）
  → `CJK_FONT PASS`（输出 family/source/path，不再误报 MISSING）；Case C（仅
  区域变体）→ `WARN`（strict 下 FAIL），不得静默 PASS；Case A（真正无字体）
  → `MISSING`（normal WARN / strict FAIL，保持原语义）。
- **统一所有消费者**：chart theme（`_cjk_family()` 解析+注册，SC face 不可加载
  时大声报错给出安装指引）、chart_polish、Word 管线 helper、SVG QA
  （`is_approved_cjk_family`）、Doctor——全部共用 `common/fonts.py`，不再各自
  findfont / 各自维护候选列表；文档字体名（docx/pptx/excel 的 SimSun/YaHei）
  为输出文档标准，审美标准未改。

### 新增测试

- **`regression_test_font_discovery.py` 8/8**：①matplotlib 直接找到 SimSun →
  source=matplotlib；②matplotlib 找不到 + fc-match 找到 SC TTC → PASS
  （family/path/source=fontconfig）；③fc-match fallback 到无关字体（DejaVu Sans）
  → 不 PASS；④仅 JP variant → SC 不静默 PASS、opt-in 显式标记；⑤无任何字体 →
  None；⑥**核心回归**：SC TTC 存在 + fontconfig 说 SC + matplotlib 只暴露 JP →
  存在性必须 PASS；⑦addfont 后 SC face 出现 → True、只暴露 JP → 诚实 False；
  ⑧QA 分类（SC 接受 / JP+DejaVu 拒绝）。全部 mock 发现原语，任意宿主机确定性。
- **`integration_test_fontconfig_cjk.py`**（optional）：真实 `fc-match` 集成测试，
  无 fc-match/无 SC 字体 → SKIP（exit 0）；Linux 主机有 SC 字体时必须与解析器
  一致。
- **`regression_test_doctor.py` 8/8**：适配新 API（healthy 基线注入 ResolvedFont
  + find_regional_variant + register_font_for_matplotlib），新增 Case B（fontconfig
  SC → PASS 且 detail 含 family/source/path）与 Case C（区域变体 → WARN / strict
  FAIL）。

### 验证（全部 PASS）

- compileall 全量编译 OK；font_discovery 8/8、doctor 8/8、figure、final_report_
  package、ppt_delivery（--work-dir）、word_delivery、workflow 12/12、
  source_independence 100 例、modeling、web_collection、excel、anysearch embed、
  parity、requirements parser、svg self-test——全部 exit 0；
- 生产 doctor 实测：`CJK_FONT PASS: family=SimSun source=matplotlib
  path=C:\Windows\Fonts\simsun.ttc`（Windows 无回归）；
- 真实渲染冒烟：SVG 输出 `font-family: 'SimSun', 'Times New Roman'` 双轨正确；
- 集成测试在 Windows 主机正确 SKIP（exit 0），不产生 FAIL。

### 验收对照（12/12）

①Windows SimSun/YaHei 不回归 ✓ ②macOS STSong/Noto Serif SC 优先级保留 ✓
③Linux matplotlib 直连 SC → PASS ✓ ④matplotlib 找不到 + fontconfig 找到 SC TTC
→ PASS ✓ ⑤无关 fallback 不误判 ✓ ⑥区域变体不静默冒充 SC ✓ ⑦无字体仍
WARN/FAIL ✓ ⑧figure regression PASS ✓ ⑨final package regression PASS ✓
⑩doctor 与实际系统字体状态一致（三态）✓ ⑪README 字体 Source of Truth 已改为
`scripts/common/fonts.py` ✓ ⑫全部既有核心 regression 无回归 ✓

## v1.2.5 — 2026-08-12（剩余问题收口：TTC SC-face 提取注册 + macOS 系统字体）

### 修复 1：TTC 只有 JP-first face 时渲染路径不再诚实失败而是真实可用

- **问题**：v1.2.4 中若 Linux 只有 JP-first 的 Noto CJK TTC 且无 SC 单文件，
  字体存在性 PASS，但 matplotlib 无法加载 SC face → 图表渲染大声报错。
- **修复**：`register_font_for_matplotlib()` 新增第三层策略——用 fontTools
  （matplotlib≥3.5 的**硬依赖**，零新增安装）打开 TTC（`TTCollection`），
  按 name table（nameID 16/1）枚举每个 face，选取与目标 family **精确等值
  匹配**的 SC face，提取为独立缓存字体（`%TEMP%/overseas_energy_market_
  research_cjk_faces/`）并 `addfont` 注册，再实际验证 SC family 可解析。
  仅当 fontTools 缺失 / 非 TTC / 无 SC face 时才诚实返回 False。
- **face 选择修正（真实 bug 抓取）**：提取匹配不能用 fc-match 校验用的子串
  规则——"SimSun" 会误配 "NSimSun" 请求（`simsun` ⊂ `nsimsun`）提取错误
  face；改为归一化精确等值。
- **真实硬件验证**：本机 `C:\Windows\Fonts\simsun.ttc` 的 face 1（NSimSun，
  matplotlib cache 默认不认识）——提取 → 注册 → `findfont("NSimSun")` 命中
  （`before: None → after: nsimsun_1.otf`）端到端 PASS；`msyh.ttc` 双 face
  枚举正确。

### 修复 2：macOS 系统字体发现缺口

- **问题**：macOS 若只有系统自带 Songti.ttc / PingFang.ttc（无 Noto/思源），
  原候选列表（STSong/Noto Serif SC/Source Han Serif SC）全部落空 → 误报
  MISSING，尽管系统有 SC 字体。
- **修复**：Darwin 候选追加 `PingFang SC`、`Songti SC`（保持文档规定的
  STSong → Noto Serif SC → Source Han Serif SC 前三优先级不变，追加在其
  后）；文件系统模式补充 `pingfang` / `songti` / `stsongti-sc`；两者均纳入
  QA 审批（`_EXTRA_SC_FAMILIES` + `is_approved_cjk_family`）。TTC 提取机制
  同样覆盖 macOS TTC（PingFang.ttc 的 SC face 可被精确提取注册）。

### 回归固化（regression_test_font_discovery.py 8/8 → 10/10）

- **Case 9**：`addfont(TTC)` 只注册首个 face 时，fontTools 提取 SC face →
  True（断言 addfont 序列 `[ttc, extracted]`）；无可用 SC face → 诚实 False
  （断言只尝试 direct addfont）。
- **Case 10**：macOS 优先级不破坏（文档前三在 PingFang SC 之前）、PingFang/
  Songti 为发现候选且 QA 审批通过、Darwin 端到端解析 PingFang SC。

### 验证（全部 PASS，exit 0）

- compileall OK；font_discovery 10/10、doctor 8/8、figure、final_report_
  package、ppt（--work-dir）、word、workflow 12/12、source_independence
  100 例、modeling、web_collection、excel、anysearch、parity、requirements
  parser、svg self-test 全部 PASS；
- 生产 doctor：`CJK_FONT PASS: family=SimSun source=matplotlib path=...` 无回归；
- 真实 TTC 提取端到端：NSimSun 从未知 → 提取 → 注册 → findfont 命中；
- 集成测试仍正确 SKIP（exit 0）。

### Remaining Issues（更新后）

- macOS 未走 CoreText API（pyobjc）——现通过 matplotlib + 文件系统 + TTC
  提取覆盖系统字体，行为正确且零新依赖；CoreText 直连仍为 future work；
- 极端场景（fontTools 缺失且 TTC 不可加载）下图表渲染仍大声报错并给出
  安装指引——诚实失败，不静默豆腐块/JP。

## v1.2.2 — 2026-08-12（Reliability Final：Workflow 语义 + PSL 正确性 + 依赖判定收口）

### P1 修复

- **P1-1 `--all` pre-collection Stage Gate 参数**：首次 gate 此前传全局默认 `--stages 0-8`
  （注释声称 0-4）导致新项目在 Stage 5-8 产物未生成时被错误阻断、采集无法开始。
  新增 `PRE_COLLECTION_STAGES = "0-4"` / `FINAL_VALIDATION_STAGES = "0-8"` 显式分离，
  `--all` 首次 gate 固定验证 0-4（回归 [8/10] 精确断言 validate_stage_gate 命令的 stages）。
- **P1-2 `--all` 真实前置条件**：`--all` 定义为"研究计划、人工审批、采集计划已完成后的
  总执行入口"——新增 `_planning_prerequisites_met`（00_Research_Approval 有 approved 记录 +
  02_Web_Collection_Tasks 有任务），不满足 → **BLOCKED**（exit 1，不进入 collect）；
  dry-run 仅提示不阻断。README 同步（--all 不自动替代人工研究审批）。
- **P1-3/4/5 PSL Prevailing Rule 算法**：重写 `_psl_registrable`——
  例外优先 → 最长 exact/wildcard → 默认 `*` 规则；wildcard `*.ck` 改为 **label 级匹配**
  （恰好 1 个 label + 基后缀），不再用字符串 endswith 任意深度；
  深层域名正确：`y.x.a.ck → x.a.ck`、`sub.www.ck → www.ck`、
  `z.a.b.kawasaki.jp → a.b.kawasaki.jp`、`x.city.kawasaki.jp → city.kawasaki.jp`。
- **P1-7/8 Frozen PSL 唯一确定性 Source of Truth**：移除 tldextract 优先路径（不再
  咨询 optional 包），所有环境一律使用 `references/public_suffix_list.dat`；
  安装/不安装 tldextract 结果必然一致；requirements-optional 同步移除 tldextract。

### P2 修复

- **P2-8/11/12 PEP 508 Environment Marker**：`common/requirements.py` 不再手工 `split(";")`，
  改用 `packaging.requirements.Requirement` 完整解析（名称/版本/extra/marker），
  marker 求值为 False 的依赖（如 Python 3.13 的 tomli）从核心清单剔除——
  Python 3.10 要求 tomli、3.11+ 不要求（doctor regression [1/6][2/6] 实测 + 模拟 3.13 验收）。
- **P2-13 新增 `regression_test_doctor.py`**（6 Case）：marker 生效/不生效（模拟 3.13）、
  missing core → CORE FAIL / NOT_READY、missing optional → WARN 不 FAIL、
  missing required font → 普通 WARN / strict FAIL、外部服务不可达 → WARN 仍 READY；
  doctor 新增 optional 包缺失 WARN 行。
- **P2-15 Workflow regression 扩展至 10 项**：新增 pre-collection gate 参数断言、
  planning 未审批 → BLOCKED、planning 完成 → 进入 collect。

### 测试与故障注入（全部 PASS）

- compileall 全量编译 OK；回归 13/13 PASS（anysearch/word/figure/excel/workflow 10 项/
  modeling/final_report_package/doctor 6 项/web_collection/ppt/parity/
  source_independence 100 例/svg self-test）；
- 故障注入 8 项：0-4 gate 不验证 5-8 ✓、planning 未审批 BLOCKED ✓、planning 完成进入
  collect ✓、y.x.a.ck→x.a.ck ✓、sub.www.ck→www.ck ✓、无 tldextract 路径（唯一源）✓、
  Python 3.13 tomli 忽略 ✓、Python 3.10 tomli 要求 ✓；
- 四副本（.claude/.codex/.openclaw×2）同步，关键文件哈希一致。

## v1.2.1 — 2026-08-11（Reliability Final：状态传播闭环 + 完整交付链 + 全球 PSL）

### P1 修复

- **P1-1/2/3 Workflow 状态传播闭环**（`run_workflow.py`）：
  - `--all` 改为**逐阶段 Gate**（`_handle_gate` 每阶段立即判断，不再依赖 results[-1]）：
    collect=BLOCKED + modeling=SKIP 时立即停止，build/audit 不执行；
  - `run_modeling` 透传真实 `--mode`（不再内部写死 draft），`--mode final` 正确到达
    modeling gate；
  - final + Human Gate PENDING → **PENDING_HUMAN**（exit=3 暂停码），不生成 12/13/14
    final artifacts、不进入 final report/audit；draft 模式保留既有灵活性；
  - dry-run 预览不再把"文件缺失"误判为 BLOCKED（DRY-RUN 状态）。
- **P1-4 Workflow 回归扩展**：新增 3 Case（collect BLOCKED 阻断 / final+PENDING /
  draft+PENDING），7/7 PASS；业务代码与测试期望同步修正（不绕过错误）。
- **P1-5 修复 Final Report 一键交付链 ImportError**（Blocker）：
  - 根因：`build_final_report_package.py` import 了不存在的 `render_charts.save_manifest`，
    且以错误签名调用 CHART_BUILDERS（真实签名 `builder(project_dir, plt)`）；
  - 新建 `scripts/common/chart_manifest.py`（统一 manifest writer），render_charts 改用；
    `render_all_charts` 改为真实调用 render_charts 管线（透传 claim registry + 从
    theme.json 补 path 字段）；
  - 验收：minimal project 真实组装 **DOCX+XLSX+PPTX+双 manifest 全部生成，BUILD_EXIT=0**。
- **P1-6 新增 `regression_test_final_report_package.py`**：minimal valid project 真实组装
  回归（不 Mock 核心逻辑），PASS。

### P2 修复

- **P2-7 完整 Frozen PSL**：`references/public_suffix_list.dat` 由 129 行子集升级为
  官方完整快照（16397 行，snapshot_date 2026-08-11，来源 publicsuffix.org）；
  tldextract 加入 requirements-optional（可用时自动启用完整 PSL，network disabled）。
- **P2-8 PSL 引擎修复**：exception 规则判断不匹配 bug（`!www.ck` 存储/判断格式统一）；
  `www.` 剥离改在 PSL 解析之后（例外域 www.ck 不再被误剥）；剥离偏移修正；
  regression 扩展至 **90 例**（含 *.ck 通配、!www.ck 例外、全球 70+ 后缀）全 PASS。
- **P2-9 Doctor 依赖源统一**：新建 `scripts/common/requirements.py`（机器可读解析
  requirements.txt / requirements-optional.txt）；doctor 与 verify_install 不再维护
  各自硬编码模块清单；**当场捕获并修复 Python 3.10 缺失 tomli**（PyPI 不可达，从
  GitHub 手动安装）——验证了"required missing → CORE FAIL"语义真实生效。
- **P2-10 Doctor 真实服务 probe**：Kimi WebBridge（127.0.0.1:10086/command）与 EWO
  （EWO_ORIGIN，默认 18799）真实可达性探测（HTTP 短超时），不再固定打印"未检测"。
- **P2-11 constraints 补 tomli 条件依赖**：`tomli==2.0.2; python_version < "3.11"`。

### P3 修复

- **P3-12** 删除 `scripts/requirements.txt`（根目录为唯一核心 Source of Truth；
  确认无代码引用该路径，bootstrap/update_repo 均用根目录文件）。
- **P3-13** 字体 Source of Truth 收口：chart_polish 的 YaHei 为 ImportError 兜底（合理），
  svg_quality_checker 两处为 PPT-safe 提示文案（非候选列表）；统一入口
  `scripts/common/fonts.py` 已由 kami_broker_chart_theme / verify_chart_svg_quality /
  doctor 共用。

### 测试与故障注入（全部 PASS）

- compileall 全量编译 OK；
- 回归 10/10：anysearch embed、word、figure、excel、workflow（7 项）、modeling、
  final_report_package、ppt、anysearch parity、source_independence（90 例）、
  svg self-test；
- 故障注入 Case A（任务文件缺失→BLOCKED+exit≠0）、B（collect 阻断后 modeling/
  build/audit 不执行）、C（final+PENDING→PENDING_HUMAN+无 final artifacts）、
  D（minimal 组装无 ImportError）、E（PSL 例外域）、F（核心依赖缺失→doctor --strict
  EXIT≠0，以 tomli 缺失实证）；
- 四副本（.claude/.codex/.openclaw×2）已同步，关键文件哈希一致。

## v1.2.0 — 2026-08-11（Reliability & Test Integrity Upgrade）

按内部《工程可靠性与测试体系专项修复文档》完成 9 项修复，不削弱研究强度/采集门槛/建模推进/内部品牌与 API key 模式：

### FIX-01 AnySearch 测试职责分离（P2）
- `regression_test_anysearch_embed.py` 只做自包含离线回归：embedded CLI SHA256 与新增
  `references/anysearch_manifest.json` 内部清单比对（不再依赖外部官方 Skill，纯净环境不再假失败）；
- 新增 `integration_test_anysearch_parity.py`：embedded vs official 的 SHA256/doc zero-diff/
  command surface；官方未安装时 **SKIP**（exit 0）而非 FAIL；
- README 增加测试三层（self-contained regression / official parity integration / live smoke）说明。

### FIX-02 Workflow 子流程状态传播（P1）
- `run_workflow.py` 新增 `_status_for`/`_wrap_step`：collect/modeling 不再硬编码 returncode=0，
  统一状态 PASS/FAIL/BLOCKED/PENDING_HUMAN/SKIP/DRY-RUN；
- 验收：Case A 任务文件缺失 → [BLOCKED] + exit=1；Case B 正常 → [PASS] + exit=0；
  Case C 人工门未决 → PENDING_HUMAN（--all 流程中止后续 build/audit，exit=3 暂停码）。

### FIX-03 SVG 重叠检测 XML Parser 化（P1）
- `verify_chart_svg_quality.py` 弃用正则解析 `<text>`，改 `xml.etree.ElementTree`（属性顺序无关），
  支持 text-anchor（end/middle 锚点）、rotate(±90) 竖直文本（ylabel）、fill 色系（顶部残留
  仅判灰色图注）；
- `--self-test` 验收：A/B/C 三种属性顺序解析、D 完全重叠检出、E 分离放行、F 竖直 ylabel 不误报；
- 实图回归 16/16：XML 解析当场暴露正则版漏检的 6 处真实重叠（fig1 YoY 注释、fig14 合计标签、
  fig15 双标注同 y、fig2/5/8/10/12 ylabel 间距）并全部修复。

### FIX-04 Source Independence 完整 PSL 规则（P1/P2）
- `source_independence.py` 弃用手工 MULTI_LABEL_PUBLIC_SUFFIXES，内置冻结快照
  `references/public_suffix_list.dat`（PSL 行格式，含 snapshot_date）实现最长匹配算法；
  tldextract 可用时自动升级为完整 PSL（离线，network update disabled）；
- 新增 `test_source_independence.py` 回归：20 例 PASS，a.com.es/b.com.es、energia.gob.es/
  industria.gob.es 正确判为独立根域。

### FIX-05 统一 Runtime Doctor（P2）
- 新增 `scripts/doctor.py`：CORE/OFFICE/WORD/EXCEL/PPT/IMAGE/MODELING/WEB_COLLECTION/
  DELIVERY/OPTIONAL 十域检查（Python/核心包/LibreOffice/CJK 字体/embedded CLI+manifest/
  模板/磁盘）；`--strict` 模式必需域缺失即 exit≠0。

### FIX-06 依赖冻结（P2）
- 新增 `constraints-tested.txt`：当前环境全回归通过时锁定的 19 个精确版本；
  `pip install -r requirements.txt -c constraints-tested.txt`；升级必须走
  Regression → Office QA → Workflow E2E → 全 PASS → 更新文件。

### FIX-07 Optional Requirements 去重（P2）
- 删除 `scripts/requirements-optional.txt`，根目录 `requirements-optional.txt` 为唯一
  Source of Truth（此前两份内容漂移：nbformat/urllib3 仅存在于一份）。

### FIX-08 update_repo 根目录修正（P3）
- 弃用固定 parent 链，按 OVERSEAS_ENERGY_SKILL_ROOT 环境变量 → .git 向上搜索 → skill 根
  解析 REPO_ROOT；git pull 前强制校验 .git 存在 + 目录身份，否则 ABORT（实测无 .git 时正确拒绝）。

### FIX-09 中文字体规则统一（P3）
- 新增 `scripts/common/fonts.py`：CJK_FONT_CANDIDATES（含 Noto Serif CJK SC/Source Han Serif SC）
  与 resolve_cjk_font 唯一来源；kami_broker_chart_theme 与 verify_chart_svg_quality 统一引用，
  Linux/macOS 合法中文字体不再被 QA 误拒。

### 验收
- 全量回归 9/9 PASS（anysearch/word/figure/excel/workflow/modeling/ppt + 新增
  test_source_independence 20 例 + verify_chart_svg_quality self-test 6 项 + doctor 双模式）；
- 西班牙户储项目：图表 16/16 全绿、FIX-03 修图后重嵌 Word（新 SHA256 efcb28b1…）、
  Word delivery OK；
- 已同步 .claude/.codex/.openclaw×2 四副本，关键文件哈希一致。

## v1.1.6 — 2026-08-10（新电脑依赖审计 + 全流程回归验证）

### 依赖审计（import 静态扫描 vs 声明）

- 扫描全部 203 个 .py 的 import（AST），对照 requirements 两份清单：
  - **核心 requirements.txt（20 项）**：全覆盖，无缺口——新增门禁脚本
    `verify_ppt_render_geometry.py`（PyMuPDF）、`verify_chart_svg_quality.py`（Pillow）
    所依赖的包均已声明；
  - **可选 requirements-optional.txt（6 项）**：cairosvg（PPT PNG 导出，缺失回退
    svglib+reportlab）、curl-cffi（TLS 指纹采集，回退 requests）、playwright（视觉
    预览，缺失跳过）、google-genai（Gemini 生图后端）、nbformat（ipynb 转换，有
    try/except 保护）、urllib3（CLI 警告抑制）——本轮补齐 nbformat/urllib3 两条
    声明，并**撤回误入核心清单的重复项**（保持"核心 vs 可选"架构与 verify_install
    语义一致）。
- 系统级依赖（README 补齐）：LibreOffice（渲染 QA）、中文字体 SimSun + Times New
  Roman（非 Windows 需 Noto Serif SC 等并配置 resolve_cjk_font）、Georgia/Microsoft
  YaHei（PPT）、playwright chromium（仅 visual_review）；外部服务：EWO 生图（封面
  路径 A）、AnySearch API key、Kimi WebBridge。

### 全流程跑通检测（7 项全 PASS）

- 全量 py_compile：203 文件无语法错误；
- `check_runtime_dependencies.py`：19 项 OK（含 LibreOffice）；
- `verify_install.py`：PASS（dependencies / embedded_components / journal_init）；
- 回归测试 7/7 PASS：word_delivery、figure_delivery、excel_delivery、
  ppt_delivery、workflow_runner（4/4）、modeling_chain（14/14）、
  anysearch_embed（6/6，错误归一化/额度信号等纯逻辑项）；
- fcntl（visual_review.py）确认有 Windows 回退，非跨平台 bug。

## v1.1.5 — 2026-08-10（图表美化全部规则封装 + 机械回归门禁固化）

### 新增

- **`scripts/verify_chart_svg_quality.py`（机械回归门禁）**：把本轮所有美化教训封装为
  可执行检查——① 字号 ≥8pt；② 色板白名单（kami-broker + 允许着色，matplotlib 默认色泄漏即失败）；
  ③ 字体双轨按内容判定（含中文必有 SimSun、含拉丁必有 Times New Roman，纯拉丁图合法无 SimSun）；
  ④ 图内顶部零文字（图内标题/图注残留检测）；⑤ 文本重叠检测（**解析器兼容 style 在前的
  属性顺序**——v1.1.4 教训：旧正则漏报 fig5 底部 5 标签全挤重叠）。注册/插入 Word 前必过。
- `references/chart-polish-and-variety.md` §5：写作层预控规则固化——底部刻度按柱间距
  `fit_label` 截断、类别轴禁数据坐标装饰带（fig8 xlim 撑爆教训）、Pareto 数值入柱白色、
  散点/矩阵标注白底衬+象限偏移。
- SKILL.md 新增图表机械回归门禁硬性条款。

### 重跑验证（与当前 Word 文档一致性）

- `verify_chart_svg_quality.py`：16/16 OK（并当场抓到 fig3 纯拉丁热力图无 SimSun 的
  误判，门禁改为按内容判定后通过——门禁本身经过真实回归打磨）；
- `validate_figure_delivery` 16/16 OK、`validate_word_delivery` OK、Stage gate OK；
- docx 内嵌 16 图与 deliverables PNG 哈希逐一比对一致（zip 级核对，非仅渲染 QA）。

## v1.1.4 — 2026-08-10（图9-1 底部主题标签挤压 + 重叠检测正则补漏）

### 修复（用户反馈：图9-1 底部"品牌口碑、疑虑"等文字重叠）

- **fig5 Pareto 底部 x 轴刻度标签截断**：5 个主题名（如"投资回报疑虑（是否值得装）"）
  在柱间距仅 ~68px 下全部互相挤压重叠（9pt 中文每字 12px，6 字以上必撞）——用
  `chart_polish.fit_label` 按每格 ~62px 预算截断（"投资回报疑虑（是否值得装）"→
  "投资回报疑…"、"品牌口碑积累"→"品牌口碑…"等）。
- **重叠检测正则补漏（重要教训）**：matplotlib SVG 的 `<text>` 属性顺序可能为
  `style="font-size: 9px; ..." x=".." y=".."`（style 在前），此前检测正则要求
  `x..y..font-size` 顺序导致 fig5 等图**漏检**（误报 0 重叠）。修正为正则兼容两种顺序，
  全 16 张重扫：**0 重叠**（fig5 截断后底部标签恢复正常分布）。
- 重生成 + 重嵌 Word + 渲染 QA（29 页、16 页各含 1 图、图9-1 在第 19 页）
  → Word delivery OK → Stage gate OK。

## v1.1.3 — 2026-08-10（图9-1 Pareto 与图13-1 风险矩阵注释重叠修正）

### 修复（用户反馈：图9-1 图注、图13-1 文字重叠）

- **fig5 Pareto**：柱顶数值标签与累计线（右轴红色曲线）视觉交叉——数值标签**移入柱内
  白色居中**（与热力图深格白字一致），柱顶区域只保留累计线与 80% 参考虚线，文字不再压线。
- **fig15 风险矩阵**：风险名标注与象限分隔虚线/区域着色交叉——标注加**白色圆角底衬**
  （bbox facecolor=white alpha=0.9）+ **按象限智能偏移**（右上象限的标注左移避免出界、
  左下象限的标注右上偏移避开分隔线），任何线穿过时文字仍可读。
- 重生成 + 重嵌 Word + 渲染 QA（29 页、16 页各含 1 图、图9-1 在第 19 页/图13-1 在第 26 页）
  → Word delivery OK → Stage gate OK。

## v1.1.2 — 2026-08-10（图内顶部零文字 + fig8 类别轴装饰带 bug）

### 修复（用户反馈：去掉顶部灰色字；fig8 底部"基准"重叠）

- **图内顶部零文字（硬性）**：16 张图全部移除顶部灰色图注（`title_block` 改 no-op）——
  图题由 Word 图题行承载，任何图内顶部文字都会与绘图区重叠（两轮用户反馈固化）。
- **fig8 情景预测重叠根因**：`ax.axvspan(700, 1080)` 写在**类别轴**上，xlim 被撑到 ~1080，
  三根柱与"低/基准/高"刻度标签全部挤在 x≈69px 处互相重叠——删除该装饰带后标签正常分布
  （x=92/217/341）。
- 重生成 + 回归（色板/字号/字体/0 重叠/顶部 0 残留）→ 重嵌 Word → 渲染 QA
  （29 页、16 页各含 1 图、图题对应正确）→ Word delivery OK → Stage gate OK。

## v1.1.1 — 2026-08-10（图内标题/饰线移除 + 图注单行化）

### 修复（用户反馈：美观达标但文字重叠/错版）

- `title_block` 重定义（v2.1）：**移除图内 16 pt 标题与 3 px 墨蓝饰线**——Word 图题行
  （"图X-X 标题"）已承载标题，图内重复导致渲染重叠/错版；仅保留顶部一行 9 pt 灰短图注，
  ≤32 字符、超长截断加省略号、禁止换行压入绘图区。
- 16 张图图注全部精简为单行短句（如 fig10 "2019 松绑 → 2025 密集落地 → 2026 IDAE + 新 RD"、
  fig9 "官方 5/协会 2/研究 10/零售 10/社区 6/媒体 11"）。
- 重生成 + 回归（色板/字号/字体/0 重叠）→ 重嵌 Word（16 图 + 尺寸修正）→ 渲染 QA
  （30 页、16 页各含 1 图）→ Word delivery OK → Stage gate OK。

## v1.1.0 — 2026-08-10（Word 图表全量美化：kami-broker-v2 视觉层）

### 规则固化（用户反馈"图很丑"后的返工教训）

- 主题升级 `kami-broker-v2`（`scripts/kami_broker_chart_theme.py`，THEME_ID 已提升）：
  - `apply_kami_broker_theme_v2()`：标题 16 pt 粗体墨蓝（v1 的 12pt 在 Word 宽度下过小）；
  - `bump_min_font(fig, 8)`：**8 pt 标签下限**机械兜底（v1 曾出现 7px 标签）；
  - `apply_mixed_text_fonts` 升级：混合中英串改为 `['SimSun','Times New Roman']`
    逐字形回退（v1 deck 全部 SimSun，数字未走 Times New Roman）；
  - `title_block()`：16 pt 标题 + 3px 墨蓝饰线 + 9pt 灰副题。
- `scripts/chart_polish.py`：`place_bar_labels` 默认 min_font 7→**8**（放不下丢弃而非缩小）；
  `save_manifest` theme_id 随 THEME_ID 升级。
- 验证器与打包器 `kami-broker-v1` 硬编码全部升级为 v2
  （validate_word_delivery / build_final_report_package / build_fused_word_template）。

### 全量返工（16 张图逐图升级）

- fig1 趋势线 + 2026E 预测虚线/淡色带；fig5 Pareto + 累计占比线 + 80/20 参考；
  fig6 雷达图例置顶、刻度 ≥8pt；fig7 横向排名条；fig8 情景区间带；
  fig14 毛利堆叠条 + 分区线；fig15 风险矩阵象限分隔线；fig3/4 热力蓝阶
  （#EEF2F7→#1B365D 五阶）+ 深格白字；fig2/9/10/11/12/13/16 按 v2 层重出。
- 机械回归全绿：16 张色板白名单 0 违规、字号下限 ≥8pt、字体双轨齐全、标签 0 重叠、
  `validate_figure_delivery` 16/16 OK。
- Word 重新嵌入（zip 级原位替换 16 图 + 按新宽高比修正显示尺寸）→
  `polish_word_ib_style` → 渲染 QA（30 页、16 页各含 1 图、图题对应正确）→
  Word delivery OK (0 fail, 0 warn) → Stage gate OK。

## v1.0.7 — 2026-08-10（封面/正文排版方案全量固化）

### 规范统一（消除文字规范与机械门禁漂移）

- `references/ppt-style-prompts.md` §2.3 浅色咨询降级封面配方**重写为审计裁决版**：
  此前描述为"全宽 4px 顶部/底部饰带 #0033A0"（旧版，与实际左侧竖条版不一致），现与
  `audit_cover_compliance.py` 8 项机械检查逐项对齐，并给出 2026-08-10 验证通过的坐标级
  配方（白底/18+5px 左饰带/机构页眉/46-52px 衬线主标题/结论横幅单行/三列元信息/
  页脚 start 锚定 x≈1092/零插图），注明以审计为最终裁决。
- `references/ppt-style-prompts.md` 新增 **§1.3 正文页页面件坐标级约定**：动作标题
  （Georgia 30px y=120）、章节名/页码（x=120/1220 y=59）、页脚双行（y=678，左数据来源
  右机构·日期 start 锚定 x=1108，禁 end 锚定靠右缘）、卡片样式（圆角+1px D9E2EC 描边/
  F3F6FA 浅底）、KPI 三列卡（Georgia 40px 单行含单位永不拆行）、结论横幅、底部
  "详见第 X 页"链接（与正文末行 ≥20px）、正文行距 font-size×1.45。

### 验收

- 西班牙户储最终版 PPT 全部页面件与本约定一致（12 页 0 重叠 0 越界）；
- 三道门禁（文本溢出 --check / 封面审计 8/8 / 渲染几何 verify_ppt_render_geometry）
  全绿，规范与机械裁决零漂移。

## v1.0.6 — 2026-08-10（渲染后几何门禁固化）

### 新增

- `scripts/verify_ppt_render_geometry.py`：**渲染后几何门禁**——导出 PPTX 后自动调
  LibreOffice 渲染为 PDF，PyMuPDF 提取 span 级文本几何：任何文本重叠 >3pt×3pt、或越出
  1280px 画布（右界 >962pt / 左界 <0pt）即退出码 1 阻断注册。捕获渲染器独有的问题
  （LibreOffice 忽略 spAutoFit 按框宽重排拆行、换行块压入下方元素、右缘文本框越画布被裁），
  此前仅为临时内联检测，现为注册前必过门禁。
- SKILL.md 新增该门禁硬性条款；references/text-control-spec.md 新增 1c 节
  （渲染几何门禁契约与修复原则：回到 SVG 写入源头，不在渲染层打补丁）。

### 试跑结论

- 西班牙户储最终版 PPT：12 页 span 级 0 重叠、0 越界，门禁通过（EXIT=0）。

## v1.0.5 — 2026-08-10（页2 错版修复 III：token 断行 + 渲染重排防护）

### 修复

- `scripts/wrap_slide_text.py`：
  - `card_rights` 修复 `<path>` 卡片**高度推断 bug**：此前仅捕获 `M x0,y0 H x1` 片段、未解析
    `V` 命令，高度回退 y0+60 导致页眉标签/分隔线（真实高 <30px）被当作幻影卡片，窄右界
    误触发大量碎行换行（"351.6"被拆成"351/.6"、"540 MWh"被拆行的根源）；现解析完整
    d 属性取真实 y1，真实高 ≤30px 的装饰条自动排除；
  - 换行算法改为**原子 token 断行**：数字串+单位（"351.6 MWh"、"2026–2030"）、拉丁单词
    永不拆行；闭合标点（，。；：、）】）不悬行；超宽单 token 才做字符级硬切；
  - 宽度估算**衬线感知**（Georgia/serif 拉丁 0.62em vs 无衬线 0.55em），并新增**自由文本
    画布越界检查**（不在卡片内的标题/页脚按 1280 画布右界校验，防 Georgia 标题渲染越界）；
  - KPI/衬线大字号（Georgia 或 font-size≥25）永远单行，由写入方缩短措辞适配。
- `scripts/svg_to_pptx/drawingml_elements.py`：
  - 单行文本框宽加 1.5x/多行 1.3x 余量：LibreOffice 忽略 `spAutoFit`、按框宽重排，
    估算 0.55em 低于 Georgia 实际字形宽，导致 "540 MWh" 渲染拆行——加余量后两个渲染器一致；
  - 文本框钳制在画布内（防右缘文本余量框越出 1280 导致端对齐页脚被裁）。
- 封面：Path B 纯白封面必须**零插图残留**（此前备份含 translate(890,150) 能量流插画组，
  标签"储能/电网"越出画布被裁、"自用"剩"自"）；审计新增 `no_illustration` 检查：
  已知插画标记 + 任何 translate(x≥500) 的右区插画组判定。

### 试跑结论

- 12 页 PDF 像素级检测：**0 重叠、0 越界**；页 2 KPI（540 MWh/700–1,080 MWh/+589%）单行；
- 页 8 价格表 "€2,734.60 / 4,550 / 6,430" 单行；页 12 高风险项/时间线布局恢复正常；
- 封面审计 8/8 passed（含 no_illustration: true）；最终审计 Stage gate validation: OK。

## v1.0.4 — 2026-08-10（试跑回归修复 II）

### 修复

- `scripts/wrap_slide_text.py`：
  - 换行输出改为**独立 `<text>` 元素**（svg_to_pptx 不支持 `<tspan>`，此前 tspan 导致导出失败）；
  - `card_rights` 兼容 finalize_svg 转换后的**圆角矩形 `<path>` 形态**（M/H/V 边界盒解析）；
  - 卡片右界取**最小命中卡**（此前全页背景卡优先导致 max_w 过大、长文本漏拆）；
  - `--check` 校验加 10% 渲染宽度安全边距。
- PPT 封面插画组位置修正（translate 890→620，电网塔等右端元素此前超出画布右界）。

### 试跑结论

- 12 页卡片长文本全部换行（58 处，独立 text 元素）；像素级检测**全部页面零越界、零文字堆叠**；
- 封面 Path B 白底咨询风确认（背景白、左侧饰带、底部深蓝文字为正常元素）；
- 封面审计 passed；最终审计 Stage gate validation: OK (0 fail, 0 warn)。

## v1.0.3 — 2026-08-10（文字事前控制规范）

### 规则固化（从"事后修复"改为"事前控制"）

- 新增 `references/text-control-spec.md`：PPT 每个 `<text>` 写入前按卡片宽度预换行（`<tspan>` 行距 font-size×1.45，续行同 x）；标题/数字单行缩短措辞；图表标签窄面板先截断再写入；页码不换行。
- SKILL.md 新增硬性条款：导出前必须跑 `wrap_slide_text.py --check`（退出码 1 阻断导出），修复在写入源头而非事后。

### 工具增强

- `scripts/wrap_slide_text.py`：新增 `--check` 预检模式（仅检测不修改，退出码 1=存在溢出），并支持 `--project-dir` 通用参数。
- `scripts/chart_polish.py`：新增 `text_width`（CJK≈1.0em/拉丁≈0.55em 宽度估算）与 `fit_label`（写入前截断标签到可用宽度，带省略号）。

## v1.0.2 — 2026-08-10（试跑回归修复）

### 新增

- `scripts/wrap_slide_text.py`：PPT SVG 卡片长文本自动换行工具（检测超宽 `<text>`，按卡片右界拆分为 `<tspan>` 多行；保留 font-family/fill 等属性；跳过 text-anchor=end 页码与已换行文本；中文/拉丁混合宽度估算）。

### 修复

- `scripts/audit_cover_compliance.py`：`conclusion_bar` 检查兼容 finalize 后的 `<path>` 形态（圆角矩形被 finalize_svg 转为 path），此前仅匹配 `<rect>` 导致封面审计误报。

### 试跑回归结论

- PPT 12 页卡片长文本溢出（页 2-12 右侧卡片正文超出卡片右界）已通过 tspan 换行全部修复；渲染后无结构性溢出，仅剩 PDF 文本提取伪影级差异（同行词中心距 <1px）。
- 封面 Path B 合规审计通过（7 项全过），`cover_prompt_compliance` 来自真实审计。
- 最终审计：Stage gate validation: OK (0 fail, 0 warn)。

## v1.0.1 — 2026-08-10（西班牙项目实战修复沉淀）

### 新增（内嵌能力）

- `scripts/chart_polish.py`：券商研报级图表组件——浅色面板/细网格/label-safe 数据标签避让（`place_bar_labels`，无 adjustText 依赖）/`save_manifest`（自动写 generator、源 hash、qa 块）；图型库：环形图、对数气泡图、2×2 风险矩阵、漏斗图、瀑布图。
- `scripts/audit_cover_compliance.py`：路径 B 白底咨询风封面真实合规审计（7 项检查），结果写入 `image_acquisition_manifest.cover_compliance_audit`。
- `references/chart-polish-and-variety.md`：图型选择矩阵、label-safe 布局契约、manifest 卫生与回归清单。
- `references/cover-path-b-audit.md`：路径 B 封面审计规范（白底/饰带/衬线标题/结论横幅/三列元信息/页脚）。

### 修复

- `register_high_fidelity_ppt_delivery.py`：`cover_prompt_compliance` 改为读取真实封面审计结果（此前硬编码 True，审计形同虚设）。
- `recalculate_excel.py`：新增 `restore_consulting_fonts()`——LibreOffice 重算把 Arial 替换为系统 CJK 字体导致 data_font 校验失败，现 zip 级恢复 Arial 且保留公式缓存。
- `presentation_production.py`：PIPELINE_ID 对齐正式 PPT 管线 `embedded-pptmaster-svg-v1`（原先 fallback 标识导致正式 PPT 审计误报）。
- `validate_deliverables.py`：PPTX 扫描排除 `~$` Office 锁文件（用户打开旧版时阻塞审计）。
- `generate_collection_audits.py`：count-evidence JSON/注册表官方生成器（此前仅验证器无生成器，字段名漂移：`critical_claims`/`query_batches`/`high_priority_remaining_ids`；主源判定、R3 独立三角验证、评论单平台约束与验证器规则一致）。

### 规则固化（SKILL.md 新增硬性条款）

- 图表美化与多样性：必须用 `chart_polish.py` 组件，图型按选择矩阵多样化（禁止章节全柱状图），`figure_type` 准确标注。
- 路径 B 封面必须通过 `audit_cover_compliance.py` 真实审计，`cover_prompt_compliance` 禁止硬编码。

# Changelog

本仓库版本记录（按语义化版本）。

## v1.0.1 — 2026-08-10

### 新增

- **单入口一键总流程**（`run_workflow.py`）：
  - `--all`：init（缺省时）→ check(0-4 draft) → collect → modeling → build-final-report → audit，输出每步汇总；
  - `--collect`：按 `02_Web_Collection_Tasks.csv` 机械执行（每行 run_task 至目标/政策下限 attempt 数，自动台账与状态更新）；
  - `--modeling`：建模链脚本化步骤（gates draft 检查 + 人工门通过时生成 12/13/14；门未决报告待决不假装通过）；
  - `--dry-run`：打印命令序列不执行；`--official-cli` 双路径支持。
- 回归：`regression_test_workflow_runner.py`（4 用例：dry-run 序列 / 无网络小流程 / 建模分支产物 / 人工门待决）。
- GitHub 封装（P2a）：README/README_zh、LICENSE（Apache 2.0）、THIRD_PARTY_NOTICES、
  .gitignore、.env.example、install.ps1/install.sh、verify_install.py。

### 修复

- math-figure-generator 附件布局（相对链接解析）、doctor 建模链 27 项同步检查、manifest 计数与 legacy 清单对齐；
- `install.ps1` Windows PowerShell 5.1 中文乱码（输出改英文，指引在 README_zh）；
- `verify_install.py` 依赖模块表修正（svgfig→svglib，与实际 requirements 一致）；
- `run_workflow.py` 补 `--official-cli` 参数与 `read_csv` 导入（collect 步骤所需）。

## v1.0.0 — 2026-08-10

一体化海外能源市场调研 Skill 首版。全部能力已内嵌并经回归测试 + 真实环境验收。

### 新增（内嵌能力）

- **联网采集**：官方 AnySearch 3.0.1 CLI 零 diff 内嵌（全命令面、16 垂直域、Apache 2.0）；
  Kimi WebBridge 客户端（13 action 契约表、生命周期、登录态检查、故障分类）+ 官方契约/操作文档完整内嵌；
  统一 CLI（`web_collection/cli.py`：doctor/search/batch-search/extract/browse/auth-check/journal-summary）、
  采集台账（`13_Collection_Attempt_Journal.csv`）、错误归一化（402/429→insufficient_balance、503 重试一次、
  Rate limited 重试秒数提取）、http_fetch 静态回退（登录墙检测 + 双留痕）。
- **采集完整性门禁**：防少搜（每 R1/R2/R3 任务 attempted ≥ 目标/政策下限）、防假完成
  （未解决阻断类错误禁止 completed）、失败必须带错误类与原因、成功必须有存在的 raw capture；
  与既有来源台账/记录注册表/数量政策 v8 全链衔接。
- **数学建模完整链**：24 个建模 skill 指令文档零 diff 内嵌（MIT，含 math-figure-generator 及附件）；
  G1/G2/G3/G6 机械门脚本化，G2.5/G4.5 人工门（`decided_by=human` 强制，AI 不可自置通过）、
  G4 冻结新鲜度；12/13/14 CSV 唯一写入方与完整性校验；建模链门禁接入 Stage 6。
- **交付链**（承接既有验收）：Word（投行风格、三线表、逐页渲染 QA）、Excel（咨询主题、公式保留）、
  图表（SVG+300dpi PNG+登记）、高保真 PPT（svg→DrawingML 全管线、转场/动画/讲稿、EWO 回退）。
- **打包**：README/README_zh、LICENSE（Apache 2.0）、THIRD_PARTY_NOTICES、.gitignore、
  .env.example、install.ps1/install.sh、verify_install.py。

### 修复（真实闭环与审计发现）

- 采集层：CLI `--project-dir` 子命令位置解析、raw capture 文件名唯一性（防覆盖丢数据）、
  auth-check 证据落盘、kimi 错误类归一化、401/403→auth_required、PSL 缺失 `co.th`（泰国域名）、
  信封响应格式兼容（真实 daemon v1.11）、URL 回声不误分类、并发台账 ID/表头、
  `run_action` 异常拆分（未知异常归 unknown 而非误标 timeout）、`daemon_logs(follow)` 明确拒绝、
  goal 路径清洗（防路径逃逸）、stderr/stdout 错误特征合并扫描、台账 session 与 daemon 归一化对齐、
  `update_task_status` 找不到任务时显式报错、"Rate limited" 识别与重试秒数提取（anysearch 额度刷新信号）。
- 建模链：G1/G2/G3/G6 接入 Stage 6 门禁、G6/G3/G2 假绿正则修复（NOT PASSED/NOT PASS/小节计数）、
  人工门按 decision_id 分派、CRLF/BOM 决策工件解析、frozen 损坏→fail、manifest 缺省语义对齐、
  math-figure-generator 附件布局链接修复。

### 验收

- 8 个离线回归全 PASS（anysearch/kimi/web_collection/modeling/word/excel/figure/ppt）；
- 真实环境验收：anysearch 真实 API（search/extract 与官方逐字节一致）、kimi 真实浏览器
  （navigate/snapshot/登录墙检测）、真实项目闭环（R1/R2/R3 → 台账 → 验证器 → 审计报告）。
## v1.2.9 — 2026-08-12（无视觉模型图表生产 + 真实图表重绘）

- DeepSeek 等无视觉模型只提交证据关系、字段、结论和来源，Python 确定性解析器接管选型、排版、配色与长标签处理；新增自动视觉 QA，检查字号、越界、实质文字碰撞、画布比例和文字密度。
- 图型门禁升级为“类型 + 视觉家族”双层：bar/ranking-bar/grouped-bar/lollipop/dot-plot 合并为单轴比较家族，全篇最多 4 次，禁止用棒棒糖图替代柱状图制造虚假多样性。
- 新增 KPI 卡片、评分卡、决策卡片、风险卡片、点图、情景区间、气泡排名与 Pareto 渲染器，以及按章节原位替换 Word 内嵌图的脚本。
- 澳洲 V2G 真实报告 15 张图已重绘并原位替换，Word 31 页渲染和结构门禁全部通过。
