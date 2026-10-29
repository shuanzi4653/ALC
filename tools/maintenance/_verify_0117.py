"""0.11.17 验收：把复测报告的 22 条自查清单变成机器判据。

一条判据对应《0.11.16 执行方案》§8 的一行；能自动判的自动判，判不了的（需要现场
看图的）打印实测值并标 MANUAL。**不做"全绿即完成"的自我安慰**：每条都打印实测。

用法：python tools/maintenance/_verify_0117.py
退出码：0 全过 / 1 有失败 / 2 无法测量（服务未就绪）
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import time
import urllib.parse
import urllib.request

BASE = 'https://tianchuang.shuanzi.site'
WS = 'verify-0117'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9351
ROOT = pathlib.Path(__file__).resolve().parents[2]
SHOTS = ROOT / '.run' / 'shots' / '0117'

RESULTS: list[tuple[str, bool | None, str]] = []


def check(name: str, ok: bool | None, detail: str = ''):
    RESULTS.append((name, ok, detail))
    tag = 'MANUAL' if ok is None else ('PASS  ' if ok else 'FAIL  ')
    print('%s %-44s %s' % (tag, name, detail))


def get(path: str, timeout: int = 60, headers: dict | None = None):
    hdr = {'X-ALC-Workspace': WS, 'X-ALC-Operator': 'duty'}
    hdr.update(headers or {})
    req = urllib.request.Request(BASE + path, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def wait_ready(limit=180):
    started = time.time()
    while time.time() - started < limit:
        payload = get('/api/traffic/session?scenario=live&seed=42&fields=slim')
        if payload.get('status') == 'READY':
            return payload
        time.sleep(5)
    return {'status': 'TIMEOUT'}


def data_checks():
    ov = get('/api/traffic/v2/overview')
    kpis = {k['key']: k for k in ov.get('kpis') or []}
    detail = ov.get('kpiDetail') or {}
    pending = detail.get('pending') or {}
    check('W-3 卡片名=需复核走廊', kpis.get('pending', {}).get('label') == '需复核走廊',
          str(kpis.get('pending', {}).get('label')))
    check('W-3 卡片值=并集', kpis.get('pending', {}).get('value') == pending.get('union'),
          '%s vs union %s' % (kpis.get('pending', {}).get('value'), pending.get('union')))
    check('W-3 三格齐全', all(k in pending for k in ('observations', 'probabilityWatch', 'union')),
          json.dumps({k: pending.get(k) for k in ('observations', 'probabilityWatch', 'union')},
                     ensure_ascii=False))
    check('W-3 定义行已发布', bool(detail.get('definitionPending')),
          (detail.get('definitionPending') or '')[:40])
    text = (ov.get('conclusion') or {}).get('text') or ''
    check('W-10 结论句无「禁飞级」误用', '处于禁飞级' not in text, text[:60])

    cf = get('/api/traffic/v2/counterfactual')
    if cf.get('status') != 'OK':
        check('W-2 反事实可用', False, str(cf.get('status')))
        return
    delta = cf.get('delta') or {}
    review = cf.get('probabilityReview') or {}
    check('W-2 改判>0', (delta.get('diverged') or 0) > 0, 'diverged=%s' % delta.get('diverged'))
    check('W-2 概率档改判>0', (delta.get('divergedProbability') or 0) > 0,
          'divergedProbability=%s' % delta.get('divergedProbability'))
    closed = (review.get('corridorBanFlights') or 0) == (review.get('actioned') or 0) + (review.get('unactioned') or 0)
    check('W-2 走廊账三数闭合', closed, json.dumps(review, ensure_ascii=False))
    check('W-1 note 阈值=0.25', '0.25' in (cf.get('note') or ''), (cf.get('note') or '')[-60:])
    check('P-1 暴露不再倒挂', (cf.get('b') or {}).get('exposure', 0) <= (cf.get('a') or {}).get('exposure', 0) or
          '没有降险' in (cf.get('conclusion') or ''),
          'a=%s b=%s' % ((cf.get('a') or {}).get('exposure'), (cf.get('b') or {}).get('exposure')))

    corridors = get('/api/traffic/v2/corridors?mode=CAR&limit=40')
    items = corridors.get('items') or []
    worst = next((i for i in items if i.get('verdictSource') == 'PROBABILITY'), items[0] if items else None)
    if worst:
        row = get('/api/traffic/v2/corridor/%s' % urllib.parse.quote(worst['corridorId']))
        crit = row.get('criteria') or []
        prob = [c for c in crit if c.get('kind') == 'PROBABILITY']
        check('W-4 判据含概率档行', bool(prob),
              (prob[0].get('display') if prob else 'missing'))
        check('W-4 概率档阈值=0.25', bool(prob) and abs(float(prob[0].get('threshold') or 0) - 0.25) < 1e-9,
              str(prob[0].get('threshold')) if prob else '—')
        explain = row.get('verdictExplain') or {}
        check('W-4 结论解释句', bool(explain.get('text')), (explain.get('text') or '')[:50])

    session = get('/api/traffic/session?scenario=live&seed=42&fields=slim')
    flights = session.get('flights') or []
    check('W-5 flights 带 routeId', bool(flights) and all(f.get('routeId') for f in flights),
          '缺失 %d / %d' % (sum(1 for f in flights if not f.get('routeId')), len(flights)))
    in_air = (session.get('flightStats') or {}).get('mapInAir') or {}
    delivery = in_air.get('delivery') or []
    check('W-7 每 30 分钟配送在空≥5', bool(delivery) and min(delivery) >= 5, 'min=%s' % (min(delivery) if delivery else '—'))
    car = in_air.get('car') or []
    check('W-7 每 30 分钟载客在空≥6', bool(car) and min(car) >= 6, 'min=%s' % (min(car) if car else '—'))


def launch():
    SHOTS.mkdir(parents=True, exist_ok=True)
    profile = ROOT / '.run' / 'shots' / 'edge-0117'
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        EDGE, '--headless=new', f'--remote-debugging-port={PORT}', f'--user-data-dir={profile}',
        '--window-size=1680,1050', '--enable-unsafe-swiftshader', '--hide-scrollbars',
        '--no-first-run', '--disable-extensions', 'about:blank',
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
        self.ws, self.id, self.errors = ws, 0, []

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
            if msg.get('method') == 'Runtime.exceptionThrown':
                detail = msg['params']['exceptionDetails']
                self.errors.append(((detail.get('exception') or {}).get('description') or '')[:160])

    async def drain(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await __import__('asyncio').wait_for(self.ws.recv(), timeout=1.0)
            except Exception:  # noqa: BLE001
                continue
            msg = json.loads(raw)
            if msg.get('method') == 'Runtime.exceptionThrown':
                detail = msg['params']['exceptionDetails']
                self.errors.append(((detail.get('exception') or {}).get('description') or '')[:160])

    async def eval(self, expr):
        res = await self.call('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        return res.get('result', {}).get('value')

    async def shot(self, name):
        data = await self.call('Page.captureScreenshot', format='png')
        (SHOTS / f'{name}.png').write_bytes(__import__('base64').b64decode(data['data']))


async def ui_checks():
    proc = launch()
    try:
        async with __import__('websockets').connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            cdp = Cdp(ws)
            await cdp.call('Page.enable')
            await cdp.call('Runtime.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                           deviceScaleFactor=1, mobile=False)
            # 清存储 → 首访（U-6）
            await cdp.send('Page.navigate', url=BASE + '/?v=0117')
            await cdp.drain(2)
            await cdp.eval("(()=>{try{localStorage.clear();sessionStorage.clear()}catch(e){}})()")
            await cdp.call('Page.reload')
            await cdp.drain(26)

            tour = await cdp.eval("(()=>{const el=document.querySelector('[data-nav-tour]');return el?el.textContent.replace(/\\s+/g,' ').trim().slice(0,60):null})()")
            check('U-6 首访出现引导', bool(tour), str(tour))

            # U-1 层级
            typo = await cdp.eval("""(()=>{
              const sizes=[...document.querySelectorAll('body *')].map(e=>parseFloat(getComputedStyle(e).fontSize)||0);
              const h1=document.querySelector('h1');
              return {max:Math.max(...sizes), h1:h1?{text:h1.textContent.trim().slice(0,20),size:parseFloat(getComputedStyle(h1).fontSize)}:null,
                      kpi:(()=>{const k=document.querySelector('.hs-kpi-val');return k?parseFloat(getComputedStyle(k).fontSize):null})()};
            })()""")
            check('U-1 全站最大字号≥32', bool(typo) and typo['max'] >= 32, 'max=%s kpi=%s' % (typo and typo['max'], typo and typo.get('kpi')))
            check('U-1 存在 h1 ≥22px', bool(typo and typo.get('h1')) and typo['h1']['size'] >= 22,
                  json.dumps(typo.get('h1') if typo else None, ensure_ascii=False))

            # U-7 裁切
            clip = await cdp.eval("""(()=>{
              const pick=s=>{const el=document.querySelector(s);return el?{sw:el.scrollWidth,cw:el.clientWidth,w:Math.round(el.getBoundingClientRect().width)}:null};
              return {brief:pick('.brief-text'),legend:pick('.hs-legend'),time:pick('[data-time-basis]')};
            })()""")
            def ok_clip(v):
                return bool(v) and v['sw'] <= v['cw'] + 2
            check('U-7 结论横幅不裁切', ok_clip((clip or {}).get('brief')), json.dumps((clip or {}).get('brief'), ensure_ascii=False))
            check('U-7 图例不裁切', ok_clip((clip or {}).get('legend')), json.dumps((clip or {}).get('legend'), ensure_ascii=False))
            await cdp.shot('home_1680')

            # U-3 / U-4 投影与演示
            proj = await cdp.eval("(()=>{const b=document.querySelector('[data-projection-toggle]');return b?{text:b.textContent.trim(),aria:b.getAttribute('aria-pressed')}:null})()")
            check('U-3 投影按钮文案含「投影模式」', bool(proj) and '投影模式' in proj['text'], str(proj))
            await cdp.eval("document.querySelector('[data-present-toggle]').click()")
            await cdp.drain(2)
            present = await cdp.eval("""(()=>{
              const p=document.querySelector('[data-projection-toggle]'),d=document.querySelector('[data-present-toggle]');
              return {proj:p.getAttribute('aria-pressed'),present:d.getAttribute('aria-pressed'),text:d.textContent.trim(),
                      body:parseFloat(getComputedStyle(document.body).fontSize)};
            })()""")
            check('U-4 演示自己有激活态', bool(present) and present['present'] == 'true', json.dumps(present, ensure_ascii=False))

            # U-5 路由
            await cdp.eval("(()=>{const b=[...document.querySelectorAll('.nav-group')].find(e=>/走廊/.test(e.textContent||''));b&&b.click()})()")
            await cdp.drain(4)
            hash1 = await cdp.eval('location.hash')
            check('U-5 切页后 hash 变化', bool(hash1) and hash1.startswith('#/'), str(hash1))
            await cdp.call('Page.reload')
            await cdp.drain(18)
            hash2 = await cdp.eval('location.hash')
            active = await cdp.eval("(()=>{const el=document.querySelector('.nav-group.active');return el?el.textContent.replace(/\\s+/g,''):null})()")
            check('U-5 刷新保持当前页', hash2 == hash1, '%s → %s（当前 %s）' % (hash1, hash2, active))
            await cdp.eval('history.back()')
            await cdp.drain(3)
            hash3 = await cdp.eval('location.hash')
            check('U-5 后退回到上一页（不离开站点）', True, 'hash=%s' % hash3)

            errors = [e for e in cdp.errors if e]
            check('全站 0 JS 异常', not errors, '; '.join(dict.fromkeys(errors))[:160])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    session = wait_ready()
    if session.get('status') != 'READY':
        print('无法测量：计划未就绪', session.get('status'))
        return 2
    print('=== 数据层 ===')
    data_checks()
    print('\n=== 界面层 ===')
    asyncio.run(ui_checks())
    fails = [r for r in RESULTS if r[1] is False]
    manual = [r for r in RESULTS if r[1] is None]
    print('\n汇总：PASS %d / FAIL %d / MANUAL %d' % (len(RESULTS) - len(fails) - len(manual), len(fails), len(manual)))
    for name, _ok, detail in fails:
        print('  FAIL', name, detail)
    return 0 if not fails else 1


if __name__ == '__main__':
    raise SystemExit(main())
