@echo off
chcp 65001 >nul
title TianChuang - Low-Altitude Weather Monitor
setlocal

set ROOT=%~dp0
set JAVA_BIN=C:\Users\12921\.jdks\ms-17.0.19\bin\java.exe
set JAVA_HOME=C:\Users\12921\.jdks\ms-17.0.19
set MVN=D:\Intellij IDEA\IntelliJ IDEA 2026.1\plugins\maven\lib\maven3\bin\mvn.cmd
set JAR=%ROOT%backend-java\target\tianchuang-server-0.1.0.jar

echo ============================================================
echo  TianChuang Starter
echo  1) Python AI service  : http://127.0.0.1:8600
echo  2) Spring Boot server : http://127.0.0.1:8085
echo ============================================================
echo.

REM -- 0. Build backend JAR if missing (first run only) --
if not exist "%JAR%" (
  echo  First run: packaging backend JAR, please wait ...
  call "%MVN%" -f "%ROOT%backend-java\pom.xml" -q -DskipTests package
)

REM -- 1. Start Python service in a new window --
start "TianChuang-Python" cmd /k "chcp 65001 >nul && cd /d "%ROOT%backend-python" && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8600"

REM -- 2. Start Spring Boot in a new window (work dir = project root so ./config and ./data resolve) --
start "TianChuang-Java" cmd /k "chcp 65001 >nul && cd /d "%ROOT%" && "%JAVA_BIN%" -jar "%JAR%" --server.port=8085 --spring.config.additional-location=file:./config/application.yml"

echo  Waiting for backend to be ready (up to 90s) ...
set /a TRIES=0
:waitloop
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8085/api/dashboard -TimeoutSec 3; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 goto ready
set /a TRIES+=1
if %TRIES% geq 30 goto timeout
goto waitloop

:ready
echo  Backend is ready. Opening dashboard ...
start "" http://127.0.0.1:8085
echo.
echo  Dashboard  : http://127.0.0.1:8085
echo  H2 Console : http://127.0.0.1:8085/h2-console  (JDBC URL: jdbc:h2:file:./data/tianchuang, user: sa, empty password)
echo  Stop: click the "End System" button on the dashboard, or double-click stop.bat.
pause
exit /b 0

:timeout
echo  Backend did not respond within 90s. Check the TianChuang-Java window for errors.
pause
exit /b 1
