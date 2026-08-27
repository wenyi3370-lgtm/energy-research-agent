# ADR-0005: 自动化持久化 SQLite 起步、PostgreSQL 可移植

- 状态：Accepted
- 日期：2026-08-19

## 背景
dev/测试需要零依赖起步；生产（docker-compose）用 PostgreSQL。审计 §5 要求
自动化表与 evidence 库分离。

## 决策
自动化表（research_tasks/runs/workflow_events/human_reviews/run_metrics/
user_feedback）用 SQLAlchemy 可移植类型（String/Integer/Float/Boolean/
DateTime/JSON），同一套模型跑 `sqlite://` 与
`postgresql+psycopg://`（`ERA_AUTOMATION_DATABASE_URL` 切换）。时区差异
（SQLite naive vs PG aware）在 repository 层 `_as_utc` 归一化。evidence 仍为
workdir 内 append-only SQLite，两者互不触碰。

## 后果
- 测试用临时文件 SQLite（TestClient + 后台任务需文件库而非 :memory:）。
- 生产迁移到 PG 不改代码；`docker-compose.yml` 已注入 PG URL。
