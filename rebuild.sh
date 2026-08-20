#!/usr/bin/env bash
# 重建研究服务的安全入口：先只读检查运行中任务，再重建。
# 用法：./rebuild.sh [--force]   （--force 仅供已确认可中断任务时使用）
set -e
cd "$(dirname "$0")"

if [ "$1" != "--force" ]; then
  echo "[检查] 运行中任务…"
  if ! RUNNING=$(docker compose exec -T postgres \
      psql -U research -d research -Atc \
      "SELECT count(*) FROM research_runs WHERE status='RESEARCHING'" 2>/dev/null); then
    echo "❌ 无法读取数据库中的运行状态；为避免误杀任务，已取消重建。"
    echo "   排查后重试；如已人工确认可中断任务，才使用：./rebuild.sh --force"
    exit 1
  fi
  RUNNING=$(printf '%s' "$RUNNING" | tr -d '[:space:]')
  if [ -z "$RUNNING" ]; then
    echo "❌ 数据库未返回运行状态；已取消重建。"
    exit 1
  elif [ "$RUNNING" != "0" ]; then
    echo "⚠️  发现 $RUNNING 个正在执行的任务；已取消重建，避免把任务变成悬挂状态。"
    docker compose exec -T postgres psql -U research -d research -Atc \
      "SELECT run_id || ' | ' || task_id || ' | ' || coalesce(started_at::text, '-') FROM research_runs WHERE status='RESEARCHING' ORDER BY started_at"
    echo "   请等待完成，或从本地网页停止任务后再重建。"
    echo "   如已确认要中断：./rebuild.sh --force"
    exit 1
  else
    echo "✅ 无正在执行的研究任务"
  fi
fi
echo "[重建] docker compose up -d --build research-api"
docker compose up -d --build research-api
echo "✅ 重建完成"
