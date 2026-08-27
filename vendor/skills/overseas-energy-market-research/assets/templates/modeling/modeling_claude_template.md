# Modeling Workspace Convention (intermediate/modeling)

> 本文件是建模分支的 **schema of record**（单一事实源）。执行建模链前必须先加载本文件。
> 完整契约（gate 表、完整链、round 机制、目录树、12/13/14 映射）见 skill 的 `references/modeling-chain-adaptation.md`。

## 适用范围

建模分支（`analysis_branch = modeling`）的所有产物挂载在本 workspace：

```
intermediate/modeling/
├── CLAUDE.md                  # 本文件
├── planning/                  # progress_dashboard.md, session_config.json,
│                              # decision_log_index.md, parse/, classification/,
│                              # symbol_table.md, model_assumptions.md, question_dependency.md
├── workspace/
│   ├── problem/problem-parser/problem_parse.json
│   ├── problem/problem-classifier/problem_classification.json
│   └── papers/related_paper_analysis.md
├── methods/Qx/                # qx_method_candidates.md, qx_method_iteration_log.md,
│                              # qx_decision_log.md, qx_final_method_explanation.md,
│                              # qx_figure_table_plan.md, poc/, decisions/
├── code/                      # model-code-analyzer.md, Qx/ 脚本, Qx/reviews/
├── results/Qx/                # experiments/roundN/ (+run_summary.json), reports/
│                              # (qx_final_result_analysis.md, qx_solution_package_for_writer.md,
│                              #  frozen_numbers.json)
└── robustness/Qx/             # qx_robustness_report.md, sensitivity CSV, figures/
```

## Human Decision Artifact Convention（决策工件 schema）

每个决策工件放在 `methods/Qx/decisions/<skill>_modeler_decision.md`，结构：

```yaml
---
schema_version: 1
skill: <skill 名>                 # method-selector / result-report-generator /
                                  # robustness-checker / final-method-explainer /
                                  # solution-package-builder
scope: Qx                         # 子问题编号
decision_id: qx_method_choice | qx_result_verdict | qx_stability_verdict |
             qx_method_explanation | qx_package_signoff
decision_point: framing | method_choice | assumption_necessity | baseline |
                hyperparameter | result_verdict | confidence | claim_scope | figure_role
status: PENDING | DECIDED         # 人工确认后置 DECIDED
decided_by: human                 # 必须为 human（PENDING/ai/auto = 未通过）
decided_at: <ISO 时间戳>
ai_suggestion: <AI 唯一建议字段，明确标注非 verdict>
choice: <<<HUMAN>>>               # 人工填写（含 per-claim approve∈{keep,downgrade,drop}）
rejected_alternatives: []         # 人工填写被否方案及理由
confidence:                       # 人工填写
evidence_refs:                    # 指向真实文件路径，供人工 rationale 引用
  - methods/Q1/qx_decision_log.md
---
## Modeler's rationale
<<<HUMAN>>>
```

### 机械有效性检查（无脚本，文档化规则）

1. `status == DECIDED` 且 `decided_by == human`
2. `## Modeler's rationale` 正文非空，且**不是**逐字复制 `ai_suggestion`
3. rationale 至少引用一个 `evidence_refs` 中的路径 token
4. 无哨兵残留：`[AI-DRAFT`、`[MODELER INPUT NEEDED`、`<<<HUMAN>>>`

## Frozen Numbers Convention（冻结数字约定）

- 冻结文件：`results/Qx/reports/frozen_numbers.json`，含 `frozen_at` 字段
- 冻结前置：G4.5 的 `qx_result_verdict` / `qx_stability_verdict` / `qx_method_explanation` 三个工件全部 `DECIDED`
- **解冻三步**：解冻 → 修改 → 重冻结；`frozen_at` 必须新于所有被引用的 `code/Qx/*` 文件 mtime
- 数字改判用 `supersedes`（对应解冻-重冻结），禁止原地改写
- `numbers` 中每个结果对象必须包含 `excel_formula`。用 `{{assumption:A-Qx-nnn:low|base|high}}` 引用假设，禁止常数公式或把冻结结果值重新包进公式。例如：`"excel_formula": "={{assumption:A-Q1-001:base}}*{{assumption:A-Q1-004:base}}"`。

## Access Rules（执行红线）

1. **AI 永不自行置 G2.5 / G4.5 通过**——门通过只由人类在决策工件中置 `DECIDED`
2. **AI 永不填写** `modeler_decision` / `modeler_rationale` 的最终内容（只填 `ai_suggestion` / `options_considered` / `evidence` / `evidence_refs`）
3. 每个闸门前必须先经 `decision-prompt-builder` 抛出 2–3 个 trade-off 问题
4. `planning/session_config.json` 的 mode（learning/speed）只影响提示措辞，**不放松任何 gate**
5. 12/13/14 CSV 的唯一写入方是 `scripts/create_modeling_artifacts.py`，禁止手工编辑（防与 frozen_numbers 失联）
6. 只有市场事实缺失可进入 `11_Evidence_Issues.csv`；数学建模输入缺失必须用 Python 生成最真实可复现的模拟数据，`12` 标记 `value_class=simulated`，并在 `workspace/data/simulated_modeling_data.csv` 记录校准来源、过程/分布、参数、边界、相关性、固定种子、样本量、代码/数据路径、验证和敏感性。
