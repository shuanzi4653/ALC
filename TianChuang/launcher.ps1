[CmdletBinding()]
param(
    # 交给哪个浏览器打开。'auto' = 优先找一个能强制隐私窗口的浏览器
    # （edge -> chrome -> firefox），找不到才退回系统默认浏览器。
    [ValidateSet('auto', 'edge', 'chrome', 'firefox', 'default')]
    [string]$Browser = 'auto',

    # 窗口模式。默认 'normal'（不带隐私开关）。
    # ⚠️ 2026-10-14 起**默认由 private 改成 normal**，起因是一次真实冲突：
    #    本站已无登录门，身份改成「工作区编号」，存在浏览器的 Cookie + localStorage 里；
    #    而隐私窗口**关闭时就把这些存储丢掉**，于是每次用启动器打开都会拿到一个
    #    全新的空工作区 —— 用户会以为自己之前的数据"没了"。隐私窗口的旧理由
    #    （口令不许在别人机器上被保存）已随登录门一起消失，它现在只剩这个坏处。
    # 'private' 仍可显式指定：想在这台机器上"不留痕"地看一眼时用。
    [ValidateSet('private', 'normal')]
    [string]$Profile = 'normal',

    # 只探测并打印结论，不打开浏览器、不改任何状态。供自检使用。
    [switch]$ProbeOnly,

    # 在本机桌面创建一个指向本包的快捷方式，然后退出。不改注册表、不设开机启动。
    [switch]$CreateDesktopShortcut
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# =============================================================================
#  天窗智巡 · 云端访问启动器
#
#  这个包只做三件事：
#    1. 探测云端站点是否可达（TCP 连接为主判据，并区分「超时」与「被拒绝」）
#    2. 可达就把地址交给浏览器打开
#    3. 结果如实打印；连不上就说明原因和排查方向，不假装成功
#
#  【窗口模式】默认 'normal'。旧版默认 'private' 的唯一理由是「口令不许被保存」；
#  2026-10-14 登录门删除后这条理由不存在了，而且隐私窗口**关闭即丢弃**
#  Cookie / localStorage，会与工作区编号机制直接冲突（每次打开都变成新的空工作区）。
#  想不留痕地看一眼时，仍可显式传 -Profile private。
#
#  它【不】读取本机项目文件、【不】启动本地服务、【不】做本地构建、
#  【不】改注册表、【不】写开机启动项。整个文件夹可以整体拷给别人，
#  唯一依赖是「能连到下面这个地址」。脚本内除自身所在目录外不引用任何本机路径。
#
#  目标地址只在 $SiteHost / $SitePort 定义一次，别在别处硬编码。
#
#  本文件含中文，必须保存为 UTF-8 带 BOM；否则 Windows PowerShell 5.1 会按
#  ANSI 解码，中文全变乱码。不要在这里写 chcp：让控制台用自己的默认代码页即可。
# =============================================================================

$PackageStamp = '2026-10-14'

# ⚠️ 2026-10-14 两处换代：
#    ① 入口从「IP + 端口」改成「域名 + 443」。旧写法
#       `http://62.234.154.34:28081/` **必须弃用**：28081 已收回回环，公网在
#       控制台里也没有它的放行规则 ⇒ 打它只会超时；而且那个地址上没有 TLS。
#    ② 同日起**取消登录页**：不再有账号和口令。改为在你的浏览器本地生成一个
#       随机的「工作区编号」，用它把各人的推演 / 方案 / 通道分开
#       （页面右上角可「重置工作区」）。因此本启动器不再需要隐私窗口。
#    地址只在 $SiteHost / $SitePort 定义一次，别在别处硬编码。
$SiteHost = 'tianchuang.shuanzi.site'
$SitePort = 443
$SiteUrl = 'https://{0}/' -f $SiteHost

# 探测用「根路径」，不能用 /healthz。
# 理由（实测）：nginx 的 `location = /healthz { return 200 ...; }` 跑在 rewrite 阶段，
# 早于 access 阶段，所以 /healthz **永远 200、不通往任何业务**；拿它判断站点状态会
# 恒得出「站点正常」—— 一句写在屏幕上的假话（哪怕整站 302 打转）。
# 根路径 `/` 才是正确判据：**2026-10-14 起本站没有登录门，直接返回 200**。
# ⚠️ 探测必须**不跟随重定向**（见 Get-HttpStatus 的 -MaximumRedirection 0）：
#    万一哪天有人把登录门装回来，第一跳会是 302 → /login；默认会跟着它拿到 /login
#    的 200，于是"登录门又回来了"被读成"站点正常"。状态码判据量到的必须是**第一跳**。
$AuthProbePath = '/'
$AuthProbeOpenStatus = 200
$LivenessPath = '/healthz'

$TcpTimeoutMs = 6000
$TcpAttempts = 3
$TcpGapMs = 2500
$HttpTimeoutSec = 10

# 退出码：0 已打开 / 3 连不上 / 9 脚本自身异常
$EXIT_OK = 0
$EXIT_UNREACHABLE = 3
$EXIT_INTERNAL = 9

function Write-Rule {
    Write-Host '  ------------------------------------------------------------'
}

function Get-LocalIpv4List {
    # 只用于诊断输出，帮助判断「本机走的是哪张网卡」。
    try {
        $rows = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
        $list = @($rows | ForEach-Object { $_.IPAddress })
        if ($list.Count -gt 0) { return ($list -join ', ') }
    } catch { }
    return $null
}

function Test-SiteReachable {
    # 反复尝试若干次，并区分失败类型 —— 这两种失败含义完全相反，必须分开报：
    #   timeout  对方把包丢了（云防火墙没放通 / 来源 IP 不在白名单 / 网络阻断）
    #   refused  机器在、但该端口没人监听（服务没起 / 公网入口没挂上）
    # 只报「连不上」会把这两种混成同一个现象，然后去查错的对象。
    param(
        [int]$Attempts = 3,
        [int]$TimeoutMs = 6000,
        [int]$GapMs = 2500
    )

    if ($Attempts -lt 1) { $Attempts = 1 }
    $last = @{ Ok = $false; Kind = 'timeout'; ElapsedMs = 0; Attempts = 0 }

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        $client = $null
        $kind = 'error'
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $async = $client.BeginConnect($SiteHost, $SitePort, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
                $client.EndConnect($async)     # 被拒绝时会在这里抛 SocketException
                $stopwatch.Stop()
                return @{ Ok = $true; Kind = 'connected'; ElapsedMs = [int]$stopwatch.ElapsedMilliseconds; Attempts = $attempt }
            }
            $kind = 'timeout'
        } catch [System.Net.Sockets.SocketException] {
            switch ($_.Exception.SocketErrorCode.ToString()) {
                'ConnectionRefused' { $kind = 'refused' }
                'HostUnreachable' { $kind = 'noroute' }
                'NetworkUnreachable' { $kind = 'noroute' }
                'TimedOut' { $kind = 'timeout' }
                default { $kind = 'error' }
            }
        } catch {
            $kind = 'error'
        } finally {
            if ($null -ne $client) { $client.Close() }
        }
        $stopwatch.Stop()
        $last = @{ Ok = $false; Kind = $kind; ElapsedMs = [int]$stopwatch.ElapsedMilliseconds; Attempts = $attempt }
        if ($attempt -lt $Attempts) {
            Write-Host ('    第 {0}/{1} 次未通（{2}，{3} ms），{4} ms 后重试 ...' -f $attempt, $Attempts, $kind, $last.ElapsedMs, $GapMs)
            Start-Sleep -Milliseconds $GapMs
        }
    }
    return $last
}

