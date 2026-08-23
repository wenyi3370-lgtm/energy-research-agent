# Artifact specification

## 1. Publication contract

Publishers receive only a validated `freeze_id` and their bindings from `artifact_manifest.json`. They must not search, call research models, alter claim values or introduce unbound images. Any factual correction requires a new evidence version, validation and freeze.

## 2. Output tree

```text
outputs/{canonical_company}/{run_id}/
├─ 00_run_manifest.json
├─ 01_evidence/
│  ├─ facts.json
│  ├─ sources.jsonl
│  ├─ images.jsonl
│  ├─ enterprise_graph.json
│  ├─ products.json
│  ├─ energy_profile.json
│  ├─ solutions.json
│  └─ artifact_manifest.json
├─ 02_research_quality/
│  ├─ research_quality.json
│  └─ saturation_report.json
├─ 03_visual_assets/
│  ├─ visual_manifest.json
│  ├─ figures/{visual_id}.html
│  ├─ figures/{visual_id}.svg
│  ├─ figures/{visual_id}.png
│  ├─ image_discovery_manifest.json
│  ├─ image_evidence_manifest.json
│  └─ image_publication_manifest.json
├─ 04_word/enterprise_research.docx
├─ 05_excel/enterprise_research.xlsx
├─ 06_html/enterprise_research_dashboard.html
├─ 06_html/enterprise_research_dashboard_assets/  # audit manifests; HTML remains single-file
├─ 07_validation/validation_report.json
├─ 07_validation/html_visual_validation.json
├─ 07_validation/artifact_consistency_report.json
├─ 08_ppt/enterprise_research.pptx                # when requested
└─ checksums.sha256
```

Use filesystem-safe canonical company names while retaining the exact canonical name inside manifests.

## 3. Excel workbook

Generate through `ExcelMasterAdapter`. Required sheets:

1. `01_企业基本信息`
2. `02_集团及子公司`
3. `03_生产基地`
4. `04_产品矩阵`
5. `05_产品参数`
6. `06_经营数据`
7. `07_工艺与用能`
8. `08_EPC机会`
9. `09_零碳节能`
10. `10_储能ODM`
11. `11_出海合作`
12. `12_原始事实`
13. `13_来源URL`
14. `14_图片来源`
15. `15_冲突数据`
16. `16_数据缺口`
17. `17_图表数据`

Requirements:

- Freeze panes, filters, explicit units and as-of dates.
- Include IDs in data tables; source and image ledgers are never hidden.
- Preserve URLs as clickable links and plain text.
- Keep numbers numeric; do not embed units into numeric cells.
- Use a legend for verification and statement types.
- Ensure source rows correspond one-to-one with Word Appendix B.

## 4. Word report

Use the supplied 普什 report as the structural/visual baseline. Do not redesign it as an unrelated style.

Required structure:

- cover;
- important notice;
- real automatic TOC;
- executive summary;
- 1 调研概述;
- 2 集团/企业概况;
- 3 重点产业与优势产品;
- 4 子公司/工厂逐一分析;
- 5 能源消费与节能潜力;
- 6 新能源 EPC;
- 7 零碳与节能改造;
- 8 储能 ODM;
- 9 出海合作;
- 10 合作模式与商务路径;
- 11 项目优先级与 90 天计划;
- 12 风险与边界;
- 13 调研结论;
- Appendix A terms, B sources, C images, D gaps.

Rules:

- Apply [docs/archive/office-visual-production.md](docs/archive/office-visual-production.md), [references/fifth-round-quality-contract.md](references/fifth-round-quality-contract.md), and `config/office_visual_policy.yaml`; the fifth-round contract supersedes archived length-first rules.
- Use A4 with approximately 2.54 cm margins. Body is 12 pt SimSun plus Times New Roman, exactly 22 pt line spacing, two-character first-line indent and justified alignment. Heading 1/2/3 are 22/14/12 pt with controlled spacing and keep-with-next behavior.
- Use formal three-line tables: 1.5 pt black top/bottom rules, 1 pt navy header rule, pale-blue header fill, no vertical/internal grid. Center the table on the page; center every cell horizontally and vertically; explicitly set every cell paragraph's first-line, left and right indents to zero. `Table Grid` is prohibited in formal output.
- Formal depth follows research density rather than a character/page quota. Target a 50% facts/data, 35% analysis/insight and 15% constraints/limitations mix.
- Core chapters prioritize concise evidence-backed analysis. Missing data triggers a targeted retry or an explicit limitation; it never triggers prose padding.
- Every core chapter contains at least one decision-useful figure/table when real data supports it. If numeric evidence is unavailable, retain prose/table treatment rather than inventing a framework diagram.
- Use only VisualSpec figures whose evidence data satisfies the Visual Router's data-sufficiency checks for the routed diagram-design type. The router's anti-abuse rules decide: real time series → line, real categories → bar, real x/y metrics → quadrant/scatter, real flows → Sankey, verified relationships → tree. Insufficient data degrades to table/KPI/prose — never to an implied chart, and never to process/relationship/hierarchy/decision-tree decorations.
- Follow the fixed sequence analysis paragraph → “见图/表 N-x” → visual → caption → `数据来源：`. Every visual must exist as offline standalone HTML, 300 DPI PNG and editable SVG; chart text is at least 8 pt and a chart may not carry its own competing page title.
- Build `image_publication_manifest.json` separately from the chart manifest. Revalidate every selected real image against its archived SHA-256, MIME and dimensions, normalize it to an offline PNG, and insert it in the mapped cover/entity/product/factory/process/certificate chapter. Images never substitute for a qualifying data chart and never trigger a fabricated chart. Every non-cover image has a `图 N-Px` caption and exact original-page source note.
- Use Heading 1-2 entries in the Word TOC field; never hand-write TOC pages. Each entry is an independent left-aligned paragraph with a page number.
- For `GROUP_LARGE`, list every publicly identified member and expand material entities; do not claim completeness without proof.
- For `SMALL_SIMPLE`, shorten the entity-depth section automatically.
- Give every figure a number, title, source ID and image ID.
- Repeat table headers across pages and prevent unreadable row splits where practical.
- Place page numbers in the footer; use consistent headers after front matter.
- Clearly label observed facts, analytical inference and on-site diligence requirements.
- Refresh fields with LibreOffice/Word and visually inspect cover, TOC, dense tables, images and final appendices.
- Treat an orphan table title, duplicate caption, empty placeholder, duplicate template chapter or unreferenced visual as a blocking layout defect.

## 5. Enterprise HTML dashboard

Generate through `FrontendDesignAdapter` as one directly openable HTML file. Bind all data from the freeze.

Every chapter uses the fixed Dashboard grammar: one core judgement, 3–6
evidence-backed KPIs, 1–3 meaningful visuals, three concise insights and a
collapsed detail panel. The hero has at most six KPIs. Full source and product
ledgers remain collapsed. For large enterprises, require at least eight
meaningful visuals; for multi-base enterprises, require a geographic map.

### Company-style header

Use the SEVC reference as the primary header grammar:

- sticky 72 px translucent brand bar;
- verified logo plus two-line report/organization lockup;
- desktop section navigation and responsive accessible menu;
- large verified official hero image with controlled dark gradient;
- short eyebrow, decisive headline and concise subtitle;
- KPI cards crossing the hero/content boundary.

Use official brand colors when verified; otherwise use the fallback tokens in `references/reference-findings.md`. Combine this branded header with the deep-navy/cyan industrial analysis surfaces of the 普什 dashboard. Avoid generic white/purple-gradient AI styling.

Interaction/accessibility:

- responsive at 360/768/1440 px;
- keyboard navigation, visible focus, semantic landmarks and reduced-motion support;
- subsidiary/factory filters only when applicable;
- chart summaries and non-color status labels;
- sources available without requiring network access;
- print stylesheet and an honest empty state.

## 6. Product HTML dashboard

