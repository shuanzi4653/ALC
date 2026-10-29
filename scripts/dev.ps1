[CmdletBinding()]
param(
    [switch]$SkipCompile,
    [switch]$OpenBrowser,
    [switch]$Wait
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runRoot = Join-Path $projectRoot '.run'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$statePath = Join-Path $runRoot 'processes.json'
$stoppingPath = Join-Path $runRoot 'stopping'
if (Test-Path -LiteralPath $statePath) { throw '请先运行 stop.bat 停止已有受管服务。' }
$javaHomeCandidates = @($env:JAVA_HOME, (Join-Path $env:USERPROFILE '.jdks/ms-17.0.19'))
$jdkDirectory = Join-Path $env:USERPROFILE '.jdks'
if (Test-Path -LiteralPath $jdkDirectory) {
    $javaHomeCandidates += @(Get-ChildItem -LiteralPath $jdkDirectory -Directory | ForEach-Object { $_.FullName })
}
$jdk = $null
foreach ($candidate in $javaHomeCandidates) {
    if (-not $candidate) { continue }
    $releaseFile = Join-Path $candidate 'release'
    if (-not (Test-Path -LiteralPath $releaseFile) -or -not (Test-Path -LiteralPath (Join-Path $candidate 'bin/javac.exe'))) { continue }
    $versionMatch = [regex]::Match((Get-Content -LiteralPath $releaseFile -Raw), '(?m)^JAVA_VERSION="(\d+)')
    if ($versionMatch.Success -and $versionMatch.Groups[1].Value -in @('17','21')) { $jdk = $candidate; break }
}
if (-not $jdk) { throw '需要 JDK17 或21，请设置 JAVA_HOME。' }
$env:JAVA_HOME = $jdk
Write-Host "使用兼容 JDK：$jdk"
$classpathFile = Join-Path $runRoot 'java-classpath.txt'
if (-not $SkipCompile) {
    Push-Location (Join-Path $projectRoot 'backend-java')
    try {
        & .\mvnw.cmd "-Dmaven.repo.local=$env:USERPROFILE/.m2/repository" compile dependency:build-classpath "-Dmdep.outputFile=$classpathFile" '-DincludeScope=runtime'
        if ($LASTEXITCODE -ne 0) { throw '源码编译失败（未执行打包）。' }
    } finally { Pop-Location }
}
if (-not (Test-Path $classpathFile)) { throw '缺少本地类路径，请去掉 SkipCompile 重试。' }
$pythonExe = Join-Path $projectRoot 'backend-python/.venv/Scripts/python.exe'
$nodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$javaExe = Join-Path $jdk 'bin/java.exe'
$classes = Join-Path $projectRoot 'backend-java/target/classes'
$classpath = $classes + ';' + (Get-Content -LiteralPath $classpathFile -Raw).Trim()
# 静态包新鲜度。Spring Boot 会把 `target/classes/static` 当 `classpath:/static` 提供，
# 于是 8085 端口**可能悄悄回答一份几天前的前端** —— 而浏览器真正该用的是 vite 的 5180。
# 留一份过期包在那里，等于给"改了却看不到"留一个永远查不出来的出口：
# 2026-09-12 的包一直躺到 2026-09-24，期间任何前端修复都到不了 8085。
# 规则：有当前构建产物就同步过去；没有就删掉，让 8085 老老实实 404 而不是说谎。
$staticRoot = Join-Path $projectRoot 'backend-java/target/classes/static'
$distRoot = Join-Path $projectRoot 'frontend/dist'
if (Test-Path -LiteralPath (Join-Path $distRoot 'index.html')) {
    if (Test-Path -LiteralPath $staticRoot) { Remove-Item -LiteralPath $staticRoot -Recurse -Force }
    Copy-Item -LiteralPath $distRoot -Destination $staticRoot -Recurse -Force
    Write-Host '已同步前端产物：frontend/dist -> target/classes/static（8085 与 5180 同一版本）。'
} elseif (Test-Path -LiteralPath $staticRoot) {
    Remove-Item -LiteralPath $staticRoot -Recurse -Force
    Write-Host '未找到 frontend/dist，已移除过期静态包：8085 不再提供前端，请访问 http://127.0.0.1:5180/。'
}
foreach ($port in @(8085,8600,5180)) {
    $probe = New-Object System.Net.Sockets.TcpClient
    try { $probe.Connect('127.0.0.1',$port); throw "端口 $port 已占用，请先停止对应服务。" }
    catch [System.Net.Sockets.SocketException] { }
    finally { $probe.Dispose() }
}
$created = @()
try {
    $python = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8600') -WorkingDirectory (Join-Path $projectRoot 'backend-python') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'python-dev.out.log') -RedirectStandardError (Join-Path $runRoot 'python-dev.err.log')
    $created += $python
    $java = Start-Process -FilePath $javaExe -ArgumentList @('-cp',('"'+$classpath+'"'),'com.tianchuang.TianchuangApplication','--server.port=8085','--server.address=127.0.0.1','--local.source-mode=true','--push.mail.enabled=false','--push.dingtalk-webhook=','--push.feishu-webhook=','--push.wecom-webhook=') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'java-dev.out.log') -RedirectStandardError (Join-Path $runRoot 'java-dev.err.log')
    $created += $java
    $frontend = Start-Process -FilePath $nodeExe -ArgumentList @(('"'+(Join-Path $projectRoot 'frontend/node_modules/vite/bin/vite.js')+'"'),'--host','127.0.0.1','--port','5180','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'frontend-dev.out.log') -RedirectStandardError (Join-Path $runRoot 'frontend-dev.err.log')
    $created += $frontend
    @{projectRoot=$projectRoot;javaPid=$java.Id;javaStartedAt=$java.StartTime.ToString('o');pythonPid=$python.Id;pythonStartedAt=$python.StartTime.ToString('o');frontendPid=$frontend.Id;frontendStartedAt=$frontend.StartTime.ToString('o');mode='source'} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        foreach ($process in $created) { if ($process.HasExited) { throw '源码服务提前退出，请查看 .run/*-dev.err.log。' } }
        try {
            Invoke-WebRequest 'http://127.0.0.1:8600/health' -UseBasicParsing -TimeoutSec 1 | Out-Null
            Invoke-WebRequest 'http://127.0.0.1:8085/api/health/live' -UseBasicParsing -TimeoutSec 1 | Out-Null
            Invoke-WebRequest 'http://127.0.0.1:5180' -UseBasicParsing -TimeoutSec 1 | Out-Null
            $ready = $true; break
        } catch { Start-Sleep -Milliseconds 700 }
    }
    if (-not $ready) { throw '服务未在限定时间内就绪，请查看 .run 日志。' }
    $dashboardUrl = 'http://127.0.0.1:5180/'
    Write-Host "本地源码服务已就绪：$dashboardUrl；未生成JAR或前端发布包。日志在 .run。"
    if ($OpenBrowser) {
        try {
            Start-Process $dashboardUrl | Out-Null
            Write-Host '已使用系统默认浏览器打开运行中心。'
        } catch {
            Write-Warning "无法自动打开浏览器，请手动访问 $dashboardUrl"
        }
    }
    if ($Wait) {
        Write-Host '启动窗口将保持打开并监控服务；需要停止时请运行 stop.bat。'
        while (Test-Path -LiteralPath $statePath) {
            if (Test-Path -LiteralPath $stoppingPath) {
                Start-Sleep -Seconds 1
                continue
            }
            $stopped = @($created | Where-Object { $_.HasExited })
            if ($stopped.Count -gt 0) {
                $names = @($stopped | ForEach-Object { "PID $($_.Id)" }) -join ', '
                throw "受管服务意外退出（$names），请查看 .run 日志。"
            }
            Start-Sleep -Seconds 2
        }
        Write-Host '已检测到 stop.bat 完成停止，启动监控结束。'
    }
} catch {
    foreach($process in $created) { if(-not $process.HasExited) { Stop-Process -Id $process.Id } }
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
    throw
}
