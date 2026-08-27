# Format And Visual Style

## Contents

1. Word
2. Excel
3. PPT
4. Visual system
5. Narrative and QA

## Word

Use the embedded fused-template Word pipeline for typesetting and approved charts. Apply an objective strategy-consulting style with evidence-rich paragraphs and restrained language. Avoid decorative wording, generic AI phrasing, quotation marks used for emphasis, and semicolons in Chinese narrative.

Exact typography:

- 一级标题: 黑体二号, bold, centered, explicit 0 pt left/right/first-line indents (并清除字符单位缩进 `rightChars` 等), 18 pt before, 12 pt after, fixed 30 pt line spacing, 无底部横线（删除样式/段落级 `pBdr` 底边线，横线横跨整栏会让居中标题看起来居左）。仅设置居中而保留模板继承缩进或横线视为失败。
- 前置内容: 生成报告只保留正文；封面后的"文档控制与使用说明"章节由 `build_template_report.py` 的 `strip_template_front_matter()` 删除。
- **模板残留章节检测（硬性）**：生成报告后必须检查是否存在重复章节标题（如同一编号出现两次，如两个"二、"章节）。若发现重复，删除模板残留版本（通常内容较短或为占位文本），保留实际内容版本。检测方法：遍历所有 Heading 1 标题，检查是否有相同编号前缀重复出现。
- **章节文字完整性（硬性）**：每个章节（Heading 1）和子章节（Heading 2）的标题之后、图表之前，必须有至少一段实质性分析文字（≥50字符）。禁止标题后直接跟图表。若内容不足，必须补充该章节的分析概述段落。
- 二级标题: 仿宋四号, bold, left, 6 pt before/after, fixed 24 pt.
- 三级标题: 仿宋小四, bold, left, 6 pt before/after, fixed 24 pt.
- 四级标题: use `（1）（2）（3）`, not `1.1.1.1`; 宋体小四, 0 pt before/after, fixed 24 pt, first-line indent two Chinese characters.
- Body: Chinese 宋体小四; Western text/numbers Times New Roman 小四; 0 pt before/after; fixed 22 pt; first-line indent two Chinese characters; justified.
- Figure/table caption: 宋体五号, not bold. Number by chapter, such as `图1-4` and `表2-3`.
- Table title above the table: 6 pt before, 0 pt after.
- Table title: centered and set to `keep_with_next=true` plus `keep_together=true`, so the title and the following table cannot split across pages. A table title orphaned at the page bottom is a blocking error.
- Every report table has exactly one caption immediately before it; every caption is immediately followed by exactly one table, and every `表N-x` number is unique. Duplicate generic captions or orphan captions are blocking errors.
- Figure title below the figure: 0 pt before, 6 pt after.
- Refer to every figure/table in body text, such as `见图1-2`.
- Table body: 宋体**小五(9pt)**, single spacing, all text horizontally and vertically centered, no first-line indent, three-line table. 表格整体居中（tblPr `jc=center`），表头加粗。
- **表格规则（验证版）**：整体居中、文字宋体小五 9pt + 西文 Times New Roman、表头加粗、全部单元格水平垂直居中、无首行缩进、段前段后 0、单倍行距。严格三线表的顶线和底线均使用黑色 `#000000`、1.5 pt（OOXML `sz=12`）；表头下线使用深蓝 `#1B365D`、1 pt（`sz=8`）；禁止左右边线、竖线和表体内部横线。表头浅蓝灰底 `#D9E2EC` + 深蓝字，表体白底。由 `scripts/build_template_report.py` 的 `format_tables()` 自动应用。
- **数据来源命名（硬性）**：图表/表格来源注统一以 `数据来源：` 开头，禁止使用 `资料来源：` 或 `数来源：`。
- **图片段落规则（验证版）**：单倍行距、段前 6pt、居中；图题在图下方（宋体五号 10.5pt 不加粗、按章编号 图1-x），来源注 9pt 灰色。
- **图表中文字体（验证版，硬性）**：图表 SVG 必须保留可编辑 `<text>` 节点，并显式记录当前系统可用的 CJK 字体样式；禁止文字转路径或只交付 PNG。`validate_figure_delivery.py` 机械检查可编辑文本节点与字体样式，最终仍需打开 SVG/PNG 目检中文显示。
- **图表配色（验证版）**：`kami-broker-v1` 使用白底、深蓝 `#1B365D` / 次级蓝 `#2D5A8A` / 冷灰阶，绿色和红色仅表达正负方向；与模板表头色 `#D9E2EC` 协调，不使用米色底、渐变或装饰性 3D。
- **图表命名规范（验证版，硬性）**：正式图表命名 `figN_*.png`（fig1_price.png / fig2_mix.png / fig3_rating.png）；测试/临时图命名 `test_*`，**不得**留在 charts 目录（`build_template_report.py` 只插入 `fig*.png`，混入测试图会进入报告）。
- **图表唯一责任路由（硬性）**：非模型市场洞察/证据图由 `embedded-market-figure-v1` 独占负责；预测、优化、经济性、敏感性、稳健性及其他建模图由 `embedded-modeling-figure-v1` 独占负责。两者均由本 Skill 的 Python 管线执行，禁止重复生成或二次美化。每张正式图的 `.theme.json` 必须记录 `figure_pipeline_id=embedded-figure-production-v1`、唯一 owner、class、来源/脚本/输出哈希、可编辑 SVG、≥300 dpi PNG 以及机械和人工视觉检查结果。
- **每章必有图表规则（硬性）**：每个一级标题章节至少包含一张正式图表（figN_*.png）。不允许任何章节仅有文字而无图表。数据不足时使用示意图、流程图或框架图补充，仍须遵循命名和格式规范。
- **图表接文规则（硬性）**：图表不得单独出现或悬空插入，必须紧跟在成段文字之后。顺序：先写分析段落 → 段落末尾引用图表（"见图N-x"） → 插入图表、图题、来源注。禁止在章节开头、空白段落后或两个图表之间无文字过渡时直接插入图表。
- Written text is black. Color is limited to charts, fills, dividers, and data encodings.

