[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$failed = 0
Write-Host ('PowerShell parser: ' + $PSVersionTable.PSVersion.ToString())
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $nonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count -gt 0
    $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if (($nonAscii -and -not $bom) -or $parseErrors.Count -gt 0) {
        $failed++
        Write-Host ('FAIL {0}: BOM={1}; parse errors={2}' -f $file.Name, $bom, $parseErrors.Count)
        foreach ($errorItem in $parseErrors) {
            Write-Host ('  line {0}: {1}' -f $errorItem.Extent.StartLineNumber, $errorItem.ErrorId)
        }
    } else { Write-Host ('PASS ' + $file.Name) }
}
if ($failed) { Write-Host ('Failed scripts: ' + $failed); exit 1 }
Write-Host 'All PowerShell scripts passed encoding and syntax checks.'
