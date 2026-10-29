"""验收 H-2 的浏览器侧：切通道后自动重建，且**那次请求不走磁盘缓存**。

复测报告的铁证是 `fromDiskCache: true` + `encodedDataLength: 0` —— 一个字节都没走网络。
这里在同一位置测回来：

  ① 点「重新调度」后发出的 session 请求，URL 里必须含 `mode=`
  ② 那条响应的 `fromDiskCache` 必须是 **false**
  ③ 那次重建耗时 ≥ 3 秒（真在建，不是 0.5 秒返回旧结果）

为什么点「重新调度」而不是切通道按钮：两者走的是**同一条** `check()` 路径
（同一个 URL 构造、同一个 fetch），而「重新调度」在任何页面都点得到，不依赖通道权限。
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
URL = 'https://tianchuang.shuanzi.site/?v=h2probe'
PORT = 9341
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-h2')


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
        self.sessions: list[dict] = []
        self.errors: list[str] = []

    async def send(self, method, **params):
        self.id += 1
        await self.ws.send(json.dumps({'id': self.id, 'method': method, 'params': params}))
        return self.id

    def note(self, msg):
        method = msg.get('method')
        if method == 'Network.responseReceived':
            resp = msg['params']['response']
            if '/api/traffic/session' in resp.get('url', ''):
                self.sessions.append({
                    'url': resp['url'],
                    'status': resp.get('status'),
                    'fromDiskCache': resp.get('fromDiskCache'),
                    'fromServiceWorker': resp.get('fromServiceWorker'),
                    'encodedDataLength': resp.get('encodedDataLength'),
                    'at': time.time(),
                })
        elif method == 'Runtime.exceptionThrown':
            detail = msg['params']['exceptionDetails']
            self.errors.append(str((detail.get('exception') or {}).get('description', ''))[:160])

    async def pump(self, seconds: float, stop_on_session: bool = False):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            self.note(msg)
            if stop_on_session and self.sessions:
                return

    async def call(self, method, **params):
        want = await self.send(method, **params)
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=120)
            msg = json.loads(raw)
            if msg.get('id') == want:
                return msg.get('result', {})
            self.note(msg)

    async def eval(self, expr):
        res = await self.call('Runtime.evaluate', expression=expr, returnByValue=True,
                              awaitPromise=True)
        return res.get('result', {}).get('value')


READY = ("((document.querySelector('.traffic-session')||{}).innerText||'')")
CLICK_RESCHEDULE = """(()=>{
  const want='重新调度';
  const btn=[...document.querySelectorAll('button')].find(b=>(b.textContent||'').replace(/\\s+/g,'')===want);
  if(!btn) return 'missing';
  if(btn.disabled) return 'disabled';
  btn.click(); return 'ok';
})()"""


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
            await cdp.send('Page.navigate', url=URL)

            for _ in range(40):
                await cdp.pump(3)
                text = await cdp.eval(READY) or ''
                if '就绪' in text:
                    break
            print('首屏状态：', (await cdp.eval(READY) or '')[:40])

            cdp.sessions.clear()
            started = time.time()
            clicked = await cdp.eval(CLICK_RESCHEDULE)
            print('点「重新调度」：', clicked)

            # 收到第一条 session 响应后再等 1 秒，让 encodedDataLength 落定
            await cdp.pump(90, stop_on_session=True)
            await cdp.pump(2)
            elapsed = time.time() - started
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not cdp.sessions:
        print('没有抓到 /api/traffic/session 响应 —— 无法判定')
        return 2
    row = cdp.sessions[0]
    print('\n抓到的第一次重建请求：')
    print('  URL            ', row['url'])
    print('  status         ', row['status'])
    print('  fromDiskCache  ', row['fromDiskCache'])
    print('  encodedDataLength', row['encodedDataLength'])
    print('  点击后耗时      %.1f 秒' % elapsed)

    has_mode = 'mode=' in row['url']
    not_cached = row['fromDiskCache'] is False
    really_built = elapsed >= 3

    checks = [
        ('H-2① URL 里含 mode=', has_mode, row['url'].split('?')[-1][:90]),
        ('H-2② fromDiskCache = false', not_cached, str(row['fromDiskCache'])),
        ('H-2 重建耗时 ≥ 3 秒', really_built, '%.1f 秒' % elapsed),
        ('无 JS 异常', not cdp.errors, '；'.join(dict.fromkeys(cdp.errors))[:120] or '无'),
    ]
    print()
    failed = 0
    for name, ok, detail in checks:
        print(('  PASS  ' if ok else '  FAIL  ') + name + '  |  ' + detail)
        failed += 0 if ok else 1
    print('\n裁决：', 'PASS' if failed == 0 else 'FAIL（%d 项）' % failed)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