Create only if `ProductDetection.dashboard_decision == GENERATE`.

Required:

- verified real product images archived locally and embedded offline for every displayed product;
- category filter, keyword search and sorting;
- details and image zoom;
- selectable comparison for 2-4 products;
- parameter matrix and per-value source IDs;
- evidence state and source index;
- `null` displayed as `—`.

Do not generate an empty or speculative product page. Do not normalize incompatible parameter definitions into a false comparison; show scope/unit qualifiers.

The product dashboard is a network-independent release artifact. Its cards, detail dialog and comparison table must render the archived image bytes embedded in the HTML. `source_url` may be shown as provenance, but remote loading, remote-only images, placeholders and partial displayed-product image coverage are prohibited. If any qualifying product lacks a valid archived binary, block publication rather than silently omitting the image.

## 7. PPT deck

Generate through `PPTMasterAdapter`. Strictly 15-20 slides; target 17:

1. Cover
2. Executive summary
3. Enterprise profile
4. Ownership and organization
5. Industry layout
6. Product matrix
7. Subsidiaries/factories
8. Multi-factory comparison
9. Process and energy
10. Efficiency opportunities
11. EPC
12. Zero carbon
13. Storage ODM
14. Overseas cooperation
15. Business model
16. 90-day plan
17. Conclusion

Large-group completeness belongs in matrices/charts; expand only priority entities. Reuse verified Word/evidence images without excessive repetition. Put source IDs in slide footers or speaker notes. A missing non-applicable product section may be replaced with an industry/capability slide without changing the 15-20 limit.

Formal PPT requirements:

- Use the embedded serial SVG route with `design_spec.md`, `spec_lock.md`, storyline and evidence map; quick native generation is a draft fallback only.
- Before drawing, produce one slide contract per page containing action title, question, 2-4 evidence themes, visual ID, SO WHAT, layout family, claim/image IDs and source/date/bias footer.
- Use answer-first titles on every substantive slide and a decision-useful visual on every slide. Reuse approved Word charts first, then verified product/factory images, then frozen-evidence SVG frameworks.
- Preserve each slide's required chart/framework when adding real images. Supply selected images through `image_placements` with local path, role, caption, source note, `contain` fitting and no-semantic-crop policy; all contracted image IDs must appear in the final PPTX.
- Use at least four layout families and do not repeat one family on three consecutive slides.
- Use a 1280×720 geometry budget. Keep title baseline near y=120 and footer near y=678; data-dense pages may use 290/520/290 px evidence/chart/implication columns plus a SO WHAT band.
- Body slides are white/black consulting canvases with restrained SEVC purple, cobalt and cool gray; the cover may use the deep navy-purple company identity.
- Put source, update date and bias/assumption context on every substantive slide.
- Run token-aware wrapping before SVG finalization. KPI value/unit, Latin words, numeric strings, page numbers and badges must remain unbroken; chart labels must be at least 8 pt.
- Convert the final deck to PDF and block any text/shape overlap or boundary escape greater than 3 pt.
- Render every slide, create a contact sheet, inspect all slides, fix at least one visual defect and rerender the complete deck before registration.
- Zero unresolved overflow, clipping, low contrast, placeholder text, wrapped page numbers/badges or unsupported visual claims.

## 8. Artifact manifest and charts

Before publishing, bind each section/slide/sheet/widget to claim, source, image and chart IDs. `visual_manifest.json` is mandatory and a visual record includes title, analytical purpose, family, canonical type, data/analysis/schematic class, source claim/source/image IDs, transformation, units, display rounding and Word/HTML/PPT targets. Publishers may format/round only according to this record. Word, unified HTML and PPT must reference the same visual ID when they present the same analysis.

## 9. Packaging rules

- Include validation reports and checksums.
- Omit the product HTML when skipped and record the reason in manifests.
- For `BLOCKED`, retain evidence and diagnostics but do not present unfinished formal artifacts as final.
- Use `PASS_WITH_WARNINGS` only for non-critical, disclosed gaps that do not make core conclusions misleading.
