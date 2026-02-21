@echo off
chcp 65001 >nul
title DataForge Backend

echo ============================================================
echo   DataForge AI - Backend
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

:: Activate venv or use system python
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
    echo [*] Using uv venv
) else (
    set PYTHON=python
    echo [*] Using system python
)

echo [*] Starting on http://localhost:4433/docs
echo.

%PYTHON% -m uvicorn backend.main:app --host 127.0.0.1 --port 4433 --reload
