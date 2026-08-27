# Overseas Energy Market Research Skill

A single, self-contained AI skill for **overseas energy market research**: web evidence
collection, mathematical modeling, and IB/consulting-style Word + Excel + high-fidelity PPT
deliverables — with mechanical gates on every stage.

Chinese installation guide: [README_zh.md](README_zh.md)

## What's Inside

| Capability | Status | Notes |
|---|---|---|
| Web collection (search + browser) | Embedded | Official AnySearch 3.0.1 CLI copied verbatim (`scripts/anysearch/`); Kimi WebBridge client + contract docs embedded (`scripts/_kimi_webbridge.py`, `references/kimi-webbridge-*.md`) |
| Collection integrity gates | Embedded | Attempt journal (`13_Collection_Attempt_Journal.csv`), anti-under-collection, anti-fake-completion, R1/R2/R3 saturation floors, source ledger, record registry |
| Mathematical modeling chain | Embedded | 24 skill instruction docs verbatim (`references/modeling_chain/`, MIT); G1–G6 mechanical gates (`scripts/validate_modeling_chain_gates.py`) incl. human decision gates that AI cannot self-approve |
| Word production | Embedded | Broker-style template, three-line tables, inline figures, 15k+ chars, page-level rendering QA |
| Excel production | Embedded | Consulting light theme + jade, formula preservation, recalc, print layout QA |
| Figures | Embedded | Python SVG master + 300-dpi PNG, source/hash registration, claim-first contract |
| High-fidelity PPT | Embedded | Full ppt-master pipeline: design_spec → handwritten SVG → DrawingML export, transitions/animations/narration, LibreOffice+PyMuPDF per-page QA, EWO image fallbacks |
| Stage gates 0–8 | Embedded | `scripts/validate_stage_gate.py` + `scripts/run_workflow.py` orchestration |

**No external skill installation required.** Normal runtime is fully self-contained —
the bundled AnySearch CLI is used for collection; no external AnySearch Skill installation is
required for business execution. Runtime prerequisites: Python 3.10+ with `requirements.txt`,
LibreOffice (Office rendering), an AnySearch API key (optional, anonymous works with lower
limits), the Kimi WebBridge daemon + browser extension (browser tasks), and EWO image API
(optional, for cover art).

**Test layers (FIX-01):**
- Self-contained regression tests (`scripts/regression_test_*.py`): offline, no external Skill
  required; the bundled AnySearch CLI is verified against `references/anysearch_manifest.json`.
- Official parity integration tests (`scripts/integration_test_anysearch_parity.py`): offline,
  official AnySearch Skill required as a comparison reference — SKIPs when it is not installed.
- Live smoke tests: may require network, API credentials and available quota — never mixed
  with the offline regression.

## Installation

```bash
# 1. Copy this skill into your AI agent's skills directory
cp -r overseas-energy-market-research ~/.claude/skills/

# 2. Install Python dependencies (use a Python 3.10+ interpreter)
pip install -r requirements.txt

# 3. Self-check
python scripts/verify_install.py
```

Windows users can run `scripts/install.ps1` (backup-aware copy + deps + self-check).
macOS/Linux: `scripts/install.sh`.

Then configure (see `.env.example`):
- `ANYSEARCH_API_KEY` — optional, for higher search rate limits
- `EWO_ORIGIN` / `EWO_KEY` — optional, for AI cover images
- LibreOffice — required for Word/Excel/PPT rendering QA
- Kimi WebBridge daemon + browser extension — required for browser/authenticated collection
- CJK/latin fonts — chart & PPT rendering requires 宋体 SimSun + Times New Roman
  (Windows ships both; macOS/Linux install Noto Serif SC / Liberation Serif;
  font discovery Source of Truth is `scripts/common/fonts.py`, NOT
  `kami_broker_chart_theme.py`); the PPT pipeline additionally uses Georgia
  (fallback to serif) and Microsoft YaHei
