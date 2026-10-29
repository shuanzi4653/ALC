"""定位"那些没有标签的圈"是谁画的。

做法：把 9 个图层开关**逐个**关掉、各截一张，再由 `_diff_layer.py` 批量比对 ——
变化量最大的那一层，就是画面上最抢眼的东西。这比读代码猜快，也避免又一次
"我以为它是城市光环"的误判（0.11.12 已经误判过一次）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'https://tianchuang.shuanzi.site/?case=fog-20250105'
PORT = 9336
OUT = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\layers')
PROFILE = OUT / 'edge-profile'


def launch():
    OUT.mkdir(parents=True, exist_ok=True)
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

    async def shot(self, name: str):
        data = (await self.call('Page.captureScreenshot', format='png',
                                captureBeyondViewport=False))['data']
        (OUT / f'{name}.png').write_bytes(base64.b64decode(data))


LABELS = r"""(()=>{
  return [...document.querySelectorAll('.layers label, .hstage-layers label, label')]
    .map((el,i)=>({i,text:(el.textContent||'').trim().slice(0,14)}))
    .filter(x=>x.text.length>1);
})()"""

TOGGLE = """(()=>{
  const labels=[...document.querySelectorAll('label')];
  const el=labels[%d];
  if(!el) return 'missing';
  const input=el.querySelector('input[type=checkbox]');
  (input||el).click();
  return 'ok';
})()"""


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
            for _ in range(45):
                await asyncio.sleep(3)
                if (await cdp.eval("document.querySelectorAll('.fog-label').length") or 0) > 0:
                    break
            labels = await cdp.eval(LABELS) or []
            print('图层开关：', [x['text'] for x in labels])
            await cdp.shot('base')
            for item in labels:
                done = await cdp.eval(TOGGLE % item['i'])
                await asyncio.sleep(2.2)
                safe = ''.join(ch if ch.isalnum() else '_' for ch in item['text'])[:12]
                await cdp.shot(f'{item["i"]:02d}_{safe}')
                await cdp.eval(TOGGLE % item['i'])   # 点回来
                await asyncio.sleep(1.2)
                print('已切', item['text'], done)
            print('截图目录：', OUT)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
