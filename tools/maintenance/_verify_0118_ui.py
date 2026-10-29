"""0.11.18 定向验收：把执行方案 §6 里能在浏览器侧验的条目逐条跑。

判据优先看**页面正文**与**地址栏**，不看内部状态变量 —— 后者只能证明"代码变了"，
不能证明"读者看到的变了"。

（用 `websockets` 的 asyncio 客户端，与 `_probe_all_pages.py` 同一套；本机没装
`websocket-client`，那是另一个包。）
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
BASE = 'https://tianchuang.shuanzi.site'
PORT = 9338
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-0118')


def launch():
    PROFILE.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        EDGE, '--headless=new', f'--remote-debugging-port={PORT}',
        f'--user-data-dir={PROFILE}', '--window-size=1680,1050',
        '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run',
        '--disable-extensions', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ws_url(timeout=40.0):
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
        want = self.id
        await self.ws.send(json.dumps({'id': want, 'method': method, 'params': params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get('id') == want:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result', {})

    async def js(self, expr):
        r = await self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        return r.get('result', {}).get('value')

    async def goto(self, url, wait=8.0, ready_timeout=180.0):
        await self.call('Page.navigate', url=url)
        await asyncio.sleep(wait)
        # **等页面自己把计划建完再判**。踩过的坑：探针用 `scenario=clear` 去"预热"，
        # 而页面读的是 `live` —— 两个不同的计划键，于是页面这边还在「正在按实测气象重建」，
        # 探针却在窗口期里问"正文有没有某个词"，量到的全是空骨架。
        # 判据改成读**页面自己**的状态：正文里那句重建提示消失为止。
        deadline = asyncio.get_event_loop().time() + ready_timeout
        while asyncio.get_event_loop().time() < deadline:
            busy = await self.js(
                "(()=>{const t=document.body?document.body.textContent:'';"
                "return /正在按|准备模拟|正在生成并复核/.test(t)})()")
            if not busy:
                return
            await asyncio.sleep(6)

    async def text(self):
        # **必须用 textContent 而不是 innerText**：调度台账与判据区都在 <details> 里，
        # 未展开时 innerText 里根本没有它们 —— 第一版探针因此误判「台账没有模拟乘客」。
        # 判据要看的是"内容在不在 DOM 里"，不是"此刻展没展开"。
        await self.js("document.querySelectorAll('details').forEach(d=>d.open=true)")
        return await self.js("document.body?document.body.textContent:''") or ''

    async def hash(self):
        return await self.js('location.hash') or ''


async def main() -> int:
    proc = launch()
    try:
        async with websockets.connect(ws_url(), max_size=8 * 1024 * 1024) as ws:
            c = Cdp(ws)
            await c.call('Page.enable')
            await c.call('Runtime.enable')

            checks = []

            # 0) **先把这个工作区建成 READY 再测**：新工作区首个请求要建场 20–120 秒，
            #    在这段时间里页面骨架是空的 —— 直接在窗口期内测"正文有没有某个词"，
            #    量到的是"还在建场"，不是"页面坏了"。
            await c.goto(f'{BASE}/?ws=verify18#/situation/home', wait=8)
            for _ in range(24):
                st = await c.js(
                    "fetch('/api/traffic/session?scenario=clear&seed=42&fields=slim',"
                    "{headers:{'X-ALC-Workspace':'verify18'}}).then(r=>r.json())"
                    ".then(d=>d.status).catch(()=>'ERR')")
                if st == 'READY':
                    break
                await asyncio.sleep(10)
            print(f'（建场完成：status={st}）')

            # ① 直达三个代表页（13 个的完整覆盖由单元判据负责）
            for path, want in (
                ('#/corridor/profile', '走廊剖面'),
                ('#/corridor/briefing', '民航情报'),
                ('#/compare/ledger', '分歧台账'),
            ):
                await c.goto(f'{BASE}/?ws=verify18{path}', wait=18)
                got = await c.hash()
                txt = await c.text()
                checks.append((f'直达 {path}', got.endswith(path.lstrip('#')) and want in txt,
                               f'hash={got} 含「{want}」={want in txt}'))

            # ② 未知 hash 纠正地址栏
            await c.goto(f'{BASE}/?ws=verify18#/nope', wait=16)
            got = await c.hash()
            checks.append(('未知 hash 纠正为首页', got.endswith('/situation/home'), f'hash={got}'))

            # ③ 调度台账 undefined
            await c.goto(f'{BASE}/?ws=verify18#/dispatch/ledger', wait=18)
            txt = await c.text()
            undef = txt.count('undefined')
            checks.append(('台账无 undefined', undef == 0, f'{undef} 次'))
            checks.append(('台账有「位模拟乘客」', '位模拟乘客' in txt, ''))

            # ④ 走廊页两档 + 阈值次数
            await c.goto(f'{BASE}/?ws=verify18#/corridor/profile', wait=18)
            # 判据区在"选中某条走廊"之后才出现
            await c.js("(document.querySelector('.corr-row')||{click(){}}).click()")
            await asyncio.sleep(3)
            txt = await c.text()
            checks.append(('判据区出现「谨慎」档', '谨慎' in txt, ''))
            thr = txt.count('（阈值')
            checks.append(('「（阈值」≤ 6 次', thr <= 6, f'{thr} 次'))

            # ⑤ 投影 tooltip
            await c.goto(f'{BASE}/?ws=verify18#/situation/home', wait=11)
            title = await c.js("(document.querySelector('[data-projection-toggle]')||{}).title||''") or ''
            checks.append(('投影 tooltip 无 16→18', '16→18' not in title, title[:44]))

            # ⑥ 版本
            await c.goto(f'{BASE}/api/health/live', wait=3)
            txt = await c.text()
            checks.append(('Java health 就绪', 'UP' in txt, txt[:70]))

            print('=' * 72)
            print('0.11.18 定向验收')
            print('=' * 72)
            bad = 0
            for label, ok, note in checks:
                print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f'  —— {note}' if note else ''))
                if not ok:
                    bad += 1
            print(f'\n{len(checks) - bad} / {len(checks)} PASS')
            return 0 if bad == 0 else 1
    finally:
        proc.terminate()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
