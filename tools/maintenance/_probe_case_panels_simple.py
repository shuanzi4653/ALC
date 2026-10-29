"""极简验收：案例页「3 处置」里的 `[data-case-panels]` 是否出现。

刻意**不监听任何 CDP 事件**：上一个探针同时收事件与响应，两条 recv 循环互相抢消息，
`querySelectorAll` 的返回值可能是过期的 —— 那会得出"面板没出来"的假结论。
这里只用 request/response（与 `_diff_fog_layer.py` 同一套 Cdp），并且**等够**：
未标识工作区首次建场要 60 秒上下（实测 counterfactual 从 BUILDING 63% 到 OK 用了约 50 秒）。
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
PORT = 9339
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-case2')


class Cdp:
    def __init__(self, ws):
        self.ws, self.id = ws, 0

    async def call(self, method, **params):
        self.id += 1
        await self.ws.send(json.dumps({'id': self.id, 'method': method, 'params': params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get('id') == self.id:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result', {})

    async def eval(self, expr):
        res = await self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        return res.get('result', {}).get('value')


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


CLICK = """(()=>{
  const want='3处置';
  const els=[...document.querySelectorAll('button,a')];
  const hit=els.find(e=>(e.textContent||'').replace(/\\s+/g,'')===want);
  if(!hit)return 'missing';
  hit.click();return 'ok';
})()"""

STATUS = "((document.querySelector('.traffic-build-strip')||{}).innerText||'idle').slice(0,40)"
COUNT = "document.querySelectorAll('[data-case-panels]').length"
TEXT = "((document.querySelector('[data-case-panels]')||{}).innerText||'').slice(0,160)"


async def main() -> int:
    proc = launch()
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            cdp = Cdp(ws)
            await cdp.call('Page.enable')
            await cdp.call('Runtime.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                           deviceScaleFactor=1, mobile=False)
            await cdp.call('Page.navigate', url=URL)

            for step in range(30):
                await asyncio.sleep(5)
                building = await cdp.eval(STATUS)
                if step % 3 == 0:
                    print('  等待建场… %s' % (building or 'idle'))
                if not building or building == 'idle':
                    break

            print('点击 3 处置：', await cdp.eval(CLICK))
            panels = 0
            for _ in range(24):
                await asyncio.sleep(5)
                panels = await cdp.eval(COUNT) or 0
                if panels:
                    break
            print('data-case-panels =', panels)
            if panels:
                print('面板内容：', (await cdp.eval(TEXT) or '').replace('\n', ' | ')[:160])
            print('\n裁决：', 'PASS' if panels else 'FAIL')
            return 0 if panels else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
