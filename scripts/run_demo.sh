#!/usr/bin/env bash
# run_demo.sh — one-command launcher for the Test Data Mining Agent demo (macOS/Linux).
#   bash scripts/run_demo.sh
# Starts the FastAPI backend (:8000) and the Vite frontend (:5173); Ctrl+C stops both.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

py="$repo/.venv/bin/python"
[ -x "$py" ] || py="python"

echo "Starting backend  -> http://localhost:8000 (docs at /docs)"
( cd "$repo" && "$py" -m uvicorn backend.app:app --port 8000 ) &
backend_pid=$!

echo "Starting frontend -> http://localhost:5173"
( cd "$repo/frontend" && npm run dev ) &
frontend_pid=$!

trap 'kill $backend_pid $frontend_pid 2>/dev/null || true' INT TERM
echo "Open http://localhost:5173 — upload data/sample_upload/test_cases/ (+ results/). Seed with scripts/generate_fixtures.py."
wait
