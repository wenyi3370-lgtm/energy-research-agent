# Eval（Phase 12）

`evals/evals.json` 现含 **10 条**用例：原 3 条人工驱动 golden 用例（id 1-3，杉杉等）
+ 7 条结构化自动化用例（id 4-10，带 `task` 字段，覆盖 market_entry / policy_regulation /
company_profile / competitor_analysis / channel_research / product_research / market_monitor）。

## 运行器

`scripts/run_automation_eval.py`：

- 对每个带 `task` 的用例：离线 pipeline（SyntheticKernelExecutor，无网络）submit → execute；
- 断言 run == PUBLISHED 且所有 `expectations` 子串出现在结果 JSON（如 "PASS"、"excel"、"word"）；
- 输出逐条 PASS/FAIL，exit code 非零即失败 → 可进 CI。

```
PYTHONPATH="src" ./.venv/Scripts/python.exe scripts/run_automation_eval.py
```

这是**工作流机制回归**，不是 golden LLM 评测：原 3 条自由文本用例（id 1-3）由人工驱动，
运行器自动跳过。新增用例：追加 `task` + `expectations` 到 evals.json 即可。
