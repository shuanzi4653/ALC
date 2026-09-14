[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BackupFile,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $projectRoot 'data/tianchuang.mv.db'
$source = [System.IO.Path]::GetFullPath($BackupFile)
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "备份文件不存在：$source" }
if ([System.IO.Path]::GetExtension($source) -ne '.db' -or -not $source.EndsWith('.mv.db')) { throw '只接受 .mv.db 备份文件。' }
if (Get-NetTCPConnection -State Listen -LocalPort 8085 -ErrorAction SilentlyContinue) { throw 'Java 服务仍在运行，拒绝恢复数据库。' }
if (-not $Force) { throw '恢复会替换当前数据库。核对 BackupFile 后加 -Force 执行；脚本会先保存当前库的回滚副本。' }

$rollbackDir = Join-Path $projectRoot ("backup/pre-restore_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $rollbackDir -Force | Out-Null
if (Test-Path -LiteralPath $target) {
    Copy-Item -LiteralPath $target -Destination (Join-Path $rollbackDir 'tianchuang.mv.db') -Force
}
Copy-Item -LiteralPath $source -Destination $target -Force
Write-Host "恢复完成：$target"
Write-Host "原数据库回滚副本：$rollbackDir"
