@echo off
chcp 65001 >nul
title DataForge AI

echo ============================================================
echo   DataForge AI - 7 Agents + LangGraph
echo ============================================================
echo.

cd /d "%~dp0"
echo [*] Working dir: %cd%

:: Clean old databases
if exist "data\datamind.db" (
    echo [*] Cleaning old database...
    del /q "data\datamind.db" 2>nul
    del /q "data\dataforge.db" 2>nul
)

:: Use uv venv if available
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [*] Starting backend on http://localhost:4433/docs
start "DataForge Backend" %PYTHON% -m uvicorn backend.main:app --host 127.0.0.1 --port 4433

echo [*] Starting frontend on http://localhost:5173
cd frontend
if not exist "node_modules" call npm install
call npm run dev
