"""雾圈图层的像素差分（G-1 验收第 2 条）—— 走 Edge headless + CDP。

为什么不直接用截图工具：本会话的浏览器截图管线会超 10 MiB 限制（整页 canvas），
而 `msedge --screenshot` 又会因为页面开着 WebSocket 长连接永不 idle、卡死。
CDP 的好处是**我们能自己控制"什么时候算画完了"**：轮询 `Runtime.evaluate`，
而不是等一个 idle 事件。

判据（执行方案 §1.4-2）：
  开/关「低能见度（雾·示意）」→ **地图区**变化像素 > 3000；同时
  `.fog-label` 的数量在开时 ≥1、关时 == 0（DOM 侧的第二处证据，防"像素变了但变的是文案"）。

用法：
    python tools/maintenance/_diff_fog_layer.py
输出：`.run/shots/fog_on.png`、`fog_off.png` 与三行计数。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'https://tianchuang.shuanzi.site/?case=fog-20250105'
PORT = 9333
ROOT = pathlib.Path(r'C:\Users\12921\Desktop\ALC\.run\shots')
PROFILE = ROOT / 'edge-profile'
REGIONS_1680 = {'legend': (0, 430, 1680, 460), 'map': (0, 480, 1680, 880), 'footer': (0, 880, 1680, 1000)}


def launch() -> subprocess.Popen:
    ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [
        EDGE, '--headless=new', f'--remote-debugging-port={PORT}',
        f'--user-data-dir={PROFILE}', '--window-size=1680,1050',
        '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run',
        '--disable-extensions', '--disable-background-networking', 'about:blank',
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ws_url(timeout: float = 30.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list', timeout=2) as resp:
                tabs = json.loads(resp.read())
            for tab in tabs:
                if tab.get('type') == 'page':
                    return tab['webSocketDebuggerUrl']
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError('CDP 没起来')


class Cdp:
    def __init__(self, ws):
        self.ws = ws
        self.id = 0

    async def call(self, method: str, **params):
        self.id += 1
        await self.ws.send(json.dumps({'id': self.id, 'method': method, 'params': params}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get('id') == self.id:
                if 'error' in message:
                    raise RuntimeError(f'{method}: {message["error"]}')
                return message.get('result', {})

    async def eval(self, expression: str):
        result = await self.call('Runtime.evaluate', expression=expression,
                                 returnByValue=True, awaitPromise=True)
        return result.get('result', {}).get('value')

    async def shot(self, path: pathlib.Path):
        result = await self.call('Page.captureScreenshot', format='png', captureBeyondViewport=False)
        path.write_bytes(base64.b64decode(result['data']))
        return path


async def main() -> int:
    proc = launch()
    try:
        ws_endpoint = ws_url()
        async with websockets.connect(ws_endpoint, max_size=64 * 1024 * 1024) as ws:
            cdp = Cdp(ws)
            await cdp.call('Page.enable')
            await cdp.call('Runtime.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', width=1680, height=1050,
                           deviceScaleFactor=1, mobile=False)
            await cdp.call('Page.navigate', url=URL)

            # 等"圈真的画出来"：DOM 里 .fog-label 是每个圈一枚标签。
            deadline = time.time() + 150
            labels = 0
            while time.time() < deadline:
                await asyncio.sleep(3)
                labels = await cdp.eval("document.querySelectorAll('.fog-label').length") or 0
                stage = await cdp.eval(
                    "(document.querySelector('.brief-sentence')||{}).textContent||''")
                if labels > 0:
                    print(f'圈已出现：.fog-label = {labels}')
                    break
                print('  等待中… 标签 %d' % labels)
            else:
                print('超时：`.fog-label` 一直是 0 —— 圈没画出来', file=sys.stderr)
                await cdp.shot(ROOT / 'fog_timeout.png')
                return 1

            print('结论条：', (stage or '').strip()[:60])
            on_path = await cdp.shot(ROOT / 'fog_on.png')

            # 点「低能见度」那个图例开关（找它的 input 再 click，label 文本不稳）
            clicked = await cdp.eval("""(()=>{
              const rows=[...document.querySelectorAll('label')]
                .filter(el=>/低能见度/.test(el.textContent||''));
              if(!rows.length) return 'no-label';
              const input=rows[0].querySelector('input[type=checkbox]');
              (input||rows[0]).click();
              return 'clicked:'+rows[0].textContent.trim().slice(0,12);
            })()""")
            print('点图层：', clicked)
            await asyncio.sleep(2.5)
            off_labels = await cdp.eval("document.querySelectorAll('.fog-label').length") or 0
            off_path = await cdp.shot(ROOT / 'fog_off.png')
            print('关掉后 .fog-label =', off_labels)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f'\n截图：{on_path} / {off_path}')
    print('DOM 证据：开时 .fog-label = %d，关后 = %d' % (labels, off_labels))
    print('下一步跑差分（用带 PIL 的解释器）：')
    print('  D:/Anaconda3/python.exe tools/maintenance/_diff_layer.py --a "%s" --b "%s"'
          % (on_path, off_path))
    return 0 if (labels > 0 and off_labels == 0) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
