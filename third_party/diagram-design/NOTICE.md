# Third-Party Notices

## diagram-design

- **Skill**: [diagram-design](https://github.com/cathrynlavery/diagram-design) by Cathryn Lavery
- **Version**: vendored snapshot, installed 2026-08-21
- **License**: MIT — see `third_party/diagram-design/LICENSE` (full text preserved verbatim).
- **Usage**: The `enterprise-energy-research` skill adapts the diagram-design
  editorial design system (visual tokens, 4px grid, connector rules,
  accessibility contract, export conventions) as its consulting
  visualization engine.  Diagrams are generated deterministically in Python
  (`artifacts/diagram_design_adapter.py`) following the skill's style guide
  and export procedures, with an enterprise consulting profile applied
  (pure white paper, near-black ink, deep navy `#1B365D` accent, CJK font
  stack).  The skill itself is vendored under `vendor/skills/diagram-design/`
  for reference and licensing fidelity.
- **Modifications**: The enterprise profile changes only color/font tokens;
  no diagram-design code is modified.  The vendored copy is a verbatim
  snapshot of the upstream skill at install time.
- **Third-party components inside diagram-design**: see
  `vendor/skills/diagram-design/THIRD_PARTY_LICENSES.md`.

## Lieflat Charts (removed)

- The previous visualization stack (`lieflat-charts`, PolyForm
  Noncommercial licensed) has been **removed from the runtime** in this
  release and is no longer vendored.  Any historical migration notes live
  in `docs/archive/` only and do not participate in the runtime.
