[CmdletBinding()]
param(
    [switch]$SkipJava,
    [switch]$SkipPython,
    [switch]$SkipFrontend
)

# 天窗智巡 · 本地聚合测试入口（G01）
# 职责：按顺序运行三端测试，任一步失败立即以非零退出；
#       不结束任何非本脚本启动的进程，不占用业务端口，不调用外部服务。

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$results = @()

function Resolve-Maven {
    $wrapper = Join-Path $projectRoot 'backend-java/mvnw.cmd'
    if (Test-Path -LiteralPath $wrapper) { return $wrapper }
    $candidates = @(
        (Join-Path $env:USERPROFILE '.m2/wrapper/dists'),
        'D:\Intellij IDEA\IntelliJ IDEA 2026.1\plugins\maven\lib\maven3\bin\mvn.cmd'
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c) -and $c.EndsWith('mvn.cmd')) { return $c }
    }
    return 'mvn.cmd'
}

function Invoke-Step([string]$name, [scriptblock]$body) {
    Write-Host ""
    Write-Host "==== $name ====" -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $body
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "$name 失败（退出码 $LASTEXITCODE）"
        }
        $sw.Stop()
        $script:results += [pscustomobject]@{ Step = $name; Status = 'PASS'; Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
    } catch {
        $sw.Stop()
        $script:results += [pscustomobject]@{ Step = $name; Status = 'FAIL'; Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
        Write-Host "  错误：$($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

try {
    if (-not $SkipJava) {
        $mvn = Resolve-Maven
        $jarRoot = Join-Path $projectRoot 'backend-java'
        Invoke-Step 'Java 单元测试' {
            & $mvn -f (Join-Path $jarRoot 'pom.xml') test
        }
    }

    if (-not $SkipPython) {
        $python = Join-Path $projectRoot 'backend-python/.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $python)) { throw "未找到 Python 虚拟环境：$python" }
        Invoke-Step 'Python 测试' {
            Push-Location (Join-Path $projectRoot 'backend-python')
            try { & $python -m pytest tests -q } finally { Pop-Location }
        }
    }

    if (-not $SkipFrontend) {
        $frontend = Join-Path $projectRoot 'frontend'
        Invoke-Step '前端测试 + 生产构建' {
            Push-Location $frontend
            try {
                npm run test
                if ($LASTEXITCODE -ne 0) { throw '前端单元测试失败' }
                npm run build
            } finally { Pop-Location }
        }
    }

    Write-Host ""
    Write-Host "==== 汇总 ====" -ForegroundColor Green
    $results | Format-Table -AutoSize
    Write-Host "全部通过。" -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host "==== 汇总（存在失败）====" -ForegroundColor Red
    $results | Format-Table -AutoSize
    Write-Host "测试未全部通过：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
