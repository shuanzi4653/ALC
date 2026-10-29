@echo off
title TianChuang - Create Desktop Shortcut
setlocal

rem ===================================================================
rem  Creates a desktop shortcut pointing at the main launcher .bat in this
rem  folder (see the file list in readme.txt). The launcher's filename is
rem  Chinese, which is why it is not spelled out here -- a .bat must stay
rem  pure ASCII.
rem
rem  Pure ASCII + CRLF on purpose: cmd.exe parses a .bat using the
rem  console code page, so Chinese text here would decode as garbage.
rem  All Chinese output comes from launcher.ps1 instead.
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

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1" -CreateDesktopShortcut
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Could not create the shortcut ^(exit code %RC%^)
    echo ------------------------------------------------------------
    echo   The Chinese messages above say what went wrong.
    echo   This window stays open so you can read them.
    echo ============================================================
    echo.
    pause
)

exit /b %RC%
