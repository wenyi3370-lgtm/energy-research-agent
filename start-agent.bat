@echo off
REM Energy Research Agent — local startup (Windows).
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist ".venv\Scripts\python.exe" (
  set "AGENT_PYTHON=.venv\Scripts\python.exe"
) else (
  set "AGENT_PYTHON=python"
)

echo Starting Energy Research Agent API on http://localhost:8000
echo   - Agent portal: http://localhost:8000/
echo   - API docs:     http://localhost:8000/docs
echo Press Ctrl+C to stop.
echo.
"%AGENT_PYTHON%" -m uvicorn energy_research_agent.automation.api.app:create_app --factory --host 0.0.0.0 --port 8000
endlocal