### 文风标准（2026-08-06 定稿：投行行业研究风格，硬性）

Word 报告必须读起来像人写的投行研报，而非模板填充产物。禁止任何"工作底稿痕迹"：

- **禁止骨架标题残留**：每章的"本章关键问题：…？；…？"、"证据、分析与反证："等模板四级标题一律删除或改写为自然过渡句。
- **禁止标签前缀段**：正文段不得以"小结：""数据引用：""证据支撑：""反证与限制：""看宏观/看行业/看客户/看自己："等标签开头。改写为自然叙述："综上，…""从宏观层面看，…""需要指出的是，…"。
- **禁止数据行 dump**：CSV 表格行（字段粘连，如"BESS市场规模（2025）18亿美元Mark & Spark Solutions"）不得作为正文段。数据融入通顺分析句或放表格。
- **禁止内部痕迹**：证据编号（S001/C001/R001）、CSV 文件名、内部缺口编号（D003）不得入正文；引用改为自然表述（"根据 Mark & Spark Solutions 数据…"）。
- **禁止转义符**：正文不得含 `\-` `\.` `\+` 等 markdown 转义符。
- **来源注位置**：来源注只在图表下方（9pt 灰、`数据来源：` 开头、自然来源描述）；正文段尾不得悬挂"（数据来源：…）"独立段。
- **术语中性化**：避免"证据"类内部用语——列名"关键事项/来源编号"、表题"本章关键数据与来源"、章节名"数据体系/数据缺口"。
- **重复内容清理**：章节间不得有完全相同的段落；同一来源注不得连续堆叠多条。
- **图表引用**：每个图表必须在正文中被引用（"见图N-x"/"见表N-x"），引用格式正确（不得出现"（见图图N-x）"重复字）。

### Word 生产常见错误与纠正（2026-08-06 教训固化，生成后逐条自查）

**生成后必须运行 `scripts/polish_word_ib_style.py <docx>`（幂等后处理，硬性）**——自动完成：删模板骨架/占位段、删模板占位正文、来源注去重与规范化、表头/表题中性化、图按章分布重编号（IMG→图题→来源注）、正文引用修复。未运行视为交付失败。以下为清单：

