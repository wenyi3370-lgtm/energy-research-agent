# 数学建模体系接入说明（Modeling Chain Adaptation）

> 本文档是建模分支的**单一事实源**：完整链、gate 表、决策工件 schema、round 机制、workspace 目录树、12/13/14 CSV 映射规则。
> 项目内落地副本：`intermediate/modeling/CLAUDE.md`（路径实例化模板）。
> 涉及的 23 个建模 skill 指令文档已**内嵌**于 `references/modeling_chain/`（零 diff 搬运、MIT，
> 见 `references/modeling_chain/README_embedded.md`），不依赖外部建模 skill 安装。
> 机械门验证：`scripts/validate_modeling_chain_gates.py`（G1/G2/G3/G6）+ `create_modeling_artifacts.py`
> 的决策门（G2.5/G4.5）与冻结新鲜度（G4）。

## 1. 适配后完整链（科学层，去掉竞赛论文层）

竞赛论文层（`paper-section-writer`、`paper-polisher`）按接入决策裁掉；`figure-table-planner` 仅保留其"规划图表"职责（其"写论文段落"职责一并裁掉）。三审计层的 `paper/` 路径引用重定向到 `results/Qx/` 与 `frozen_numbers.json`。

```
【0】全局启动
    problem-parser（输入=research_outline.md 的问题树章节，非竞赛题目文本）
    → problem-classifier → related-paper-analyzer（可显式跳过）
    → symbol-table-builder → model-assumptions-builder → planning/question_dependency.md
    [G1 机械门：planning/parse/ + planning/classification/ 存在，无 [MODELER INPUT NEEDED] 哨兵]
【1】方法池（每题 Qx）
    method-selector → methods/Qx/qx_method_candidates.md（2-4 候选 + ≤30 行 PoC + baseline）
    [G2 机械门]
    → decision-prompt-builder → methods/Qx/decisions/method-selector_modeler_decision.md
    [G2.5★ 人工门：decision_id=qx_method_choice，DECIDED + decided_by:human]
【2】编程实验（round1 必跑）
    data-auditor-cleaner（输入=01~11 CSV 证据集）
    → model-code-analyzer → python/matlab-model-code-generator
    → code-reviewer（路由）→ python-code-reviewer / matlab-code-reviewer
    → results/Qx/experiments/roundN/（含 run_summary.json）
    [G3 机械门：review 报告 ≥5 pass items + run_summary.json]
【3】实验报告
    result-report-generator → results/Qx/experiments/roundN/qx_experiment_report_roundN.md
【4】结果判定（人工）
    decision-prompt-builder →
      result-report-generator_modeler_decision.md（qx_result_verdict，含 round_decision）
      robustness-checker_modeler_decision.md（qx_stability_verdict）
      final-method-explainer_modeler_decision.md（qx_method_explanation）
    [G4.5★ 人工门：三份工件全 DECIDED + decided_by:human]
【5】锁定
    final-method-explainer → methods/Qx/qx_final_method_explanation.md
【6】最终结果分析
    result-report-generator(final) → results/Qx/reports/qx_final_result_analysis.md
【7】稳健性
    robustness-checker → robustness/Qx/qx_robustness_report.md（含 sensitivity CSV）
【8】图表
    figure-table-planner（仅规划职责）→ embedded-modeling-figure-v1（每图先 human-confirmed core claim，
    SVG 主 + 300dpi PNG 辅，plot 数据存盘）
【9】材料包与冻结
    solution-package-builder → results/Qx/reports/qx_solution_package_for_writer.md
    + results/Qx/reports/frozen_numbers.json
    + methods/Qx/decisions/solution-package-builder_modeler_decision.md（qx_package_signoff）
    [G4 机械门：qx_package_signoff DECIDED；frozen_at 新于引用 code mtime]
【10】独立审计（三者全过 = G6）
    consistency-auditor → completeness-auditor → quality-assurance-auditor
    （路径全部指向 intermediate/modeling/ 内 results/Qx/ 与 frozen_numbers.json，不指 paper/）
```

门依赖图：`G1 → G2 → G2.5★ → G3 → [实验] → G4.5★ → G4 → G6`

## 2. Gate 表

