# Word Template Fusion Contract

## Purpose

Use this contract whenever the Skill creates, edits, packages, or exports a Word report. The fused template is the design authority. Do not start a formal report from a blank `Document()` and do not replace the template with a generic document preset.

## Source Contribution Map

| Source | Contribution |
|---|---|
| `assets/templates/reference_originals/券商研报模板01.docx` | Base OOXML theme, page furniture, style ancestry, and consulting-report visual lineage |
| `assets/templates/reference_originals/word_fusion_sources/规则限定描述.docx` | Mandatory fonts, sizes, line spacing, title hierarchy, caption rules, three-line tables, narrative tone, page/length target, and render requirement |
| `assets/templates/reference_originals/word_fusion_sources/欧洲阳台光储产品竞品分析-20260602.docx` | Competitor taxonomy, exact-model comparison, pricing/channel, user pain points, and opportunity synthesis |
| `assets/templates/reference_originals/word_fusion_sources/澳洲V2G&V2H市场深度调研计划-V1.2-20260520.docx` | Tariffs, household load, V2G/V2H economics, grid rules, customer archetypes, and regional policy analysis |
| `assets/templates/reference_originals/word_fusion_sources/非洲移动储能和户用储能深度市场调研计划-V1.0-20260610.docx` | Grid reliability, outage scenarios, affordability, mobile/off-grid storage, PAYG, serviceability, and country localization |
| `assets/templates/reference_originals/word_fusion_sources/车网互动规模化应用试点项目调研大纲-20260720.docx` | Pilot-project benchmarking, technical route, operating model, project results, scalability, and bottlenecks |

## Fusion Priority

1. Explicit user instruction.
2. `规则限定描述.docx` for typography and layout constraints.
3. The fused template for page system, styles, components, and placeholder structure.
4. The four research-plan documents for chapter coverage and field completeness.
5. The embedded securities-research editorial rules for restrained consulting-style composition.
6. Generic Word/document defaults only when the fused template has no applicable pattern.

Conflicts are resolved by the highest item in this list. Do not combine incompatible source styles on the same page.

## Authoritative Template

- Path: `assets/templates/word/energy_market_research_report_template.docx`
- Builder: `scripts/build_fused_word_template.py`
- Source manifest: `assets/templates/word/word_template_fusion_manifest.json`
- Retained originals: `assets/templates/reference_originals/`

The builder must open the retained broker-report DOCX, preserve its theme and package lineage, clear only the body content, and rebuild the editable body with fused styles and placeholders.

## Page System

- Page: A4 portrait.
- Margins: top 2.6 cm, bottom 2.4 cm, left 2.8 cm, right 2.6 cm.
- Use a restrained securities-research header: fixed institution name "四川动力电池产业创新中心" on the left, research category ("能源与电力设备专题研究") on the right, and one thin ink-blue divider.
- Use a restrained footer: internal-use disclaimer on the left and real `PAGE` / `NUMPAGES` fields on the right. Static page text such as `第2页 共9页` is forbidden.
- Keep the first-page header and footer blank.
- Formal reports include a cover, document-control block, executive summary, body chapters, conclusions/actions, and sources/appendices.
- Use real Word page breaks and real paragraph styles. Do not use blank paragraphs to force pagination.

## Embedded Securities Visual Boundary

Use the bundled Word template and style scripts for the overall editorial composition: disciplined whitespace, one ink-blue accent (`#1B365D`), warm gray metadata, thin dividers, restrained header shading, data-first hierarchy, and compact securities-report page furniture. Preserve a white Word page and a conservative Chinese securities-research appearance.

The following are immutable:

- A4 portrait, 21 × 29.7 cm.
- Margins: left 2.8 cm, right 2.6 cm, top 2.6 cm, bottom 2.4 cm.
- Cover title and Heading 1: 22 pt; Heading 2: 14 pt; Heading 3/4/body: 12 pt.
- Chinese fonts: title/Heading 1 黑体, Heading 2/3 仿宋, Heading 4/body 宋体.
- Latin letters and numbers: Times New Roman.
- Body: justified, two-character first-line indent, fixed 22 pt line spacing.
- Captions and data-source notes: 10.5 pt.
- Tables: 15.6 cm total width, explicit DXA geometry, repeating header, and vertically centered cells. Use deterministic three-line borders: black `#000000` top/bottom rules at 1.5 pt and a dark-blue `#1B365D` header-bottom rule at 1 pt; header cells use `#D9E2EC` shading with dark-blue text, while body cells stay white.

Do not introduce parchment backgrounds, decorative display fonts, rounded cards, shadows, multi-color surfaces, or an HTML/PDF-first workflow into the Word template.

## Typography

| Role | Chinese / Latin font | Size | Alignment and spacing |
|---|---|---:|---|
| Cover title | 黑体 / Times New Roman | 22 pt | centered, bold |
| Heading 1 | 黑体 / Times New Roman | 22 pt | centered, bold, 18 pt before, 12 pt after, fixed 30 pt |
| Heading 1 geometry | — | — | explicit 0 pt left indent, 0 pt right indent, and 0 pt first-line indent at style and paragraph level |
| Heading 2 | 仿宋 / Times New Roman | 14 pt | left, bold, 6 pt before/after, fixed 24 pt |
| Heading 3 | 仿宋 / Times New Roman | 12 pt | left, bold, 6 pt before/after, fixed 24 pt |
| Heading 4 | 宋体 / Times New Roman | 12 pt | use `（1）（2）（3）`, first-line indent 2 Chinese characters, fixed 24 pt |
| Body | 宋体 / Times New Roman | 12 pt | justified, first-line indent 2 Chinese characters, 0 pt before/after, fixed 22 pt |
| Figure/table caption | 宋体 / Times New Roman | 10.5 pt | not bold; table title above, figure title below |
| Table body | 宋体 / Times New Roman | 9 pt（小五） | all text centered horizontally and vertically; no first-line indent; 0 pt before/after; single spacing |

