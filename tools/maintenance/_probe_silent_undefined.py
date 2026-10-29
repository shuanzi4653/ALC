"""静默异常探针：逐页扫「页面上出现了 undefined / NaN / null / [object Object]」。

**为什么要有这个探针**：`_probe_all_pages.py` 只看 `Runtime.exceptionThrown` 和 4xx/5xx，
而「字段没返回 → 模板渲染成 undefined」**不会抛异常、不改状态码**。上一轮调度台账
1010 行「undefined 位模拟乘客」就是这么漏了两轮的 —— 它不报错，只是难看。

判据分两类：
  · **硬失败**：`undefined` / `NaN` / `[object Object]` —— 这些在任何中文界面里都不该出现；
  · **待确认**：`null` —— 有的地方是刻意打印的（比如 JSON 片段），要人看位置。

用法：python tools/maintenance/_probe_silent_undefined.py
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
BASE = 'https://tianchuang.shuanzi.site/?v=silent'
import os
CASE = os.environ.get('ALC_PROBE_CASE', '')
BASE = BASE + (f'&case={CASE}' if CASE else '')
PORT = 9344
PROFILE = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots\edge-silent')

# 13 个可导航页（与 SECTION_HASHES 一致）
PAGES = [
    ('运行首页', '#/situation/home'),
    ('运行总览', '#/situation/overview'),
    ('气象监测', '#/situation/weather'),
    ('走廊剖面', '#/corridor/profile'),
    ('民航情报', '#/corridor/briefing'),
    ('事件处置台', '#/dispatch/console'),
    ('调度台账', '#/dispatch/ledger'),
    ('大模型取证', '#/dispatch/evidence'),
    ('模型卡', '#/model/card'),
    ('口径与来源', '#/model/reference'),
    ('反事实对照', '#/compare/counterfactual'),
    ('分歧台账', '#/compare/ledger'),
    ('运行日志', '#/compare/log'),
]

HARD = ('undefined', 'NaN', '[object Object]')


def launch():
    PROFILE.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        EDGE, '--headless=new', f'--remote-debugging-port={PORT}',
        f'--user-data-dir={PROFILE}', '--window-size=1680,1050',
        '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run',
        '--disable-extensions', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ws_url(t=40.0):
    end = time.time() + t
    while time.time() < end:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list', timeout=2) as r:
                for tab in json.loads(r.read()):
                    if tab.get('type') == 'page':
                        return tab['webSocketDebuggerUrl']
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError('no cdp')


async def main():
    proc = launch()
    findings = []
    try:
        async with websockets.connect(ws_url(), max_size=8 * 1024 * 1024) as ws:
            seq = 0
            errors = []

            async def call(m, **p):
                nonlocal seq
                seq += 1
                want = seq
                await ws.send(json.dumps({'id': want, 'method': m, 'params': p}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get('id') == want:
                        return msg.get('result', {})
                    if msg.get('method') == 'Runtime.exceptionThrown':
                        d = msg['params']['exceptionDetails']
                        errors.append(((d.get('exception') or {}).get('description') or d.get('text') or '')[:180])

            async def js(e):
                r = await call('Runtime.evaluate', expression=e, returnByValue=True, awaitPromise=True)
                return r.get('result', {}).get('value')

            await call('Page.enable')
            await call('Runtime.enable')

            # 先建一次场，否则每页都在骨架态上扫，扫不出真实的渲染问题
            await call('Page.navigate', url=f'{BASE}/#/situation/home')
            for _ in range(20):
                st = await js(
                    "fetch('/api/traffic/session?scenario=live&seed=42&fields=slim" + (f'&case={CASE}' if CASE else '') + "')"
                    ".then(r=>r.json()).then(d=>d.status).catch(()=>'ERR')")
                if st == 'READY':
                    break
                await asyncio.sleep(8)
            print(f'（建场状态：{st}）\n')

            for label, hsh in PAGES:
                await call('Page.navigate', url=f'{BASE}/{hsh}')
                await asyncio.sleep(6)
                # 把折叠块全部展开，否则 details 里的内容扫不到
                await js("document.querySelectorAll('details').forEach(d=>d.open=true)")
                await asyncio.sleep(1)
                txt = await js("document.body?document.body.innerText:''") or ''
                page = await js('location.hash')

                hits = []
                for bad in HARD:
                    idx = txt.find(bad)
                    if idx >= 0:
                        hits.append((bad, txt[max(0, idx - 45):idx + 45].replace('\n', ' ')))
                nulls = txt.count('null')
                findings.append((label, page, hits, nulls))
                flag = 'FAIL' if hits else ('nullx%d' % nulls if nulls else 'ok')
                print(f'  [{flag:>7}] {label:<10} {page}')
                for bad, ctx in hits:
                    print(f'            ↳ {bad} … {ctx}')
    finally:
        proc.terminate()

    bad_pages = [f for f in findings if f[2]]
    print()
    print('=' * 70)
    if bad_pages:
        print(f'裁决：{len(bad_pages)} / {len(findings)} 页出现硬异常文本')
        for label, page, hits, _ in bad_pages:
            print(f'  · {label} ({page})：{[h[0] for h in hits]}')
        return 1
    print(f'裁决：PASS —— {len(findings)} 页均无 undefined / NaN / [object Object]')
    null_pages = [(l, p, n) for l, p, _, n in findings if n]
    if null_pages:
        print('（出现 null 的页面，需人看一眼是否刻意：）')
        for l, p, n in null_pages:
            print(f'  · {l} ({p})：{n} 次')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
