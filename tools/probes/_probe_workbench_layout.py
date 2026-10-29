"""Measure the real rendered geometry of the workbench, and detect overlap.

Why this exists
---------------
场景美化（用户 2026-10-01 第 4 条）改的是背景、边框、阴影，以及面板标题条上的
一个伪元素竖条。**这些都不会让构建失败** —— `vite build` 只做转译，不跑 CSS
布局。一次 `padding-left` 或一个没有让开占位的伪元素，能让右侧窄栏里的文字折到
第二行、或者让标题文字压在别的东西下面，而构建、单元测试、lint 全部照过。

所以美化必须用**独立于被验证对象**的手段核验：在真实浏览器里把元素量出来。
这个探针渲染真实的工作台页面，然后：

  1. 量出主要面板的 bounding box，断言它们互不重叠（同名区域的兄弟不得相交）；
  2. 断言关键控件（运行区域下拉、推演按钮）确实可见且未被剪裁，且**运行区域
     只有一处入口**（2026-10-02 第 6 条起的契约）；
  3. 断言面板标题条里的文字没有与右侧角标相交 —— 伪元素竖条挤掉文字正是这一类。

**2026-10-02 第 6 条的改动同时改了这份判据。** 用户说「区域的选择可能需要优化，
有的地方有重复或者选择过于复杂」，于是运行总览左栏那块 `aside.traffic-cities`
（整个城市列表）被删掉 —— 它与导航栏的下拉是同一件事的两个入口。这份探针原本
有一条第 2 项判据是「'返回全域' 按钮必须存在」，而那个按钮正是被删掉的两个
重复入口之一。**判据跟着设计改，而不是反过来让设计迁就判据**；但也不能就这样
把一条判据删掉 —— 新的契约是「区域控件**恰好一处**」，所以那条判据被换成
"数一数页面上有几个运行区域控件，必须等于 1"。删掉的那条守的是旧结构，
换上来的这条守的是新契约。

判据是"盒子不相交"，不是"看起来还行"。为了让探针有牙齿，它同时跑一次
**负向对照**：把右栏宽度人为压窄到必然重叠，断言检测器能报出来（M29 —— 没有
负向验证的探针等于没有牙齿）。

跑法（**必须先有后端**，探针会把 `/api/*` 转发给它；用哪种前缀由它实测决定）：

  python tools/harness/_start_services.py &        # Java 8085（默认）+ Python 8600
  backend-python/.venv/Scripts/python.exe tools/probes/_probe_workbench_layout.py

  ALC_BACKEND_PORT=8600 可以改成直连 Python（这时探针会自己把 `/api` 剥掉，
  并代答 Python 没有的 `/api/auth/status`）。

退出码：**0** 通过 · **1** 量出来是坏的 · **2** **无法测量**（缺 Edge / 构建产物过期 /
后端不在 / 无法判断前缀）。这三种必须分得开 —— 混在一起会让"没量成"被读成"有问题"。
"""

import asyncio
import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'
# The probe serves the **build output**, not the source tree.
#
# `index.html` references `/src/main.js`, which resolves only under the Vite dev
# server (it rewrites `.vue` imports and bare `vue` specifiers). A plain static
# server hands the browser the raw `main.js`, which then fails to resolve
# `import App from './App.vue'` -- the page loads, `#app` stays empty, and the
# probe would sit forever waiting for panels that can never appear. Serving
# `dist/` removes the bundler from the loop entirely: `vite build` has already
# inlined every module and stylesheet, and the output is what ships anyway, so
# measuring it is also the more honest target.
DIST = FRONTEND / 'dist'

EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
)

PAGE_TIMEOUT_S = 120.0


def find_edge():
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def backend_up(timeout=1.5):
    """Is a service listening on BACKEND_PORT?

    这份探针把 `/api/*` 转发给本地服务，而页面要拿到计划才能自述「计划就绪」。
    服务不在时，页面会永远停在「服务暂不可达，正在自动重连」，探针则在就绪门上
    超时退出、报一句「home never reported 计划就绪」—— **那句报错看起来像版面
    坏了，其实这一次测量根本没发生**。所以要提前问一次"我要量的那个东西在不在"，
    并且把「无法测量」与「量出来是坏的」用**不同的退出码**分开（2 vs 1），
    就像缺 Edge 或缺构建产物那样。
    """
    try:
        with socket.create_connection(('127.0.0.1', BACKEND_PORT), timeout=timeout):
            return True
    except OSError:
        return False


# `'gateway'` = 目标保留 `/api` 前缀（Java 网关，默认端口）；
# `'direct'`  = 目标路由在根路径、要把 `/api` 剥掉（Python 直连，8600）。
# 由 detect_api_mode() 实测决定，**不在代码里写死**（理由见 QuietHandler._api）。
API_MODE = None
# 用来判形态的那条路由：两侧都存在，且两侧的前缀不同。
PROBE_ROUTE = 'traffic/network'


def detect_api_mode():
    """Ask the service which prefix scheme it uses. Returns 'gateway'/'direct'/None.

    写成"问一次"而不是"按端口猜"，是因为端口只是**默认值**（`ALC_BACKEND_PORT`
    可以指向任何一个），而真正决定前缀的是**服务本身**。判据是两条实测都存在的
    路由：Java 网关答 `/api/traffic/network`，Python 直连答 `/traffic/network`。
    两条都不通就返回 None —— 这时探针**不应该去量**（拿到的一定是一屏 404），
    而应该明说"我连不上任何一个后端"。
    """
    import urllib.error
    import urllib.request

    def ok(path):
        url = 'http://127.0.0.1:%d/%s' % (BACKEND_PORT, path)
        try:
            with urllib.request.urlopen(url, timeout=6) as resp:
                return resp.status == 200
        except urllib.error.HTTPError:
            return False
        except Exception:  # noqa: BLE001
            return False

    if ok('api/' + PROBE_ROUTE):
        return 'gateway'
    if ok(PROBE_ROUTE):
        return 'direct'
    return None


# ---------------- 后端世代：这个进程是"磁盘上这份代码"跑出来的吗 ----------------
#
# ISS-0.9.19-04。这份探针一直只检查**前端 dist 的新鲜度**（见 main() 里那段），
# 而**后端进程的世代没有任何检查**。真例：前端重建了、8085 上的服务还是旧的，
# 量到的是一对**混版**（新前端 + 旧后端），**几何照样 PASS**，而面板上那句话
# 来自旧后端根本没发的字段。这个项目已经栽过两次。
#
# 判据用**后端自己的话**，不用文件时间戳去推断：
#   `decision_service.py` 里 `VERSION = (ROOT/'VERSION').read_text().strip()` 是
#   **进程启动时读一次**，所以 `/health` 自述的版本 == "启动那一刻磁盘上的版本"。
#   于是"自述版本 ≠ 当前磁盘版本"**直接等价于**"这个进程比代码旧" —— 这正是
#   "是哪一代"这个问题最直接的答案。
# 文件时间戳只作补充，管的是另一半：改了 .py 而没改 VERSION。
VERSION_FILE = ROOT / 'VERSION'
SERVICES_STATE = ROOT / '.run' / 'processes.json'
BACKEND_SOURCE_ROOT = ROOT / 'backend-python'
# 依赖与缓存不是"代码"。不排掉 `.venv`，装一次包就能让这条判据永远判旧。
SOURCE_EXCLUDE = ('.venv', '__pycache__', 'node_modules', '.git')


def disk_version():
    try:
        return VERSION_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return None


def ask_backend_version():
    """问后端"你是哪一代"。返回 (version, route)；问不到时 version 为 None。

    两种形态问法不同，理由与 QuietHandler._api 那条一样 —— 前缀由实测决定：
      · direct（Python 8600）：根路径 `/health` 就是它自己。
      · gateway（Java 8085）：Python 的 `/health` 会被 Java 的 HealthController
        （`@RequestMapping("/api/health")`）接走，问不到；但 Java 把 Python 的
        `/health` 结果**嵌进了自己的响应**（`DecisionController.version()`：
        `{"version":"1.2.0", ..., "python": <python /health 的 body>}`），
        所以走 `/api/system/version` 再取 `python.version`。
    """
    import urllib.error  # noqa: F401
    import urllib.request

    route = 'health' if API_MODE == 'direct' else 'api/system/version'
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/%s' % (BACKEND_PORT, route),
                                    timeout=8) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except Exception:  # noqa: BLE001
        return None, route
    if API_MODE == 'direct':
        return body.get('version'), route
    return (body.get('python') or {}).get('version'), route


