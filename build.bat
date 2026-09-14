@echo off
chcp 65001 >nul
title TianChuang Builder
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build.ps1"
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Build FAILED ^(exit code %RC%^)
    echo   See build output above for details.
    echo   Full log: .run\build.log
    echo ============================================================
    echo.
    pause
)
exit /b %RC%
