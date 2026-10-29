@echo off
title TianChuang Cloud Launcher
setlocal

rem ===================================================================
rem  TianChuang cloud-access launcher.
rem
rem  This file is deliberately pure ASCII with CRLF line endings.
rem  cmd.exe reads a .bat using the console code page, so Chinese text
rem  written here would be decoded as garbage and the script would die
rem  with bogus "not a valid command" errors.
rem  Every Chinese message is printed by launcher.ps1 instead, which is
rem  saved as UTF-8 with BOM and sets the console encoding itself.
rem
rem  Do NOT add: chcp, non-ASCII characters, or LF-only line endings.
rem ===================================================================

if not exist "%~dp0launcher.ps1" (
    echo.
    echo   ERROR: launcher.ps1 is missing from this folder.
    echo   Keep the whole TianChuang folder together, then run again.
    echo.
    pause
    exit /b 2
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Launch FAILED ^(exit code %RC%^)
    echo ------------------------------------------------------------
    echo   The Chinese messages above say which check failed and
    echo   what to do about it.
    echo   This window stays open so you can read them.
    echo ============================================================
    echo.
    pause
)
exit /b %RC%