def newest_backend_source():
    """后端源码（`.py`）里最新的那个文件。

    只认 `.py`：`backend-python/` 下同时有运行时**写**的数据文件，把它们算进"源码"
    会让这条判据在服务跑起来之后**永远**判旧 —— 那是另一种"量具骗人"。
    """
    newest = None
    for path in BACKEND_SOURCE_ROOT.rglob('*'):
        if not path.is_file() or path.suffix != '.py':
            continue
        if any(part in SOURCE_EXCLUDE for part in path.parts):
            continue
        if newest is None or path.stat().st_mtime > newest.stat().st_mtime:
            newest = path
    return newest


def listening_pid(port):
    """谁在这个端口上 LISTENING。**参考信息**，不参与判定。

    单独打印是因为"记下来的 pid 不一定是在干活的 pid"。原因不是"服务经一层 shell
    起的"，而是更具体的一件 Windows 事实：**venv 里的 `Scripts/python.exe` 是一个
    launcher 程序**，它启动后会再 exec 一个真正的 `python.exe`（2026-10-03 实测：
    `processes.json` 记的 pythonPid=31984，而 `netstat` 上绑 8600 的是 31484 ——
    两个 pid、一对父子）。记下的那个 pid 因此**永远不是**在服务的那个。

    判据不依赖它，但打印出来能让人一眼看出这件事；判据只依赖后端自己的话
    （见 check_generation）。
    """
    try:
        # 收 bytes 再自己解码：`text=True` 会让 subprocess 在内部线程里用 UTF-8 解
        # 中文 Windows 的 GBK 输出，解码一失败就把 stdout 置成 None（异常发生在
        # reader 线程里，主线程只看到一个 None）—— 量具自己坏了，观感却像被测对象
        # 出了问题。这里显式 errors='replace'：netstat 里我们真正要看的那几列
        # （协议、地址、LISTENING、pid）全是 ASCII。
        raw = subprocess.run(['netstat', '-ano', '-p', 'TCP'],
                             capture_output=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    for line in raw.decode('utf-8', errors='replace').splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == 'LISTENING' and parts[1].endswith(':%d' % port):
            return parts[4]
    return None


def check_generation():
    """这个后端是不是磁盘上这份代码跑出来的？返回 'ok' / 'stale' / 'unknown'。

    'stale' 与 'unknown' 都不允许继续量：前者量到的是一份**已经不存在的版本**，
    后者是**无法确证**。两者都按"无法测量"（exit 2）出口 —— 它们与"量出来是坏的"
    （exit 1）必须分得开（M60：量具的每种"没量成"都会长得像"量出来坏了"）。
    """
    disk = disk_version()
    reported, route = ask_backend_version()
    try:
        state = json.loads(SERVICES_STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    started = state.get('launchedAt')
    source = newest_backend_source()

    print('backend generation:')
    print('  version  disk=%s  backend=%s  (asked /%s)'
          % (disk or '?', reported or '(no answer)', route))
    if started:
        print('  started  %s' % time.strftime('%H:%M:%S', time.localtime(started)))
    else:
        print('  started  no .run/processes.json -- start via tools/harness/_start_services.py'
              ' to make this verifiable')
    if source is not None:
        if not started:
            print('  sources  newest=%s' % source.name)
        else:
            delta = source.stat().st_mtime - started
            print('  sources  newest=%s  (%.1fh %s the process)'
                  % (source.name, abs(delta) / 3600,
                     'NEWER than' if delta > 0 else 'older than'))
    # pid 是**参考信息**，不参与判定 —— 而且必须问**Python 自己的端口**：探针连的
    # BACKEND_PORT 在 gateway 形态下是 Java（8085），拿它去比 pythonPid 就是把两个
    # 不同服务的 pid 放在一起比（这一行第一版就是这么错的，打印出来还自带一句张冠
    # 李戴的 "launcher" 注解 —— 量具把两样东西当成一样来量，观感与"真的对上了"
    # 几乎无法分辨）。这也是 pid 不参与判定的理由：它最容易这样错，而它本就不是
    # 权威判据（权威判据是后端自己的话，见上面那行 version）。
    python_port = (state.get('ports') or {}).get('python', 8600)
    recorded = state.get('pythonPid')
    actual = listening_pid(python_port)
    note = ''
    if recorded is not None and actual is not None and str(recorded) != str(actual):
        note = ("   (differs, and that is expected: venv's python.exe is a launcher, so the"
                ' recorded pid is its parent, not the process bound to the port)')
    print('  pid      python recorded=%s  listening on %d=%s%s'
          % (recorded, python_port, actual, note))

    if disk and reported and disk != reported:
        print('  -- the backend self-reports a different version than the one on disk')
        return 'stale'
    if started and source is not None and source.stat().st_mtime > started:
        print('  -- %s is newer than the running process' % source.name)
        return 'stale'
    if not reported:
        return 'unknown'
    return 'ok'


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map['.mjs'] = 'text/javascript'
    extensions_map['.js'] = 'text/javascript'

    def log_message(self, *args):
        pass

    def _api(self):
        """Does this request need forwarding to the service?

        This probe serves the built `dist/` with no bundler, so it has to do the
        `/api` forwarding itself -- otherwise the page loads but never gets a plan,
        and the panels it is supposed to measure never appear.

        **前缀不在这里决定。** 后端有两种形态、路径前缀不同：
          · Java 网关（8085，默认）—— 前端请求 `/api/traffic/session` **原样**转发
            给它（`frontend/vite.config.js` 的 `/api` 代理**没有 rewrite**），
            由它再转 Python；`/api/auth/status` 也由它回答（实测 200）。
          · Python 直连（8600）—— 路由挂在**根路径**（`/traffic/session`），没有 `/api`；
            `/api/auth/status` 它没有（实测 404），所以要代答。
        上一版把「剥掉 `/api`」**写死在转发里**，注释还写着"vite.config.js 这么做"
        —— 而 vite.config.js 里根本没有 rewrite。实测（2026-10-02）：
        8085 上 `/api/health/live` **200** 而 `/health/live` **404**，8600 上正好相反。
        于是"默认端口 8085 + 写死的剥前缀"= **每一次请求都 404**，页面自述
        「请求失败（HTTP 404）」、就绪门永远等不到「计划就绪」，而报错读起来像版面坏了。
        现在**不猜**：开局问一次哪种前缀通（见 detect_api_mode），按实测结果决定，
        并在输出里写明在用哪一种。
        """
        return self.path.startswith('/api/')

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's contract
        if self._api():
            self._forward()
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        if self._api():
            self._forward()
            return
        self.send_error(405)

    def _forward(self):
        # `/api/auth/status` 是本探针唯一**代答**的一跳，理由是它必须被代答。
        #
        # 这一跳属于 Java 网关（Spring，8085 上的 Python 服务里没有这个路由，实测 404）。
        # 前端拿到 404 会走 `fetchAuthStatus` 的 catch 分支写
        # `{enabled:true, authenticated:false, statusUnavailable:true}` —— 这是**故意
        # fail-closed**，于是 `LoginOverlay` 的 `.login-mask`（`position:fixed;inset:0;
        # z-index:9999`）把整个工作台盖住。
        #
        # **遮罩不影响几何**：`.hstage` 的盒子还在原地、还是那么大，所以上一版探针
        # 隔着遮罩也能量出一组漂亮的数字并且 PASS —— 那正是 M55（判据只约束"存在"、
        # 不约束"可见"）落在**量具自己**身上的样子。这里补上代答，量到的才是操作员
        # 真正看到的那一屏。代答值抄的是网关的**默认**行为，不是编的：
        # `AuthController` 的 `@Value("${security.enabled:false}")` 默认为 false，
        # 此时 `signedIn` 为 true、无 authentication 时 username 为 ""。
        # 代答**只发生在 direct 形态**：Python 直连时它没有 `/api/auth/status`（实测
        # 404），必须代答；Java 网关形态下这一跳由 **Java 自己回答**（实测 200），
        # 再代答一遍就是拿我的假设去顶替真实响应 —— 而真实响应正是这份探针要量的东西。
        if API_MODE == 'direct' and self.path.split('?')[0] == '/api/auth/status':
            payload = json.dumps({'enabled': False, 'authenticated': True,
                                  'username': ''}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        import urllib.error
        import urllib.request
        # 前缀由**实测形态**决定，不写死（见 QuietHandler._api / detect_api_mode）：
        # gateway 保留 `/api/...` 原样，direct 把它剥掉。
        path = self.path if API_MODE == 'gateway' else self.path[len('/api'):]
        target = 'http://127.0.0.1:%d%s' % (BACKEND_PORT, path)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        request = urllib.request.Request(target, data=body, method=self.command)
        for header in ('Content-Type', 'Accept'):
            if self.headers.get(header):
                request.add_header(header, self.headers[header])
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                payload = resp.read()
                status = resp.status
                content_type = resp.headers.get('Content-Type', 'application/json')
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            content_type = exc.headers.get('Content-Type', 'application/json')
        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({'error': str(exc)}).encode('utf-8')
            status = 502
            content_type = 'application/json'
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


BACKEND_PORT = int(os.environ.get('ALC_BACKEND_PORT', '8085'))


def start_server(directory):
    handler = lambda *a, **kw: QuietHandler(*a, directory=str(directory), **kw)  # noqa: E731
    httpd = socketserver.TCPServer(('127.0.0.1', 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


# The page collects geometry. It runs in the browser, so it may only use DOM APIs.
#
# `narrowRight` injects a CSS override that forces the right panel to overlap its
# neighbour. That is the negative control: if the detector cannot see a *deliberate*
# overlap, it cannot see an accidental one either.
COLLECT_JS = r"""
(() => {
  const q = (sel) => document.querySelector(sel);
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
  };
  // 运行总览已由三栏收敛为两栏：左栏那块城市列表（`.traffic-cities`）在
  // 2026-10-02 第 6 条里被删掉了。所以这里只枚举**现在真的存在**的面板 ——
  // 把一个已不存在的元素留在清单里，只会让探针永远报「cities panel not found」，
  // 那是判据没跟着设计改，不是版面坏了。
  const panels = {
    map: box(q('.traffic-map-panel')),
    detail: box(q('.traffic-detail')),
    summary: box(q('.traffic-summary')),
    playback: box(q('.traffic-playback')),
    nav: box(q('.operations-nav')),
  };
  // 右栏标题条：标题文字与右侧那枚区域角标（`<span class="detail-scope">`，它取代了
  // 原来的「返回全域」按钮）不得相交。伪元素竖条把文字挤过去，或者窄栏里两者相撞，
  // 都是构建看不出来的那一类错。
  const titleEl = q('.traffic-detail .traffic-panel-title');
  const scopeEl = titleEl ? titleEl.querySelector('.detail-scope') : null;
  const titleText = titleEl
    ? (() => {
        // Measure the text node by range, so a pseudo-element cannot hide behind
        // the element's own box.
        const range = document.createRange();
        for (const node of titleEl.childNodes) {
          if (node.nodeType === 3 && node.textContent.trim()) { range.selectNodeContents(node); break; }
        }
        const r = range.getBoundingClientRect();
        return r.width ? { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom } : null;
      })()
    : null;
  return JSON.stringify({
    viewport: { w: window.innerWidth, h: window.innerHeight },
    panels,
    detailTitle: {
      row: box(titleEl),
      scope: box(scopeEl),
      text: titleText,
    },
    scopeLabel: scopeEl ? scopeEl.textContent.trim() : '',
    // 区域控件**应当恰好一处**（用户 2026-10-02 第 6 条）。这里把所有能被当成
    // "选区入口"的东西都数出来：导航栏的下拉，以及旧版左栏那块城市列表。
    // 后者已删，所以正常状态下这个数组长度为 1；它变成 2 就是重复入口又长回来了，
    // 变成 0 就是控件没了或选择器写错了 —— 两端都判失败。
    regionControls: [
      ...document.querySelectorAll('.operations-nav select[aria-label="运行区域"]'),
    ].map(box).filter(Boolean),
    legacyCityPanels: document.querySelectorAll('.traffic-cities').length,
    regionLabel: box(q('.operations-nav .nav-region > span')),
    bodyText: document.body.innerText.length,
  });
})()
"""

# 运行首页（用户 2026-10-02）是一块固定 1920×1080 的舞台，等比缩放塞进容器。
# 它最可能出的错**不是重叠，而是裁剪**：缩放比例算大了，舞台就比 `.hstage-wrap`
# 大，而那个容器是 `overflow:hidden` —— 多出来的部分既看不见也滚不到。这正是
# 0.9.24 修掉的缺陷类别，也是"构建不会失败"的那一类。
#
# 所以判据不用"看着正常"，用几何：**缩放后的舞台矩形必须落在容器矩形之内**。
# `getBoundingClientRect()` 返回的就是**变换之后**的视觉盒子，所以这一条判据
# 同时也是在检验 `stageScale` 的调用方有没有拿错容器的尺寸（旧实现用
# `window.innerWidth/innerHeight`，那会算出一个偏大的比例）。
# 首页**可用**的判据。用页面自己的自述，而不是从数字里猜："计划就绪"是顶栏自己
# 渲染的状态（`plan.status==='READY'`），地图画布的挂载是地图组件的自述。
# 登录遮罩单列一条：`.login-mask` 是 `position:fixed;inset:0;z-index:9999`，它盖住
# 整个工作台时几何照样量得出来（M55：存在 ≠ 可见），所以它必须在就绪判据里。
READY_JS = r"""
(() => {
  if (document.querySelector('.login-mask')) return false;
  // 0.11.2：`hs-top` 整条按手册 §3.1.5 ① 删掉了（顶部让给内容），状态自述挪到
  // 推演条上的 `[data-plan-status]`。判据跟着**锚点**走，而不是跟着"哪一天那两个类
  // 还在"—— 否则删一条 UI 就会让探针报"页面没就绪"，而它看起来像版面坏了。
  const top = document.querySelector('[data-plan-status]');
  if (!top || (top.innerText || '').indexOf('计划就绪') < 0) return false;
  return !!document.querySelector('.hs-map-bd .maplibregl-canvas');
})()
"""

COLLECT_HOME_JS = r"""
(() => {
  const q = (sel) => document.querySelector(sel);
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
  };
  const wrap = q('.hstage-wrap'), stage = q('.hstage');
  // 舞台内部的长度一律换算回**布局像素**再比：`getBoundingClientRect` 给的是缩放后的
  // 视觉盒子，而 `clientHeight` / `offsetHeight` 是未缩放的布局值，两套混用会得到
  // 一个随窗口大小变化的假读数。
  const stageScale = stage && stage.offsetWidth ? stage.getBoundingClientRect().width / stage.offsetWidth : 1;
  return JSON.stringify({
    viewport: { w: window.innerWidth, h: window.innerHeight },
    wrap: box(wrap),
    stage: box(stage),
    kpis: box(q('.hs-kpis')),
    main: box(q('.hs-main')),
    foot: box(q('.hs-foot')),
    // 舞台的**未缩放**布局尺寸 + 缩放后的盒子，两者一起看才能把"布局错了"与
    // "比例错了"分开 —— 只看其中一个数，两种原因会长得一模一样（M39）。
    natural: stage ? { w: stage.offsetWidth, h: stage.offsetHeight } : null,
    // 空隙判据负向对照的**注入回执**（M58）：注入是否真的把目标面板撑高了，由注入
    // 自己回读它自己的 computed 高度写在这里。判据只看这个回执，不再看"哪一栏的第几行
    // 的栅格声明变了没有" —— 后者会把"注入打在了别的地方"读成"判据没有牙齿"，
    // 而 2026-10-02 第四轮真的这样栽过一次（左栏由两块变三块）。见 HOME_OVERTALL_JS。
    stretch: window.__probeStretch || null,
    columns: [...document.querySelectorAll('.hs-main > .hs-col')].map(box),
    // 每个面板**中间有没有洞**。
    //
    // 判据为什么需要它：面板够高、内容没溢出，是看不到任何异常的 —— `scrollHeight`
    // 等于 `clientHeight`，"没有裁切"的检查全绿，可面板中间空着一大片，读的人会说
    // "信息密度不够"。用户 2026-10-02 的原话就是「信息密度与重点…记得要抓重点」。
    //
    // 上一版量的是"子元素高度之和"，那个指标**会撒谎**：子元素若是 `flex:1` 的容器
    // （滚动列表就是），它的盒子本身就等于可用高度，"已用"于是永远等于 100%，
    // 而它里面可能只有一行字。眼睛看到的是**洞**，所以这里量的就是洞：
    // 相邻子元素之间的最大空隙，以及最后一个子元素下面的尾部空隙。
    //
    // 空隙用 `getBoundingClientRect` 量、再除以舞台缩放，换算回**布局像素**，
    // 这样才能和未缩放的 `clientHeight` 比。
    panels: [...document.querySelectorAll('.hstage .hs-panel')].map((panel) => {
      const head = panel.querySelector('.hs-panel-hd');
      const body = panel.querySelector('.hs-panel-bd');
      const title = head ? (head.querySelector('b') || {}).textContent : '';
      if (!body) return { title, h: panel.offsetHeight, avail: null, gap: null, tail: null, text: '' };
      const cs = getComputedStyle(body);
      const padBottom = parseFloat(cs.paddingBottom) || 0;
      const kids = [...body.children];
      const boxes = kids.map((child) => child.getBoundingClientRect());
      let gap = 0, gapAfter = '';
      for (let i = 1; i < boxes.length; i += 1) {
        const size = (boxes[i].top - boxes[i - 1].bottom) / stageScale;
        if (size > gap) { gap = size; gapAfter = String(kids[i].className || ''); }
      }
      const last = boxes.length ? boxes[boxes.length - 1] : null;
      const tail = last ? (body.getBoundingClientRect().bottom - padBottom * stageScale - last.bottom) / stageScale : 0;
      return { title, h: panel.offsetHeight, avail: body.clientHeight,
               gap: Math.round(Math.max(0, gap)), gapAfter,
               tail: Math.round(Math.max(0, tail)),
               // 面板的**自述**。没有它，一个"87% 空白"的读数有两种解释：面板真的空了，
               // 或者页面还没拿到计划（那时叙事块退化成两段说明文字）。两种解释的下一步
               // 动作完全相反，所以量的时候就得把判据带回来（M56）。
               text: (body.innerText || '').replace(/\s+/g, ' ').slice(0, 72) };
    }),
    // 滚动列表：一屏能完整放下几行，以及条目内容有没有被挤出去。
    //
    // 量出来才明白的两件事（写在这里免得下一个人再推一遍）：
    //   · 条目的高度是它自己的**内容高度**（实测 61 px），不随面板高度变化 ——
    //     列表里的条目没有 flex-grow，所以"面板长高"不会把行撑大，只会让**更多行**
    //     同时落在可视区里（一屏可见行数 ≈ 可视区高 / 行距）。
    //   · `maxVisible` 只决定**步进量**（`rowHeight = 可视区 / maxVisible`），
    //     与一行有多高无关。
    // 所以"余量换密度"的实测依据是 `fully`（完整落在可视区内的行数），而"有没有把
    // 内容挤掉"的依据是 `footOut`（脚注那行被挤出条目盒子的行数）。后者能被一个压扁
    // 条目的样式触发，见下面的负向对照 —— 一条只会通过的判据等于没有判据。
    lists: [...document.querySelectorAll('.hstage .sl-wrap')].map((wrap) => {
      const view = wrap.querySelector('.sl-view');
      const page = view ? view.querySelector('.list-page') : null;
      const items = page ? [...page.children] : [];
      let footOut = 0, worst = 0, bodyGap = Infinity;
      for (const el of items) {
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const padBottom = (parseFloat(cs.paddingBottom) || 0) * stageScale;
        const kids = [...el.children].map((child) => child.getBoundingClientRect());
        if (kids.length) {
          const overflow = (kids[kids.length - 1].bottom - (box.bottom - padBottom)) / stageScale;
          worst = Math.max(worst, overflow);
          if (overflow > 1) footOut += 1;
        }
        // 条目内部是两行并排的标题/记号 + 两行跨栏的正文/脚注，所以"相邻子元素互相压住"
        // 这种通用判据会把**并排**的标题与记号当成重叠（实测 35/35 全报，全是误报）。
        // 真正要看的是**叠放**的那一对：正文最后一行与脚注行之间还剩多少。
        if (kids.length >= 2) {
          const gap = (kids[kids.length - 1].top - kids[kids.length - 2].bottom) / stageScale;
          bodyGap = Math.min(bodyGap, gap);
        }
      }
      const viewBox = view ? view.getBoundingClientRect() : null;
      const fully = viewBox ? items.filter((el) => {
        const box = el.getBoundingClientRect();
        return box.top >= viewBox.top - 0.5 && box.bottom <= viewBox.bottom + 0.5;
      }).length : 0;
      return {
        label: wrap.getAttribute('aria-label') || '',
        items: items.length,
        view: view ? view.clientHeight : null,
        box: items.length ? Math.round(items[0].clientHeight) : 0,
        fully, footOut, worst: Math.round(worst),
        bodyGap: Number.isFinite(bodyGap) ? Math.round(bodyGap) : null,
      };
    }),

    hasHeader: !!q('.traffic-header') && getComputedStyle(q('.traffic-header')).display !== 'none',
    wrapOverflow: wrap ? { sw: wrap.scrollWidth, sh: wrap.scrollHeight, cw: wrap.clientWidth, ch: wrap.clientHeight } : null,
  });
})()
"""

# 切到「运行总览」。用小节按钮上的 `data-section` 而不是它的中文标签：标签是文案，
# 改文案不该让探针静默失效（改 key 会，而那是真的结构变化）。
SELECT_SECTION_JS = r"""
((key) => {
  // 0.11.1（Beta）：导航分成两层 —— 顶层是五个编号入口（`.nav-group`，带 `data-group`），
  // 具体分节的按钮搬到了页内子视图行（`.nav-subs`，带 `data-section`）。
  // 所以选择器**不能再限定在 `.operations-nav` 里**：那会一直找不到（实测报
  // `missing:briefing`，而页面上那个按钮就在下面一行）。改为全文档找 `data-section` ——
  // 它才是"分节"这件事的唯一标识，容器位置是排版细节，不该被探针写死。
  const btn = document.querySelector('[data-section="' + key + '"]');
  if (!btn) return 'missing:' + key;
  btn.click();
  return 'clicked';
})
"""

# 首页的负向对照：把舞台放大到必然探出容器。用 transform 走**与真实错算同一条**
# 几何通路（`getBoundingClientRect` 看到的就是变换后的盒子），所以它检验的是判据，
# 而不是"有没有被某个 !important 挡住"。
#
# **必须用样式表规则 + `!important`**：`transform` 是 Vue 绑在同一个元素上的**内联
# 样式**，下一次 patch 就会把脚本设的内联值覆盖掉。上一版把 `style.transform` 直接
# 写在元素上，于是这个对照会**静默失效** —— 实测有一次真的没触发，而它本该必然触发。
# `!important` 的样式表声明优先级高于非 `!important` 的内联声明，Vue 覆盖不掉。
# 同时回读宽度，确认它**真的**变大了；没变大就报错，而不是"通过"。
HOME_OVERGROW_JS = r"""
(() => {
  const stage = document.querySelector('.hstage');
  if (!stage) return JSON.stringify({ error: 'no-stage' });
  const style = document.createElement('style');
  style.id = '__probe_overgrow';
  style.textContent = '.hstage{transform:translate(-50%,-50%) scale(1.45)!important}';
  document.head.appendChild(style);
  const after = stage.getBoundingClientRect().width;
  return JSON.stringify({ after: after });
})()
"""

# 空隙判据的负向对照：**把一块"按内容定高"的面板撑得远高于它的内容** —— 那正是产生
# 空洞的版面（ADR-43 禁止的那一种），所以判据必须能看见它；看不见，说明判据没有牙齿。
#
# **2026-10-02 第四轮与 2026-10-03 第五轮各失效过一次，三次修正都值得写下来。**
#
# 第一版（`grid-template-rows: minmax(0,1fr) minmax(0,1fr)`——直接抄了**当时**那个
# 错误声明）在第四轮失效：左栏由**两块**变**三块**之后，这个注入把**前两块**平分、
# 第三块落进隐式行 —— 它**仍然生效**（栅格确实变了），但**不再复现那个空洞**了，
# 于是对照报"未触发"，而"未触发"与"通过"长得一模一样。
# 教训：注入写的是"当时那个错误条件"，而判据守的是"**这个错误总能被看见**"，
# **结构一改两者就脱钩**（**M61**）。⇒ 第二版改成与行数无关的写法：只钉**第一行**的
# 固定高度（640 px），其余行留空按 `auto` 走。
#
# 第二版在第五轮失效：左栏的「基于气象确定航道」亮点面板被删掉之后，左栏只剩两块
# **撑满容器**的滚动列表。「钉住第一行」**确实生效了**，可被钉住的那一块长高时列表
# 跟着长，多出来的高度落在**列表内部**，而判据量的是面板身体里**孩子之间/最后一个孩子
# 下面**的空隙 —— 它量不到列表内部的洞。这说明"钉某一行的固定高度"仍不是判据真正守的
# 那个缺陷；判据守的是**面板自身的高度与内容不相称**。
#
# ⇒ 第三版不再猜"哪一栏的第几行"，改成**按标题点名一块内容定高的面板**（放行许可 =
# 报文块 + 紧跟其后的一句注脚，高度完全由内容决定），用**样式表规则**把它撑到 640 px
# （不用内联 `!important` —— CSS 解析器会把它丢掉，那是假的加固，M58），再回读它自己的
# `offsetHeight` 自证生效。
# 点名仍然是一种耦合：那块面板改名或消失时 `effective` 会是 false，对照**大声失败** ——
# 这正是我们要的失败方式，而不是静默地"什么都没发生"。
HOME_OVERTALL_JS = r"""
(() => {
  const want = '放行许可';
  const all = [...document.querySelectorAll('.hstage .hs-panel')];
  const panel = all.find((p) => ((p.querySelector('.hs-panel-hd b') || {}).textContent || '').trim().startsWith(want));
  if (!panel) return 'no-panel';
  const title = (((panel.querySelector('.hs-panel-hd b') || {}).textContent) || '').trim();
  const heightBefore = panel.offsetHeight;
  panel.classList.add('__probe_stretch');
  const style = document.createElement('style');
  style.id = '__probe_overtall';
  style.textContent = '.hstage .hs-panel.__probe_stretch{height:640px!important}';
  document.head.appendChild(style);
  const heightAfter = panel.offsetHeight;
  // 自证生效：不只是"规则挂上去了"，而是"高度真的变了"。撑高 100 px 以上才算数，
  // 免得把面板自身的内边距变化读成生效。
  window.__probeStretch = {
    title: title,
    heightBefore: heightBefore,
    heightAfter: heightAfter,
    effective: heightAfter >= heightBefore + 100 && heightAfter >= 600,
  };
  return JSON.stringify(window.__probeStretch);
})()
"""

HOME_RESTORE_JS = r"""
(() => {
  const ids = ['__probe_overgrow', '__probe_overtall', '__probe_squash'];
  const removed = ids.filter((id) => {
    const el = document.getElementById(id);
    if (el) { el.remove(); return true; }
    return false;
  });
  document.querySelectorAll('.__probe_stretch').forEach((el) => el.classList.remove('__probe_stretch'));
  delete window.__probeStretch;
  return JSON.stringify({ removed });
})()
"""

# 行高判据的负向对照：把条目压扁到装不下自己的内容（真实缺陷的形状就是每行分到的
# 高度小于内容高度）。判据看不见这个，就看不见"余量换成了更多行、但行被压扁"。
HOME_SQUASH_JS = r"""
(() => {
  const tick = document.querySelector('.hstage .sl-wrap .hs-tick');
  if (!tick) return 'no-tick';
  const style = document.createElement('style');
  style.id = '__probe_squash';
  style.textContent = '.hstage .hs-tick{height:40px!important}';
  document.head.appendChild(style);
  return 'squashed';
})()
"""

NARROW_JS = r"""
(() => {
  // The negative control must produce an overlap the detector can see, using the
  // same geometry path as a real one. The first version set a grid template on
  // `.traffic-main`, which the component's own scoped rule (and its `!important`
  // overrides) won -- the control silently did nothing and "passed" by doing
  // nothing, which proves nothing about the detector.
  //
  // What actually moves a panel is a transform. It is applied to the existing
  // element, so no layout rule can out-specify it, and it shifts the measured
  // bounding box exactly the way a real overlap would.
  const detail = document.querySelector('.traffic-detail');
  if (!detail) return 'no-detail';
  detail.style.transform = 'translateX(-420px)';
  return 'shifted';
})()
"""


def overlaps(a, b):
    """True when two axis-aligned rectangles share area."""
    if not a or not b:
        return False
    return a['x'] < b['right'] and b['x'] < a['right'] and a['y'] < b['bottom'] and b['y'] < a['bottom']


def evaluate(ws_holder, expression):
    return ws_holder['call']('Runtime.evaluate', {'expression': expression, 'returnByValue': True})


async def drive(page_url, debug_port):
    import websockets

    targets = None
    for _ in range(60):
        try:
            import urllib.request
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % debug_port, timeout=2) as resp:
                targets = json.loads(resp.read().decode('utf-8'))
            if targets:
                break
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    if not targets:
        raise RuntimeError('Edge did not expose a debug target within 30s')
    page = next((t for t in targets if t.get('type') == 'page'), None)
    if page is None:
        raise RuntimeError('no page target')
    ws_url = page.get('webSocketDebuggerUrl')
    if not ws_url:
        raise RuntimeError('page target has no webSocketDebuggerUrl')

    async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
        counter = [0]

        async def call(method, params=None):
            counter[0] += 1
            mid = counter[0]
            await ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=PAGE_TIMEOUT_S)
                data = json.loads(raw)
                if data.get('id') == mid:
                    if 'error' in data:
                        raise RuntimeError('%s -> %s' % (method, data['error']))
                    return data.get('result', {})

        await call('Page.enable')
        await call('Runtime.enable')
        await call('Page.navigate', {'url': page_url})

        # 默认分节现在是「运行首页」（用户 2026-10-02），所以先等**舞台**出现。
        # 这里原来等的是 `.traffic-detail` —— 那是运行总览的节点。默认页换了之后，
        # 那个等待会一直等到超时，然后报"面板从未出现"，把一次结构变化报成一次
        # 渲染故障（参照物过期，本项目的常客）。先量首页，再切到总览量三栏。
        deadline = time.monotonic() + PAGE_TIMEOUT_S
        while time.monotonic() < deadline:
            result = await call('Runtime.evaluate', {
                'expression': "!!document.querySelector('.hstage')",
                'returnByValue': True})
            if (result.get('result') or {}).get('value'):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError('home stage never appeared within %.0fs' % PAGE_TIMEOUT_S)

        # **舞台存在 ≠ 页面可用。** 计划要构建十几秒（BUILDING → READY），在那之前
        # 五个面板全都是空态自述（「本计划未声明回波避让几何」「正在载入城市地图」），
        # 量出来的是一屏操作员永远看不到的画面。上一版没有这道门，于是"亮点面板
        # 87% 空白"这种读数既可能是真缺陷、也可能只是还没就绪 —— 两种解释的下一步
        # 动作相反。所以这里等的是**页面自己的契约**：登录遮罩不在 + 顶栏自述
        # 「计划就绪」 + 地图画布已挂载。
        deadline = time.monotonic() + PAGE_TIMEOUT_S
        while time.monotonic() < deadline:
            result = await call('Runtime.evaluate', {
                'expression': READY_JS, 'returnByValue': True})
            if (result.get('result') or {}).get('value'):
                break
            await asyncio.sleep(1.0)
        else:
            # M56 落在探针**自己的错误路径**上：结论与预期不符时，先取被测对象的自述
            # （页面第一句话），再怀疑别的东西。没有这一句，一次"后端不可达"会被
            # 读成"版面坏了" —— 而且两者的下一步动作完全相反。
            said = (await call('Runtime.evaluate', {
                'expression': '(document.body.innerText||"").replace(/\\s+/g," ").slice(0,140)',
                'returnByValue': True})).get('result', {}).get('value') or '(页面没有说话)'
            raise RuntimeError(
                'home never reported 计划就绪 within %.0fs -- measuring an unready page would '
                'report empty-state geometry as a layout defect.\n'
                '  the page itself says: %s' % (PAGE_TIMEOUT_S, said))

        # 舞台比例由 ResizeObserver 驱动，量之前给它一帧。
        await asyncio.sleep(2.0)
        home_normal = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_HOME_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')

        grown_raw = (await call('Runtime.evaluate', {
            'expression': HOME_OVERGROW_JS, 'returnByValue': True})).get('result', {}).get('value')
        grown_info = json.loads(grown_raw or '{}')
        # 对照必须**自证生效**：注入没生效时它不会失败，只会"什么也没发生"，
        # 而"什么也没发生"看起来和一个通过了的对照一模一样。
        baseline_width = ((home_normal.get('stage') or {}).get('w')) or 0
        grown_width = grown_info.get('after') or 0
        control_effective = grown_width > baseline_width * 1.35
        await asyncio.sleep(0.6)
        home_grown = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_HOME_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')

        # 空隙判据的负向对照：把一块内容定高的面板撑到 640 px，判据必须看得见那个洞。
        await call('Runtime.evaluate', {'expression': HOME_OVERTALL_JS, 'returnByValue': True})
        await asyncio.sleep(0.6)
        home_overtall = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_HOME_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')

        # 行高判据的负向对照：把条目压扁，判据必须看得见"内容装不下"。
        await call('Runtime.evaluate', {'expression': HOME_SQUASH_JS, 'returnByValue': True})
        await asyncio.sleep(0.6)
        home_squash = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_HOME_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')
        await call('Runtime.evaluate', {'expression': HOME_RESTORE_JS, 'returnByValue': True})
        await asyncio.sleep(0.4)

        # 切到「运行总览」。
        selected = (await call('Runtime.evaluate', {
            'expression': "(%s)('overview')" % SELECT_SECTION_JS,
            'returnByValue': True})).get('result', {}).get('value')
        if selected != 'clicked':
            raise RuntimeError('could not switch to the overview section: %s' % selected)

        deadline = time.monotonic() + PAGE_TIMEOUT_S
        while time.monotonic() < deadline:
            result = await call('Runtime.evaluate', {
                'expression': "!!document.querySelector('.traffic-detail')",
                'returnByValue': True})
            if (result.get('result') or {}).get('value'):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError('workbench panels never appeared within %.0fs' % PAGE_TIMEOUT_S)

        # Let layout settle (fonts, grid tracks).
        await asyncio.sleep(2.0)
        normal = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')

        await call('Runtime.evaluate', {'expression': NARROW_JS, 'returnByValue': True})
        await asyncio.sleep(1.0)
        narrowed = json.loads((await call('Runtime.evaluate', {
            'expression': COLLECT_JS, 'returnByValue': True})).get('result', {}).get('value') or '{}')

    return (home_normal, home_grown, home_overtall, home_squash,
            {'baseline': baseline_width, 'grown': grown_width, 'effective': control_effective},
            normal, narrowed)


def main():
    edge = find_edge()
    if edge is None:
        print('no Edge binary found -- cannot measure')
        return 2
    if not (DIST / 'index.html').is_file():
        print('missing %s -- run `vite build` first' % (DIST / 'index.html'))
        return 2
    # The build output must be newer than the sources it was built from, or the
    # probe would confidently measure a stale bundle -- exactly the "参照物过期"
    # failure this project has hit before. Compare against the newest tracked
    # source file rather than eyeballing timestamps.
    source_files = list((FRONTEND / 'src').rglob('*'))
    newest = max((p for p in source_files if p.is_file()), key=lambda p: p.stat().st_mtime, default=None)
    if newest is not None and newest.stat().st_mtime > (DIST / 'index.html').stat().st_mtime:
        print('build output is older than %s -- run `vite build` first' % newest.name)
        return 2

    # 后端不在 = **无法测量**，不是"量出来坏了"。这两种结论的退出码必须不同，
    # 否则下一个人会把一次没发生的测量当成一次真实的版面故障（见 backend_up()）。
    if not backend_up():
        print('no service on 127.0.0.1:%d -- cannot measure.' % BACKEND_PORT)
        print('  this probe forwards /api/* to a local service; the home stage only')
        print('  self-reports "计划就绪" once it holds a plan. Without it the page stays on')
        print('  "服务暂不可达，正在自动重连" and every panel reads as an empty state.')
        print('  start them first:  python tools/harness/_start_services.py   (background it)')
        return 2

    # 端口上"有东西在听"还不够 —— 还要知道**它用哪种前缀**。写死的剥前缀会让
    # 每一次请求都 404，而屏幕上的表现和"版面坏了"完全一样（见 QuietHandler._api）。
    global API_MODE
    API_MODE = detect_api_mode()
    if API_MODE is None:
        print('a service is listening on 127.0.0.1:%d but neither /api/%s nor /%s answered 200'
              % (BACKEND_PORT, PROBE_ROUTE, PROBE_ROUTE))
        print('  -- cannot tell which route prefix it uses, so every /api/* request would 404.')
        print('  this is a "cannot measure" (exit 2), not a layout failure.')
        return 2
    print('backend: 127.0.0.1:%d  route prefix: %s'
          % (BACKEND_PORT, '/api/... kept (gateway)' if API_MODE == 'gateway'
             else '/api stripped (python direct)'))

    # 端口上有东西、前缀也问对了 —— 但**它是不是磁盘上这份代码跑出来的**？
    # 这就是 ISS-0.9.19-04：只查前端 dist 的新鲜度不够，混版同样能让判据给出一个
    # 漂亮的 PASS（见 check_generation 上方那段）。判据用后端自己的话，问不到也
    # 不猜 —— 不猜的代价是一次没做的测量，猜的代价是一句"已通过"。
    if check_generation() != 'ok':
        print()
        print('this backend is not the code currently on disk, or cannot prove that it is,')
        print('so every number below would describe an unknown generation -- no measurement')
        print('is taken. this is a "cannot measure" (exit 2), not a layout failure.')
        print('restart the services first:  python tools/harness/_start_services.py   (background it)')
        return 2

    httpd, port = start_server(DIST)
    debug_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix='alc-layout-profile-')
    print('edge:   %s' % edge)
    print('server: http://127.0.0.1:%d/index.html  (build output)' % port)
    print()

    proc = subprocess.Popen(
        [edge, '--headless=new', '--disable-gpu', '--no-first-run',
         '--no-default-browser-check', '--disable-extensions',
         '--remote-debugging-port=%d' % debug_port,
         '--user-data-dir=%s' % profile_dir,
         '--window-size=1600,900', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        home_normal, home_grown, home_overtall, home_squash, control, normal, narrowed = asyncio.run(
            drive('http://127.0.0.1:%d/index.html' % port, debug_port))
        baseline_width = control['baseline']
        grown_width = control['grown']
        control_effective = control['effective']
    except Exception as exc:  # noqa: BLE001
        print('FAILED: %s' % exc)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        httpd.shutdown()

    failures = []

    # --- 运行首页：舞台不得被容器裁掉 -----------------------------------------
    # 判据是几何，不是观感：缩放后的舞台矩形必须完整落在 `.hstage-wrap` 之内。
    # `getBoundingClientRect` 返回的是**变换之后**的盒子，所以拿错容器尺寸
    # （旧实现用 window.innerWidth/innerHeight）会当场被这一条抓住。
    def fits(inner, outer, tol=1.0):
        if not inner or not outer:
            return False
        return (inner['x'] >= outer['x'] - tol and inner['y'] >= outer['y'] - tol
                and inner['right'] <= outer['right'] + tol and inner['bottom'] <= outer['bottom'] + tol)

    h_wrap = home_normal.get('wrap')
    h_stage = home_normal.get('stage')
    h_natural = home_normal.get('natural') or {}
    print('运行首页 视口 %sx%s' % ((home_normal.get('viewport') or {}).get('w'),
                                (home_normal.get('viewport') or {}).get('h')))
    for name in ('wrap', 'stage', 'kpis', 'main', 'foot'):
        b = home_normal.get(name)
        if not b:
            print('  %-7s MISSING' % name)
            failures.append('home %s is not rendered' % name)
            continue
        print('  %-7s x=%-7.1f y=%-7.1f w=%-7.1f h=%-7.1f' % (name, b['x'], b['y'], b['w'], b['h']))
        if b['w'] < 1 or b['h'] < 1:
            failures.append('home %s has no area (%.1fx%.1f)' % (name, b['w'], b['h']))
    print('  natural %sx%s (未缩放布局尺寸)' % (h_natural.get('w'), h_natural.get('h')))

    if h_wrap and h_stage:
        if not fits(h_stage, h_wrap):
            failures.append(
                'home stage escapes its container: stage %sx%s at (%.0f,%.0f) vs wrap %sx%s at (%.0f,%.0f)'
                % (round(h_stage['w']), round(h_stage['h']), h_stage['x'], h_stage['y'],
                   round(h_wrap['w']), round(h_wrap['h']), h_wrap['x'], h_wrap['y']))
        # 等比缩放的意义：**至少一维**贴着容器。两维都明显留白说明比例被无谓缩小了；
        # 一维溢出而另一维留白是"用了 max"的典型形状，上面那条已经抓住。
        else:
            slack_w = h_wrap['w'] - h_stage['w']
            slack_h = h_wrap['h'] - h_stage['h']
            if min(slack_w, slack_h) > 2.0:
                failures.append(
                    'home stage fits but touches neither edge (slack %.1f x %.1f) -- not a filled scale'
                    % (slack_w, slack_h))
    # 首页**不该**再渲染工作台自己的品牌头与那五张指标卡：舞台自带一套，重复出现
    # 既挤高度又让标题出现两次。
    if home_normal.get('hasHeader'):
        failures.append('home section still renders the workbench brand header')
    # 舞台内部是三栏。它们都在同一个 grid 里，栅格不会重叠 —— 但**内容**会：
    # 一栏里的不换行长文本会把栏撑开，另一栏被挤窄，视觉上就压过去了（构建不跑
    # CSS 布局，这件事只有量出来才知道）。所以这里量的是栏的盒子。
    cols = home_normal.get('columns') or []
    print('  columns %s' % ', '.join('%.0fx%.0f@%.0f' % (c['w'], c['h'], c['x']) for c in cols if c))
    if len(cols) != 3:
        failures.append('home stage has %d columns, expected 3' % len(cols))
    for i in range(len(cols) - 1):
        if cols[i] and cols[i + 1] and overlaps(cols[i], cols[i + 1]):
            failures.append('home column %d overlaps column %d' % (i, i + 1))
    if home_normal.get('wrapOverflow'):
        ov = home_normal['wrapOverflow']
        if ov['sh'] > ov['ch'] + 1 or ov['sw'] > ov['cw'] + 1:
            failures.append('home stage container scrolls (%sx%s in %sx%s) -- content is cut'
                            % (ov['sw'], ov['sh'], ov['cw'], ov['ch']))

    # 面板内容空隙：**量出来之后**才立判据，而阈值取的是"这一点余量是版面呼吸，
    # 再多就是洞"的那条线。判据不能先于测量存在 —— 没见过分布就写一个"空隙不得
    # 超过 N px"，那个 N 只是把当天的画面钉成了标准（M39）。
    #
    # 为什么需要它：面板比内容高出去的那一块，在同屏其它面板里根本不存在（那几个的
    # 空隙都是个位数），所以它不是"设计留白"，是一块结构性的洞。判据钉的是**内部**
    # 与**尾部**两种形态取大者，上限 24 px。
    #
    # 这块判据最初的触发案例是「基于气象确定航道」—— 那一块只有五行字却和滚动列表
    # 各占一半高度，中间空出 178 px。**2026-10-03 用户删掉了那一块面板**（「第一个框
    # 不显示，这个没用」），于是判据的**适用范围**变成左栏剩下的两张列表；判据本身
    # 一个字都没改 —— 上一轮的要求不是这一轮的契约，为它写死的断言已经删掉。
    #
    # 判据只钉**内部**空隙、不钉尾部空隙 —— 这条边界要写清楚，因为它刚刚证伪过一次。
    #
    # 原来的理由：尾部空隙是"最后一行下面剩多少"，随内容条数变化（改航班次只有一条时，
    # 列表尾部本来就会空），把它也钉死等于逼着界面在没有内容的时候假装有内容。
    # **但那个理由只对"被设计来吃余量"的那一块成立。** 2026-10-02 第四轮实测：
    # 把左栏三行平分之后，「受气象影响改航的班次」由 **97 px 涨到 269 px**，而它
    # **只有一个孩子**（一行「本场景没有因气象影响改航的班次」）—— 于是 `gap` 仍是 **0**、
    # 那块 **172 px** 的洞全部落在 `tail` 里，判据**看不见**，对照于是报"未触发"。
    # 教训：**判据不得先假设现象长什么样**（与 **M53** 同族 —— M53 说"别假设它落在哪一维"，
    # 这里说"别假设它以哪种形态出现"）。洞有两种形态：夹在孩子**中间**（`gap`）
    # 与落在最后一个孩子**下面**（`tail`），只认前者就等于把所有单孩子面板排除在外。
    #
    # 例外只有"余量承载者"：`minmax(0,1fr)` 那一块天生要替别人吃掉剩下的高度，
    # 它的列表短时尾部本来就空。例外**按标题点名** —— 标题一旦改了，判据会**变严**
    # （把例外也钉上）然后报出来，而不是静默放行。
    HIGHLIGHT_GAP_LIMIT = 24.0
    LEFTOVER_CARRIERS = ('放行队列', '气象情报')

    def panel_hole(panel):
        """面板比它的内容高出去的那一块（布局像素）：中间的空隙与尾部的空隙取大者。"""
        return max(panel.get('gap') or 0, panel.get('tail') or 0)

    def pinned(panel):
        title = panel.get('title') or ''
        return not any(title.startswith(name) for name in LEFTOVER_CARRIERS)

    home_panels = home_normal.get('panels') or []
    print('  面板内容空隙（布局像素，未缩放）:')
    for p in home_panels:
        if p.get('avail') is None:
            print('    %-16s h=%-5s 无内容区' % (p.get('title'), p.get('h')))
            continue
        print('    %-16s 面板 %-5s 内容区 %-5s 内部最大空隙 %-5s (在 %s 之前) 尾部 %-5s'
              ' 洞 %-5s%s  「%s」'
              % (p.get('title') or '—', p.get('h'), p['avail'], p.get('gap'), p.get('gapAfter') or '—',
                 p.get('tail'), panel_hole(p), '' if pinned(p) else ' [余量承载者]', p.get('text') or ''))
    print()
    print('面板高度与内容相称判据（上限 %.0f px，余量承载者除外）:' % HIGHLIGHT_GAP_LIMIT)
    for p in home_panels:
        if not pinned(p) or p.get('avail') is None:
            continue
        measured = panel_hole(p)
        verdict = '通过' if measured <= HIGHLIGHT_GAP_LIMIT else '超限'
        print('    %-16s 洞 %-5s —— %s' % (p.get('title') or '—', measured, verdict))
        if measured > HIGHLIGHT_GAP_LIMIT:
            failures.append(
                'home panel 「%s」 has a %.0f px hole (gap %s / tail %s, limit %.0f) -- it is taller '
                'than its own evidence'
                % (p.get('title'), measured, p.get('gap'), p.get('tail'), HIGHLIGHT_GAP_LIMIT))
    # 原来这里有一条「亮点面板必须在」的断言（用户 2026-10-02 要求展示基于气象确定航道的
    # 亮点）。**2026-10-03 用户明确删掉了那一块面板**（「第一个框不显示，这个没用」），
    # 所以断言随之删除 —— 留着它等于把"上一轮的要求"当成"这一轮的契约"，探针会永远红。
    # 那一条真正要守的东西没有丢：`weatherCorridorStory()` 的载荷契约仍由
    # frontend/tests/homeStage.test.mjs 钉住，判据本身也已写进地图图例那一行。

    # 负向对照：把舞台放大到必然探出容器。看不见这个的判据，也看不见真实的算错。
    grown = home_grown.get('stage')
    print()
    print('negative control (home stage forced to scale 1.45):')
    if not control_effective:
        print('  control did NOT take effect (stage width %.1f -> %.1f) -- a control that cannot'
              ' trip proves nothing about the criterion' % (baseline_width, grown_width))
        failures.append('home stage negative control did not take effect (width %.1f -> %.1f)'
                        % (baseline_width, grown_width))
    elif grown and h_wrap and not fits(grown, h_wrap):
        print('  overgrown stage detected -- the fit criterion has teeth (stage %.0f -> %.0f px)'
              % (baseline_width, grown_width))
    else:
        print('  control did NOT trip -- the fit criterion cannot see an overgrown stage')
        failures.append('home stage negative control did not trip')

    # 空隙判据的负向对照：**某一块的高度不由内容决定**的版面必须被判据看见。
    # 判据用的是 `panel_hole`（gap 与 tail 取大者）与同一份例外表 —— 对照检证的必须是
    # **判据真正用的那个口径**，否则它会为一个"判据并不检查的东西"背书（M29/M39 的老毛病）。
    # 生效与否只看注入自己的回执（`stretch`），不看"栅格声明变了没有"：后者会把
    # "这一针打在了别的地方"读成"判据没有牙齿"（M58 / M61）。
    split_panels = home_overtall.get('panels') or []
    split_pinned = [p for p in split_panels if pinned(p) and p.get('avail') is not None]
    worst_split = max(split_pinned, key=panel_hole) if split_pinned else None
    stretch = home_overtall.get('stretch') or {}
    print()
    print('negative control (the content-sized panel 「%s」 forced to 640 px):'
          % (stretch.get('title') or '—'))
    print('  panel height (layout px): %s -> %s'
          % (stretch.get('heightBefore'), stretch.get('heightAfter')))
    if not stretch.get('effective'):
        # 注入没生效时，下面那条"没触发的对照"会被读成"判据没有牙齿"，
        # 而真相是"这一针打在了别的地方"。两者必须分开报（M58）。
        print('  control did NOT take effect -- the named content-sized panel was not stretched')
        failures.append('gap negative control did not take effect (named panel not stretched)')
    elif worst_split is None:
        print('  control did NOT take effect -- no pinned panel measured')
        failures.append('gap negative control did not take effect')
    elif panel_hole(worst_split) <= HIGHLIGHT_GAP_LIMIT:
        print('  control did NOT trip (worst hole %.0f px <= limit %.0f) -- the criterion cannot see'
              ' a half-empty panel' % (panel_hole(worst_split), HIGHLIGHT_GAP_LIMIT))
        failures.append('gap negative control did not trip (worst hole %.0f px under the %.0f px limit)'
                        % (panel_hole(worst_split), HIGHLIGHT_GAP_LIMIT))
    else:
        print('  half-empty panel detected (「%s」 hole %.0f px > limit %.0f, gap %s / tail %s)'
              ' -- the criterion has teeth'
              % (worst_split.get('title'), panel_hole(worst_split), HIGHLIGHT_GAP_LIMIT,
                 worst_split.get('gap'), worst_split.get('tail')))

    # 滚动列表：一屏完整放下几行（密度证据），以及条目内容有没有被挤出去（缺陷判据）。
    #
    # 判据为什么钉在"最后一行文字"上：条目被压扁时，最先消失的不是标题也不是正文的
    # 第一行，而是**脚注那行**（航程 km / 观测时刻）—— 而 `overflow:hidden` 会让它消失
    # 得毫无痕迹。所以量的不是"盒子够不够"，而是"最后那行文字有没有落在盒子之外"。
    print()
    print('滚动列表（布局像素，未缩放）:')
    for item in home_normal.get('lists') or []:
        print('    %-16s 条目 %-4s 可视区 %-5s 条目高 %-5s 完整可见 %-3s 行  脚注出框 %s 条'
              ' (最远 %s px)  正文与脚注间距 %s px'
              % (item.get('label') or '—', item.get('items'), item.get('view'), item.get('box'),
                 item.get('fully'), item.get('footOut'), item.get('worst'), item.get('bodyGap')))
        if item.get('footOut') or (item.get('bodyGap') is not None and item['bodyGap'] < 0):
            failures.append(
                '%s list: %s of %s rows push their last text line outside the box (worst %s px), '
                'body/footnote gap %s px -- the row is squashed and the footnote is being lost'
                % (item.get('label') or 'unnamed', item.get('footOut'), item.get('items'),
                   item.get('worst'), item.get('bodyGap')))

    squash_control = [i for i in (home_squash.get('lists') or []) if i.get('footOut')]
    print()
    print('negative control (list rows forced to 40 px):')
    if squash_control:
        print('  squashed rows detected (%s of %s in 「%s」, worst %s px outside) -- the row criterion'
              ' has teeth' % (squash_control[0].get('footOut'), squash_control[0].get('items'),
                               squash_control[0].get('label'), squash_control[0].get('worst')))
    else:
        print('  control did NOT trip -- the row criterion cannot see a squashed row')
        failures.append('row-height negative control did not trip')

    # --- 运行总览：两栏不得互相重叠 -------------------------------------------
    print()
    panels = normal.get('panels') or {}
    viewport = normal.get('viewport') or {}

    print('视口 %sx%s' % (viewport.get('w'), viewport.get('h')))
    for name in ('map', 'detail', 'summary', 'playback', 'nav'):
        b = panels.get(name)
        if not b:
            print('  %-9s MISSING' % name)
            failures.append('%s panel not found' % name)
            continue
        print('  %-9s x=%-7.1f y=%-7.1f w=%-7.1f h=%-7.1f' %
              (name, b['x'], b['y'], b['w'], b['h']))
        # A panel with no area is a panel that failed to lay out.
        if b['w'] < 1 or b['h'] < 1:
            failures.append('%s panel has no area (%.1fx%.1f)' % (name, b['w'], b['h']))

    # 运行总览现在是两栏：中间的地图面板与右栏的班次剖面不得重叠。
    for left, right in (('map', 'detail'),):
        if left in panels and right in panels and overlaps(panels[left], panels[right]):
            failures.append('%s overlaps %s' % (left, right))

    # --- 运行区域控件：必须**恰好一处**（用户 2026-10-02 第 6 条）--------------
    # 原来有两个入口指向同一件事：导航栏的下拉，以及左栏那块城市列表。后者已删；
    # 旧判据守的「右栏标题里有『返回全域』按钮」也正是被删掉的第二个入口（它只
    # 是把区域清空，与下拉重复）。判据跟着设计改，但不能就这样少一条 —— 新契约
    # 是"数出来必须等于 1"。
    # 这条判据天然双向，所以不另配负向对照：控件被删或选择器写错 → 0，重复入口
    # 长回来 → 2，两端都判失败。M29 要的"牙齿"由这两端同时提供。
    regions = normal.get('regionControls') or []
    label = normal.get('regionLabel')
    print('  区域控件 %d 处（契约：恰好 1），标签 %s' %
          (len(regions), '可见' if label and label['w'] >= 1 else '缺失/不可见'))
    for i, b in enumerate(regions):
        print('    #%d x=%-7.1f y=%-7.1f w=%-7.1f h=%-7.1f' % (i + 1, b['x'], b['y'], b['w'], b['h']))
    if len(regions) != 1:
        failures.append('expected exactly 1 region control, found %d' % len(regions))
    if regions and (regions[0]['w'] < 1 or regions[0]['h'] < 1):
        failures.append('region control has no area (%.1fx%.1f)' % (regions[0]['w'], regions[0]['h']))
    if normal.get('legacyCityPanels'):
        failures.append('left-column city list is back (%d node(s)) -- two entries for one choice'
                        % normal.get('legacyCityPanels'))
    if not label or label['w'] < 1:
        failures.append('region control has no visible label ("运行区域")')

    # 标题文字不得与右侧那枚区域角标相交。
    detail_title = normal.get('detailTitle') or {}
    text = detail_title.get('text')
    scope = detail_title.get('scope')
    print('  scopeBadge: %s' % (normal.get('scopeLabel') or '(none)'))
    if text and scope and overlaps(text, scope):
        failures.append('detail title text overlaps its region badge')

    # --- negative control -------------------------------------------------
    # Force the right column wide enough to collide with the middle one. A detector
    # that cannot see this cannot see a real overlap either.
    narrowed_panels = (narrowed.get('panels') or {})
    control_tripped = overlaps(narrowed_panels.get('map'), narrowed_panels.get('detail'))
    print()
    print('negative control (right column forced to 520px):')
    if control_tripped:
        print('  map/detail overlap detected -- detector has teeth')
    else:
        print('  control did NOT trip -- the detector cannot see overlap')
        failures.append('negative control did not trip')

    print()
    out_dir = ROOT / 'artifacts'
    out_dir.mkdir(exist_ok=True)
    (out_dir / 'workbench_layout.json').write_text(
        json.dumps({'home': home_normal, 'home_overgrown': home_grown,
                    'normal': normal, 'narrowed': narrowed, 'failures': failures},
                   ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote %s' % (out_dir / 'workbench_layout.json'))

    if failures:
        print('WORKBENCH LAYOUT FAIL')
        for item in failures:
            print('  - %s' % item)
        return 1
    print('WORKBENCH LAYOUT PASS -- home stage fully inside its container, no panel overlap, '
          'region control unique and labelled')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
