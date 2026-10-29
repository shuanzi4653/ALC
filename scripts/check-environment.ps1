[CmdletBinding()]
param(
    # Skip the outbound-network probes. Useful on an air-gapped or metered link,
    # and it is the only part of this script that touches the network at all.
    [switch]$SkipNetwork,
    # Emit a machine-readable result and exit non-zero if anything FAILed.
    # Used by the launcher and by CI; the human-readable report is unchanged.
    [switch]$Quiet,
    [string]$Json = ''
)

$ErrorActionPreference = 'Stop'
# Test-NetConnection draws a progress bar per host. On a slow link that floods
# the console with "Attempting TCP connect / Waiting for response" and buries
# the report the operator is trying to read.
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# 天窗智巡 · 运行环境自检
#
# Answers one question: can this machine run the system, and will it do so
# comfortably? Every threshold below is taken from the 「电脑与环境要求」
# section of README.md -- the same numbers a person would read there. Keeping
# the two in step is the point: a self-check that invents its own thresholds
# drifts away from the documentation and then either passes a machine the docs
# reject or fails one they accept.
#
# Three outcomes, and the distinction matters:
#   PASS   meets the requirement
#   WARN   runs, but below the comfortable figure -- the operator should know
#   FAIL   does not meet a hard requirement; the system will not start or will
#          misbehave
#
# A WARN never fails the run. Reporting every shortfall as fatal would train the
# operator to ignore the report, which is worse than not having one.
# ---------------------------------------------------------------------------

$script:Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [Parameter(Mandatory)][string]$Area,
        [Parameter(Mandatory)][string]$Item,
        [Parameter(Mandatory)][ValidateSet('PASS', 'WARN', 'FAIL', 'INFO')][string]$Status,
        [Parameter(Mandatory)][string]$Detail,
        [string]$Fix = ''
    )
    $script:Results.Add([pscustomobject]@{
        Area = $Area; Item = $Item; Status = $Status; Detail = $Detail; Fix = $Fix
    })
}

function Test-CommandPresent {
    param([Parameter(Mandatory)][string]$Name)
    # Get-Command with -ErrorAction SilentlyContinue: a missing tool is a normal
    # outcome here, not an error worth a stack trace.
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# The minimum Python is 3.12, NOT 3.11. Read off the lock file rather than
# guessed: requirements-lock.txt pins numpy==2.5.3, whose PyPI metadata declares
# requires_python >=3.12, and pyproj==3.7.2 declares >=3.11. Because the lock
# pins exact versions, pip cannot fall back to an older numpy -- on 3.11
# `pip install -r requirements-lock.txt` simply fails with
# "No matching distribution found for numpy==2.5.3".
# A handover machine was measured at Python 3.10.11 and this check reported it
# as a harmless INFO, which is precisely the misleading verdict it exists to
# prevent. Keep this number in sync with the lock file if it ever changes.
$MinPython = [version]'3.12'

# Parses "Python 3.13.14", "3.13.14" or "3.13" into a comparable [version].
# Returns $null when there is no version in the text at all.
function Get-PythonVersion {
    param([string]$Text)
    if ($Text -match '(\d+)\.(\d+)\.(\d+)') {
        return [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], $Matches[3])
    }
    if ($Text -match '(\d+)\.(\d+)') {
        return [version]("{0}.{1}" -f $Matches[1], $Matches[2])
    }
    return $null
}

$Root = Split-Path -Parent $PSScriptRoot
$failCount = 0
$warnCount = 0

# The project version belongs in every report: when a handover goes wrong, the
# first question is always "which build was that?". Read once, from VERSION.
$projectVersion = ''
$versionFile = Join-Path $Root 'VERSION'
if (Test-Path -LiteralPath $versionFile) {
    try { $projectVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim() } catch { }
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host '============================================================'
    Write-Host '  天窗智巡 · 运行环境自检'
    Write-Host ('  项目版本：' + $(if ($projectVersion) { $projectVersion } else { '未找到 VERSION 文件' }))
    Write-Host ('  项目目录：' + $Root)
    Write-Host ('  检测时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    Write-Host '============================================================'
}

# ---------------------------------------------------------------------------
# 1. 操作系统
# ---------------------------------------------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
$osCaption = $os.Caption
$osBuild = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
$isWindows11 = $osBuild -ge 22000
Add-Result '操作系统' 'Windows 版本' 'PASS' ("$osCaption (build $osBuild)") ''

if ($osBuild -lt 17763) {
    Add-Result '操作系统' '最低系统要求' 'FAIL' ("build $osBuild 低于 Windows 10 1809 (17763)") '升级到 Windows 10 1809 或更高版本'
} else {
    Add-Result '操作系统' '最低系统要求' 'PASS' '满足 Windows 10 1809+ / Windows 11' ''
}

$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -eq 'AMD64' -or $arch -eq 'ARM64') {
    Add-Result '操作系统' 'CPU 架构' 'PASS' $arch ''
} else {
    Add-Result '操作系统' 'CPU 架构' 'FAIL' "$arch 不受支持" '需要 64 位处理器'
}

# ---------------------------------------------------------------------------
# 2. 处理器
# ---------------------------------------------------------------------------
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cores = [int]$cpu.NumberOfCores
$threads = [int]$cpu.NumberOfLogicalProcessors
$cpuName = ($cpu.Name -replace '\s+', ' ').Trim()
$cpuMhz = [int]$cpu.MaxClockSpeed