| Gate | 名称 | enter_condition | pass_criteria（机械可检查） | fail_fallback |
|---|---|---|---|---|
| G1 | PROBLEM_PARSED | research_outline.md 已批准 | `planning/parse/` + `planning/classification/` 存在；无 `[MODELER INPUT NEEDED` / `[AI-DRAFT` 哨兵 | 回 problem-parser / classifier |
| G2 | METHOD_VALIDATED | G1 过；data-auditor-cleaner 已跑 | 每 Qx 候选 2-4 个；每候选有 ≤30 行 PoC + 可行性数字；有 baseline | 回 method-selector 补 PoC |
| G2.5★ | METHOD_CHOSEN_BY_HUMAN | G2 过 | `methods/Qx/decisions/method-selector_modeler_decision.md`：status=DECIDED ∧ decided_by=human ∧ rationale 非空非复制 ai_suggestion ∧ 引 evidence_refs | `code_generation_allowed_Qx=false`；退回人工（AI 永不自置通过） |
| G3 | CODE_REVIEWED | G2.5 过；脚本已跑 | `code/Qx/reviews/qx_python_review.md`（或 matlab）≥5 pass items；`run_summary.json` 存在 | 回对应语言 reviewer |
| G4.5★ | RESULTS_JUDGED_BY_HUMAN | G3 过；roundN 报告已出 | 三份工件（qx_result_verdict / qx_stability_verdict / qx_method_explanation）全 DECIDED + decided_by:human | `freeze_allowed_Qx=false`；退回人工 |
| G4 | RESULTS_FROZEN | G4.5 过；final result analysis 存在 | `qx_package_signoff` DECIDED；`frozen_numbers.json` 存在且 frozen_at 新于引用 code mtime | 不发 frozen；漂移→解冻三步 |
| G6 | AUDIT_LAYER_PASSED | G4 过；材料包齐 | consistency + completeness + quality-assurance 三审计全 PASSED（路径指 results/Qx/） | 回失败的审计者；任一 FAIL 阻 final assembly |

★ = 人工闸门（仅 G2.5、G4.5，共 2 个）。

## 3. 决策工件 schema（Human Decision Artifact Convention）

完整 schema 见 `intermediate/modeling/CLAUDE.md`（schema of record）。要点：

```yaml
---
schema_version: 1
skill: method-selector | result-report-generator | robustness-checker |
      final-method-explainer | solution-package-builder
scope: Qx
decision_id: qx_method_choice | qx_result_verdict | qx_stability_verdict |
             qx_method_explanation | qx_package_signoff
decision_point: framing | method_choice | assumption_necessity | baseline |
                hyperparameter | result_verdict | confidence | claim_scope | figure_role
status: PENDING | DECIDED
decided_by: human            # 必须 human
decided_at: <ISO 时间戳>
ai_suggestion: <AI 唯一建议>
choice: <<<HUMAN>>>
rejected_alternatives: []
confidence:
evidence_refs:
  - methods/Q1/qx_decision_log.md
---
## Modeler's rationale
<<<HUMAN>>>
```

机械有效性检查（4 条）：DECIDED ∧ decided_by=human ∧ rationale 非空非逐字复制 ai_suggestion ∧ 引用 evidence_refs token；无哨兵残留（`[AI-DRAFT` / `[MODELER INPUT NEEDED` / `<<<HUMAN>>>`）。

**执行红线**：AI 永不自行置 G2.5/G4.5 通过；永不填充 modeler_decision/modeler_rationale 最终内容；每门先经 decision-prompt-builder 发 2-3 个 trade-off 问题。

## 4. Frozen Numbers Convention（冻结数字约定）

- 冻结文件：`results/Qx/reports/frozen_numbers.json`，含 `frozen_at`
- 冻结前置：G4.5 三份 verdict 全 DECIDED + `qx_package_signoff` DECIDED
- **解冻三步**：解冻 → 修改 → 重冻结；`frozen_at` 必须新于所有引用 `code/Qx/*` mtime
- 数字改判用 `supersedes`，禁止原地改写
- 12/13/14 CSV 唯一写入方是 `scripts/create_modeling_artifacts.py`，禁止手工编辑

## 5. round 机制裁剪

| 轮次 | 触发 | 产物 |
|---|---|---|
| round1 | 必跑（G2.5 通过后） | `results/Qx/experiments/round1/` |
| round2 | 仅当 G4.5 的 `qx_result_verdict.round_decision == iterate` | `results/Qx/experiments/round2/` |
| 回退 | round_decision == return | 回 G2.5 改方法，重跑 round1 |
| 收敛 | round_decision == proceed | 进锁定（final-method-explainer） |
| 上限 | 任何 Qx 最多 3 轮 | 超限需人工强制 proceed |

`round_decision ∈ {proceed, iterate, return}` 由人类在 qx_result_verdict 中裁决，AI 只给 `[AI-SUGGESTED]`。

## 6. Qx 子问题映射规则（research_outline → 建模子问题）

来源：`research_outline.md` 的 `## 问题树与章节大纲`（及模板 `research_outline_template.md` 对应章节）。

