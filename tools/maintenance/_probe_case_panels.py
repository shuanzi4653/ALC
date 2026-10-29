"""验收 0.11.13 的修复：案例页的「反事实判据面板」现在能不能加载出来。

0.11.13 之前 `OperationsConsole.vue` 里 `session.value` 误用（props 当 ref），
watch 的 getter 一读就抛 `ReferenceError`，于是：
  · 气象监测 / 走廊两页控制台报错；
  · `data-case-panels` 那一块**从来没出现过**。
修复后用两条判据同时看：
  ① DOM 里出现 `[data-case-panels]`；
  ② 网络里确实发出过 `/api/traffic/v2/counterfactual`。
两条缺一不可 —— 只有 DOM 可能是残留，只有请求可能是请求完又炸。
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
PORT = 9338
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-case')


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
    requests: list[str] = []
    errors: list[str] = []
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            async def send(method, **params):
                await ws.send(json.dumps({'id': 1, 'method': method, 'params': params}))

            await send('Page.enable')
            await send('Runtime.enable')
            await send('Network.enable')
            await send('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                       deviceScaleFactor=1, mobile=False)
            await send('Page.navigate', url=URL)
            # **必须先切到「3 处置」**，而且不能停在首页或走廊页：
            #   · `OperationsConsole` 只在 `!['home','overview','schedule'].includes(activeSection)` 时渲染；
            #   · `[data-case-panels]` 又只在 `view==='alerts'` 分支里（=「3 处置」）。
            # 本轮探针前后在这一条上错了两次（首页 → 2 走廊），都是"问错了地方"，
            # 症状却长得像"功能没修好"。
            await asyncio.sleep(26)
            await _call(ws, """(()=>{
              const els=[...document.querySelectorAll('button,a')];
              const hit=els.find(e=>(e.textContent||'').replace(/\s+/g,'')==='3处置');
              if(!hit)return 'missing';
              hit.click();return 'ok';
            })()""")

            deadline = time.time() + 150
            panels = 0
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)
                    if msg.get('method') == 'Network.requestWillBeSent':
                        url = msg['params']['request']['url']
                        if '/api/' in url:
                            requests.append(url.split('?')[0])
                    elif msg.get('method') == 'Runtime.exceptionThrown':
                        detail = msg['params']['exceptionDetails']
                        errors.append(str((detail.get('exception') or {}).get('description', ''))[:160])
                except asyncio.TimeoutError:
                    pass
                panels = await _count(ws)
                if panels:
                    break
            await asyncio.sleep(2)
            panels = await _count(ws)
            text = await _text(ws)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    print('data-case-panels 数量 =', panels)
    print('面板首行：', (text or '')[:110].replace('\n', ' '))
    print('案例相关请求：', [u for u in dict.fromkeys(requests) if 'counterfactual' in u or 'overview' in u])
    if errors:
        print('JS 异常：', dict.fromkeys(errors))
    ok = panels > 0 and any('counterfactual' in u for u in requests) and not errors
    print('\n裁决：', 'PASS（面板已加载且无异常）' if ok else 'FAIL')
    return 0 if ok else 1


async def _call(ws, expression):
    await ws.send(json.dumps({'id': 99, 'method': 'Runtime.evaluate',
                              'params': {'expression': expression, 'returnByValue': True,
                                         'awaitPromise': True}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get('id') == 99:
            return (msg.get('result', {}).get('result') or {}).get('value')


async def _count(ws):
    return await _call(ws, "document.querySelectorAll('[data-case-panels]').length") or 0


async def _text(ws):
    return await _call(ws, "((document.querySelector('[data-case-panels]')||{}).innerText||'')") or ''


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