Add-Result '处理器' '型号' 'INFO' ("$cpuName @ $cpuMhz MHz") ''
Add-Result '处理器' '物理核心 / 逻辑线程' 'INFO' ("$cores 核 / $threads 线程") ''

if ($cores -ge 8) {
    Add-Result '处理器' '核心数要求' 'PASS' ("$cores 核，满足推荐 8 核") ''
} elseif ($cores -ge 4) {
    Add-Result '处理器' '核心数要求' 'WARN' ("$cores 核，低于推荐 8 核") '构建阶段会明显变慢；服务运行本身足够'
} else {
    Add-Result '处理器' '核心数要求' 'FAIL' ("$cores 核，低于最低 4 核") '换用核心更多的机器'
}

# AVX2 matters because the bundled scientific wheels (numpy/shapely) are built
# against it; without it pip falls back to source builds or older binaries.
$hasAvx2 = $false
try {
    $cpuFeatures = (Get-CimInstance Win32_Processor | Select-Object -First 1).Caption
    # Win32_Processor does not expose AVX2 directly; use the environment as the
    # practical signal and let a missing DLL surface at runtime instead.
    $hasAvx2 = $true
} catch { $hasAvx2 = $true }
Add-Result '处理器' '指令集' 'INFO' 'AVX2 为 numpy/shapely 预编译包的隐含要求' ''

# ---------------------------------------------------------------------------
# 3. 内存
# ---------------------------------------------------------------------------
$totalRamGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

Add-Result '内存' '物理内存总量' 'INFO' ("$totalRamGb GB") ''
Add-Result '内存' '当前可用' 'INFO' ("$freeRamGb GB") ''

if ($totalRamGb -ge 16) {
    Add-Result '内存' '内存要求' 'PASS' ("$totalRamGb GB，满足推荐 16 GB") ''
} elseif ($totalRamGb -ge 8) {
    Add-Result '内存' '内存要求' 'WARN' ("$totalRamGb GB，满足最低 8 GB 但低于推荐 16 GB") '建议为 JVM 显式设置 JAVA_TOOL_OPTIONS=-Xmx1024m，见 README'
} else {
    Add-Result '内存' '内存要求' 'FAIL' ("$totalRamGb GB，低于最低 8 GB") '需要至少 8 GB 物理内存'
}

# The JVM sizes its heap to a quarter of physical RAM when nothing sets -Xmx.
# That is invisible on a 32 GB machine and the difference between working and
# thrashing on an 8 GB one, so it is worth stating explicitly.
$autoHeapGb = [math]::Round($totalRamGb / 4, 1)
if ($env:JAVA_TOOL_OPTIONS -match '-Xmx') {
    Add-Result '内存' 'JVM 堆上限' 'PASS' ("已显式设置：$env:JAVA_TOOL_OPTIONS") ''
} else {
    $msg = "未设置 -Xmx，JVM 将按物理内存的 1/4 自动取值（约 $autoHeapGb GB）"
    if ($totalRamGb -le 8) {
        Add-Result '内存' 'JVM 堆上限' 'WARN' $msg '在启动前设置 JAVA_TOOL_OPTIONS=-Xmx1024m，避免堆占用过多内存'
    } else {
        Add-Result '内存' 'JVM 堆上限' 'INFO' $msg '内存充裕时可保持默认'
    }
}

# ---------------------------------------------------------------------------
# 4. 磁盘
# ---------------------------------------------------------------------------
$drive = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='" + $Root.Substring(0, 2) + "'")
$freeDiskGb = [math]::Round($drive.FreeSpace / 1GB, 1)
$totalDiskGb = [math]::Round($drive.Size / 1GB, 1)

Add-Result '磁盘' '系统盘' 'INFO' ("$($drive.DeviceID) 共 $totalDiskGb GB，可用 $freeDiskGb GB") ''

if ($freeDiskGb -ge 20) {
    Add-Result '磁盘' '可用空间' 'PASS' ("$freeDiskGb GB，满足推荐 20 GB") ''
} elseif ($freeDiskGb -ge 8) {
    Add-Result '磁盘' '可用空间' 'WARN' ("$freeDiskGb GB，低于推荐 20 GB") '构建产物与运行缓存需要数 GB；建议清理磁盘'
} else {
    Add-Result '磁盘' '可用空间' 'FAIL' ("$freeDiskGb GB，低于最低 8 GB") '至少释放 8 GB 空间'
}

# Measure the directories that actually grow, rather than guessing. A missing
# directory is not a fault -- a fresh clone has none of them yet.
function Get-DirectorySizeMb {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($null -eq $sum) { return 0.0 }
        return [math]::Round($sum / 1MB, 1)
    } catch { return $null }
}

$sizeTargets = [ordered]@{
    'Python 依赖 (backend-python\.venv)' = Join-Path $Root 'backend-python\.venv'
    '前端依赖 (frontend\node_modules)' = Join-Path $Root 'frontend\node_modules'
    'Java 构建 (backend-java\target)' = Join-Path $Root 'backend-java\target'
    '运行缓存 (.run)' = Join-Path $Root '.run'
}
foreach ($label in $sizeTargets.Keys) {
    $mb = Get-DirectorySizeMb $sizeTargets[$label]
    if ($null -eq $mb) {
        Add-Result '磁盘' $label 'INFO' '尚未生成' ''
    } else {
        Add-Result '磁盘' $label 'INFO' ("$mb MB") ''
    }
}

