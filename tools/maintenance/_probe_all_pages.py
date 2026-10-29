"""扫全部页面：逐页点开，收集 JS 异常 / console error / 失败请求。

为什么值得单独写一个：0.11.10 那轮的"图层开着、像素为零"与"读错来源"两个缺陷，
**自动化判据全绿、只有读截图才看见**。要在无人报错的情况下发现同类问题，
最省事的一把尺就是"把每个页面都点开，看浏览器报不报错"。

判据：
  · `Runtime.exceptionThrown` 一条都不许有（那是 JS 崩了）；
  · 4xx/5xx 请求要按 URL 归类 —— 底图瓦片 404 是常态（离线包），接口 5xx 是故障。
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
BASE = 'https://tianchuang.shuanzi.site/?v=sweep'
PORT = 9337
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-sweep')

PAGES = ['1 态势', '2 走廊', '3 处置', '4 推演', '5 日志', '运行首页', '运行总览', '气象监测']
# 0.11.22 起第 4 组叫「推演」、第 5 组只剩「日志」（复盘对照/分歧台账进了隐藏集，
# 不进导航 —— 这里按**导航上看得见的字**匹配，所以清单要跟着改，否则这两页永远扫不到。


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
        self.errors: list[str] = []
        self.failed: dict[str, int] = {}

    async def send(self, method, **params):
        self.id += 1
        await self.ws.send(json.dumps({'id': self.id, 'method': method, 'params': params}))
        return self.id

    async def call(self, method, **params):
        want = await self.send(method, **params)
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get('id') == want:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result', {})
            self._note(msg)

    def _note(self, msg):
        method = msg.get('method')
        if method == 'Runtime.exceptionThrown':
            detail = msg['params']['exceptionDetails']
            text = (detail.get('exception') or {}).get('description') or detail.get('text') or ''
            self.errors.append('EXCEPTION ' + text.strip().split('\n')[0][:220])
        elif method == 'Runtime.consoleAPICalled' and msg['params'].get('type') == 'error':
            args = ' '.join(str(a.get('value', a.get('description', '')))
                            for a in msg['params'].get('args', []))
            if args.strip():
                self.errors.append('CONSOLE ' + args.strip()[:220])
        elif method == 'Network.responseReceived':
            resp = msg['params']['response']
            if resp.get('status', 200) >= 400:
                url = resp['url'].split('?')[0]
                self.failed[url] = self.failed.get(url, 0) + 1

    async def drain(self, seconds: float):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._note(json.loads(raw))

    async def eval(self, expr):
        res = await self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        return res.get('result', {}).get('value')


async def main() -> int:
    proc = launch()
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            cdp = Cdp(ws)
            await cdp.call('Page.enable')
            await cdp.call('Runtime.enable')
            await cdp.call('Network.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                           deviceScaleFactor=1, mobile=False)
            await cdp.send('Page.navigate', url=BASE)
            await cdp.drain(28)

            for name in PAGES:
                before = len(cdp.errors)
                # 0.11.13：**按去空白后的文本匹配**。tab 文案是「1 态势」，而 DOM 里
                # `textContent` 可能带额外空格/换行（按钮里混了图标节点）——
                # 用 `===` 全等会让 5 个 tab 全部 missing，扫描看上去"跑完了"，
                # 实际一个子页都没进。这种"扫描器自己没扫到"比漏 bug 更危险。
                clicked = await cdp.eval(r"""(()=>{
                  const want=%s.replace(/\s+/g,'');
                  const els=[...document.querySelectorAll('button,a')];
                  const hit=els.find(e=>(e.textContent||'').replace(/\s+/g,'')===want);
                  if(!hit)return 'missing';
                  hit.click();return 'ok';
                })()""" % json.dumps(name, ensure_ascii=False))
                await cdp.drain(4.5)
                new = len(cdp.errors) - before
                print(f'{name:<8} 点击={clicked} 新增错误={new}')
            print()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    print('=== JS 异常 / console error ===')
    if not cdp.errors:
        print('  （无）')
    for line in dict.fromkeys(cdp.errors):
        print('  ', line)
    print('\n=== 4xx/5xx 请求（按 URL） ===')
    api = {u: n for u, n in cdp.failed.items() if '/api/' in u}
    tile = {u: n for u, n in cdp.failed.items() if '/api/' not in u}
    if api:
        for url, n in sorted(api.items()):
            print(f'  API {n:>3}x {url}')
    else:
        print('  API：（无）')
    print(f'  其它（底图/字体等）：{len(tile)} 个 URL，共 {sum(tile.values())} 次')
    return 1 if cdp.errors or api else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