1. **CSV 行 dump 成正文段**（曾出现 123 段）：字段粘连行必须写成通顺分析段或放表格；生成后扫描短段+无句号+含数值/公司名粘连特征。
2. **模板占位段残留**（"表X-X 本章证据与分析索引"、"数据来源：；访问/提取日期：；…"空占位、"（1）本章关键问题"骨架）：占位章节必须 `strip_all_template_chapters()` 移除或完全覆盖；polish 脚本自动清理，运行后扫描"表X"、"数据来源：；"。
3. **来源注重复堆叠**（曾同一来源注连续 19 条）：每图/表仅一条来源注；polish 只删连续堆叠，跨章节各自表后的同文本来源注是合理布局，不得误删。
4. **来源注前缀粘正文**（"数据来源：项目组分析从客户收入看，…"）：必须拆分，正文恢复自然开头；polish 仅对含完整句子的长正文拆分，图表下方短来源注不受影响。
5. **图题位置**：图题必须在图片下方（图片段 → 图题段 → 来源注段），polish 自动重排并逐页渲染检查。
6. **段落索引错位**（曾按序号删除误删/误改段）：结构性增删后必须重新获取段落列表（fresh），或按内容定位（startswith/全文匹配），禁止沿用旧索引。
7. **整段替换截断**（曾把长段替换成只剩前缀）：改写新文本必须含完整内容；改写后扫描异常短段（<15 字非来源注段）。
8. **LibreOffice 渲染崩溃**（退出码 3221226505）：python-docx 保存后偶发，round-trip（重新打开再保存）即可正常渲染。
9. **引用重复字**（"（见图图N-x）"）：编号已含"图/表"字，拼接时编号需去掉前缀；polish 自动修复。
10. **表头"证据"字样**：列名"证据/分析项"→"关键事项"，"证据编号"→"来源编号"，表题"证据与分析索引"→"关键数据与来源"；polish 自动处理。

### Template Remnant Handling (Critical)

The Word template (`energy_market_research_report_template.docx`) contains 14 placeholder chapters with empty tables and placeholder text. These MUST be removed before adding content:

```python
from word_report_helpers import strip_all_template_chapters
doc = Document(str(TEMPLATE))
strip_all_template_chapters(doc)
```

**Why this is needed**: The template has H1 headings for chapters like "核心结论与证据状态", "一、执行摘要与决策问题", etc., each with empty tables and placeholder text. If not removed, these appear in the final report alongside the actual content.

**What `strip_all_template_chapters` does**:
- Finds the first H1 heading in the document
- Removes all elements from that H1 to the end of the document
- Preserves `w:sectPr` (page layout properties)
- Returns the number of elements removed

**After stripping**, add your content using `add_three_line_table()` from `word_report_helpers.py` for proper three-line table formatting.

Content requirements:

- Unless shortened by the user, target 15,000-30,000 Chinese characters and at least 30 pages.
- Use large evidence-backed paragraphs where interpretation needs depth, but preserve chapter summaries and readable visual anchors.
- Put source, update date, value type, and caveat below each major chart/table.
- Use the bundled `market-insight-five-views.md` and `market-insight-report-contract.md` for market-research writing; use the modeling chain for modeling chapters. The external `market-insight` Skill is optional.
- Load `libreoffice-rendering.md`, render with `scripts/libreoffice_render.py`, and inspect every page before delivery. Do not call unbounded `soffice --convert-to` directly.
- During page inspection, confirm every table title appears on the same page as the first row of its table; fix pagination and rerender if any orphan title is found.

## Excel

Use the embedded `style_excel_consulting.py` consulting-report visual system; do not require a separately installed Excel Skill.

- Separate scope/approval, observed evidence, assumptions, calculations, outputs, and sources.
- Freeze headers, enable filters, use data validation, consistent units, and professional number formats.
- Keep formulas as formulas and add formula/logic notes.
- Clearly label `观测值`, `推导值`, `模型估算`, `情景假设`, and `待核实`.
- Do not include a visible data-gap sheet. Keep internal issues outside the workbook.
- Keep the complete URL ledger in the final sheet named `99_来源与口径`.
- Use source hyperlinks and make long URLs readable.
- Audit formulas, error cells, units, currencies, exchange rates, tax basis, time periods, and totals.
- Use charts only where they improve a decision.
- **Excel 主题（验证版，硬性）**：使用内置 **浅色主题**（`default` 水蓝 #4472C4 或 `jade` 墨玉绿 #375623），不提供深色主题（长文本/URL 表格可读性差）。表头主题色底 + 白字加粗。
- **数据行填充（验证版，硬性）**：**数据行禁止继承表头填充色**（`sync_csv_to_excel.py` 已修复：`copy_style(copy_fill=False)`，数据行保持无填充白底）。曾出现 bug：表头 #123A7A 深蓝被复制到全部 438 个数据单元格导致看不清。**2026-08-06 补充修复：数据行字体同步强制为深色常规体（#1F2937、非加粗）**——只清填充不清字色会导致"白字白底"数据不可见；模板未覆盖列的表头统一套用深蓝底白字样式。
- **工作表维度压缩（验证版，硬性）**：sync 后必须压缩维度（`delete_rows` 删除数据区以下空行）。图表锚点会把 sheet 的 max_row 撑大（曾出现 201 行带格式空行导致数据"位移"）。
- **Excel 图表（2026-08-06 起废止，硬性）**：**不再生成任何 Excel 原生图表**——此前"图表锚定在数据表右侧（最后一列+2，`TwoCellAnchor`）"的规则废止，`scripts/add_excel_native_charts.py` 停用，工作簿只保留格式化数据表。图表需求由 Word 的唯一责任 Skill 路由生成，并由 PPT 复用或制作 slide-native 视觉。原图表量纲过滤、中文标签辅助列、防重叠、无数值列跳过、图表类型库等配套规则一并废止。