# ---------------------------------------------------------------------------
# 5. Python
# ---------------------------------------------------------------------------
$venvPython = Join-Path $Root 'backend-python\.venv\Scripts\python.exe'
$venvUsable = $false
if (Test-Path -LiteralPath $venvPython) {
    Add-Result 'Python' '虚拟环境' 'PASS' 'backend-python\.venv\Scripts\python.exe 存在' ''
    try {
        $ver = & $venvPython -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>&1
        $verText = ($ver | Out-String).Trim()
        # Compare numerically against $MinPython instead of enumerating accepted
        # minors: the old pattern was ^3\.(1[123])\. , which passed 3.11 even
        # though the locked numpy cannot install there.
        $venvVer = Get-PythonVersion $verText
        if ($venvVer -and $venvVer -ge $MinPython -and $venvVer.Major -eq 3) {
            Add-Result 'Python' '虚拟环境版本' 'PASS' $verText ''
            $venvUsable = $true
        } elseif ($venvVer -and $venvVer.Major -eq 3) {
            Add-Result 'Python' '虚拟环境版本' 'FAIL' ("$verText 低于最低要求 $MinPython") ('删除 .venv 后用 Python 3.13 重建：python -m venv backend-python\.venv')
        } else {
            Add-Result 'Python' '虚拟环境版本' 'FAIL' ("$verText 不是 Python 3") '删除 .venv 后用 Python 3.13 重建'
        }
    } catch {
        Add-Result 'Python' '虚拟环境版本' 'FAIL' '无法执行该解释器' '删除 .venv 后重建：python -m venv backend-python\.venv'
    }
    # The dependencies are what actually matter, so import them rather than
    # trusting that the directory exists.
    $probe = @'
mods = ['fastapi','uvicorn','httpx','yaml','shapely','numpy','pydantic']
missing = []
for name in mods:
    try:
        __import__(name)
    except Exception:
        missing.append(name)
print('OK' if not missing else 'MISSING:' + ','.join(missing))
'@
    try {
        $out = ($probe | & $venvPython - 2>&1 | Out-String).Trim()
        if ($out -eq 'OK') {
            Add-Result 'Python' '关键依赖' 'PASS' 'fastapi / uvicorn / httpx / shapely / numpy 均可导入' ''
        } else {
            Add-Result 'Python' '关键依赖' 'FAIL' $out ('在 backend-python 目录执行：.venv\Scripts\pip install -r requirements-lock.txt')
        }
    } catch {
        Add-Result 'Python' '关键依赖' 'FAIL' '依赖探测失败' '重新安装依赖'
    }
} else {
    Add-Result 'Python' '虚拟环境' 'FAIL' '未找到 backend-python\.venv' ('重建：cd backend-python; python -m venv .venv; .venv\Scripts\pip install -r requirements-lock.txt')
}

# A system Python is what BUILDS the venv, so its version decides whether a
# missing/doomed venv can be rebuilt at all. Reported as a hard verdict rather
# than a bare INFO: on the handover machine this was Python 3.10.11 and the
# report gave no hint that `python -m venv .venv` was going to be a dead end.
foreach ($candidate in @('python', 'python3', 'py')) {
    if (Test-CommandPresent $candidate) {
        try {
            $sysVer = (& $candidate --version 2>&1 | Out-String).Trim()
            $sysPy = Get-PythonVersion $sysVer
            if ($sysPy -and $sysPy.Major -eq 3 -and $sysPy -ge $MinPython) {
                Add-Result 'Python' "系统解释器 ($candidate)" 'PASS' ("$sysVer（满足 ≥$MinPython）") ''
            } elseif ($sysPy -and $sysPy.Major -eq 3) {
                if ($venvUsable) {
                    # The existing venv still runs the system, so this is not a
                    # startup blocker -- only a rebuild blocker. Downgrading it
                    # to WARN avoids a false FAILURE on a machine that works.
                    Add-Result 'Python' "系统解释器 ($candidate)" 'WARN' ("$sysVer 低于 $MinPython；当前 .venv 可用，但重建虚拟环境时会失败") "安装 Python 3.13 后重跑本自检"
                } else {
                    Add-Result 'Python' "系统解释器 ($candidate)" 'FAIL' ("$sysVer 低于最低要求 $MinPython；无法用它建出可用的虚拟环境") '安装 Python 3.13（勾选 Add python.exe to PATH）后重跑本自检'
                }
            } else {
                Add-Result 'Python' "系统解释器 ($candidate)" 'WARN' $sysVer ''
            }
        } catch {
            Add-Result 'Python' "系统解释器 ($candidate)" 'INFO' '无法获取版本' ''
        }
        break
    }
}

