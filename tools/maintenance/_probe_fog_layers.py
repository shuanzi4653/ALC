"""探针：地图上那些紫色椭圆到底是谁画的（fog-rings 还是别的图层）。

这不是"看一眼截图就能定"的事：0.11.11 的像素差分给出 1876 px（判据 3000），
而截图里明明有 4 个大紫圈 —— 两种可能：
  ① 圈是 `fog-rings`，但关掉图层后 source 没清（真 bug）；
  ② 圈是别的图层（起降场缓冲/城市光晕），与雾无关（那差分就只量到了标签）。
判据只能问**地图自己**：列出 style 里所有 fill/line 层的 id 与 source，
再读 `fog-rings` 的要素数。
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
PORT = 9334
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-probe')


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


PROBE = r"""(()=>{
  // MapLibre 实例通常没有全局句柄；先从 DOM 反查：canvas 的父节点挂了 _map 或者
  // 组件的 refs。两条路都试，返回"摸到了什么"而不是猜。
  const out={globals:[],hasMap:false};
  for (const k of Object.keys(window)) {
    if (/^(map|__map|maplibre|_map)$/i.test(k) || /maplibre/i.test(k)) out.globals.push(k);
  }
  const canvas=document.querySelector('.city-map-canvas canvas');
  let map=null;
  if (canvas) {
    const host=canvas.closest('.city-map-canvas');
    // MapLibre 会在容器上挂 _map（部分版本）；Vue 组件实例也可能能拿到
    map = host?._map || host?.__map || null;
    if (!map && host && host.__vueParentComponent) {
      const inst=host.__vueParentComponent;
      map = inst.setupState?.map?.value || inst.ctx?.map || null;
    }
  }
  out.hasMap = !!map;
  if (map) {
    const style=map.getStyle();
    out.layers=(style.layers||[]).map(l=>({id:l.id,type:l.type,source:l.source}));
    const src=map.getSource('fog-rings');
    out.fogFeatures = src && src._data && src._data.features ? src._data.features.length : null;
  }
  out.fogLabels=document.querySelectorAll('.fog-label').length;
  return out;
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
            for _ in range(40):
                await asyncio.sleep(3)
                if (await cdp.eval("document.querySelectorAll('.fog-label').length") or 0) > 0:
                    break
            result = await cdp.eval(PROBE)
            print(json.dumps(result, ensure_ascii=False, indent=1)[:4000])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
