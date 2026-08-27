#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
  AGENT_PYTHON=".venv/bin/python"
else
  AGENT_PYTHON="python3"
fi

echo "Starting Energy Research Agent at http://localhost:8000"
exec "$AGENT_PYTHON" -m uvicorn energy_research_agent.automation.api.app:create_app \
  --factory --host 0.0.0.0 --port 8000