- Recommended CJK fonts on Linux: `Noto Serif CJK SC`, `Noto Serif SC`,
  `Source Han Serif SC`. The runtime font resolver (`resolve_cjk_font` in
  `scripts/common/fonts.py`) uses Matplotlib first, then Fontconfig on Linux
  (`fc-match`, TTC-aware) and finally a filesystem scan, so TTC-based SC
  fonts (e.g. `/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc`) are
  discovered even when Matplotlib's cache only exposes the JP face of the
  collection — no more "字体已安装但误报缺失". When Matplotlib still cannot
  load the SC face of a TTC, the resolver extracts the exact SC face via
  fontTools (a hard dependency of Matplotlib itself) and registers it, so
  chart rendering works with correct SC glyphs. macOS additionally resolves
  the system fonts PingFang SC / Songti SC. SC families are preferred;
  JP/KR/TC/HK regional variants are never silently substituted.
- Playwright browser — only for `scripts/visual_review.py` (visual QA server);
  run `playwright install chromium` once if you use it

## Quick Start

```bash
# Initialize a research project (frozen quantity policy snapshot + task templates)
python scripts/run_workflow.py --init --project-dir ./my-project \
  --region Thailand --category "Residential Battery Energy Storage" \
  --market-model-pair "thailand::BYD Battery-Box Premium 8.3kWh"

# Environment health check (embedded CLI hashes vs official, bridge, deps, journal)
python scripts/web_collection/cli.py doctor --project-dir ./my-project

**`--all` 语义（FIX round-3）**：`--all` 是研究计划阶段完成后的总执行入口——
前置条件（research planning + human approval + populated collection plan）不满足时返回
BLOCKED 且不进入采集；它不自动替代人工研究审批。第一次 pre-collection gate 验证
`--stages 0-4`（采集前置阶段），最终交付验证才使用 0-8。

# Real collection (anysearch search / extract, kimi browser, attempt journal auto-written)
python scripts/web_collection/cli.py search "Thailand BESS policy 2026" --task-id T1 --round 1 --round-goal coverage --project-dir ./my-project

# Validate gates after collection updates
python scripts/validate_collection_tasks.py --project-dir ./my-project
python scripts/validate_collection_attempts.py --project-dir ./my-project
python scripts/validate_source_ledger.py --project-dir ./my-project
```

## One-Command Pipeline

```bash
# Full pipeline: init(if missing) -> check(0-4) -> collect -> modeling -> build final report -> audit
python scripts/run_workflow.py --all --project-dir ./my-project \
  --region Thailand --category "Residential Battery Energy Storage" \
  --analysis-branch modeling

# Preview the exact commands without executing anything
python scripts/run_workflow.py --all --dry-run --project-dir ./my-project --region Thailand --category BESS

# Mechanical collection only (executes the task table, auto-journaling)
python scripts/run_workflow.py --collect --project-dir ./my-project

# Modeling chain scripted steps (gates + 12/13/14 artifacts once human gates pass)
python scripts/run_workflow.py --modeling --project-dir ./my-project
```

Note: human decision gates (G2.5/G4.5, `decided_by=human`) cannot be self-approved by AI —
`--modeling` reports pending gates instead of pretending they passed.

## Validation & Regression

The skill ships with offline regression tests covering every embedded pipeline:

```bash
python scripts/regression_test_anysearch_embed.py   # anysearch command surface + error normalization
python scripts/regression_test_kimi_embed.py        # kimi client contract, envelope format, auth checks
python scripts/regression_test_web_collection.py    # end-to-end collection flow + integrity gates
python scripts/regression_test_modeling_chain.py    # G1–G6 gates, human-gate anti-forgery (14 cases)
python scripts/regression_test_word_delivery.py     # Word production
python scripts/regression_test_excel_delivery.py    # Excel production
python scripts/regression_test_figure_delivery.py   # Figure production
python scripts/regression_test_ppt_delivery.py --work-dir <tmp>  # PPT production
```

All tests are offline (mock servers; no real network or browser required) and exit non-zero on
failure. Real-environment acceptance (live API calls, real browser) is documented in
`assets/config/integration_manifest.yaml`.

## License

Apache License 2.0. Embedded third-party components keep their own licenses — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
