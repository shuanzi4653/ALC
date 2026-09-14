[CmdletBinding()]
param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path $projectRoot '.run'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$logFile = Join-Path $runRoot 'start.log'
$pythonExe = Join-Path $projectRoot 'backend-python/.venv/Scripts/python.exe'
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
$jar = Join-Path $projectRoot "backend-java/target/tianchuang-server-$version.jar"

# 所有关键步骤同时写入 .run/start.log：双击窗口关闭后仍可回溯失败原因
function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    try { Add-Content -LiteralPath $logFile -Value $line -Encoding utf8 } catch { }
}

# 读取 Java 版本。
# 策略（按可靠性排序）：
#   1) 读 JDK 自带的 release 文件（纯文件读取，不受 stderr / 管道 / 代码页影响，最可靠）
#   2) 执行 java -version 并把输出重定向到临时文件后再读
#   3) 从安装路径名推断（如 jdk-17、ms-17.0.19）
# 说明：java -version 把版本写到 stderr，直接 & 捕获在部分环境下拿不到内容，
#       因此不能作为唯一判断依据。
function Get-JavaVersionText([string]$ExePath) {
    $javaHome = Split-Path -Parent (Split-Path -Parent $ExePath)
    $releaseFile = Join-Path $javaHome 'release'
    if (Test-Path -LiteralPath $releaseFile) {
        try {
            $content = Get-Content -LiteralPath $releaseFile -Raw -ErrorAction Stop
            if ($content -match 'JAVA_VERSION="([^"]+)"') {
                return "version `"$($Matches[1])`""
            }
        } catch { }
    }

    $temp = [System.IO.Path]::GetTempFileName()
    try {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & $ExePath -version *> $temp } catch { }
        $ErrorActionPreference = $previous
        if (Test-Path -LiteralPath $temp) {
            $text = Get-Content -LiteralPath $temp -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($text)) {
                return ($text -replace "\s+", ' ').Trim()
            }
        }
    } catch { }
    finally {
        Remove-Item -LiteralPath $temp -ErrorAction SilentlyContinue
    }

    if ($ExePath -match '(?:jdk|jre|openjdk)[-_.]?((?:17|21)(?:[._]\d+)*)') {
        return "version `"$($Matches[1])`""
    }
    return ''
}

# 选择 Java：逐个候选校验版本，只接受 JDK 17/21
# （避免 JAVA_HOME 指向更新的 JDK 或 PATH 上的任意 java 导致兼容问题）
function Resolve-JavaExe {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:JAVA_HOME) { $candidates.Add((Join-Path $env:JAVA_HOME 'bin/java.exe')) }

    $jdks = Join-Path $env:USERPROFILE '.jdks'
    if (Test-Path -LiteralPath $jdks) {
        Get-ChildItem -LiteralPath $jdks -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(17|21)' } |
            Sort-Object Name -Descending |
            ForEach-Object { $candidates.Add((Join-Path $_.FullName 'bin/java.exe')) }
    }

    $candidates.Add('C:\Program Files\Java\jdk-17\bin\java.exe')
    Get-ChildItem -Path 'C:\Program Files\Eclipse Adoptium\jdk-17*' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add((Join-Path $_.FullName 'bin/java.exe')) }

    $pathJava = (Get-Command java.exe -ErrorAction SilentlyContinue).Source
    if ($pathJava) { $candidates.Add($pathJava) }

    $rejected = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        $versionText = (Get-JavaVersionText $candidate).Trim()
        if ($versionText -match 'version "?(17|21)') {
            Write-Log "已选定 Java：$candidate"
            return $candidate
        }
        if ([string]::IsNullOrWhiteSpace($versionText)) {
            $rejected.Add("$candidate → 无法获取版本")
        } else {
            $rejected.Add("$candidate → " + ($versionText -replace "`n", ' '))
        }
    }
    $detail = if ($rejected.Count -gt 0) { "`n已检测到的候选：`n" + ($rejected -join "`n") } else { '' }
    throw "未找到 JDK 17 或 21（项目要求）。请安装 JDK 17 并设置 JAVA_HOME。$detail"
}

function Assert-PortFree([int]$Port) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conn) {
        $owner = ($conn | Select-Object -First 1).OwningProcess
        throw "端口 $Port 已被进程 $owner 占用。请先运行 stop.bat 释放端口，或检查是否有旧实例未退出。"
    }
}

function Wait-Json([string]$Uri, [string]$ExpectedService, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $body = Invoke-RestMethod -Uri $Uri -TimeoutSec 2
            if (-not $ExpectedService -or $body.service -eq $ExpectedService) { return }
        } catch { Start-Sleep -Milliseconds 500 }
    } while ((Get-Date) -lt $deadline)
    throw "服务未在期限内就绪：$Uri（详细日志：$logFile）"
}

Write-Log "天窗智巡启动中（项目根：$projectRoot）"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到 Python 虚拟环境：$pythonExe。初始化方法见 docs/deployment.md。"
}
if (-not (Test-Path -LiteralPath $jar)) {
    throw "未找到 JAR：$jar。请先运行 build.bat（或 scripts\build.ps1）完成构建。"
}

$javaExe = Resolve-JavaExe
Write-Log "使用 Java：$javaExe"

Assert-PortFree 8600
Assert-PortFree 8085

$python = $null
$java = $null
try {
    $python = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8600') `
        -WorkingDirectory (Join-Path $projectRoot 'backend-python') -WindowStyle Hidden -PassThru
    Write-Log "Python 服务已启动（PID $($python.Id)），等待就绪..."
    Wait-Json 'http://127.0.0.1:8600/health' 'tianchuang-python' 30
    Write-Log "Python 服务就绪"

    $java = Start-Process -FilePath $javaExe -ArgumentList @('-jar',$jar,'--server.address=127.0.0.1','--server.port=8085',
        '--spring.config.additional-location=file:./config/application.yml') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Log "Java 服务已启动（PID $($java.Id)），等待就绪..."
    Wait-Json 'http://127.0.0.1:8085/api/health/live' 'tianchuang-java' 120
    Write-Log "Java 服务就绪"

    @{ pythonPid=$python.Id; pythonStartedAt=$python.StartTime.ToString('o'); javaPid=$java.Id;
       javaStartedAt=$java.StartTime.ToString('o'); projectRoot=$projectRoot } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'processes.json') -Encoding utf8
} catch {
    foreach ($created in @($java, $python)) {
        if ($null -ne $created -and -not $created.HasExited) {
            Stop-Process -Id $created.Id -ErrorAction SilentlyContinue
            Write-Log "启动失败，已回收本次创建的进程 PID $($created.Id)"
        }
    }
    throw
}

if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8085' }
Write-Log "天窗智巡已启动：http://127.0.0.1:8085"
