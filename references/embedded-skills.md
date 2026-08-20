# Embedded external Skill capability packs

## Contents

1. Resolution order
2. Capability map
3. Quality-preservation rules
4. Runtime boundaries
5. Supply-chain verification

## Resolution order

Use the copy under `vendor/skills/<name>/` first. Accept an explicitly injected root only for tests or a controlled upgrade. Do not prefer a mutable user-global Skill when the bundled copy is present.

## Capability map

| Capability | Embedded root | Runtime entry | Required gate |
|---|---|---|---|
| Excel Master | `vendor/skills/excel-master/` | `scripts/make_excel.py` | type/format and chart-layout delivery checks |
| PPT Master | `vendor/skills/ppt-master/` | `scripts/project_manager.py`, `scripts/svg_quality_checker.py`, `scripts/finalize_svg.py`, `scripts/svg_to_pptx.py` | Eight Confirmations, sequential SVG authoring, quality check, preview, export |
| Frontend Design | `vendor/skills/frontend-design/` | instructions consumed by `FrozenHtmlPublisher` | standalone HTML, accessibility, interaction and 360/768/1440 render checks |
| Kimi WebBridge | `vendor/skills/kimi-webbridge/` | external daemon at `127.0.0.1:10086` | status must show daemon running and extension connected |
| AnySearch | `vendor/skills/anysearch/` | `scripts/anysearch_cli.py` with JS/PowerShell/Bash alternatives | run `get_sub_domains` before vertical search; try all present bundled runtimes before outage; preserve required parameters and fail closed |
| Lieflat Charts | `vendor/skills/lieflat-charts/` | deterministic Python/SVG adapter in `artifacts/visuals.py` | catalog-only data charts; one offline HTML + editable SVG + 300 DPI PNG; no process/relationship fallback; PolyForm Noncommercial license gate |

## Quality-preservation rules

- Read each embedded `SKILL.md` completely when its capability is activated. Read the directly routed references it requires before execution.
- Keep upstream hard stops. Embedded resources do not authorize bypassing interactive confirmations, identity review, authentication, visual review, or completion contracts.
- Preserve the application adapter boundary: publishers consume only a frozen research bundle; research adapters never write presentation facts directly.
- Prefer deterministic scripts supplied by the embedded Skill to reimplementations.
- Treat licenses and attribution files as immutable vendor metadata.
- Search exclusivity is a hard boundary: only embedded AnySearch and Kimi WebBridge may access the web for this workflow. No fallback to another search Skill or provider is permitted.
- A Python-only AnySearch transport failure is not an adapter outage. The adapter must continue through Node.js, PowerShell and Bash when installed, record only redacted proxy metadata, and accept the first contract-valid response. Missing API credentials do not disable supported anonymous access.
- Downloading the exact binary URL already recorded by approved discovery is image acquisition, not a new search route. It must not introduce a third search provider.

## Runtime boundaries

Bundling makes instructions, scripts, templates, tests and portable source code self-contained. It cannot safely embed machine-specific services or private state. The following remain external runtime dependencies:

- Kimi WebBridge daemon and browser extension;
- AnySearch network endpoint and optional user-supplied API key (anonymous access remains supported at lower limits);
- a compatible Python runtime and packages declared by this project and the embedded tools;
- browser binaries used by Playwright or the user's installed browser;
- LibreOffice or Microsoft Office for final Office rendering where required;
- user-supplied API keys and authenticated browser sessions.

Never include cookies, login profiles, browser fingerprints, caches, task history, API keys, tokens, populated `.env` values, virtual environments, or Git metadata in the trusted manifest or distributable Skill. Local source trees may accumulate interpreter caches during testing; the packager must exclude them.

## Supply-chain verification

Run `python scripts/vendor_skills.py verify`. It must report `status: pass`. Regenerate the manifest only during an intentional upstream refresh with `python scripts/vendor_skills.py manifest` and then run all tests and render gates again.
