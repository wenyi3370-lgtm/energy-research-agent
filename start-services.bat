@echo off
rem ============================================================
rem  Energy Research Agent - Docker 一键启动（Windows）
rem  用途：启动 Docker Desktop 并拉起 Agent API、PostgreSQL 与 n8n。
rem ============================================================
setlocal

rem 1. 检查 Docker CLI 与引擎。不要假设 Docker Desktop 的安装路径。
where docker >nul 2>&1
if errorlevel 1 (
  echo 错误：未找到 docker 命令。请安装并启动 Docker Desktop 后重试。
  pause
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo 错误：Docker 引擎未就绪。请启动 Docker Desktop 后重试。
  pause
  exit /b 1
)

rem 2. 拉起全部服务。
echo 正在启动 Energy Research Agent 服务...
cd /d "%~dp0"
docker compose up -d --build
echo.
echo ============================================================
echo   全部服务已启动
echo   Agent 操作入口：http://localhost:8000
echo   API 文档：http://localhost:8000/docs
echo   n8n：http://localhost:5678
echo ============================================================
timeout /t 5 >nul
