# 数学建模链内嵌文档（24 个外部建模 skill 零 diff 搬运）

> 本目录是数学建模竞赛体系 skill 链的**文档内嵌副本**：24 个 SKILL.md 原样拷贝
> （内容零删减，`cmp` 逐字节一致），许可证 MIT（各文件 YAML frontmatter 保留
> `license: MIT` 声明）。不依赖外部建模 skill 安装即可运行完整建模链。

## 内嵌清单

| 阶段 | 文档 |
|---|---|
| 全局启动 | `problem-parser.md`、`problem-classifier.md`、`related-paper-analyzer.md`（可显式跳过）、`symbol-table-builder.md`、`model-assumptions-builder.md` |
| 方法池 | `method-selector.md`、`decision-prompt-builder.md` |
| 编程实验 | `data-auditor-cleaner.md`、`model-code-analyzer.md`、`python-model-code-generator.md`、`matlab-model-code-generator.md`、`code-reviewer.md`、`python-code-reviewer.md`、`matlab-code-reviewer.md` |
| 实验报告与判定 | `result-report-generator.md`、`robustness-checker.md`、`final-method-explainer.md` |
| 图表与材料包 | `math-figure-generator.md`（附件在 `references/` 子目录：chart-patterns/color-systems/layout-guide）、`figure-table-planner.md`（仅规划职责）、`solution-package-builder.md` |
| 独立审计 | `consistency-auditor.md`、`completeness-auditor.md`、`quality-assurance-auditor.md` |
| 决策记录 | `modeler-decision-logger.md` |

按设计未内嵌：`paper-section-writer.md`、`paper-polisher.md`（竞赛论文层，adaptation 方案明确裁掉；
结果经 12/13/14 CSV 进 Stage 7 报告）。

## 版本同步（doctor）

`scripts/web_collection/cli.py doctor` 会对比本目录 24 个文档与官方源
（`~/.claude/skills/<name>/SKILL.md`）的 SHA256：`in_sync` 或列出 OUT_OF_SYNC 项
（官方更新后需重新零 diff 搬运）。官方 skill 未安装时为可选提示，不阻塞。

## 使用方式

1. **链编排与门禁**：读 `references/modeling-chain-adaptation.md`（单一事实源：G1-G6 门表、
   决策工件 schema、Qx 映射、12/13/14 CSV 规则、断点适配）。
2. **指令文档**：每个环节执行前读本目录对应 `<name>.md`（内容与外部原版一致）。
3. **机械门验证**：`scripts/validate_modeling_chain_gates.py --project-dir <项目>` 校验
   G1/G2/G3/G6 工件 + 复用 `create_modeling_artifacts.py` 的决策门 G2.5/G4.5 与冻结新鲜度 G4。
4. **12/13/14 CSV**：唯一写入方 `scripts/create_modeling_artifacts.py`（禁止手工编辑），
   `scripts/validate_model_integrity.py` 兜底校验。

## 适配断点（竞赛体系 → 能源市场场景）

- problem-parser 输入 = `research_outline.md` 的问题树章节（非竞赛题目文本）；
- data-auditor-cleaner 数据 = 01~11 CSV 证据集；
- 论文写作层（paper-section-writer / paper-polisher）裁掉，结果经 12/13/14 CSV 进 Stage 7 报告；
- 三审计层路径指向 `results/Qx/` 与 `frozen_numbers.json`；
- 数据缺口哲学：市场事实缺失 → `11_Evidence_Issues.csv`；建模输入缺失 → 可复现模拟数据（12/14，`value_class=simulated`）。

## 许可证

各文件版权归原作者，MIT License（见各文件 frontmatter）。本副本按 MIT 条款使用，
分发/修改时须保留许可声明。