1. 大纲中每个**量化/建模价值分支节点**标注 `modeling: Qx`（大纲批准时固化）
2. 无建模价值、需定性综合的节点 → 归 market-insight 分支
3. Qx 依赖关系登记在 `planning/question_dependency.md`（如 Q2 经济性引用 Q1 的 TAM 输出）
4. 每个 Qx 对应四件套：`methods/Qx/`、`code/Qx/`、`results/Qx/`、`robustness/Qx/`

示例（海外户用储能 + 德国市场）：

| Qx | 大纲节点 | 问题类型 | 主方法族 |
|---|---|---|---|
| Q1 | 市场规模 TAM/SAM/SOM | 预测/评估 | 自下而上 + 交叉校验；baseline=单价×装机 |
| Q2 | 经济性 CAPEX/OPEX/NPV/IRR/回收期 | 优化/评估 | cash-flow DCF + 场景对比；baseline=无储 |
| Q3 | 价格敏感度/电价政策敏感性 | 模拟/回归 | Monte Carlo / 单变量敏感性；baseline=线性 |
| Q4 | 电池衰减与更换影响 | 机理/预测 | degradation ODE + 离散折现 |

## 7. 12/13/14 CSV 映射规则（create_modeling_artifacts.py 执行）

### 12_Model_Assumptions.csv（18 列）← `planning/model_assumptions.md`

| CSV 列 | 来源 |
|---|---|
| assumption_id | `A-Qx-nnn`（自动编号） |
| model_module | Qx |
| parameter_symbol / parameter_name | symbol_table.md 符号 + 假设名 |
| value_class | 默认 `scenario_assumption`，按来源标注 |
| low_value / base_value / high_value | 假设的 low/base/high（base 必填，low/high 缺省留空） |
| unit / geography / period | 拷贝假设 |
| rationale | 假设文本 |
| formula_or_use | symbol_table 符号用途 |
| source_ids / source_urls | 假设的 evidence 引用 |
| confidence / owner | 拷贝决策工件 |
| approval_status | G4.5 覆盖后置 `approved`，否则 `pending` |
| notes | `mapped_from: intermediate/modeling/planning/model_assumptions.md` |

### 13_Model_Results.csv（19 列）← 各 Qx `frozen_numbers.json` 展开

| CSV 列 | 来源 |
|---|---|
| result_id | `R-Qx-nnn` |
| model_module | Qx |
| scenario | json 的 scenario key |
| metric / value / unit | frozen number |
| geography / period | json 或假设 |
| value_class | `modeled_estimate` |
| formula_or_method | qx_final_method_explanation |
| excel_formula | frozen number 的可执行 Excel 公式；使用 `{{assumption:A-Qx-nnn:low|base|high}}` 标记引用 12 表假设，禁止常数公式 |
| input_assumption_ids | json 引用的假设集（**必须命中 12 的 assumption_id**，validate_model_integrity 兜底） |
| evidence_row_ids | json evidence 引用 |
| validation_check / sensitivity_or_uncertainty | qx_robustness_report |
| confidence / verification_status | 决策工件（稳健性 PASS → `verified`） |
| interpretation | qx_final_result_analysis |

### 14_Simulated_Modeling_Data.csv（25 列）← `workspace/data/simulated_modeling_data.csv`

仅用于数学建模所需、但无法取得真实观测的输入。必须由 Python 生成实际数据文件，并逐变量记录：校准来源、分布/过程、参数、物理边界、相关性/时间结构、固定随机种子、样本量、生成代码路径、生成数据路径、验证结果与敏感性。对应的 `12_Model_Assumptions.csv` 行必须为 `value_class=simulated`。禁止写入 `11_Evidence_Issues.csv`，禁止伪装为 `observed`。

生成后跑 `validate_stage_gate.py --stage 6`（model_integrity 校验 input_assumption_ids 引用、value_class 枚举）。

## 8. 断点适配（竞赛体系 → 能源市场场景）

| 断点 | 竞赛原意 | 适配 |
|---|---|---|
| problem-parser 输入 | 竞赛题目文本/PDF | research_outline.md 的问题树章节 |
| data-auditor-cleaner 数据 | 竞赛数据附件 | 01~11 CSV 证据集（带 value_class/source_ids）；`workspace/data_raw/` → `intermediate/modeling/workspace/data/` |
| 数据缺口哲学 | 缺数据即阻断 | 只有市场事实缺失可写入 `11_Evidence_Issues.csv`（`data_domain=market`）；数学建模输入缺失必须生成最真实、可复现、可校准验证的模拟数据，记录于 12/14，且 `value_class=simulated` |
| G6 审计层路径 | paper/ | results/Qx/ 与 frozen_numbers.json |
| 论文写作层 | paper-sections/LaTeX | 裁掉；结果经 12/13/14 CSV 进 Stage 7 Word 报告 |
