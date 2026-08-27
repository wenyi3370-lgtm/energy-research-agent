# Embedded Market Insight Report Contract

Use this contract for the Stage 6 qualitative branch.

## Required Artifact

Path: `intermediate/market-insight/market_insight_report.md`

Frontmatter must contain:

- `method_id: embedded-market-insight-five-views-v1`
- `analysis_branch: market-insight`
- `status: final` before final delivery
- `outline_version` matching `project_manifest.json`

## Required Sections

1. 决策问题与证据边界
2. 看宏观
3. 看行业
4. 看客户
5. 看竞争
6. 看自己
7. 跨视角综合与反证
8. So What
9. 优先行动建议
10. 风险与不确定性

Every included View must end with `对本企业/产品的启示`. A view may be marked out of scope only with a reason approved by the outline.

## Evidence Rules

- Use `【证据：ID1, ID2】` anchors for material claims.
- Every cited ID must exist in a project CSV.
- Final reports require at least five valid evidence anchors and no unresolved template placeholders.
- Link recommendations to evidence IDs, owner, timing, KPI, and dependencies.
- Keep observed facts, calculations, interpretations, recommendations, and counter-evidence distinguishable.

## Gate

Run:

```text
python scripts/validate_market_insight.py --project-dir <project> --mode final
```

The Stage 6, 7, and 8 validators call this gate automatically when `analysis_branch=market-insight`.
