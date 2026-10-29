"""拍下**每一个分节**实际渲染出来的样子（当前 10 个）。

为什么需要它
------------
构建不跑 CSS 布局，版面探针只量"盒子互不相交" —— **观感没有测试**。每轮改完版面
都得真的看一眼，所以这个驱动是**长期工具**，不是一次性的临时件。

它原来住在 `.run/shot_home.py`。2026-10-03 清理 `.run` 时被移除，而 `changelog/`
里有三处引用它 —— **文档链接闸门当场报了 3 条 dead**。一个每轮都要用的工具住在
"用完即弃"的目录里，本身就是架构问题；这次把它落到 `tools/probes/`，与版面探针
并列，并**复用它已经写好的那些部件**（Edge 查找、静态服务 + `/api` 转发、
形态实测、后端世代判定），而不是抄一份。

判据（每一条都来自一次真实的骗局）
----------------------------------
* **先等页面自述就绪**：`.login-mask` 不在 + 顶栏自述「计划就绪」+ 地图画布已挂载
  （直接用探针的 `READY_JS`）。只等某个 div 出现是不够的 —— ISS-0.9.25-03 里整屏
  被登录遮罩盖住时，三条存在性判据全为真，而截图只有一张"服务暂不可达"的卡片。
* **三张图的 md5 必须互不相同**：三张同 md5 ＝ 有一刀没切，而它会"成功"返回。
* **页面内的语法错误不会让 CDP 报错**：`Runtime.evaluate` 遇到语法错误是**成功
  返回**的，异常在 `result.exceptionDetails` 里，`result.result.value` 是 undefined。
  只读 value 会把语法错误读成"点了没反应"（上一版就栽在 `%r` 生成的选择器上）。
  这里把 `exceptionDetails` 读出来，并且**不再用 `%r` 拼选择器** —— 分节 key 经
  `json.dumps` 传进去。
* **后端世代**：沿用探针的 `check_generation()`。一张"未知世代"的截图比没有截图更
  糟，因为它看起来像证据。
* **截图张数必须等于分节清单的长度，而清单从 `runtime.js` 读**（§十七③）。
  原来 `VIEWS` 只覆盖 7 个分节，缺的恰好是当轮"可见化"那条的落地页 —— 一条
  "可见"结论若缺第二处判据，它与"读错了路径"无法区分。清单在这里写第二份也不行：
  新增一个分节时驱动会静默少拍一张，而"少拍一张"与"这个分节本来就没有截图"
  在产物上完全同形。所以**从被检查的源码里读清单**，两边不等就 FAIL。

跑法（**必须先有后端**，前置条件与版面探针完全相同）：

  python tools/harness/_start_services.py &        # 后台起三个服务
  backend-python/.venv/Scripts/python.exe tools/probes/_shot_screens.py
  backend-python/.venv/Scripts/python.exe tools/probes/_shot_screens.py --minute 360

`--minute N` 额外拍一张"推演时刻拨到 T+N 的首屏"（`<版本>-home-t<N>.png`）。
用户报的缺陷有一半带时刻（「T+6 之后没有飞行汽车了」），而"把时间轴拨到 T+6 再拍一张"
以前每次都靠现写一次注入 —— 现写的注入可能点错控件，也可能**点了没生效**；
这里把它钉成三件事：只认舞台里那个 `aria-label="运行推演时间"` 的滑块；用原生 value
setter 写值再派发 `input`（直接改 `el.value`，Vue 的 `@input` 收不到）；**回读**
页面自己渲染出来的时刻文字与滑块值，对不上就报错（M58）—— "拨了没生效"与
"拨过去什么都没有"必须报成两件事，不能长得一样。

对照渲染（不覆盖正式产物）：

  ALC_NO_LCD_TEXT=1 ALC_SHOT_TAG=ctrl-off backend-python/.venv/Scripts/python.exe \
      tools/probes/_shot_screens.py

`ALC_NO_LCD_TEXT` 关掉次像素抗锯齿、`ALC_SHOT_TAG` 换掉文件名前缀。两样必须一起用：
深色底上普通文字的边缘会被次像素渲染涂出红/蓝单通道边缘，一个"扫红"探针会把它们
全记成红；同一页、同一字体、只关抗锯齿再拍一套，两边相减剩下的才是真红。**只声称
"那是渲染边缘"没有牙齿，得让它在对照里自己消失**（M29）。

退出码沿用三分（M60）：**0** 拍到 · **1** 拍出来是坏的（三张同 md5）·
**2** 无法测量（缺 Edge / 缺构建产物 / 后端不在 / 世代不符）。
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _probe_workbench_layout as probe  # noqa: E402

SHOTS = probe.ROOT / 'artifacts'

# 截图窗口比版面探针大：探针要一个"普通"视口来量换行会不会发生，而这里要的是
# **大屏舞台**真实的样子（首屏按 1920×1080 设计，容器比它宽才看得出两侧是不是被撑满）。
VIEWPORT = (2150, 1250)

# 每个分节的就绪判据只问**结构**：这张屏的根在不在、上一张的根走没走。
# 两个大块是互斥挂载的（`v-if`，不是 `v-show` —— 见 TrafficWorkbench.vue 里那段
# 关于"两张 MapLibre 实例会同时活着"的注释），所以这一对判据是充分且不依赖任何
# 未知 class 的。运行首页是默认分节，不用点。
CONSOLE_READY_JS = (
    "!document.querySelector('.hstage') && !document.querySelector('.traffic-main') "
    "&& !!document.querySelector('.operations-console') && "
    "document.querySelector('.operations-console').dataset.view === '%s'"
)
VIEWS = (
    ('home', "!!document.querySelector('.hstage')"),
    ('briefing', CONSOLE_READY_JS % 'briefing'),
    ('overview', "!!document.querySelector('.traffic-main') && !document.querySelector('.hstage')"),
    # 0.9.26（Beta） 第十轮补进来的四个分节。它们此前**没有任何截图证据**，而其中
    # 三个恰好在这一轮被重写（运行日志重排版、预警中心加处置台、算法机理加三要素）。
    #
    # 就绪判据**必须逐分节不同**。五个分节共用同一个 `.operations-console` 根节点，
    # 如果判据只写"控制台在"，那么"点了没生效"与"切过去了"完全同形 —— 那正是
    # ISS-0.9.25-03 那一类假通过（存在性判据全为真，而屏幕上根本不是那一页）。
    # 所以判据落在**控制台自报的 `data-view`** 上：问对象自己，不从旁边推断。
    ('mechanism', CONSOLE_READY_JS % 'mechanism'),
    ('reference', CONSOLE_READY_JS % 'reference'),
    ('alerts', CONSOLE_READY_JS % 'alerts'),
    ('history', CONSOLE_READY_JS % 'history'),
    # 0.9.26（Beta） 第十一轮补齐剩下的三个，覆盖才等于分节清单（见 `declared_sections`）。
    # 缺的这三个正好是这一轮"可见化"那几条的落地页：气象态势、AI 标记、台账。
    ('weather', CONSOLE_READY_JS % 'weather'),
    ('assistant', CONSOLE_READY_JS % 'assistant'),
    # 调度台账是**唯一一个不渲染控制台**的分节 —— 它在 TrafficWorkbench 里直接用
    # `.traffic-table-panel`。所以判据不能沿用 `CONSOLE_READY_JS`：那会恒为假，而
    # "恒为假"的判据在失败时长得像"这个分节还没做"。
    #
    # 又因为这个面板是 `v-show`（切走时留在 DOM 里、只是 `display:none`），
    # `!!querySelector` **恒为真** —— 存在性判据在这里一点牙齿都没有。所以量
    # `offsetHeight`：切过去了才有高度，"没切过去"与"切过去了"因此可区分。
    ('schedule',
     "(() => { const el = document.querySelector('.traffic-table-panel');"
     " if (!el || el.offsetHeight <= 0) return false;"
     " return !document.querySelector('.traffic-main')"
     " && !document.querySelector('.hstage')"
     " && !document.querySelector('.operations-console'); })()"),
    # 0.11.1（Beta）新增的四页。就绪判据**不是**"控制台在"，而是
    # "控制台自报是这一页 + 这一页的核心内容已经画出来"：
    #   · 这四页的数据都是**异步**拿的（`/api/traffic/v2/*`）。只等 `data-view`
    #     会拍到一张"标题在、正文还没来"的图，而那张图与"接口挂了"完全同形；
    #   · 所以每一条都带一个**内容锚点**：剖面等走廊标题、模型卡等指标表出第一行、
    #     反事实等三张对照卡、台账等表头。锚点挑的是"有数据才有、空态没有"的元素。
    # 反事实页另有一层：它要等 `traffic.session()` 走到 `READY`（首屏那条判据已经
    # 等过计划就绪，切页时不会退回 BUILDING），因此锚点选 `.cf-head` 而不是容器。
    ('profile',
     "(() => { const c = document.querySelector('.operations-console');"
     " return !!c && c.dataset.view === 'profile'"
     " && !!document.querySelector('.corr-detail h2'); })()"),
    ('card',
     "(() => { const c = document.querySelector('.operations-console');"
     " return !!c && c.dataset.view === 'card'"
     " && !!document.querySelector('.mc-table tbody tr'); })()"),
    ('counterfactual',
     "(() => { const c = document.querySelector('.operations-console');"
     " return !!c && c.dataset.view === 'counterfactual'"
     " && !!document.querySelector('.cf-head'); })()"),
    ('ledger',
     "(() => { const c = document.querySelector('.operations-console');"
     " return !!c && c.dataset.view === 'ledger'"
     " && !!document.querySelector('.dg-hd'); })()"),
)

# 分节清单的**唯一来源**：`frontend/src/traffic/runtime.js::SECTION_NAMES`。
SECTION_NAMES_RE = re.compile(r'export const SECTION_NAMES=Object\.freeze\(\{(.*?)\}\)', re.S)
SECTION_KEY_RE = re.compile(r"(\w+)\s*:\s*'")

# `--minute` 那一次的产物键，不是分节，不参与覆盖比对。
EXTRA_SHOT_KEYS = ('home-t',)


def declared_sections():
    """从被检查的源码里读分节清单，不在本文件里写第二份。

    写第二份的后果不是"不同步"这么轻：新增一个分节时驱动会**静默少拍一张**，
    而"少拍一张"和"这个分节本来就没有截图"在产物上完全同形 —— 那正是 §十七③
    记下的那类无牙齿验收。读不到源码就报"无法测量"（exit 2），不猜。
    """
    path = probe.ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'
    try:
        source = path.read_text(encoding='utf-8')
    except OSError:
        return None
    match = SECTION_NAMES_RE.search(source)
    if not match:
        return None
    keys = SECTION_KEY_RE.findall(match.group(1))
    return keys or None


def coverage_gap():
    """返回 `(declared, covered, missing, unknown)`；读不到清单时 declared 为 None。"""
    declared = declared_sections()
    if declared is None:
        return None, None, None, None
    covered = [name for name, _ in VIEWS]
    missing = [key for key in declared if key not in covered]
    unknown = [key for key in covered
               if key not in declared
               and not any(key.startswith(prefix) for prefix in EXTRA_SHOT_KEYS)]
    return declared, covered, missing, unknown


def version_tag():
    """截图文件名里的版本号：磁盘 VERSION 去掉 `-beta` 之类的后缀。

    `ALC_SHOT_TAG` 覆盖它，用来拍**对照渲染**而**不覆盖**正式产物：一个像素级
    对照（比如关掉次像素抗锯齿）只有落在**另一个文件名**上才有意义 —— 覆盖掉正式
    那一套，两边就没得比了。
    """
    override = os.environ.get('ALC_SHOT_TAG')
    if override:
        return override
    raw = probe.disk_version() or 'unknown'
    return raw.split('-')[0]


# `ALC_NO_LCD_TEXT=1` 关掉 ClearType / LCD 次像素抗锯齿。
#
# 为什么需要：在深色底上，普通文字的四边会被次像素渲染涂出**红/蓝单通道边缘**。
# 一个"扫红"探针会把它们全部记成红 —— 于是"屏幕上有红吗"这个问题永远答不完。
# 关掉它拍一张**同页同字体**的对照，两边一减，剩下的才是真正的红色元素。
# 这是**负向对照**（M29）：只声明"那些像素是渲染边缘"是没牙齿的，得让它自己消失。
LCD_TEXT_OFF_ARG = '--disable-lcd-text'


def set_minute_js(minute):
    """把舞台上的推演时刻拨到 `minute`。

    必须走原生 value setter + 派发 `input`：`el.value = n` 只改 DOM 属性，
    Vue 的 `@input` 不会响，而"改了值但页面没动"看起来和"拨过去什么都没有"一模一样。
    """
    return r"""