## PPT

Use the embedded presentation pipeline for all presentations. **风格权威文件：`references/ppt-style-prompts.md`**——内含两份固化提示词模板原文与全部可执行参数：§1 正文页麦肯锡浅色咨询风，§2 封面深蓝科技风与自动降级版。制作任何 PPT 前必读该文件；无需安装 `ppt-master`、`pptx` 或 `ewo-image-generate` Skill。

Core style:

- Top-tier strategy-consulting logic with high information density and precise visual hierarchy.
- Answer-first insight titles.
- White content slides with pure black text and restrained deep royal blue/cobalt/cool gray accents.
- High-end serif title option: Times New Roman or Georgia.
- Sans-serif body/chart option: Helvetica, Inter, Arial, or an available metrically compatible substitute.
- Thin 1 px table rules and clean vector-style charts.
- Each slide includes sources, update date, and bias/assumption note.
- Use 2x2 positioning, radar/heatmap, value curve, price-capacity scatter, waterfall, sensitivity, confidence interval, scenario path, SWOT, and risk matrix only when supported by data.

Cover:

- **路径 A（默认且优先）**：深蓝科技风封面，左文右图，右侧使用 EWO 生成的矢量插画风格 PNG/JPEG/WebP 位图主视觉；由内嵌 `resolve_presentation_images.py` 直接调用 EWO 能力。这里的“矢量插画风格”只描述视觉风格，实际文件不是 SVG。AI 图只用于封面主视觉和非数据型场景插图，不得生成数据图表、统计图或替代真实产品参数证据。
- **路径 B（仅故障降级）**：只有当 AI 生图服务连通性、凭证或上游调用失败时，才改用麦肯锡浅色咨询排版封面。路径 B 不使用图片、插画或图标素材，以白底、皇家蓝饰带、衬线标题和底部元信息完成排版。
- 路径 A 注册时必须记录实际 AI 主视觉文件路径和 SHA256；路径 B 注册时必须记录结构化 `fallback_reason.code/detail`。正文插图失败时由主代理手写 SVG 矢量图，导出为可编辑 PowerPoint 原生对象。完整参数和生图约束以 `references/ppt-style-prompts.md` 为唯一权威来源。
- Default title: `V2G与储能产品市场调研` or a project-specific equivalent.
- Keep the cover corporate, formal, and research-oriented. Avoid student-competition, cartoon, logo clutter, low-quality collage, or over-marketing.

Render and inspect every slide before delivery.

For LibreOffice conversion, use `scripts/libreoffice_render.py` with an isolated profile, valid file URI, explicit timeout, and process-tree cleanup.

## Visual System

- Deep royal blue: `#123A7A`
- Cobalt: `#2563EB`
- Charcoal: `#1F2937`
- Cool gray: `#6B7280`
- Light gray: `#F3F6FA`
- Evidence highlight: `#0EA5E9`
- Risk: `#B91C1C`
- Optional cover highlight: restrained gold/yellow only

## Narrative And QA

- Start with the answer, then evidence.
- Separate fact, calculation, interpretation, recommendation, and counter-evidence.
- State assumptions and limitations close to the affected conclusion.
- Convert weak claims into testable hypotheses.
- Check that every visual can be traced to source rows and that no chart implies more certainty than the data supports.
