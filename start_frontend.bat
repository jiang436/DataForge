@echo off
chcp 65001 >nul
title DataForge Frontend

echo ============================================================
echo   DataForge AI - Frontend
echo ============================================================
echo.

cd /d "%~dp0frontend"
echo [*] Working dir: %cd%
echo.

if not exist "node_modules" (
    echo [*] Installing packages...
    call npm install
    echo.
)

echo [*] Starting on http://localhost:5173

call npm run dev
