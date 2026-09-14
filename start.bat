@echo off
chcp 65001 >nul
title TianChuang Launcher
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\check-powershell.ps1"
if errorlevel 1 (
    echo PowerShell compatibility check failed. Scripts containing Chinese must use UTF-8 with BOM.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -OpenBrowser -Wait
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Start FAILED ^(exit code %RC%^)
    echo ------------------------------------------------------------
    echo   Common causes:
    echo     1^) Port 8085 / 8600 / 5180 already in use -^> run stop.bat first
    echo     2^) Local source compile failed        -^> see .run logs
    echo     3^) Python venv missing                 -^> see docs\deployment.md
    echo.
    echo   Service logs: .run\*-dev.out.log and .run\*-dev.err.log
    echo ============================================================
    echo.
    pause
) else (
    echo.
    echo ============================================================
    echo   TianChuang services have stopped.
    echo   Press any key to close this launcher window.
    echo ============================================================
    echo.
    pause >nul
)
exit /b %RC%
