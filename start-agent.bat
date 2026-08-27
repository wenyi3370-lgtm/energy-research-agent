@echo off
REM Energy Research Agent — local startup (Windows).
REM Fixes the known local issue: the Windows registry proxy is unusable for
REM Python clients, so the working local proxy must be set explicitly.
REM Edit AGENT_PROXY if your proxy port differs; set it empty to go direct.
setlocal
cd /d "%~dp0"

set AGENT_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=%AGENT_PROXY%
set HTTP_PROXY=%AGENT_PROXY%
set NO_PROXY=127.0.0.1,localhost
set PYTHONIOENCODING=utf-8

echo Starting Energy Research Agent API on http://localhost:8000
echo   - Agent portal:  http://localhost:8000/agent
echo   - Classic portal: http://localhost:8000/
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python.exe -m uvicorn enterprise_energy_research.automation.api.app:create_app --factory --host 0.0.0.0 --port 8000
endlocal
