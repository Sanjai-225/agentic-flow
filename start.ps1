Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "      Launching AI Workflow Designer Full Stack    " -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

$root = $PSScriptRoot

# 1. Start FastAPI Backend in new window
Write-Host "[1/2] Starting Backend (FastAPI on http://localhost:8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --reload --port 8000"

# 2. Start Next.js Frontend in new window
Write-Host "[2/2] Starting Frontend (Next.js on http://localhost:3000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; `$env:NODE_OPTIONS='--max-old-space-size=2048'; npx next dev --port 3000"

Write-Host ""
Write-Host "Both servers launched in their own terminal windows!" -ForegroundColor Green
Write-Host "Opening browser in 3 seconds..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
Start-Process "http://localhost:3000"
