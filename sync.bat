@echo off
REM AIC repo - sync local commits to GitHub + Gitee
REM Double-click friendly. Drag-free, no arguments required.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync-remotes.ps1" %*
set RC=%ERRORLEVEL%
echo.
echo Exit code: %RC%
if not "%RC%"=="0" pause
endlocal