(() => {
  const el = document.querySelector('.hstage input[type=range]');
  if (!el) return 'no-slider';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, %s);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return 'set';
})()
""" % (json.dumps(str(minute)))


# 拨完之后要向**页面自己**要回执，而不是相信"我们拨过了"（M58）。
# `labels` 是地图上真正画出来的载具标签数 —— 它同时是"地图有没有内容"的证据。
READ_TIMELINE_JS = r"""
(() => {
  const el = document.querySelector('.hstage input[type=range]');
  const clock = document.querySelector('.hstage .hs-playback strong');
  return JSON.stringify({
    slider: el ? el.value : null,
    clock: clock ? clock.textContent.trim() : null,
    labels: document.querySelectorAll('.city-map-labels .vehicle-label').length,
  });
})()
"""


async def capture(page_url, debug_port, tag, minute=None):
    import websockets
    import urllib.request

    targets = None
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % debug_port,
                                        timeout=2) as resp:
                targets = json.loads(resp.read().decode('utf-8'))
            if targets:
                break
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    if not targets:
        raise RuntimeError('Edge did not expose a debug target within 30s')
    page = next((t for t in targets if t.get('type') == 'page'), None)
    if page is None or not page.get('webSocketDebuggerUrl'):
        raise RuntimeError('no page target with a webSocketDebuggerUrl')

    async with websockets.connect(page['webSocketDebuggerUrl'],
                                  max_size=64 * 1024 * 1024) as ws:
        counter = [0]

        async def call(method, params=None):
            counter[0] += 1
            mid = counter[0]
            await ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=probe.PAGE_TIMEOUT_S)
                data = json.loads(raw)
                if data.get('id') == mid:
                    if 'error' in data:
                        raise RuntimeError('%s -> %s' % (method, data['error']))
                    return data.get('result', {})

        async def js(expression):
            """求值，并把**页面内的异常**也捞出来。

            `Runtime.evaluate` 遇页面内语法错误是成功返回的（异常在
            exceptionDetails 里），只读 value 会把"语法错误"读成"点了没反应" ——
            于是"点击从未发生"而脚本以为自己点过了。
            """
            result = await call('Runtime.evaluate', {'expression': expression,
                                                     'returnByValue': True})
            if result.get('exceptionDetails'):
                raise RuntimeError('page-side error: %s'
                                   % json.dumps(result['exceptionDetails'])[:300])
            return (result.get('result') or {}).get('value')

        async def wait_for(expression, what):
            deadline = time.monotonic() + probe.PAGE_TIMEOUT_S
            while time.monotonic() < deadline:
                if await js(expression):
                    return
                await asyncio.sleep(0.5)
            raise RuntimeError('%s never became true within %.0fs' % (what, probe.PAGE_TIMEOUT_S))

        await call('Page.enable')
        await call('Runtime.enable')
        # 精确指定视口，而不是依赖窗口尺寸 —— headless 下视口与窗口并不总相等，
        # 而这个页面的舞台比例是**按容器算**的（ADR-45），差几十像素就换一个数。
        await call('Emulation.setDeviceMetricsOverride',
                   {'width': VIEWPORT[0], 'height': VIEWPORT[1],
                    'deviceScaleFactor': 1, 'mobile': False})
        await call('Page.navigate', {'url': page_url})

        await wait_for("!!document.querySelector('.hstage')", 'home stage')
        await wait_for(probe.READY_JS, 'page self-reported readiness')

        digests = {}
        for name, readiness in VIEWS:
            if name != 'home':
                # 分节 key 走 json.dumps 传参：`%r` 会生成内层单引号选择器，
                # 那是一次真实的语法错误（见文件头）。
                clicked = await js('(%s)(%s)' % (probe.SELECT_SECTION_JS, json.dumps(name)))
                if clicked != 'clicked':
                    raise RuntimeError('could not switch to section %r (%s)' % (name, clicked))
            await wait_for(readiness, 'section %r' % name)
            # 结构对了以后还要给渲染一点时间（瓦片、字体）。这一段是**有意的固定等待**，
            # 而不是判据：它不影响任何断言，只是让图别拍到半张。判据仍是上面那条结构式。
            await asyncio.sleep(1.2)
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            blob = base64.b64decode(shot['data'])
            path = SHOTS / ('%s-%s.png' % (tag, name))
            path.write_bytes(blob)
            digests[name] = hashlib.md5(blob).hexdigest()
            print('  %-9s %9d bytes  md5 %s  -> %s' % (name, len(blob), digests[name][:12],
                                                        path.relative_to(probe.ROOT)))

        if minute is not None:
            # 回到首屏，把时刻拨到 T+N，再拍一张。判据全是**页面自述**：
            # 滑块的值 + 页面自己渲染出来的时刻文字，两者都对上才算拨到了。
            clicked = await js('(%s)(%s)' % (probe.SELECT_SECTION_JS, json.dumps('home')))
            if clicked != 'clicked':
                raise RuntimeError('could not switch back to the home section (%s)' % clicked)
            await wait_for("!!document.querySelector('.hstage')", 'home stage')
            applied = await js(set_minute_js(minute))
            if applied != 'set':
                raise RuntimeError('timeline slider not found (%s)' % applied)
            want_clock = 'T+%02d:' % (int(minute) // 60)
            state = None
            deadline = time.monotonic() + probe.PAGE_TIMEOUT_S
            while time.monotonic() < deadline:
                raw = await js(READ_TIMELINE_JS)
                state = json.loads(raw) if raw else {}
                try:
                    settled = abs(float(state.get('slider')) - minute) < 0.5
                except (TypeError, ValueError):
                    settled = False
                if settled and str(state.get('clock') or '').startswith(want_clock):
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError(
                    'timeline did not reach %s (clock=%r slider=%r) -- "the scrub never took '
                    'effect" and "nothing is there at T+%d" must not look alike'
                    % (want_clock, (state or {}).get('clock'), (state or {}).get('slider'), minute))
            print('  timeline   %s  on-screen vehicle labels: %s'
                  % (state.get('clock'), state.get('labels')))
            await asyncio.sleep(1.2)
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            blob = base64.b64decode(shot['data'])
            key = 'home-t%d' % int(minute)
            path = SHOTS / ('%s-%s.png' % (tag, key))
            path.write_bytes(blob)
            digests[key] = hashlib.md5(blob).hexdigest()
            print('  %-9s %9d bytes  md5 %s  -> %s' % (key, len(blob), digests[key][:12],
                                                        path.relative_to(probe.ROOT)))
        return digests


def main():
    edge = probe.find_edge()
    if edge is None:
        print('no Edge binary found -- cannot measure')
        return 2
    if not (probe.DIST / 'index.html').is_file():
        print('missing %s -- run `vite build` first' % (probe.DIST / 'index.html'))
        return 2
    if not probe.backend_up():
        print('no service on 127.0.0.1:%d -- cannot measure.' % probe.BACKEND_PORT)
        print('  start them first:  python tools/harness/_start_services.py   (background it)')
        return 2
    probe.API_MODE = probe.detect_api_mode()
    if probe.API_MODE is None:
        print('a service is listening on 127.0.0.1:%d but neither route prefix answered 200'
              % probe.BACKEND_PORT)
        return 2
    if probe.check_generation() != 'ok':
        print()
        print('backend generation unverified -- a screenshot of an unknown generation is worse')
        print('than no screenshot, because it looks like evidence. this is exit 2.')
        return 2

    # 覆盖比对放在起浏览器**之前**：一张缺分节的截图集不该被拍出来再报错 ——
    # 那样产物目录里会留下一批"看起来完整"的图，而它们少了一张。
    declared, covered, missing, unknown = coverage_gap()
    if declared is None:
        print('cannot read SECTION_NAMES from frontend/src/traffic/runtime.js -- cannot measure')
        print('  (the section list is the single source; a second copy here would go stale silently)')
        return 2
    if missing or unknown:
        print('SHOTS FAIL -- screenshot coverage must equal the declared section list')
        print('  declared %d: %s' % (len(declared), ', '.join(declared)))
        print('  covered  %d: %s' % (len(covered), ', '.join(covered)))
        print('  missing: %s' % (', '.join(missing) or '-'))
        print('  not a declared section: %s' % (', '.join(unknown) or '-'))
        return 1
    print('section coverage: %d of %d declared sections -- %s'
          % (len(covered), len(declared), ', '.join(covered)))

    tag = version_tag()
    minute = None
    if '--minute' in sys.argv:
        minute = float(sys.argv[sys.argv.index('--minute') + 1])
    httpd, port = probe.start_server(probe.DIST)
    debug_port = probe.free_port()
    # profile 落在系统临时目录并在结束时删除：以前这些 user-data-dir 堆在项目 `.run/`
    # 下，每个几十 MB，是那次 370 MB 清理的主要来源。产物目录不该承接浏览器缓存。
    profile = tempfile.mkdtemp(prefix='alc-shot-profile-')
    browser_args = [edge, '--headless=new', '--disable-gpu', '--no-first-run',
                    '--no-default-browser-check', '--disable-extensions',
                    '--remote-debugging-port=%d' % debug_port,
                    '--user-data-dir=%s' % profile,
                    '--window-size=%d,%d' % VIEWPORT, 'about:blank']
    if os.environ.get('ALC_NO_LCD_TEXT'):
        browser_args.insert(1, LCD_TEXT_OFF_ARG)
        print('lcd text: OFF (control render -- text edges carry no colour fringes)')
    print('edge:   %s' % edge)
    print('server: http://127.0.0.1:%d/index.html  (build output)' % port)
    print('viewport: %dx%d' % VIEWPORT)
    proc = subprocess.Popen(
        browser_args,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        digests = asyncio.run(capture('http://127.0.0.1:%d/index.html' % port, debug_port, tag,
                                      minute))
    except Exception as exc:  # noqa: BLE001
        print('FAILED: %s' % exc)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
        httpd.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    # 张数本身也是一条判据（§十七①：写了数字就要有量那个数字的判据）。
    # 期望 = 分节数 + （`--minute` 有值时多一张）。少一张就 FAIL，而不是"打成 OK"。
    expected = len(VIEWS) + (1 if minute is not None else 0)
    if len(digests) != expected:
        print('SHOTS FAIL -- expected %d screenshots ( %d sections%s ), got %d: %s'
              % (expected, len(VIEWS), ' + 1 timeline' if minute is not None else '',
                 len(digests), ', '.join(digests)))
        return 1
    unique = len(set(digests.values()))
    print('distinct screenshots: %d of %d' % (unique, len(digests)))
    if unique != len(digests):
        print('SHOTS FAIL -- two views produced identical bytes, so at least one cut never'
              ' happened (and it would have reported success)')
        return 1
    print('SHOTS OK -- %s' % ', '.join('%s %s' % (k, v[:8]) for k, v in digests.items()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
