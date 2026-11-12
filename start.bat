@echo off
title AI Workflow Designer Launcher
echo ===================================================
echo       Launching AI Workflow Designer Full Stack     
echo ===================================================
echo.

REM 1. Start FastAPI Backend on port 8000
echo [1/2] Starting Backend (FastAPI on http://localhost:8000)...
start "AI Workflow Designer - Backend (Port 8000)" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --reload --port 8000"

REM 2. Start Next.js Frontend on port 3000
echo [2/2] Starting Frontend (Next.js on http://localhost:3000)...
start "AI Workflow Designer - Frontend (Port 3000)" cmd /k "cd /d %~dp0frontend && cmd /c \"set NODE_OPTIONS=--max-old-space-size=2048 && npx next dev --port 3000\""

echo.
echo Both servers started!
echo Waiting 3 seconds to launch browser...
timeout /t 3 /nobreak >nul

REM 3. Open Browser
start http://localhost:3000
echo Browser opened at http://localhost:3000
