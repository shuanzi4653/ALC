@echo off
chcp 65001 >nul
title TianChuang Stopper
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Stop FAILED ^(exit code %RC%^)
    echo   See messages above; check ports 8085 / 8600 / 5180 manually.
    echo   Full log: .run\stop.log
    echo ============================================================
    echo.
    pause
)
exit /b %RC%
