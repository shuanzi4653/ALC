@echo off
chcp 65001 >nul
title TianChuang - Build
setlocal
set ROOT=%~dp0
set JAVA_HOME=C:\Users\12921\.jdks\ms-17.0.19
set MVN=D:\Intellij IDEA\IntelliJ IDEA 2026.1\plugins\maven\lib\maven3\bin\mvn.cmd

echo ============================================================
echo  TianChuang Builder
echo  1) frontend npm build  2) sync to static  3) backend package
echo ============================================================
echo.

echo [1/3] Building frontend...
cd /d "%ROOT%frontend"
call npm run build
if errorlevel 1 goto :err

echo.
echo [2/3] Syncing dist to backend static...
if not exist "%ROOT%backend-java\src\main\resources\static" mkdir "%ROOT%backend-java\src\main\resources\static"
xcopy /E /Y /I "%ROOT%frontend\dist\*" "%ROOT%backend-java\src\main\resources\static\" >nul

echo.
echo [3/3] Packaging backend JAR (skip tests)...
call "%MVN%" -f "%ROOT%backend-java\pom.xml" -q -DskipTests package
if errorlevel 1 goto :err

echo.
echo ============================================================
echo  Build OK
echo  JAR: %ROOT%backend-java\target\tianchuang-server-0.1.0.jar
echo ============================================================
timeout /t 3 >nul
exit /b 0

:err
echo.
echo  BUILD FAILED - see errors above.
pause
exit /b 1
