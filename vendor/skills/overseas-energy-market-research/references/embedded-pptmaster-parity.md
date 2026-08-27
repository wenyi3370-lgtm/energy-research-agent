# Embedded PPT Master parity contract

## Outcome

The formal presentation route in this Skill is `embedded-pptmaster-svg-v1`. It embeds the former PPT Master production engine and its design assets inside this single Skill, so another employee does not need to install `ppt-master`, `pptx`, or `ewo-image-generate` as separate Skills.

The formal route is the same production model as the former PPT Master:

- Strategist reads the source package and produces `design_spec.md` plus `spec_lock.md` only after the eight bundled confirmations.
- The current main agent writes every slide SVG directly and sequentially. Sub-agent page generation and script-batched SVG generation are forbidden.
- The main agent re-reads `spec_lock.md` before every page and obeys `page_rhythm`, `page_layouts`, and `page_charts`.
- The live Flask SVG editor provides preview, annotations, targeted rerender, and visual review.
- `svg_quality_checker.py` enforces XML, canvas, fonts, banned features, image, citation, template, and spec-lock rules.
- `finalize_svg.py` embeds icons/images, fixes image geometry, flattens text structures, and normalizes rounded rectangles.
- `svg_to_pptx.py` exports editable native DrawingML, speaker notes, transitions, semantic entrance animations, optional narration, and a conversion trace.
- LibreOffice and PyMuPDF render every slide for visual inspection; final registration requires at least one fix-and-full-rerender cycle.

## Formal pipeline

Use `<research-project>/presentation_project/` as the PPT Master project directory. `doctor` only checks dependencies (it does not write files); `design_spec.md` / `spec_lock.md` are written by the main agent. `init` creates `<name>_ppt169_<YYYYMMDD>/` under `--dir` — either rename it to `presentation_project` or keep it: validation/registration/cover-audit/geometry scripts **auto-detect** the presentation directory (v1.2.6) and also accept `--presentation-project <dir>`.

```text
python scripts/high_fidelity_presentation.py doctor
python scripts/high_fidelity_presentation.py init presentation_project --format ppt169 --dir <research-project>
python scripts/resolve_presentation_images.py --project-dir <research-project> ...

# After the eight confirmations:
# write design_spec.md and spec_lock.md
python scripts/high_fidelity_presentation.py preview <research-project>/presentation_project --no-browser
# current main agent writes svg_output/*.svg one page at a time

python scripts/high_fidelity_presentation.py validate <research-project>/presentation_project --format ppt169
python scripts/high_fidelity_presentation.py finalize <research-project>/presentation_project --format ppt169
python scripts/high_fidelity_presentation.py export <research-project>/presentation_project --output <final.pptx>
python scripts/high_fidelity_presentation.py qa <final.pptx> --output-dir <qa-dir>
python scripts/validate_high_fidelity_ppt_delivery.py --project-dir <research-project> --pptx <final.pptx> --qa-render-dir <qa-dir> --mode final
python scripts/register_high_fidelity_ppt_delivery.py --project-dir <research-project> --pptx <final.pptx> --qa-render-dir <qa-dir> --pages-inspected <n> --confirm-all-pages-inspected --visual-fix-cycle-count <n> --visual-inspection-notes <actual-review-notes>
```

The wrapper deliberately does not have a command that generates the slide SVGs. That omission is a quality control, not a missing feature.

## Image route

- Path A: EWO generates the cover and necessary non-data body illustrations as vector-illustration-style PNG/JPEG/WebP rasters.
- Path B: only after a normalized EWO balance, quota, connectivity, credential, permission, timeout, upstream, or global-disable failure. The cover becomes the approved light consulting typographic cover; body illustrations become handwritten SVG vectors.
- Data charts never use AI image generation. They reuse approved market/model figures and keep their source IDs.

## Embedded asset inventory

- 191 production/tool files under `scripts/` after generated cache removal. This includes 119 migrated PPT Master source files plus the energy-research Skill's own Office, research, modeling, and validation scripts.
- 11,841 template files under `templates/`: brands, charts, decks, layouts, and five icon families.
- Original strategist, executor, image, shared-standard, animation, canvas, template, and visual-review references, including the detailed image palette, rendering, and image-type prompt libraries.
- Original create-template, create-brand, animation, audio, preview, chart-verification, topic-research, resume, and visual-review workflows.

The 43 MB AI-image comparison screenshots were not embedded because they are documentation samples and are not read or executed by the production pipeline. Their omission does not remove a production capability.

## Dependency policy

`requirements.txt` is the single Python installation surface. Core Office, SVG, preview, source-conversion, image, animation/audio, and MarkItDown dependencies are installed together by `python scripts/bootstrap_runtime.py --install`. LibreOffice remains the only external desktop application required for faithful Office rendering QA.

## Fallback route

`build_executive_presentation.py` remains available for a diagnosed toolchain failure or an explicit request for a quick stable draft. It is not the default and is not quality-equivalent. Its manifest must contain `fallback_route=true` and a concrete reason; otherwise Stage 8 rejects it.
