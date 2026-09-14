[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path $projectRoot '.run'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$logFile = Join-Path $runRoot 'stop.log'
$stateFile = Join-Path $runRoot 'processes.json'
$stoppingFile = Join-Path $runRoot 'stopping'

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    try { Add-Content -LiteralPath $logFile -Value $line -Encoding utf8 } catch { }
}

if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Log '未找到本项目受管进程记录（服务可能已停止，或由其他方式启动）。'
    foreach ($port in @(8085, 8600, 5180)) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            Write-Log "提示：端口 $port 仍被占用，可执行 netstat -ano | findstr :$port 查看占用进程后手动处理。"
        }
    }
    exit 0
}
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
if (-not $state.projectRoot -or
    [string]::Compare([string]$state.projectRoot, $projectRoot, [StringComparison]::OrdinalIgnoreCase) -ne 0) {
    throw '受管进程记录不属于当前项目，未停止任何进程。'
}
Set-Content -LiteralPath $stoppingFile -Value 'stopping' -Encoding ascii
try {
foreach ($item in @(@{name='Java'; pid=[int]$state.javaPid; started=$state.javaStartedAt},
                     @{name='Python'; pid=[int]$state.pythonPid; started=$state.pythonStartedAt},
                     @{name='Frontend'; pid=[int]$state.frontendPid; started=$state.frontendStartedAt})) {
    if ($item.pid -le 0) { continue }
    $process = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Log "$($item.name) 进程（PID $($item.pid)）已不在运行。"
        continue
    }
    $recorded = [DateTime]::Parse($item.started).ToUniversalTime()
    if ([Math]::Abs(($process.StartTime.ToUniversalTime() - $recorded).TotalSeconds) -gt 2) {
        throw "$($item.name) PID 已被复用，未停止该进程。"
    }
    $command = $null
    try {
        $command = Get-CimInstance Win32_Process -Filter "ProcessId=$($item.pid)" -ErrorAction Stop
    } catch {
        Write-Log "无法读取 $($item.name) 进程命令行；已通过项目记录与启动时间校验。"
    }
    if ($command -and $command.CommandLine -and
        $command.CommandLine.IndexOf($projectRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "$($item.name) 进程命令行不属于当前项目，未停止该进程。"
    }
    Stop-Process -Id $item.pid -Force
    $process.WaitForExit(10000) | Out-Null
    Write-Log "已停止 $($item.name)（PID $($item.pid)）"
}
Remove-Item -LiteralPath $stateFile
Write-Log '已停止本项目记录的受管进程。'
} finally {
    Remove-Item -LiteralPath $stoppingFile -Force -ErrorAction SilentlyContinue
}
