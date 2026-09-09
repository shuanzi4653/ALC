@echo off
chcp 65001 >nul
title 天窗智巡 - 结束系统
color 0B

echo ============================================
echo    天窗智巡 · 停止服务并释放端口
echo ============================================
echo.

call :killport 8085
call :killport 8600

echo.
echo [验证] 等待端口释放...
timeout /t 2 /nobreak >nul

call :checkport 8085
call :checkport 8600

echo.
echo 全部完成。按任意键关闭窗口。
pause >nul
exit /b 0

:killport
set PORT=%1
set KPID=
for /f "tokens=5" %%A in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do set KPID=%%A
if "%KPID%"=="" (
    echo [信息] 端口 %PORT% 无监听进程
    goto :eof
)
echo [停止] 端口 %PORT% 进程 PID %KPID%
taskkill /F /T /PID %KPID% >nul 2>&1
goto :eof

:checkport
netstat -ano | findstr :%1 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo [成功] 端口 %1 已释放
) else (
    echo [警告] 端口 %1 仍被占用，请手动检查
)
goto :eof