function Get-HttpStatus {
    param([string]$Path, [int]$TimeoutSec = 10)
    # 不带任何凭据请求：本站已无登录门，正常就是 200。绝不使用
    # -UseDefaultCredentials，那会让 PowerShell 拿本机账号去试探并可能弹出系统凭据框。
    # ⚠️ -MaximumRedirection 0 是**必须的**：默认会自动跟随 302 到 /login 并拿到 200，
    #    于是"登录门又被装回来了"被读成"站点正常"。3xx 在 PS 5.1 下会走 catch 分支，
    #    由 $_.Exception.Response.StatusCode 取到真实的第一跳状态码。
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
    try {
        $response = Invoke-WebRequest -Uri ($SiteUrl.TrimEnd('/') + $Path) -UseBasicParsing `
            -MaximumRedirection 0 -TimeoutSec $TimeoutSec
        return [int]$response.StatusCode
    } catch {
        $resp = $_.Exception.Response
        if ($null -ne $resp) {
            try { return [int]$resp.StatusCode } catch { return 0 }
        }
        return 0
    }
}

function Resolve-BrowserExe {
    param([string]$Name)
    $candidates = switch ($Name) {
        'edge' { @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") }
        'chrome' { @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") }
        'firefox' { @("$env:ProgramFiles\Mozilla Firefox\firefox.exe", "${env:ProgramFiles(x86)}\Mozilla Firefox\firefox.exe") }
        default { @() }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $command = Get-Command ($Name + '.exe') -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    return $null
}

function Get-WindowFlag {
    # 隐私窗口的开关每个浏览器写法不同；写错就会被当成另一个参数、静默失效，
    # 所以这里按名字显式列出，不做任何猜测。
    param([string]$Which, [string]$Mode)
    if ($Mode -eq 'private') {
        switch ($Which) {
            'edge' { return '--inprivate' }
            'chrome' { return '--incognito' }
            'firefox' { return '-private-window' }
            default { return $null }
        }
    }
    if ($Which -eq 'firefox') { return '-new-window' }
    return '--new-window'
}

function Start-SiteInBrowser {
    # 返回 @{ Browser; Mode; Enforced } 。Enforced=$false 表示没能强制隐私窗口，
    # 此时调用方必须把"别保存口令"这件事明确说出来，而不是假装已经做到了。
    param([string]$Url, [string]$Which, [string]$Mode)

    # 名义上要隐私窗口时，优先挑一个"能强制隐私窗口"的浏览器；
    # 走系统默认浏览器是没法带隐私开关的（Start-Process 一个 URL 只能这样）。
    $order = if ($Which -eq 'auto') { @('edge', 'chrome', 'firefox') } else { @($Which) }
    $resolved = $null
    foreach ($name in $order) {
        $exe = Resolve-BrowserExe $name
        if ($exe) { $resolved = @{ Name = $name; Exe = $exe }; break }
    }

    if (-not $resolved) {
        Write-Host '  [i] 没有找到 Edge / Chrome / Firefox，改用系统默认浏览器打开。'
        Start-Process $Url
        return @{ Browser = 'default'; Mode = 'normal'; Enforced = $false }
    }

    $flag = Get-WindowFlag -Which $resolved.Name -Mode $Mode
    if ($flag) {
        Start-Process -FilePath $resolved.Exe -ArgumentList @($flag, $Url)
        return @{ Browser = $resolved.Name; Mode = $Mode; Enforced = $true }
    }
    Start-Process -FilePath $resolved.Exe -ArgumentList @($Url)
    return @{ Browser = $resolved.Name; Mode = 'normal'; Enforced = $false }
}

function Copy-UrlToClipboard {
    param([string]$Url)
    try { Set-Clipboard -Value $Url -ErrorAction Stop; return $true } catch { return $false }
}

function New-DesktopShortcut {
    # 指向本文件夹里的启动器；文件夹被移动后这个快捷方式会失效，需要重新创建。
    $bat = Join-Path $PSScriptRoot '启动天窗智巡.bat'
    if (-not (Test-Path -LiteralPath $bat)) {
        Write-Host ('  [X] 没找到同目录下的 启动天窗智巡.bat，无法创建快捷方式。')
        return $null
    }
    $desktop = [Environment]::GetFolderPath('Desktop')
    $link = Join-Path $desktop '天窗智巡.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath = $bat
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
    $shortcut.Description = '打开天窗智巡云端项目'
    $shortcut.Save()
    return $link
}

# ===========================================================================
#  桌面快捷方式模式
# ===========================================================================
if ($CreateDesktopShortcut) {
    Write-Host ''
    $link = New-DesktopShortcut
    if ($link) {
        Write-Host ('  [OK] 已在桌面创建快捷方式： {0}' -f $link)
        Write-Host ''
        Write-Host '  注意：这个快捷方式指向本文件夹里的启动器。'
        Write-Host '        如果以后把本文件夹移动或改名，需要重新运行一次本命令。'
        Write-Host ''
        Write-Host '  现在可以关闭本窗口。'
    }
    Write-Host ''
    if ($link) { exit $EXIT_OK }
    exit $EXIT_UNREACHABLE
}

# ===========================================================================
#  正常启动
# ===========================================================================
Write-Host ''
Write-Host '  ============================================================'
Write-Host '   天窗智巡  ·  云端访问启动器'
Write-Host '  ============================================================'
Write-Host ''
Write-Host ('  目标地址： {0}' -f $SiteUrl)
Write-Host ('  包版本：   {0}' -f $PackageStamp)
Write-Host ''
Write-Host ('  正在连接 {0}:{1} ...' -f $SiteHost, $SitePort)

$reach = Test-SiteReachable -Attempts $TcpAttempts -TimeoutMs $TcpTimeoutMs -GapMs $TcpGapMs

if (-not $reach.Ok) {
    Write-Host ''
    Write-Rule
    Write-Host '  [X] 连不上云端站点'
    Write-Rule
    Write-Host ''
    Write-Host ('  连续 {0} 次都没能与 {1}:{2} 建立连接（{3} ms）。' -f $reach.Attempts, $SiteHost, $SitePort, $reach.ElapsedMs)
    Write-Host '  这【不是】启动器坏了 —— 启动器只负责连接和打开浏览器，'
    Write-Host '  它无法让云端变得可达。下面是按可能性排序的原因：'
    Write-Host ''

    switch ($reach.Kind) {
        'refused' {
            Write-Host '  现象：连接被对方【拒绝】（端口没人监听）。'
            Write-Host ''
            Write-Host '    1) 云端的服务没有启动，或公网入口没挂上。'
            Write-Host '    2) 服务正在重启（等 1 分钟再试一次）。'
        }
        'noroute' {
            Write-Host '  现象：本机到服务器【没有可用路由】。'
            Write-Host ''
            Write-Host '    1) 你所在网络（公司/校园网/公共 WiFi）限制了对外访问。'
            Write-Host '    2) 换个网络（比如手机热点）再试一次即可区分。'
        }
        default {
            Write-Host '  现象：连接【超时】（对方没有回应，包像是被丢掉了）。'
            Write-Host ''
            Write-Host '    1) 这台云服务器当前不可达（停机 / 维护 / 平台侧网络问题）。'
            Write-Host '    2) 你所在的网络限制了对外访问（换手机热点可立刻区分）。'
            Write-Host '    3) 域名解析异常（把这一步的结果截图发给站点提供者）。'
        }
    }

    Write-Host ''
    Write-Host '  注意：本项目公网只开 22 / 80 / 443 三个端口，入口是 443 上的域名。'
    Write-Host '  不要再去「放通」28081 —— 那个端口已收回回环、不再是对外入口，'
    Write-Host '  开它既没用、也会把内网端口重新暴露出去。'
    Write-Host '  查询当前出口 IP：用浏览器搜索「我的IP」，或访问 https://ifconfig.me'
    Write-Host ''
    Write-Host '  如果是别人给你的这个文件夹：请把本窗口整屏截图发给他。'
    $localIpv4 = Get-LocalIpv4List
    if ($localIpv4) {
        Write-Host ''
        Write-Host ('  本机 IPv4： {0}   （发截图时一起附上，便于判断走的是哪张网卡）' -f $localIpv4)
    }
    Write-Host ''
    Write-Host '  地址已复制到剪贴板，你也可以自己粘到浏览器里再试。'
    [void](Copy-UrlToClipboard $SiteUrl)
    Write-Host ''
    exit $EXIT_UNREACHABLE
}

Write-Host ('  [OK] 端口已连通（第 {0} 次尝试，{1} ms）' -f $reach.Attempts, $reach.ElapsedMs)

$authStatus = Get-HttpStatus -Path $AuthProbePath -TimeoutSec $HttpTimeoutSec
$liveStatus = Get-HttpStatus -Path $LivenessPath -TimeoutSec $HttpTimeoutSec

Write-Host ''
Write-Rule
Write-Host '  [OK] 云端可达，正在打开浏览器'
Write-Rule
Write-Host ''

$copied = Copy-UrlToClipboard $SiteUrl

$launch = @{ Browser = 'default'; Mode = 'normal'; Enforced = $false }
if (-not $ProbeOnly) {
    $launch = Start-SiteInBrowser -Url $SiteUrl -Which $Browser -Mode $Profile
    Write-Host ('  已用【{0} / {1} 窗口】打开。' -f $launch.Browser, $launch.Mode)
    if ($copied) { Write-Host '  地址也已复制到剪贴板，方便你粘到别处。' }
    Write-Host ''
} else {
    Write-Host '  （ProbeOnly 模式：不打开浏览器）'
    Write-Host ''
}

if ($authStatus -eq $AuthProbeOpenStatus) {
    Write-Host '  站点正常：无需登录，打开即用。'
    Write-Host ''
    Write-Host '    * 首次打开会在你的浏览器里生成一个随机的【工作区编号】——'
    Write-Host '      它只把你和他人的数据分开，不是账号、不需要输入、也不含任何个人信息。'
    Write-Host '    * 换设备 / 换浏览器 / 清了站点数据，都会得到一个新的工作区，'
    Write-Host '      于是看到的是"空的"—— 这是正常现象，不是你的数据丢了。'
    Write-Host '    * 页面右上角有【重置工作区】：点它等于换一个新工作区'
    Write-Host '      （原工作区的内容不会被删除，只是不再显示）。'
} elseif ($authStatus -eq 301 -or $authStatus -eq 302 -or $authStatus -eq 303 `
        -or $authStatus -eq 307 -or $authStatus -eq 308) {
    Write-Host ('  [!] 探测根路径得到 HTTP {0}（跳转）—— 本站**应当**直接返回 200。' -f $authStatus)
    Write-Host '      如果它跳向 /login：说明登录门又被装回来了（或回滚时带了回来），'
    Write-Host '      而本文件夹的说明还停留在"无需登录"这一版。请把这一行截图发给站点提供者。'
} else {
    Write-Host ('  [i] 探测根路径得到 HTTP {0}（既不是 {1} 也不是跳转）。' -f $authStatus, $AuthProbeOpenStatus)
    Write-Host '      若为 0：多半是证书或 TLS 握手失败（本机时间不对也会这样）。'
    Write-Host '      浏览器已照常打开；如果页面显示异常，请把这一行截图发给站点提供者。'
}

Write-Host ''
Write-Host ('  诊断信息： / -> HTTP {0} ， /healthz -> HTTP {1}' -f $authStatus, $liveStatus)
Write-Host '  页面里的【数据】和【操作】都在云端，与你本机的任何文件无关。'
Write-Host ''

exit $EXIT_OK