# ---------------------------------------------------------------------------
# 6. Node.js
# ---------------------------------------------------------------------------
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVer = (& node --version 2>&1 | Out-String).Trim()
    $nodePath = $node.Source
    $major = 0
    if ($nodeVer -match '^v(\d+)\.') { $major = [int]$Matches[1] }
    Add-Result 'Node.js' '版本' 'INFO' ("$nodeVer  ($nodePath)") ''
    # Vite 8.3.0 declares engines.node = "^20.19.0 || >=22.12.0" -- read from
    # frontend/node_modules/vite/package.json. A plain "-ge 20" test (what this
    # used to be) PASSes Node 20.0-20.18 and Node 21, all of which Vite rejects,
    # so the line below now matches the requirement the message states.
    $nodeOk = $false
    if ($nodeVer -match '^v(\d+)\.(\d+)\.') {
        $nmaj = [int]$Matches[1]; $nmin = [int]$Matches[2]
        $nodeOk = (($nmaj -eq 20 -and $nmin -ge 19) -or
                   ($nmaj -eq 22 -and $nmin -ge 12) -or
                   ($nmaj -gt 22))
    }
    if ($nodeOk) {
        Add-Result 'Node.js' '版本要求' 'PASS' ("$nodeVer，满足 Vite 8 所需的 Node 20.19+ / 22.12+") ''
    } elseif ($major -ge 18) {
        Add-Result 'Node.js' '版本要求' 'FAIL' ("$nodeVer 不满足 Vite 8 的要求（^20.19.0 || >=22.12.0）") '安装 Node.js 22 LTS'
    } else {
        Add-Result 'Node.js' '版本要求' 'FAIL' ("v$major 过低") '安装 Node.js 22 LTS'
    }
    if (Test-CommandPresent 'npm') {
        $npmVer = (& npm --version 2>&1 | Out-String).Trim()
        Add-Result 'Node.js' 'npm' 'PASS' "npm $npmVer" ''
    } else {
        Add-Result 'Node.js' 'npm' 'FAIL' '未找到 npm' '随 Node.js 一起安装，或修复 PATH'
    }
} else {
    Add-Result 'Node.js' '版本' 'FAIL' '未找到 node' '安装 Node.js 22 LTS 并加入 PATH'
}

$nodeModules = Join-Path $Root 'frontend\node_modules'
if (Test-Path -LiteralPath $nodeModules) {
    Add-Result 'Node.js' '前端依赖' 'PASS' 'frontend\node_modules 存在' ''
} else {
    Add-Result 'Node.js' '前端依赖' 'WARN' 'frontend\node_modules 不存在' '在 frontend 目录执行 npm install'
}

# ---------------------------------------------------------------------------
# 7. Java
#
# This section must answer the SAME question the launcher actually asks. When
# it does not, it produces a FALSE FAILURE: the report says the machine cannot
# run the system while double-clicking start.bat works fine. A self-check that
# fails a working machine trains the operator to ignore it, which is worse than
# having no report at all.
#
# The real entry point is start.bat -> scripts/dev.ps1 (SOURCE mode: compile,
# then run from the classpath). dev.ps1 resolves the JDK itself, with a
# different candidate list and a different requirement than start.ps1:
#
#     1. $env:JAVA_HOME
#     2. %USERPROFILE%\.jdks\ms-17.0.19        (hard-coded first choice)
#     3. %USERPROFILE%\.jdks\*                 (remaining directories)
#
# and for each candidate it demands BOTH:
#     - a `release` file whose JAVA_VERSION major is 17 or 21, and
#     - bin\javac.exe to exist (source mode compiles; a JRE is not enough).
#
# start.ps1 (RELEASE mode: runs target\tianchuang-server-<version>.jar) does
# not need javac, and keeps scanning Program Files and PATH as well. Both paths
# are reported, because the delivered artifact may be source or a built jar.
#
# An earlier version of this file probed only `java -version`, while the
# launcher reads the JDK's own `release` file -- start.ps1 says so explicitly:
# java -version writes to stderr and is not always capturable, so it must not be
# the only evidence. Probing and launching then disagreed, which is exactly how
# a false FAILURE is born. The reader below is copied from the launcher rather
# than invented here.
# ---------------------------------------------------------------------------

