@echo off
rem ============================================================
rem  企业研究助手 - 一键启动（双击运行，或放入"启动"文件夹实现开机自启）
rem  用途：重启电脑后，启动 Docker 并拉起全部服务（8000 研究助手 / n8n 定时任务 / 数据库）
rem ============================================================
setlocal

rem 1. 如果 Docker Desktop 没在运行，先启动它
tasklist /fi "imagename eq Docker Desktop.exe" 2>nul | find /i "Docker Desktop.exe" >nul
if errorlevel 1 (
  echo [1/3] 正在启动 Docker Desktop...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
) else (
  echo [1/3] Docker Desktop 已在运行
)

rem 2. 等待 Docker 引擎就绪（最多 120 秒）
echo [2/3] 等待 Docker 引擎就绪...
set /a tries=0
:wait
docker info >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% geq 24 (
  echo 错误：Docker 引擎 2 分钟内未就绪，请手动打开 Docker Desktop 后重试
  pause
  exit /b 1
)
timeout /t 5 /nobreak >nul
goto wait
:ready
echo      Docker 引擎已就绪

rem 3. 拉起全部服务（restart 策略已配置，此处确保首次/异常后启动）
echo [3/3] 正在启动研究服务...
cd /d "%~dp0"
docker compose up -d
echo.
echo ============================================================
echo   ✅ 全部服务已启动
echo   研究助手（操作入口）：http://localhost:8000
echo   n8n 定时任务：每天 10:00 情报 / 每小时监测（后台自动运行）
echo   飞书群：10:00 自动接收 V2G & 储能日报
echo ============================================================
timeout /t 5 >nul
