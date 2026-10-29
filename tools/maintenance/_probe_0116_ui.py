"""0.11.16 界面判据：把 K-8 / K-9 / K-10 三件事**在真浏览器里**读回来。

为什么不能只靠 `node --test`：本项目的教训是「判据全绿但界面上是坏的」出现过三次
（雾 60 px、地图 0 架、面板从未渲染）。K-8/K-9/K-10 全是**显示层**的事，
所以这里一律读 DOM 文本 + 存截图，不读源码。

判据（每条都打印实测值）：
  K-8  徽标在**任何时刻**都不许在"还没收到载荷"时写「不可用」；
       收到载荷后必须落到 READY/QUIET 二者之一（不许停在 PENDING）。
  K-9  判据行的能见度值带下界标记（`≥` 或 `display` 里的「下界」字样），
       且走廊列表那一格与判据行**同一个口径**（要么都带 ≥，要么都不带）。
  K-10 模型卡标题印的是**系统版本**（`0.11.15-beta`），不是写死的 `0.11.1`；
       阈值行同时出现「训练」「运行」「两者一致」。

用法：python tools/maintenance/_probe_0116_ui.py
退出码：0 全过 / 1 有判据失败 / 2 无法测量（浏览器没起来）
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
BASE = 'https://tianchuang.shuanzi.site/?v=0116ui'
PORT = 9341
ROOT = pathlib.Path(__file__).resolve().parents[2]
SHOTS = ROOT / '.run' / 'shots' / '0116'
PROFILE = ROOT / '.run' / 'shots' / 'edge-0116'


def launch():
    PROFILE.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
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
        if msg.get('method') == 'Runtime.exceptionThrown':
            detail = msg['params']['exceptionDetails']
            text = (detail.get('exception') or {}).get('description') or detail.get('text') or ''
            self.errors.append('EXCEPTION ' + text.strip().split('\n')[0][:200])
        elif msg.get('method') == 'Runtime.consoleAPICalled' and msg['params'].get('type') == 'error':
            args = ' '.join(str(a.get('value', a.get('description', '')))
                            for a in msg['params'].get('args', []))
            if args.strip():
                self.errors.append('CONSOLE ' + args.strip()[:200])

    async def drain(self, seconds: float):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._note(json.loads(raw))

    async def eval(self, expr):
        res = await self.call('Runtime.evaluate', expression=expr, returnByValue=True,
                              awaitPromise=True)
        return res.get('result', {}).get('value')

    async def shot(self, name):
        data = await self.call('Page.captureScreenshot', format='png')
        (SHOTS / f'{name}.png').write_bytes(__import__('base64').b64decode(data['data']))
        return SHOTS / f'{name}.png'

    async def click_text(self, want):
        return await self.eval(r"""(()=>{
          const w=%s.replace(/\s+/g,'');
          const els=[...document.querySelectorAll('button,a,[role=tab]')];
          const hit=els.find(e=>(e.textContent||'').replace(/\s+/g,'')===w);
          if(!hit)return 'missing';
          hit.click();return 'ok';
        })()""" % json.dumps(want, ensure_ascii=False))


async def main() -> int:
    proc = launch()
    findings: dict[str, object] = {}
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            cdp = Cdp(ws)
            await cdp.call('Page.enable')
            await cdp.call('Runtime.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                           deviceScaleFactor=1, mobile=False)
            await cdp.send('Page.navigate', url=BASE)

            # --- K-8：首屏 0.4 秒时徽标说什么 ---------------------------------
            await cdp.drain(0.4)
            early = await cdp.eval(r"""(()=>{
              const el=document.querySelector('.radar-inline');
              return el?{text:el.textContent.trim(), cls:el.className}:null;
            })()""")
            findings['k8EarlyBadge'] = early
            await cdp.drain(26)

            # --- K-8：载荷到达之后必须落到 READY/QUIET ------------------------
            late = await cdp.eval(r"""(()=>{
              const el=document.querySelector('.radar-inline');
              return el?{text:el.textContent.trim(), cls:el.className}:null;
            })()""")
            findings['k8LateBadge'] = late

            # --- K-9：走廊页的判据行与列表 --------------------------------
            print('nav 走廊 =', await cdp.click_text('2 走廊'))
            await cdp.drain(7)
            k9 = await cdp.eval(r"""(()=>{
              const rows=[...document.querySelectorAll('.corr-row')].slice(0,6)
                .map(e=>({name:(e.querySelector('.corr-row-name')||{}).textContent||'',
                          vis:((e.querySelector('.corr-row-vis')||{}).textContent||'').trim()}));
              const crit=[...document.querySelectorAll('.corr-criteria li')].map(li=>({
                metric:(li.querySelector('.c-metric')||{}).textContent||'',
                value:(li.querySelector('.c-value')||{}).textContent||'',
                src:(li.querySelector('.c-src')||{}).textContent||''}));
              return {rows, crit};
            })()""")
            findings['k9'] = k9
            await cdp.shot('k9-corridor')

            # --- K-10：模型卡 ---------------------------------------------
            print('nav 检验 =', await cdp.click_text('4 检验'))
            await cdp.drain(5)
            print('nav 模型卡 =', await cdp.click_text('模型卡'))
            await cdp.drain(8)
            k10 = await cdp.eval(r"""(()=>{
              const h=document.querySelector('.mc-hd h2');
              const th=document.querySelector('[data-modelcard-thresholds]');
              const drift=document.querySelector('.mc-drift');
              return {title:h?h.textContent.replace(/\s+/g,' ').trim():null,
                      threshold:th?th.textContent.replace(/\s+/g,' ').trim():null,
                      drift:drift?drift.textContent.trim().slice(0,80):null};
            })()""")
            findings['k10'] = k10
            await cdp.shot('k10-modelcard')

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(json.dumps(findings, ensure_ascii=False, indent=2))

    checks = {}
    early = findings.get('k8EarlyBadge') or {}
    early_text = str(early.get('text') or '')
    # 早期徽标：要么还没渲染，要么说"正在读取"，**不许**已经在报不可用。
    checks['k8_pending_not_down'] = ('不可用' not in early_text) or early == {}
    late = findings.get('k8LateBadge') or {}
    late_text = str(late.get('text') or '')
    checks['k8_settles'] = bool(late_text) and not late_text.startswith('雷达：正在读取')
    checks['k8_late_not_down'] = '不可用' not in late_text

    k9 = findings.get('k9') or {}
    crit = k9.get('crit') or []
    vis_rows = [c for c in crit if '能见度' in str(c.get('metric'))]
    vis_value = str(vis_rows[0].get('value')) if vis_rows else ''
    checks['k9_criteria_has_value'] = bool(vis_value.strip()) and '未取得' not in vis_value
    checks['k9_lower_bound_marked'] = ('≥' in vis_value) or ('下界' in vis_value)
    row_vis = [str(r.get('vis') or '') for r in (k9.get('rows') or []) if r.get('vis')]
    checks['k9_row_vis_present'] = bool(row_vis)
    # 同一口径：判据行有 ≥ 时，走廊行也必须带 ≥（反向不强制 —— 不同站可能不是下界）
    checks['k9_row_matches_criteria'] = ('≥' not in vis_value) or all('≥' in v for v in row_vis)

    k10 = findings.get('k10') or {}
    title = str(k10.get('title') or '')
    # 版本号**从 VERSION 读**，不写死 —— 写死的话每次发版这条判据都会红，
    # 而它要判的是"标题跟不跟得上系统版本"，不是"版本号等于某个字面量"（M95）。
    expected_version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    th = str(k10.get('threshold') or '')
    checks['k10_title_has_system_version'] = bool(expected_version) and expected_version in title
    # 注意前缀陷阱：`0.11.15-beta` **以** `0.11.1` 开头，用 startswith 会把正确结果判成
    # 写死。判据要看的是"标题里那个版本号后面还有没有 ' · '"，即旧字面量 `0.11.1 ·`。
    checks['k10_title_not_hardcoded'] = '0.11.1 ·' not in title
    checks['k10_threshold_row'] = ('训练' in th) and ('运行' in th) and ('一致' in th)

    print('\n=== 判据 ===')
    for key, ok in checks.items():
        print(f'  {"PASS" if ok else "FAIL"}  {key}')
    if findings.get('k8EarlyBadge'):
        print('  首屏 0.4 s 徽标：', findings['k8EarlyBadge'])
    print('  稳定后徽标：', findings.get('k8LateBadge'))
    print('  截图目录：', SHOTS)
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