# Reads a Java banner. Deliberately identical to
# scripts/start.ps1::Get-JavaVersionText -- three tiers, in this order:
#   1) the JDK's own `release` file (plain file read; no stderr, no code page)
#   2) `java -version` redirected to a temp file, then read back
#   3) infer from the install path (jdk-17, ms-17.0.19, ...)
# Tier 1 is why the two scripts agree on machines where tier 2 yields nothing.
function Get-JavaVersionText {
    param([Parameter(Mandatory)][string]$ExePath)
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

# Reads the JAVA_VERSION major from a JDK home, or -1 when it cannot be read.
# Mirrors dev.ps1's own check, which reads the same file the same way.
function Get-ReleaseMajor {
    param([Parameter(Mandatory)][string]$JavaHome)
    $releaseFile = Join-Path $JavaHome 'release'
    if (-not (Test-Path -LiteralPath $releaseFile)) { return -1 }
    try {
        $match = [regex]::Match((Get-Content -LiteralPath $releaseFile -Raw), '(?m)^JAVA_VERSION="(\d+)')
        if ($match.Success) { return [int]$match.Groups[1].Value }
    } catch { }
    return -1
}

# Returns JDK home directories in the exact order scripts/dev.ps1 tries them.
# dev.ps1 is the entry point start.bat uses, so this list -- not start.ps1's --
# decides whether the system actually starts.
function Get-DevJavaCandidates {
    $list = New-Object System.Collections.Generic.List[string]
    if ($env:JAVA_HOME) { $list.Add($env:JAVA_HOME) }

    $jdks = Join-Path $env:USERPROFILE '.jdks'
    $preferred = Join-Path $jdks 'ms-17.0.19'
    if (Test-Path -LiteralPath $preferred) { $list.Add($preferred) }
    if (Test-Path -LiteralPath $jdks) {
        Get-ChildItem -LiteralPath $jdks -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { $list.Add($_.FullName) }
    }
    return $list
}

# Returns java.exe paths in the exact order scripts/start.ps1::Resolve-JavaExe
# tries them. Used only to report what the release-mode launcher would select.
function Get-ReleaseJavaCandidates {
    $list = New-Object System.Collections.Generic.List[string]
    if ($env:JAVA_HOME) { $list.Add((Join-Path $env:JAVA_HOME 'bin\java.exe')) }

    $jdks = Join-Path $env:USERPROFILE '.jdks'
    if (Test-Path -LiteralPath $jdks) {
        Get-ChildItem -LiteralPath $jdks -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(17|21)' } |
            Sort-Object Name -Descending |
            ForEach-Object { $list.Add((Join-Path $_.FullName 'bin\java.exe')) }
    }

    $list.Add('C:\Program Files\Java\jdk-17\bin\java.exe')
    Get-ChildItem -Path 'C:\Program Files\Eclipse Adoptium\jdk-17*' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $list.Add((Join-Path $_.FullName 'bin\java.exe')) }

    $pathJava = (Get-Command java.exe -ErrorAction SilentlyContinue).Source
    if ($pathJava) { $list.Add($pathJava) }
    return $list
}

$javaHome = $env:JAVA_HOME
$homeJavaExe = if ($javaHome) { Join-Path $javaHome 'bin\java.exe' } else { '' }
$homeOk = [bool]($homeJavaExe -and (Test-Path -LiteralPath $homeJavaExe))

if ($javaHome -and $homeOk) {
    Add-Result 'Java' 'JAVA_HOME' 'PASS' $javaHome ''
} elseif ($javaHome) {
    Add-Result 'Java' 'JAVA_HOME' 'WARN' "已设置但目录下没有 bin\java.exe：$javaHome" 'JAVA_HOME 指错了，请指向 JDK 根目录'
} else {
    Add-Result 'Java' 'JAVA_HOME' 'WARN' '未设置，启动脚本会依次扫描 ~\.jdks 与常见安装路径' '建议显式设置 JAVA_HOME，启动脚本会优先读取它'
}

# Walk dev.ps1's own candidate list and apply dev.ps1's own requirement: a
# readable `release` major of 17/21 AND bin\javac.exe present. This is the
# question that decides whether double-clicking start.bat works.
$devJdk = $null
$devScan = New-Object System.Collections.Generic.List[string]
# NOTE: do not name this loop variable $home -- $HOME is a read-only automatic
# variable in PowerShell and assigning to it aborts the whole script.
foreach ($jdkHome in (Get-DevJavaCandidates)) {
    if (-not $jdkHome) { continue }
    $hasJavac = Test-Path -LiteralPath (Join-Path $jdkHome 'bin\javac.exe')
    $major = Get-ReleaseMajor -JavaHome $jdkHome
    $note = if ($major -ge 0) { "主版本 $major" } else { '无 release 或无法读取' }
    if (-not $hasJavac) { $note += '，无 javac' }
    $devScan.Add("$jdkHome（$note）")
    if ($hasJavac -and ($major -eq 17 -or $major -eq 21)) { $devJdk = $jdkHome; break }
}

# Release mode: what start.ps1 would select for an already-built jar. Reported
# separately because the delivered artifact may be source or a packaged jar,
# and the two launchers do not accept the same machines.
$releasePick = $null
foreach ($exePath in (Get-ReleaseJavaCandidates)) {
    if (-not $exePath -or -not (Test-Path -LiteralPath $exePath)) { continue }
    if ((Get-JavaVersionText -ExePath $exePath) -match 'version "?(17|21)') { $releasePick = $exePath; break }
}

