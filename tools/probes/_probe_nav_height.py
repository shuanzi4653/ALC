"""探针：顶部导航栏的高度判据（2026-10-11）。

用户报「这一行占的垂直方向宽度太多了」。修法是让控件**换行**而不是被压缩后
逐字断行，但"改好了"不能靠肉眼 —— 需要一条会红的判据。

判据（M71 的思路：量"格子的归属"，不是量存在性）：
  1. 导航栏的**行数**必须 <= 2。行数由子元素的 `offsetTop` 去重得到 ——
     不数 DOM 层级，数"屏幕上真的占了几行"。
  2. 每个控件的**渲染高度**必须 <= 一个阈值（本例 46 px：单行控件 30-40 px，
     竖排文字会到 100 px 以上）。
  3. 逐个报出超标的控件名与它的高度 —— **红的时候要能看出是谁**。
     一条只报"导航栏太高了"的判据，无法区分"气象按钮竖排"和"区域选择器换行"。

必须在**窄视口**下量：宽视口本来就不触发这个缺陷（这正是它溜过上一轮的原因）。

用法：
  python tools/probes/_probe_nav_height.py
退出码：0 通过 · 1 超标 · 2 无法测量
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _probe_workbench_layout as probe  # noqa: E402

# 用户截图的实际宽度约 2527 px @ 1.5x DPR ≈ 1685 CSS px。取 1680 复现。
# 再取一个更窄的 1280 作为第二档：缺陷在越窄时越明显。
VIEWPORTS = ((1680, 950), (1280, 900))
MAX_CONTROL_HEIGHT = 46   # 单行控件（含 6px 上下 padding）的安全上限
MAX_NAV_ROWS = 2          # 分节行 + 控件行

MEASURE_JS = r"""
(() => {
  const nav = document.querySelector('nav.operations-nav');
  if (!nav) return JSON.stringify({error: 'no nav.operations-nav'});
  const fill = nav.querySelector('.nav-fill');
  // 量"屏幕上真的占了几行"：按 offsetTop 分桶，不数 DOM 结构。
  const tops = new Set();
  for (const el of nav.children) {
    if (el.offsetHeight > 0) tops.add(Math.round(el.offsetTop / 4) * 4);
  }
  const rows = tops.size;
  const navRect = nav.getBoundingClientRect();

  // 逐个控件量高度，并给一个人能读的名字。
  const controls = [];
  const named = [
    ['.nav-fill .weather-switch', '气象通道'],
    ['.nav-fill .weather-switch .mode-btn', '气象·实测按钮'],
    ['.nav-fill .weather-switch .caption', '气象·标题'],
    ['.nav-fill .nav-demo', '演示模式'],
    ['.nav-fill .nav-density', '信息密度'],
    ['.nav-fill .nav-map-status', '地图状态'],
    ['.nav-region', '运行区域'],
    ['.nav-region select', '区域下拉'],
  ];
  for (const [sel, name] of named) {
    for (const el of nav.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if (r.height <= 0) continue;
      controls.push({name, h: Math.round(r.height), w: Math.round(r.width),
                     text: (el.innerText || '').trim().slice(0, 14)});
    }
  }
  return JSON.stringify({
    navHeight: Math.round(navRect.height), rows,
    navWidth: Math.round(navRect.width),
    controls,
    vp: [innerWidth, innerHeight],
  });
})()
"""


async def measure(port, debug_port, viewport):
    import websockets

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
        raise RuntimeError('Edge did not expose a debug target')
    page = next((t for t in targets if t.get('type') == 'page'), None)
    if page is None:
        raise RuntimeError('no page target')

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
            result = await call('Runtime.evaluate', {'expression': expression,
                                                     'returnByValue': True})
            if result.get('exceptionDetails'):
                raise RuntimeError('page-side error: %s'
                                   % json.dumps(result['exceptionDetails'])[:300])
            return (result.get('result') or {}).get('value')

        async def wait_for(expr, what):
            deadline = time.monotonic() + probe.PAGE_TIMEOUT_S
            while time.monotonic() < deadline:
                if await js(expr):
                    return
                await asyncio.sleep(0.5)
            raise RuntimeError('%s never became true' % what)

        await call('Page.enable')
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',
                   {'width': viewport[0], 'height': viewport[1],
                    'deviceScaleFactor': 1, 'mobile': False})
        await call('Page.navigate', {'url': 'http://127.0.0.1:%d/index.html' % port})
        await wait_for("!!document.querySelector('.hstage')", 'home stage')
        await wait_for(probe.READY_JS, 'page self-reported readiness')
        # 导航栏只在**非首页分节**渲染（首页走的是舞台）。切过去再量。
        clicked = await js('(%s)(%s)' % (probe.SELECT_SECTION_JS, json.dumps('briefing')))
        if clicked != 'clicked':
            raise RuntimeError('could not switch to briefing (%s)' % clicked)
        await wait_for("!!document.querySelector('nav.operations-nav')", 'operations nav')
        await asyncio.sleep(1.2)
        raw = await js(MEASURE_JS)
        return json.loads(raw) if raw else {}


def main():
    edge = probe.find_edge()
    if edge is None:
        print('no Edge binary -- cannot measure')
        return 2
    if not (probe.DIST / 'index.html').is_file():
        print('missing build output -- run `vite build` first')
        return 2
    if not probe.backend_up():
        print('no service on 127.0.0.1:%d -- start it first' % probe.BACKEND_PORT)
        return 2
    probe.API_MODE = probe.detect_api_mode()
    if probe.API_MODE is None:
        print('service up but no route prefix answered 200')
        return 2
    if probe.check_generation() != 'ok':
        print('backend generation unverified -- exit 2')
        return 2

    httpd, port = probe.start_server(probe.DIST)
    failures = 0
    try:
        for viewport in VIEWPORTS:
            debug_port = probe.free_port()
            profile = tempfile.mkdtemp(prefix='alc-nav-profile-')
            proc = subprocess.Popen(
                [edge, '--headless=new', '--disable-gpu', '--no-first-run',
                 '--no-default-browser-check', '--disable-extensions',
                 '--remote-debugging-port=%d' % debug_port,
                 '--user-data-dir=%s' % profile,
                 '--window-size=%d,%d' % viewport, 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                data = asyncio.run(measure(port, debug_port, viewport))
            except Exception as exc:  # noqa: BLE001
                print('FAILED at %dx%d: %s' % (viewport[0], viewport[1], exc))
                failures += 1
                continue
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    proc.kill()
                shutil.rmtree(profile, ignore_errors=True)

            if data.get('error'):
                print('probe error: %s' % data['error'])
                failures += 1
                continue
            vp = data.get('vp') or viewport
            print('--- viewport %dx%d ---' % (vp[0], vp[1]))
            print('  nav height %d px, rows %d, width %d'
                  % (data['navHeight'], data['rows'], data['navWidth']))
            over = [c for c in data.get('controls', []) if c['h'] > MAX_CONTROL_HEIGHT]
            for c in data.get('controls', []):
                flag = '  <-- OVER' if c['h'] > MAX_CONTROL_HEIGHT else ''
                print('    %-14s h=%-4d w=%-5d %-16s%s'
                      % (c['name'], c['h'], c['w'], c['text'], flag))
            bad = False
            if data['rows'] > MAX_NAV_ROWS:
                print('  FAIL: nav has %d rows (max %d)' % (data['rows'], MAX_NAV_ROWS))
                bad = True
            if over:
                print('  FAIL: %d control(s) taller than %d px: %s'
                      % (len(over), MAX_CONTROL_HEIGHT,
                         ', '.join('%s=%dpx' % (c['name'], c['h']) for c in over)))
                bad = True
            if bad:
                failures += 1
            else:
                print('  PASS: %d rows, tallest control %d px'
                      % (data['rows'], max((c['h'] for c in data.get('controls', [])), default=0)))
    finally:
        httpd.shutdown()

    if failures:
        print('NAV HEIGHT FAIL -- %d viewport(s) over budget' % failures)
        return 1
    print('NAV HEIGHT OK -- all viewports within budget')
    return 0


if __name__ == '__main__':
    sys.exit(main())
