# ROI 核算（Phase 11）

`automation/roi.py`，数据全部来自落库行：

- `user_feedback`：`manual_baseline_minutes`（人工基线工时）、`human_review_minutes`、
  `human_edit_count`、`adoption_status`（ADOPTED / PARTIALLY_ADOPTED / REJECTED）
- `research_runs.duration_seconds`：机器墙钟时长（**单独记录，不与人工时间混算**）

## 口径

- `human_minutes = human_review_minutes`（机器运行不占人工）
- `minutes_saved = manual_baseline_minutes - human_minutes`
- `roi_ratio = minutes_saved / human_minutes`（1.0 为回本）
- 汇总（`GET /api/v1/roi/summary`）：`aggregate()` 只统计有 feedback 的 run，
  不外推、不补零。

## 上报链路

n8n 工作流在 PUBLISHED 后调用 `POST /api/v1/research/{run_id}/feedback`
（见 `automation/n8n/README.md`）；提交方必须提供人工基线工时，否则该 run 不计入 ROI。
