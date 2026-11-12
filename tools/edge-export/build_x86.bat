@echo off
rem ============================================================================
rem  build_x86.bat -- compile the SAME edge_infer.c for x86 (Plan B parity run)
rem
rem  Output: edge_x86.exe in this folder.
rem
rem  Why the environment is assembled by hand instead of just calling vcvars64.bat:
rem  vcvars64.bat shells out to reg.exe. On locked-down machines (and inside a
rem  sandbox that blacklists reg.exe) that call fails *silently*, INCLUDE/LIB stay
rem  empty, and the compile dies with "cannot open stdio.h" -- which looks like a
rem  broken toolchain but is only a missing environment. So: detect the toolset and
rem  the Windows SDK by folder, set PATH/INCLUDE/LIB ourselves, and only fall back
rem  to vcvars64.bat / gcc if that fails.
rem
rem  Kept ASCII-only on purpose: cmd.exe codepage 936 on a Chinese Windows garbles
rem  UTF-8 comments, and a garbled byte inside an if-block can break the script.
rem  The Chinese explanation lives in README-运行步骤.md.
rem ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VSPATH="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
)
if not defined VSPATH if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Community" set "VSPATH=%ProgramFiles%\Microsoft Visual Studio\2022\Community"
if not defined VSPATH goto :try_gcc

rem ---- 1) newest MSVC toolset folder -----------------------------------------
set "TOOLSET="
if exist "%VSPATH%\VC\Tools\MSVC" (
    for /f "delims=" %%d in ('dir /b /ad /o-n "%VSPATH%\VC\Tools\MSVC" 2^>nul') do (
        if not defined TOOLSET set "TOOLSET=%VSPATH%\VC\Tools\MSVC\%%d"
    )
)
if not defined TOOLSET goto :try_vcvars
if not exist "%TOOLSET%\bin\Hostx64\x64\cl.exe" goto :try_vcvars

rem ---- 2) newest Windows 10 SDK folder ---------------------------------------
set "SDKROOT="
if exist "%ProgramFiles(x86)%\Windows Kits\10\Include" (
    for /f "delims=" %%d in ('dir /b /ad /o-n "%ProgramFiles(x86)%\Windows Kits\10\Include" 2^>nul') do (
        if not defined SDKROOT set "SDKROOT=%%d"
    )
)

set "PATH=%TOOLSET%\bin\Hostx64\x64;%PATH%"
set "INCLUDE=%TOOLSET%\include"
set "LIB=%TOOLSET%\lib\x64"
if defined SDKROOT (
    set "INCLUDE=%INCLUDE%;%ProgramFiles(x86)%\Windows Kits\10\Include\%SDKROOT%\ucrt;%ProgramFiles(x86)%\Windows Kits\10\Include\%SDKROOT%\shared;%ProgramFiles(x86)%\Windows Kits\10\Include\%SDKROOT%\um;%ProgramFiles(x86)%\Windows Kits\10\Include\%SDKROOT%\winrt"
    set "LIB=%LIB%;%ProgramFiles(x86)%\Windows Kits\10\Lib\%SDKROOT%\ucrt\x64;%ProgramFiles(x86)%\Windows Kits\10\Lib\%SDKROOT%\um\x64"
)

echo [INFO] MSVC toolset : %TOOLSET%
if defined SDKROOT echo [INFO] Windows SDK  : %SDKROOT%
echo [INFO] compiling with cl.exe
cl /nologo /O2 /W3 /std:c11 /utf-8 /D_CRT_SECURE_NO_WARNINGS /Fe:edge_x86.exe edge_x86_main.c edge_infer.c forest_model.c
if errorlevel 1 goto :try_vcvars_direct
echo [OK] edge_x86.exe built with MSVC (manual environment)
goto :eof

rem ---- fallback: let Microsoft's own script do it (needs a working reg.exe) ---
:try_vcvars
if not exist "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" goto :try_gcc
:try_vcvars_direct
if not exist "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" goto :fail
echo [INFO] retrying through vcvars64.bat
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /O2 /W3 /std:c11 /utf-8 /D_CRT_SECURE_NO_WARNINGS /Fe:edge_x86.exe edge_x86_main.c edge_infer.c forest_model.c
if errorlevel 1 goto :fail
echo [OK] edge_x86.exe built with MSVC (vcvars)
goto :eof

:try_gcc
where gcc >nul 2>nul
if errorlevel 1 goto :nogcc
echo [INFO] compiling with gcc
gcc -O2 -std=c11 -finput-charset=UTF-8 -Wall -Wextra -o edge_x86.exe edge_x86_main.c edge_infer.c forest_model.c
if errorlevel 1 goto :fail
echo [OK] edge_x86.exe built with gcc
goto :eof

:nogcc
echo [FAIL] no compiler found.
echo        Option A: install "Build Tools for Visual Studio" with the C++ workload:
echo                  https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo        Option B: install MinGW-w64 (gcc) and re-run.
exit /b 1

:fail
echo [FAIL] compilation failed, see the messages above
exit /b 1
