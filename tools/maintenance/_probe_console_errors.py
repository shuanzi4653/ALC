"""抓页面上的运行时异常 —— 雾圈没画出来，先问浏览器"你报错了没有"。

0.11.11 现场：`.fog-label` 有 4 个（标签层 работа），但把 `fogRingLayers()` 的填充改成
亮绿之后，地图上**一个绿像素都没有** ⇒ `fog-rings` 这三层根本没建起来。
`syncFogLabels` 在 `paintFogCircles` 末尾，标签却在 —— 说明中间某一步抛了异常、
而另一条路径（`map.on('move', syncFogLabels)`）把标签补上了。

所以本轮只做一件事：把 `Runtime.exceptionThrown` 与 `Log.entryAdded` 全抓下来。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'https://tianchuang.shuanzi.site/?case=fog-20250105'
PORT = 9335
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-err')


def launch():
    PROFILE.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        EDGE, '--headless=new', f'--remote-debugging-port={PORT}',
        f'--user-data-dir={PROFILE}', '--window-size=1680,1050',
        '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run',
        '--disable-extensions', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ws_url(timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list', timeout=2) as resp:
                for tab in json.loads(resp.read()):
                    if tab.get('type') == 'page':
                        return tab['webSocketDebuggerUrl']
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError('CDP 没起来')


async def main() -> int:
    proc = launch()
    events: list[str] = []
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            async def send(method, **params):
                await ws.send(json.dumps({'id': 1, 'method': method, 'params': params}))

            await send('Runtime.enable')
            await send('Log.enable')
            await send('Page.enable')
            await send('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                       deviceScaleFactor=1, mobile=False)
            await send('Page.navigate', url=URL)

            async def pump(seconds: float):
                deadline = time.time() + seconds
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    method = msg.get('method')
                    if method == 'Runtime.exceptionThrown':
                        detail = msg['params']['exceptionDetails']
                        text = (detail.get('exception') or {}).get('description') \
                            or detail.get('text') or ''
                        events.append('EXCEPTION: ' + text.strip().split('\n')[0][:300])
                    elif method == 'Log.entryAdded':
                        entry = msg['params']['entry']
                        if entry.get('level') in ('error', 'warning'):
                            events.append('%s: %s' % (entry['level'].upper(), entry.get('text', '')[:300]))
                    elif method == 'Runtime.consoleAPICalled' and msg['params'].get('type') == 'error':
                        args = ' '.join(str(a.get('value', a.get('description', '')))
                                        for a in msg['params'].get('args', []))
                        events.append('CONSOLE: ' + args[:300])

            await pump(75)
            await send('Runtime.evaluate', expression="document.querySelectorAll('.fog-label').length",
                       returnByValue=True)
            await pump(5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    print('捕获 %d 条：' % len(events))
    seen = set()
    for line in events:
        if line in seen:
            continue
        seen.add(line)
        print(' ', line)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