Written narrative is black. Color is reserved for charts, evidence encoding, dividers, and restrained table emphasis.

## Tables, Figures, and Sources

- Use three-line tables by default: top border, header-bottom border, and table-bottom border; no vertical grid.
- Use a very light ink-blue header fill only as restrained securities-report emphasis; keep body cells white.
- Allocate column width according to content type instead of equal-width defaults.
- Use explicit DXA table geometry and cell widths.
- Repeat header rows when tables span pages.
- Number tables and figures by chapter, such as `表3-2` and `图5-1`.
- Mention every table and figure in body text.
- Put table titles above tables and figure captions below figures.
- Center every table title and apply Word `keepNext` and `keepLines` (`keep_with_next` and `keep_together`) so it stays on the same page as the following table. Treat an orphan table title at a page bottom as a blocking pagination defect.
- Put a note beginning with `数据来源：` below every material figure/table, followed by update date, value class, geography, and caveat where applicable. Do not use `资料来源：` or `数来源：`.
- Market-insight evidence/strategy figures must come from `embedded-market-figure-v1`; modeling figures must come from `embedded-modeling-figure-v1`. Each figure has one owner only, with traceable source data, a matching `embedded-figure-production-v1` manifest, and passed mechanical plus visual checks.
- Every final chart must apply `references/kami-broker-chart-theme.md` through `scripts/kami_broker_chart_theme.py` and record `theme_id: kami-broker-v1`.
- Insert every chart inline in a dedicated `Figure Image` paragraph; center the paragraph, prohibit floating anchors, and limit displayed width to 15.6 cm.
- Center every `Figure Caption` below its chart.

## Fused Chapter Architecture

1. 执行摘要与决策问题
2. 调研边界、方法、证据分级与地区适配
3. 宏观电力环境、政策、电价、市场准入与标准
4. 市场规模、细分、产业链与增长情景
5. 用户类型、负荷/出行/停电场景与需求
6. 产品系统架构、工程参数、安全与区域合规
7. 竞争格局、玩家分类与精确型号对标
8. 定价、渠道、安装、售后与服务网络
9. 原始评论、用户痛点、购买驱动与未满足需求
10. 经济性、数学模型、场景与敏感性/稳健性
11. V2G/V2H、VPP、试点项目与利益分配
12. 产品定义、目标客户、价格带与市场进入策略
13. 风险、路线图、试点计划、责任人与下一步行动
14. 来源、假设、证据问题与附录

Load only the chapters required by the approved outline, but preserve numbering and source rules.

## Embedded Word Routing

1. Use `scripts/build_template_report.py` and the authoritative fused template for creation.
2. Use `scripts/polish_word_ib_style.py` for deterministic editorial/style cleanup.
3. Use `scripts/verify_word_ib_style.py`, `scripts/validate_word_delivery.py`, and `scripts/scan_office_placeholders.py` for structural QA.
4. Use `scripts/libreoffice_render.py` with PyMuPDF for bounded rendering and inspect every page.
5. Use `scripts/register_word_delivery.py` to record the final hash, embedded component chain, figure manifests, and inspected page count.
6. Load the bundled `market-insight-five-views.md` and `market-insight-report-contract.md` for market-research narrative, or use the modeling chain for modeling narrative.

## Required Production Flow

1. Copy the authoritative fused template to a task-local working DOCX.
2. Record the template path and SHA-256 in the project manifest.
3. Fill content into real template styles and components.
4. Run Word style, section, heading, table-geometry, image, field, and placeholder checks.
5. Render the final DOCX to page PNGs with `scripts/libreoffice_render.py` per `references/libreoffice-rendering.md`; inspect every page, including table-title/table adjacency.
6. If a formal PDF is requested, export it directly from the final DOCX through Word or LibreOffice. Do not create the formal PDF through Pandoc/HTML.
7. Compare DOCX and PDF text, table/figure counts, key numbers, and page sequence before delivery.
8. Register the inspected final artifact with `scripts/register_word_delivery.py`; never hand-edit a production manifest to claim a pass.

If LibreOffice/Word rendering is unavailable after the bounded isolated-profile converter is attempted, return the DOCX with structural QA and explicitly state that visual QA is unconfirmed. Do not manufacture a substitute PDF and call it equivalent.

## Fidelity Gates

- The final DOCX must descend from the fused template, verified by manifest/template hash or an equivalent lineage record.
- `Normal`, Heading 1-4, captions, and table text must match this contract.
- Every table paragraph must be centered, 9 pt（小五）, single-spaced, with zero first-line indent; every table cell must be vertically centered.
- Every table title must be centered and carry effective `keepNext` and `keepLines`; no table title may be stranded without its table on the same page.
- Every source note must use the exact label `数据来源：`.
- Every Heading 1 paragraph, Figure Image paragraph, and Figure Caption paragraph must be centered where applicable.
- Every final chart must use `kami-broker-v1` and retain its SVG, 300 dpi PNG, source-data path, and theme manifest.
- No unresolved placeholder or template instruction may remain.
- No formal report may be built from blank `Document()`.
- Every page must pass visual review before delivery when rendering is available.
- A requested PDF must be a direct export of the final DOCX and pass cross-format consistency checks.