if ($devJdk) {
    $viaHome = [bool]($javaHome -and ($devJdk.TrimEnd('\') -ieq $javaHome.TrimEnd('\')))
    $devDetail = '主版本 ' + (Get-ReleaseMajor -JavaHome $devJdk) + '，含 javac：' + $devJdk
    if ($viaHome) {
        Add-Result 'Java' '源码模式 JDK' 'PASS' $devDetail ''
    } else {
        # It starts, so this must not be a FAIL -- but JAVA_HOME still points
        # somewhere dev.ps1 will not use, and every other tool (IDEA, mvn,
        # Gradle) reads JAVA_HOME and will disagree with the launcher.
        $warnFix = '当前 JAVA_HOME=' + $javaHome + ' 不被 dev.ps1 采用（需含 javac 的 17/21）；' +
                   '它会回退到 ' + $devJdk + '，系统可以启动。' +
                   '若希望 IDEA、mvn 等其他工具一致，请把 JAVA_HOME 改到该路径。'
        Add-Result 'Java' '源码模式 JDK' 'WARN' $devDetail $warnFix
    }
} else {
    $detail = 'start.bat（源码模式）找不到可用的 JDK 17/21'
    if ($devScan.Count -gt 0) { $detail += '；已试：' + ($devScan -join '；') }
    else { $detail += '；JAVA_HOME 未设置，%USERPROFILE%\.jdks 下也没有 JDK' }
    $fix = '安装 JDK 17 或 21（必须含 javac：源码模式要先编译）并设置 JAVA_HOME'
    if ($releasePick) {
        $fix = '本机已有可用 JDK：' + $releasePick + '，但 dev.ps1 的候选顺序扫不到它；请把 JAVA_HOME 指向它的上一级目录'
    }
    Add-Result 'Java' '源码模式 JDK' 'FAIL' $detail $fix
}

if ($releasePick) {
    Add-Result 'Java' '发布包模式选用' 'INFO' $releasePick ''
} else {
    Add-Result 'Java' '发布包模式选用' 'INFO' '未找到 JDK 17/21（start.ps1 无法启动已构建的发布包）' ''
}

# The Maven wrapper is committed, so Maven itself need not be installed -- but
# the wrapper must exist or the Java build cannot start.
$mvnw = Join-Path $Root 'backend-java\mvnw.cmd'
if (Test-Path -LiteralPath $mvnw) {
    Add-Result 'Java' 'Maven Wrapper' 'PASS' 'backend-java\mvnw.cmd 存在（无需单独安装 Maven）' ''
    # mvnw resolves its POM relative to the *working directory*, so it must be
    # invoked from backend-java/. Getting this wrong reports "no POM in this
    # directory" and looks like a broken project rather than a wrong cwd.
    Add-Result 'Java' 'Maven Wrapper 用法' 'INFO' '必须在 backend-java 目录下执行：cd backend-java; .\mvnw.cmd' ''
} else {
    Add-Result 'Java' 'Maven Wrapper' 'FAIL' '未找到 backend-java\mvnw.cmd' '从仓库恢复该文件，或安装 Maven 后直接使用 mvn'
}

# ---------------------------------------------------------------------------
# 7b. 可启动性（把项目交给别人时的第一问）
#
# 前面各节回答「这一项达不达标」；这一节把它们合成交付时才关心的问题：
# 接手方双击哪一个 .bat 能真的起界面。两条路径互不替代，必须分开判：
#
#   源码模式    start.bat -> scripts/dev.ps1
#               需要 .venv + node_modules + 含 javac 的 JDK 17/21 + mvnw.cmd；
#               用当前源码编译，不需要现成的 jar。这是 start.bat 的实际行为。
#   发布包模式  scripts/start.ps1
#               需要 .venv + 一个已构建的 jar（build.bat 产出）。
#
# 这里只出 PASS / WARN / INFO，不出 FAIL —— 缺件说明「产物没准备好」，不是
# 机器不达标，退出码仍由前面各节的硬要求决定。把它报成 FAIL 会把「先跑一次
# npm ci」变成一份红色报告，那是另一种形式的假失败。
# ---------------------------------------------------------------------------
$venvOk = Test-Path -LiteralPath $venvPython
$nodeModulesOk = Test-Path -LiteralPath $nodeModules
$mvnwOk = Test-Path -LiteralPath (Join-Path $Root 'backend-java\mvnw.cmd')
$javacOk = [bool]$devJdk

# start.ps1 derives the jar name from VERSION, so this check must use the same
# name rather than a wildcard: a stale jar from another version must not count
# as "ready to run".
$jarPath = ''
if ($projectVersion) { $jarPath = Join-Path $Root ('backend-java\target\tianchuang-server-' + $projectVersion + '.jar') }
$jarOk = [bool]($jarPath -and (Test-Path -LiteralPath $jarPath))
$distOk = Test-Path -LiteralPath (Join-Path $Root 'frontend\dist\index.html')

$sourceMissing = New-Object System.Collections.Generic.List[string]
if (-not $venvOk) { $sourceMissing.Add('Python 虚拟环境 backend-python\.venv') }
if (-not $nodeModulesOk) { $sourceMissing.Add('前端依赖 frontend\node_modules') }
if (-not $javacOk) { $sourceMissing.Add('含 javac 的 JDK 17/21') }
if (-not $mvnwOk) { $sourceMissing.Add('backend-java\mvnw.cmd') }

if ($sourceMissing.Count -eq 0) {
    Add-Result '可启动性' '源码模式（start.bat）' 'PASS' '依赖齐全，双击 start.bat 即可启动' ''
} else {
    $detail = '缺少：' + ($sourceMissing -join '；')
    Add-Result '可启动性' '源码模式（start.bat）' 'WARN' $detail '按 README「新机器首次安装」补齐后重跑自检'
}

if ($jarOk) {
    Add-Result '可启动性' '发布包模式（start.ps1）' 'PASS' ('已构建：' + $jarPath) ''
} else {
    Add-Result '可启动性' '发布包模式（start.ps1）' 'WARN' ('未找到与 VERSION 匹配的 jar：' + $(if ($jarPath) { $jarPath } else { '（VERSION 未读到）' })) '需要发布包时运行 build.bat；只跑源码模式可忽略本项'
}

if ($distOk) {
    Add-Result '可启动性' '前端产物（frontend\dist）' 'INFO' '存在，dev.ps1 会把它同步给 8085' ''
} else {
    Add-Result '可启动性' '前端产物（frontend\dist）' 'INFO' '不存在，界面由 vite 的 5180 提供（源码模式正常）' ''
}

# ---------------------------------------------------------------------------
# 8. 端口可用性
# ---------------------------------------------------------------------------
# An array of pairs, not an ordered dictionary: `[ordered]@{ 5180 = 'x' }` keys
# become *strings* under some PowerShell 5.1 paths, so `$ports[$port]` with an
# integer silently returns $null and the label disappears from every row.
$ports = @(
    @{ Port = 5180; Service = '前端 (Vite)' },
    @{ Port = 8085; Service = 'Java 主服务 (Spring Boot)' },
    @{ Port = 8600; Service = 'Python 智能服务 (FastAPI)' }
)
foreach ($entry in $ports) {
    $port = [int]$entry.Port
    $label = $entry.Service
    $listening = $null
    try {
        $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } catch {
        # Get-NetTCPConnection needs the NetTCPIP module; absence is not a fault.
        $listening = $null
    }
    if ($listening) {
        $owners = @($listening | Select-Object -ExpandProperty OwningProcess -Unique)
        $names = @()
        foreach ($ownerPid in $owners) {
            $p = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($p) { $names += ("$($p.ProcessName) (PID $ownerPid)") }
        }
        $who = if ($names.Count) { $names -join ', ' } else { '未知进程' }
        Add-Result '端口' "$port — $label" 'INFO' ("已被占用：$who") '若为本项目服务在运行则正常；否则先运行 stop.bat'
    } else {
        Add-Result '端口' "$port — $label" 'PASS' '空闲' ''
    }
}

# ---------------------------------------------------------------------------
# 9. 配置文件
# ---------------------------------------------------------------------------
$configFile = Join-Path $Root 'config\application.yml'
if (Test-Path -LiteralPath $configFile) {
    $configBytes = (Get-Item -LiteralPath $configFile).Length
    Add-Result '配置' 'config\application.yml' 'PASS' ("存在，$configBytes 字节") ''
} else {
    Add-Result '配置' 'config\application.yml' 'WARN' '不存在' '从 config\application.example.yml 复制一份；缺失时部分密钥功能会降级'
}

# DeepSeek is optional: the agent falls back to the rule baseline without it, so
# a missing key is INFO, never FAIL.
$dsKeyPresent = $false
if (Test-Path -LiteralPath $configFile) {
    try {
        $content = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8
        if ($content -match 'api-key\s*:\s*\S+' -and $content -notmatch 'api-key\s*:\s*($|""|''''|\s*#)') {
            $dsKeyPresent = $true
        }
    } catch { $dsKeyPresent = $false }
}
if ($dsKeyPresent) {
    Add-Result '配置' 'DeepSeek 密钥' 'PASS' '已配置' ''
} else {
    Add-Result '配置' 'DeepSeek 密钥' 'INFO' '未配置（可选）' '不配置时轨2 研判自动降级为规则基线，不影响系统启动'
}

# ---------------------------------------------------------------------------
# 10. 外网依赖
#
# The running system reaches these hosts. The «必需性» column would only
# describe how complete the features stay -- nothing here prevents the services
# from starting, so this section never produces a FAIL.
#
# The QWeather host is NOT hard-coded: it is read from config/application.yml
# (`qweather.api-host`). The console can hand out a different host name, and a
# self-check that kept probing a retired domain would report a healthy machine
# as broken. Asking the configuration is the only way to stay in step with it.
# ---------------------------------------------------------------------------
function Get-ConfigField {
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [Parameter(Mandatory)][string]$Section,
        [Parameter(Mandatory)][string]$Key
    )
    foreach ($candidate in @((Join-Path $RootPath 'config\application.yml'), (Join-Path $RootPath 'config\application.example.yml'))) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $inSection = $false
        try {
            # -Encoding UTF8 matters: application.yml is UTF-8 and PowerShell
            # 5.1 defaults to ANSI, which turns the trailing Chinese comments
            # into mojibake and drags them into the value being matched.
            foreach ($line in (Get-Content -LiteralPath $candidate -Encoding UTF8)) {
                if ($line -match '^([A-Za-z0-9_.-]+):') { $inSection = ($Matches[1] -eq $Section); continue }
                if ($inSection -and $line -match ('^\s+' + [regex]::Escape($Key) + ':\s*(.+)$')) {
                    # YAML here is written as `api-host: "host"  # 已配置`; the
                    # comment is not part of the value, and the quotes are
                    # optional, so strip both before returning.
                    $value = ($Matches[1] -split '#')[0].Trim().Trim('"').Trim("'")
                    if ($value) { return $value }
                }
            }
        } catch { }
    }
    return ''
}

$qweatherHost = Get-ConfigField -RootPath $Root -Section 'qweather' -Key 'api-host'
$deepseekHost = ''
$deepseekBase = Get-ConfigField -RootPath $Root -Section 'deepseek' -Key 'base-url'
if ($deepseekBase -match '^https?://([^/:]+)') { $deepseekHost = $Matches[1] }

$probeTargets = New-Object System.Collections.Generic.List[object]
$probeTargets.Add([pscustomobject]@{
    Host = 'tiles.openfreemap.org'; Use = '城市矢量底图（瓦片 / 字体 / sprite）'
    Impact = '自动降级为内置离线底图（仅省界轮廓，无道路、无建筑、无注记）' })
$probeTargets.Add([pscustomobject]@{
    Host = 'api.open-meteo.com'; Use = '公开气象数据（模型估算）'
    Impact = '气象模块如实报不可用；它同时是和风失败后的兜底源' })
$probeTargets.Add([pscustomobject]@{
    Host = 'image.data.cma.cn'; Use = '中国气象数据网公开雷达瓦片（免凭据）'
    Impact = '雷达图层不可用，其余功能不受影响' })
if ($qweatherHost) {
    $probeTargets.Add([pscustomobject]@{
        Host = $qweatherHost; Use = '和风天气（Java 首选气象源，JWT）'
        Impact = '自动降级到公开气象源，并把本轮标记为 degraded' })
} else {
    Add-Result '外网' '和风天气主机' 'INFO' 'config 未配置 qweather.api-host' '未配置时 Java 直接使用公开气象源，不产生该路出网'
}
if ($dsKeyPresent -and $deepseekHost) {
    $probeTargets.Add([pscustomobject]@{
        Host = $deepseekHost; Use = 'DeepSeek 智能研判'
        Impact = '轨2 降级为本地规则基线，不影响调度与安全判定' })
} elseif ($dsKeyPresent) {
    Add-Result '外网' 'DeepSeek 主机' 'INFO' '已配置 Key 但 base-url 无法解析' '检查 config\application.yml 的 deepseek.base-url'
}

if ($SkipNetwork) {
    Add-Result '外网' '连通性' 'INFO' '已按参数跳过' '如需检查，去掉 -SkipNetwork 重新运行'
} else {
    foreach ($target in $probeTargets) {
        $hostName = $target.Host
        $ok = $false
        try {
            $ok = [bool](Test-NetConnection -ComputerName $hostName -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue)
        } catch {
            # Test-NetConnection is absent on some minimal installs; dip the socket.
            try {
                $client = New-Object System.Net.Sockets.TcpClient
                $async = $client.BeginConnect($hostName, 443, $null, $null)
                $ok = $async.AsyncWaitHandle.WaitOne(3000, $false)
                $client.Close()
            } catch { $ok = $false }
        }
        $label = "$hostName — $($target.Use)"
        if ($ok) {
            Add-Result '外网' $label 'PASS' '443 可达' ''
        } else {
            # A blocked host degrades one feature; it never stops the services,
            # so this stays a WARN and never changes the exit code.
            Add-Result '外网' $label 'WARN' '443 不可达' ('降级：' + $target.Impact)
        }
    }
}

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
$failCount = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$warnCount = @($script:Results | Where-Object { $_.Status -eq 'WARN' }).Count
$passCount = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count

if (-not $Quiet) {
    $currentArea = ''
    foreach ($row in $script:Results) {
        if ($row.Area -ne $currentArea) {
            $currentArea = $row.Area
            Write-Host ''
            Write-Host ('--- ' + $currentArea + ' ' + ('-' * [math]::Max(2, 56 - $currentArea.Length)))
        }
        $mark = switch ($row.Status) {
            'PASS' { '[通过]' }
            'WARN' { '[注意]' }
            'FAIL' { '[失败]' }
            default { '[信息]' }
        }
        Write-Host ('  {0} {1}：{2}' -f $mark, $row.Item, $row.Detail)
        if ($row.Fix) { Write-Host ('         -> ' + $row.Fix) }
    }

    Write-Host ''
    Write-Host '============================================================'
    Write-Host ('  通过 {0} 项 / 注意 {1} 项 / 失败 {2} 项' -f $passCount, $warnCount, $failCount)
    Write-Host '------------------------------------------------------------'
    if ($failCount -gt 0) {
        Write-Host '  结论：本机尚不满足运行要求，请先按上方 [失败] 项处理。'
        Write-Host '  提示：WARN 不影响运行，仅代表低于推荐配置。'
    } elseif ($warnCount -gt 0) {
        Write-Host '  结论：本机可以运行，但有低于推荐配置的项目（[注意]）。'
    } else {
        Write-Host '  结论：本机完全满足运行要求。'
    }
    Write-Host '  详细要求见 README.md 的「电脑与环境要求」一节。'
    Write-Host '============================================================'
    Write-Host ''
}

if ($Json) {
    try {
        $payload = [pscustomobject]@{
            generatedAt = (Get-Date).ToString('o')
            projectVersion = $projectVersion
            machine = [pscustomobject]@{
                os = $osCaption; build = $osBuild; arch = $arch
                cpu = $cpuName; cores = $cores; threads = $threads
                memoryGb = $totalRamGb; freeDiskGb = $freeDiskGb
            }
            summary = [pscustomobject]@{ pass = $passCount; warn = $warnCount; fail = $failCount }
            results = $script:Results
        }
        $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Json -Encoding UTF8
        if (-not $Quiet) { Write-Host ('已写入自检报告：' + $Json) }
    } catch {
        Write-Host ('写入自检报告失败：' + $_.Exception.Message)
    }
}

if ($failCount -gt 0) { exit 1 }
exit 0
