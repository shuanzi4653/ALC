# AIC repo - manual sync to GitHub + Gitee
# Usage: powershell -ExecutionPolicy Bypass -File scripts\sync-remotes.ps1 [-Message "msg"]
# ASCII only on purpose: PowerShell 5.1 reads BOM-less UTF-8 as ANSI and garbles Chinese.

param(
    [string]$Message = "",
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Test-Path ".git")) { Write-Host "ERROR: not a git repo: $repo"; exit 2 }

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
$dirty = (git status --porcelain)
if ($dirty) {
    if ($NoCommit) {
        Write-Host "WARN: working tree is dirty and -NoCommit was given; commits are not made."
    } else {
        if ([string]::IsNullOrWhiteSpace($Message)) {
            $ver = if (Test-Path "VERSION") { (Get-Content "VERSION" -Raw).Trim() } else { "dev" }
            $Message = "sync: V$ver @ " + (Get-Date -Format "yyyy-MM-dd HH:mm")
        }
        git add -A | Out-Null
        git commit -m $Message | Out-Null
        Write-Host ("COMMIT: " + $Message)
    }
} else {
    Write-Host "COMMIT: nothing to commit"
}

$sha = (git rev-parse --short HEAD).Trim()
$failed = @()
foreach ($remote in @("origin", "gitee")) {
    $url = (git remote get-url $remote 2>$null)
    if (-not $url) { Write-Host "SKIP: $remote (not configured)"; continue }
    $ok = $false
    for ($i = 1; $i -le 2; $i++) {
        git push $remote "HEAD:$branch" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
        Start-Sleep -Seconds 2
    }
    if ($ok) { Write-Host "PUSH OK: $remote ($sha -> $branch)" } else { Write-Host "PUSH FAIL: $remote"; $failed += $remote }
}

if ($failed.Count -gt 0) {
    Write-Host ("FAILED remotes: " + ($failed -join ", "))
    exit 1
}
Write-Host "DONE: $sha synced to all remotes"
exit 0
