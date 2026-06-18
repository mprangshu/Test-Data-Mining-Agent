# run_demo.ps1 — one-command launcher for the Test Data Mining Agent demo (Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
#
# Starts the FastAPI backend (port 8000) and the Vite React frontend (port 5173) in two
# separate terminal windows so you can watch both logs. Ctrl+C in each window stops it.
#
# Prereqs (one-time): python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt
#                     cd frontend ; npm install
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "venv not found at $venvPy — run:  python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $repo "frontend\node_modules"))) {
    Write-Warning "frontend\node_modules missing — run:  cd frontend ; npm install"
}

Write-Host "Starting backend  -> http://localhost:8000  (docs at /docs)" -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -WorkingDirectory $repo `
    -ArgumentList "/k", "title TDM Backend && `"$venvPy`" -m uvicorn backend.app:app --port 8000"

Write-Host "Starting frontend -> http://localhost:5173" -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -WorkingDirectory (Join-Path $repo "frontend") `
    -ArgumentList "/k", "title TDM Frontend && npm run dev"

Write-Host ""
Write-Host "Demo launching in two windows. Open http://localhost:5173 in your browser." -ForegroundColor Green
Write-Host "Sample data: data\sample_upload\test_cases\ (+ results\). Run scripts\generate_fixtures.py to (re)seed." -ForegroundColor Green
