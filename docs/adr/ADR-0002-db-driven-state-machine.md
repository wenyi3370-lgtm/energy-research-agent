# ADR-0002: 状态转移以数据库为唯一事实源

- 状态：Accepted
- 日期：2026-08-19

## 背景
内存状态机（`TaskStateMachine`）无法支撑多 worker / 重启恢复；审计 §8.1 指出
原控制平面"无合法转移约束、无持久化"。

## 决策
所有状态写入走 `TaskRepository.update_run_status`：先查行、`assert_transition` 校验
合法转移表（`automation/state_machine.py`）、写 `research_runs.status` 并同步
`research_tasks.status`，且每次转移落一条 `workflow_events`（STATUS_TRANSITION +
reason）作为持久审计轨迹。重试计数同样取自该轨迹（ADR-0006 相关）。

## 后果
- 任何绕过状态机的裸写都会被唯一约束/转移校验拒绝；状态永不"卡在中间态"。
- 审计轨迹可回答"谁在何时把 run 从 A 移到 B，为什么"。
