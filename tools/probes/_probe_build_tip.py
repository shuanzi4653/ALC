"""构建遮罩上那句轮换的话，真的在换吗（用户 2026-10-02 第 4 条）。

为什么必须**实测**而不是只跑单测：
`buildNote()` 的单元测试证明的是**文案逻辑**会按时秒换句（`buildNote(0)` 与
`buildNote(4)` 不同）。它证明不了"页面上真的在换" —— 遮罩的渲染条件、`v-if`、
`Transition` 的 `:key`、以及"这次构建到底跑了几秒"都在这条链上。本项目已经有过
一次同类教训：**判据全绿而屏幕上那句话根本没变**，因为量的是函数不是页面
（M39 同源：判据说的是它钉住的那个样本，不是被发布出去的东西）。

本探针量的是**页面**：加载期间按秒采样 `.traffic-build-tip` 的 `innerText`，
把观察到的取值按出现顺序列出来。

判据：
  · 遮罩出现过（否则"没换"与"根本没显示"分不清）；
  · 观察到 ≥2 个不同取值；
  · 每个取值都必须来自 `runtime.js` 的 `BUILD_NOTES`（前缀匹配，避免复制整句）；
  · 观察窗口 ≥ 8 秒而只有一个取值 → **FAIL**（低于 8 秒不下结论：
    命中本地缓存时构建可能不到 4 秒，那时候还轮不到第二句，那不是缺陷）。

用法：
    python tools/probes/_probe_build_tip.py
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.run'))

import shot_home as drv  # noqa: E402  （复用它的静态 Handler 与端口约定）

DIST = ROOT / 'frontend' / 'dist'
BACKEND = ROOT / 'backend-python'
OUT = ROOT / 'artifacts' / '_probe_build_tip.json'

# 10087：在浏览器受限端口名单之外（10086 被截图驱动占了，别抢）。
SERVE_PORT = 10087
BACKEND_PORT = drv.BACKEND_PORT

# 与 runtime.js::BUILD_NOTES 的**句子开头**对齐。用前缀而不是整句：
# 整句一旦在源码里改个标点，探针就会假失败，而它要守的是"这句话确实来自那份清单"。
EXPECTED_PREFIXES = [
    '展开雷达回波时轴',
    '按 35 dBZ 以上回波重算航路',
    '逐班复核间隔',
    '核对固定管制区穿越',
    '汇总放行队列',
]

SAMPLE_SECONDS = 30
SAMPLE_EVERY = 1.0


async def sample(debug_port):
    import urllib.request
    import websockets

    listing = None
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % debug_port, timeout=2) as resp:
                listing = json.loads(resp.read().decode('utf-8'))
            if listing:
                break
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    if not listing:
        raise RuntimeError('Edge 未在 30s 内暴露调试目标')
    page = next(t for t in listing if t.get('type') == 'page')

    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=16 * 1024 * 1024) as ws:
        counter = [0]

        async def call(method, params=None):
            counter[0] += 1
            mid = counter[0]
            await ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if data.get('id') == mid:
                    if 'error' in data:
                        raise RuntimeError('%s -> %s' % (method, data['error']))
                    return data.get('result', {})

        async def evaluate(expression):
            result = await call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
            # 页面内表达式抛异常时 `Runtime.evaluate` 是**成功返回**的，
            # 例外在 `exceptionDetails` 里 —— 只读 `.value` 会把语法错误读成
            # "这句话没变"。这一条是被真实坑过的（见 shot_home.py 的注释）。
            if result.get('exceptionDetails'):
                raise RuntimeError('页面内表达式抛异常：%s\n%s'
                                   % (result['exceptionDetails'].get('text'), expression))
            inner = result.get('result') or {}
            if inner.get('subtype') == 'error':
                raise RuntimeError('页面内表达式求值出错：%s' % inner.get('description'))
            return inner.get('value')

        await call('Page.enable')
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',
                   {'width': 2150, 'height': 1250, 'deviceScaleFactor': 1, 'mobile': False})
        await call('Page.navigate', {'url': 'http://127.0.0.1:%d/index.html' % SERVE_PORT})

        samples = []
        overlay_seen = False
        stage_texts = set()
        started = time.monotonic()
        while time.monotonic() - started < SAMPLE_SECONDS:
            state = await evaluate(
                "(() => {"
                " const ov=document.querySelector('.traffic-build-overlay');"
                " const tip=document.querySelector('.traffic-build-tip');"
                " const stage=document.querySelector('.traffic-build-card h2');"
                " return {"
                "  overlay: !!ov,"
                "  tip: tip ? (tip.innerText||'').trim() : null,"
                "  stage: stage ? (stage.innerText||'').trim() : null,"
                "  pct: (document.querySelector('.traffic-build-figure strong')||{}).innerText || null"
                " };"
                "})()")
            if state.get('overlay'):
                overlay_seen = True
                if state.get('tip'):
                    samples.append((round(time.monotonic() - started, 1), state['tip']))
                if state.get('stage'):
                    stage_texts.add(state['stage'])
            elif overlay_seen:
                # 遮罩消失（构建完成）。再多采没意义，但已经采到的照单收下。
                break
            await asyncio.sleep(SAMPLE_EVERY)

        return {
            'overlay_seen': overlay_seen,
            'observed_seconds': round(time.monotonic() - started, 1),
            'samples': samples,
            'build_stages': sorted(stage_texts),
        }


def main():
    if not (DIST / 'index.html').is_file():
        print('缺少 %s —— 先跑 vite build' % (DIST / 'index.html'))
        return 2
    if drv.port_open(SERVE_PORT):
        print('静态端口 %d 已被占用，先清掉它（netstat -ano | findstr :%d）' % (SERVE_PORT, SERVE_PORT))
        return 2

    backend = None
    httpd = None
    proc = None
    try:
        if not drv.port_open(BACKEND_PORT):
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            log = open(ROOT / '.run' / 'probe-tip-backend.log', 'w', encoding='utf-8')
            backend = subprocess.Popen([str(drv.VENV_PY), 'main.py'], cwd=str(BACKEND),
                                       stdout=log, stderr=subprocess.STDOUT, env=env)
            for _ in range(120):
                if drv.port_open(BACKEND_PORT):
                    break
                time.sleep(0.5)
        print('后端：%s' % ('就绪 127.0.0.1:%d' % BACKEND_PORT if drv.port_open(BACKEND_PORT) else '启动失败'))

        import http.server
        import socketserver
        handler = lambda *a, **kw: drv.Handler(*a, directory=str(DIST), **kw)  # noqa: E731
        httpd = socketserver.TCPServer(('127.0.0.1', SERVE_PORT), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        debug_port = drv.free_port()
        profile = ROOT / '.run' / 'probe-tip-profile'
        profile.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [drv.EDGE, '--headless=new', '--disable-gpu', '--no-first-run',
             '--no-default-browser-check', '--disable-extensions',
             '--remote-debugging-port=%d' % debug_port,
             '--user-data-dir=%s' % profile,
             '--window-size=2150,1250', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        result = asyncio.run(sample(debug_port))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if httpd is not None:
            httpd.shutdown()
        if backend is not None:
            backend.terminate()
            try:
                backend.wait(timeout=20)
            except subprocess.TimeoutExpired:
                backend.kill()

    ordered = []
    for _, tip in result['samples']:
        if not ordered or ordered[-1] != tip:
            ordered.append(tip)
    observed = sorted({tip for _, tip in result['samples']})

    print('遮罩出现过：%s' % result['overlay_seen'])
    print('观察窗口：%.1f s · 采样 %d 次' % (result['observed_seconds'], len(result['samples'])))
    print('后端报出的阶段：%s' % (result['build_stages'] or '（无）'))
    print('按出现顺序的轮换：')
    for text in ordered:
        print('  · %s' % text)

    failures = []
    if not result['overlay_seen']:
        failures.append('遮罩从未出现 —— 这一条无从判起（不是"没换"，是"没显示"）')
    if not result['samples']:
        failures.append('遮罩在，但 .traffic-build-tip 一直是空的')
    for text in observed:
        if not any(text.startswith(prefix) for prefix in EXPECTED_PREFIXES):
            failures.append('出现了一句不属于 BUILD_NOTES 的话：%s' % text)
    if result['observed_seconds'] >= 8 and len(observed) < 2:
        failures.append('观察了 %.1f s 却只有一个取值 —— 轮换没生效（<8 s 不下结论）'
                        % result['observed_seconds'])

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({'result': result, 'ordered': ordered,
                               'observed': observed, 'failures': failures},
                              ensure_ascii=False, indent=2), encoding='utf-8')

    print('')
    if failures:
        for line in failures:
            print('FAIL %s' % line)
        return 1
    print('PASS 轮换生效：观察到 %d 个不同取值 · 全部来自 BUILD_NOTES' % len(observed))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
