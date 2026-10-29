@echo off
title TianChuang Environment Check
setlocal
rem 把脚本自身目录先存下来：下面的参数解析会 shift，而 shift 会移动 %0，
rem 使 %~dp0 不再指向本文件（会变成第一个参数）。循环后再用 %~dp0 就会解析到
rem 当前工作目录下的 scripts\，从而跑错项目或直接报找不到。
set "ROOT=%~dp0"

rem ===========================================================================
rem TianChuang ZhiXun - runtime environment self-check launcher
rem
rem Double-click this file to find out whether this machine can run the system.
rem It only reads: it starts no service, installs nothing, and writes nothing
rem except the optional report file in .run\. That matters -- a diagnostic that
rem changes the thing it is measuring is not a diagnostic.
rem
rem Exit code 0 = meets the requirements (warnings allowed)
rem Exit code 1 = one or more hard requirements are not met
rem
rem Options (may be combined; order does not matter):
rem   --quiet, -q     only print the verdict; the report file is still written
rem   --no-network    skip the outbound probes (air-gapped / metered link)
rem   --json-only     --quiet plus --no-network, the fastest report-only mode
rem   --help, -h      show this help
rem
rem ENCODING CONTRACT -- do not "simplify" this file:
rem   1. This file is GBK (code page 936), CRLF, NO BOM, and contains NO chcp.
rem      That is deliberate and is the only combination that gives zero errors,
rem      correct Chinese output, and a working "@echo off" at the same time.
rem      cmd.exe reads a batch file by BYTE OFFSET; switching the code page
rem      mid-file desynchronises that offset (UTF-8 CJK is 3 bytes, GBK is 2),
rem      so cmd resumes mid-line and runs the tail of a line as a command.
rem      Symptoms look like "garbage characters in the file". They are not.
rem   2. Keep it CRLF. A LF-only batch file makes cmd mis-split lines.
rem   3. Keep echo text free of square brackets; cmd may take them as
rem      redirection and swallow the lines that follow.
rem   4. Editors silently re-save as UTF-8. If you edit this file, re-check the
rem      encoding before committing (see windows-bat-launcher skill).
rem   5. The .ps1 side has a different contract (UTF-8 with BOM). Only the .ps1
rem      half is covered by scripts\check-powershell.ps1 -- this file's encoding
rem      and line endings must be verified by hand after every edit.
rem ===========================================================================

if "%~1"=="--help" goto usage
if "%~1"=="-h" goto usage

if not exist "%ROOT%scripts\check-environment.ps1" (
    echo.
    echo FAIL: missing scripts\check-environment.ps1
    echo       Run this launcher from the project root directory.
    echo.
    pause
    exit /b 1
)

rem The report is written under .run\ so it sits with the other runtime evidence
rem rather than cluttering the repository root.
if not exist "%ROOT%.run" mkdir "%ROOT%.run" >nul 2>&1
set "REPORT=%ROOT%.run\environment-check.json"

rem Translate every argument, not just the first one, so that
rem     check-env.bat --quiet --no-network
rem behaves the way it reads. An earlier version inspected %~1 only and silently
rem ignored the second flag.
set "EXTRA="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--quiet"      set "EXTRA=%EXTRA% -Quiet"
if /i "%~1"=="-q"           set "EXTRA=%EXTRA% -Quiet"
if /i "%~1"=="--no-network" set "EXTRA=%EXTRA% -SkipNetwork"
if /i "%~1"=="--json-only"  set "EXTRA=%EXTRA% -Quiet -SkipNetwork"
if /i "%~1"=="--help"       goto usage
if /i "%~1"=="-h"           goto usage
shift
goto parse
:parsed

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\check-environment.ps1" %EXTRA% -Json "%REPORT%"
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
    echo ============================================================
    echo   自检通过，可以启动系统：双击 start.bat
    echo   完整报告：%REPORT%
    echo ============================================================
) else (
    echo ============================================================
    echo   自检未通过（退出码 %RC%）
    echo ------------------------------------------------------------
    echo   请按上方标为“失败”的项处理后重新运行本自检。
    echo   标为“注意”的项不影响运行，只代表低于推荐配置。
    echo   若提示缺少依赖（Python 虚拟环境 / 前端依赖 / JDK），
    echo   请按 README.md 的“新机器首次安装”补齐。
    echo   完整报告：%REPORT%
    echo ============================================================
)

echo.
echo 按任意键关闭本窗口...
pause >nul
exit /b %RC%

:usage
echo.
echo   check-env.bat 选项
echo.
echo     --quiet, -q     只输出结论，报告文件照常写入
echo     --no-network    跳过出网探测（离线 / 计量网络）
echo     --json-only     等价于 --quiet --no-network
echo     --help, -h      显示本帮助
echo.
pause >nul
exit /b 0
