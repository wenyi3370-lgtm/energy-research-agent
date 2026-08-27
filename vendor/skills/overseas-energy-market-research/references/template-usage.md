# Office Template Usage

## Adapted Templates

- Word: `assets/templates/word/energy_market_research_report_template.docx`
- Excel: `assets/templates/excel/energy_market_research_workbook_template.xlsx`
- PPT: `assets/templates/ppt/energy_market_research_presentation_template.pptx`

These templates are geography-neutral shells. Replace region, category, date, language, currency, source scope, and project name. Never treat example data as evidence.

## Usage

- Excel: use the template as a shell, then apply the embedded `sync_csv_to_excel.py --theme default|jade` pipeline. Keep `99_来源与口径` last. Do not expose internal evidence-issue files as a workbook sheet.
- Word: use the template for report packaging, the embedded Five Views branch or modeling chain for content, and `embedded-word-production-v1` for the exact typography and QA in `format-and-visual-style.md`.
- PPT: use the embedded `templates/` deck/layout/chart/icon libraries through the handwritten-SVG route. The current main agent follows `design_spec.md` and re-reads `spec_lock.md` before every page, then exports editable DrawingML with `high_fidelity_presentation.py`; no external presentation Skill is required. `build_executive_presentation.py` is fallback-only.
- Keep sources, update date, value-class labels, and caveat notes visible.
- Automated builders produce drafts. Final files require specialist-skill formatting and render QA.

## Reference Originals

Files in `assets/templates/reference_originals/` are provenance/style references only. Do not use them as factual sources or direct deliverables unless the user explicitly asks.

## Verification

- Open and structurally inspect Word/Excel/PPT.
- Render Word and PPT and inspect every page/slide.
- Audit Excel formulas, error cells, sheet order, and source hyperlinks.
