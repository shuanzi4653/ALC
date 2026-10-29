[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$javaRoot = Join-Path $projectRoot 'backend-java'
$frontendRoot = Join-Path $projectRoot 'frontend'
$generatedRoot = Join-Path $javaRoot 'target/generated-resources/static'
$runRoot = Join-Path $projectRoot '.run'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$logFile = Join-Path $runRoot 'build.log'

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    try { Add-Content -LiteralPath $logFile -Value $line -Encoding utf8 } catch { }
}

# 读取 Java 版本（策略同 start.ps1：优先读 release 文件，其次执行命令，最后按路径推断）
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

# 自动定位 JDK 17/21（逐个校验版本，避免误用更高版本 JDK）
function Resolve-JavaHome {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:JAVA_HOME) { $candidates.Add($env:JAVA_HOME) }

    $jdks = Join-Path $env:USERPROFILE '.jdks'
    if (Test-Path -LiteralPath $jdks) {
        Get-ChildItem -LiteralPath $jdks -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(17|21)' } |
            Sort-Object Name -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
    $candidates.Add('C:\Program Files\Java\jdk-17')
    Get-ChildItem -Path 'C:\Program Files\Eclipse Adoptium\jdk-17*' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add($_.FullName) }

    $rejected = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        $exe = Join-Path $candidate 'bin/java.exe'
        if (-not (Test-Path -LiteralPath $exe)) { continue }
        $versionText = (Get-JavaVersionText $exe).Trim()
        if ($versionText -match 'version "?(17|21)') {
            Write-Log "已选定 JDK：$candidate"
            return $candidate
        }
        if ([string]::IsNullOrWhiteSpace($versionText)) {
            $rejected.Add("$candidate → 无法获取版本")
        } else {
            $rejected.Add("$candidate → " + ($versionText -replace "`n", ' '))
        }
    }
    $detail = if ($rejected.Count -gt 0) { "`n已检测到的候选：`n" + ($rejected -join "`n") } else { '' }
    throw "未找到 JDK 17 或 21。请安装 JDK 17 并设置 JAVA_HOME，或放到 %USERPROFILE%\.jdks 下。$detail"
}

function Resolve-Maven {
    $wrapper = Join-Path $javaRoot 'mvnw.cmd'
    if (Test-Path -LiteralPath $wrapper) { return $wrapper }
    $command = Get-Command mvn.cmd -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw '未找到 Maven Wrapper 或 mvn.cmd。请安装 Maven 或生成 backend-java/mvnw.cmd。'
}

foreach ($commandName in @('node', 'npm')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) { throw "未找到 $commandName，请安装 Node.js 18+。" }
}

$javaHome = Resolve-JavaHome
$env:JAVA_HOME = $javaHome
$javaExePath = Join-Path $javaHome 'bin/java.exe'
$javaVersion = Get-JavaVersionText $javaExePath
$javaVersionText = $javaVersion -join ' '
if ($javaVersionText -notmatch 'version "?(17|21)') {
    throw "需要 JDK 17 或 21，当前：$javaVersionText（来源 $javaHome）"
}
Write-Log "使用 JDK：$javaHome"
$maven = Resolve-Maven
Write-Log "使用 Maven：$maven"
$mavenRepo = Join-Path $env:USERPROFILE '.m2/repository'
$mavenRepoArg = "-Dmaven.repo.local=$mavenRepo"

Push-Location $javaRoot
try { & $maven $mavenRepoArg clean; if ($LASTEXITCODE -ne 0) { throw 'Maven clean 失败' } }
finally { Pop-Location }

Push-Location $frontendRoot
try {
    # 2026-10-15: npm/vite 把**良性**提示写到 stderr（如 vite 的分块体积告警
    # "[plugin builtin:vite-reporter]"，本仓产物 2.1 MB > chunkSizeWarningLimit 1600 kB），
    # 而 PowerShell 5.1 在 $ErrorActionPreference='Stop' 下把**原生进程的 stderr**
    # 当成终止错误 —— 于是"vite 已经建好、脚本却在下一行之前中止"，留下一个没有 JAR
    # 的半成品。这与本文件 34–37 行给 `java -version` 的处理是同一个坑、同一种修法。
    # **判据仍然是退出码**，不因为放宽错误偏好而少检查一条。
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci 失败' }
        if (-not $SkipTests) { & npm test; if ($LASTEXITCODE -ne 0) { throw '前端测试失败' } }
        $env:TIANCHUANG_FRONTEND_OUT = $generatedRoot
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
    } finally { $ErrorActionPreference = $previousEap }
} finally {
    Remove-Item Env:TIANCHUANG_FRONTEND_OUT -ErrorAction SilentlyContinue
    Pop-Location
}

# git 缺失时不应中断构建，仅记录 unknown
$sourceRef = 'unknown'
try { $sourceRef = (& git -C $projectRoot rev-parse --short HEAD 2>$null) } catch { }
$buildInfo = [ordered]@{
    buildId = [guid]::NewGuid().ToString()
    source = $sourceRef
    builtAt = [DateTimeOffset]::Now.ToString('o')
    node = (& node --version)
    java = ($javaVersion | Select-Object -First 1)
}
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $generatedRoot 'build-info.json') -Encoding utf8
Write-Log "构建信息已写入 build-info.json（source=$sourceRef）"

Push-Location $javaRoot
try {
    $mavenArgs = @($mavenRepoArg, 'package')
    if ($SkipTests) { $mavenArgs += '-DskipTests' }
    & $maven @mavenArgs
    if ($LASTEXITCODE -ne 0) { throw 'Maven package 失败' }
} finally { Pop-Location }

$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
$jar = Join-Path $javaRoot "target/tianchuang-server-$version.jar"
if (-not (Test-Path -LiteralPath $jar)) { throw '构建完成但未找到 JAR。' }

# Static-bundle self-check (2026-10-16). `maven-resources-plugin` is COPY, not mirror,
# so the moment `clean` is removed from the flow above the JAR carries BOTH the old and
# the new content-hashed generation at once -- and the build, the tests and the running
# app all stay silent (0.9.31: 6 orphan js/css entries, about 9 MB).
# The check lives here as well as in the gate for the same reason M87 gives: fix it where
# it is produced, and this script is what produces the JAR.
# NOTE: keep this block ASCII. PowerShell 5.1 reads a BOM-less .ps1 in the system ANSI
# codepage (936 here); a multi-byte comment desynchronises its parser (observed 2026-10-16).
# The interpreter is the project venv (`check-environment.ps1` guards it). When it is
# absent we warn only: "no venv" must not read as "build failed" -- the gate copy is hard.
$bundleCheck = Join-Path $projectRoot 'tools/maintenance/_verify_static_bundle.py'
$venvPython = Join-Path $projectRoot 'backend-python/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -X utf8 $bundleCheck --jar $jar
    if ($LASTEXITCODE -ne 0) { throw "静态包自检失败（产物里有多代 assets，见上方 ORPHAN 行）。" }
} else {
    Write-Log '警告：未找到 backend-python\.venv，跳过静态包自检（先跑 check-env.bat）。闸门里那一份仍会检查。'
}

Write-Log "构建成功：$jar"
Get-FileHash -LiteralPath $jar -Algorithm SHA256 | Format-List
