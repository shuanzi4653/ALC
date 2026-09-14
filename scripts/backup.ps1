[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [string]$Username = "sa",
    [string]$Password = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dbFile = Join-Path $projectRoot 'data/tianchuang.mv.db'
if (-not (Test-Path -LiteralPath $dbFile)) { throw "未找到数据库文件：$dbFile" }

# 当前版本只承诺停机一致性备份。独立 JVM 不能安全连接正在由应用独占的嵌入式 H2。
if (Get-NetTCPConnection -State Listen -LocalPort 8085 -ErrorAction SilentlyContinue) {
    throw '检测到 Java 服务仍在运行。请先用 stop.bat 停止受管实例，再执行数据库备份。'
}
if (-not $OutputDir) { $OutputDir = Join-Path $projectRoot ("backup/" + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $OutputDir))
New-Item -ItemType Directory -Path $resolvedParent -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$target = Join-Path $OutputDir 'tianchuang.mv.db'
Copy-Item -LiteralPath $dbFile -Destination $target -Force

$h2Jar = Get-ChildItem -Path (Join-Path $env:USERPROFILE '.m2/repository/com/h2database/h2') -Recurse -Filter 'h2-*.jar' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '*-sources.jar' -and $_.Name -notlike '*-javadoc.jar' } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $h2Jar) { throw '备份文件已复制，但未找到 H2 驱动，无法完成可恢复性校验。' }

$dbBase = $target.Substring(0, $target.Length - '.mv.db'.Length) -replace '\\','/'
& java -cp $h2Jar.FullName org.h2.tools.Shell -url "jdbc:h2:file:$dbBase;MODE=MySQL;ACCESS_MODE_DATA=r" `
    -user $Username -password $Password -sql "SELECT COUNT(*) AS TABLE_COUNT FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='PUBLIC';" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "备份副本无法打开，H2 校验退出码：$LASTEXITCODE" }

$item = Get-Item -LiteralPath $target
$hash = Get-FileHash -LiteralPath $target -Algorithm SHA256
[pscustomobject]@{ File=$item.FullName; Bytes=$item.Length; Sha256=$hash.Hash; Verified=$true } | Format-List
