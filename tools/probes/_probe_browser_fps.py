"""Measure the traffic panel's per-frame cost in a real browser.

Why this exists
---------------
Every evidence pack so far has carried a line like "browser 30 FPS ... still
unmeasured", which is honest but useless: it cannot fail, and it cannot be
improved. This script replaces it with a number.

Why not Playwright
------------------
No browser-automation library is installed and the package index is unreachable
from this sandbox, so adding one is not an option. It is also not necessary:
Edge is present on the machine and speaks the Chrome DevTools Protocol, and
`websockets` is already a dependency of this project's venv. So this drives Edge
directly over CDP with no new dependency at all.

How it reads the result
-----------------------
The page writes its summary into `document.title`, and `Runtime.evaluate` is used
to fetch it. That keeps the harness to a handful of protocol calls, which is the
part most likely to break if the browser version changes.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_browser_fps.py
"""

import asyncio
import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'
PERF_DIR = FRONTEND / 'perf'

EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
)

PAGE_TIMEOUT_S = 180.0


def find_edge():
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serve the frontend tree, with the right MIME type for `.mjs`."""

    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map['.mjs'] = 'text/javascript'
    extensions_map['.js'] = 'text/javascript'

    def log_message(self, *args):
        pass


def start_server(directory):
    handler = lambda *a, **kw: QuietHandler(*a, directory=str(directory), **kw)  # noqa: E731
    httpd = socketserver.TCPServer(('127.0.0.1', 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


async def drive(edge, page_url, debug_port):
    import websockets

    # Find the page target.
    targets = None
    for _ in range(60):
        try:
            import urllib.request
            with urllib.request.urlopen(
                    'http://127.0.0.1:%d/json/list' % debug_port, timeout=2) as resp:
                targets = json.loads(resp.read().decode('utf-8'))
            if targets:
                break
        except Exception:  # noqa: BLE001 - the browser is still starting
            pass
        await asyncio.sleep(0.5)
    if not targets:
        raise RuntimeError('Edge did not expose a debug target within 30s')

    page = None
    for target in targets:
        if target.get('type') == 'page':
            page = target
            break
    if page is None:
        raise RuntimeError('no page target among %d targets' % len(targets))

    ws_url = page.get('webSocketDebuggerUrl')
    if not ws_url:
        raise RuntimeError('page target has no webSocketDebuggerUrl')

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        counter = [0]

        async def call(method, params=None):
            counter[0] += 1
            message_id = counter[0]
            await ws.send(json.dumps({'id': message_id, 'method': method,
                                      'params': params or {}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=PAGE_TIMEOUT_S)
                data = json.loads(raw)
                if data.get('id') == message_id:
                    if 'error' in data:
                        raise RuntimeError('%s -> %s' % (method, data['error']))
                    return data.get('result', {})

        await call('Page.enable')
        await call('Runtime.enable')
        await call('Page.navigate', {'url': page_url})

        # Poll the title, which the page sets when it finishes.
        deadline = time.monotonic() + PAGE_TIMEOUT_S
        while time.monotonic() < deadline:
            result = await call('Runtime.evaluate',
                                {'expression': 'document.title',
                                 'returnByValue': True})
            title = (result.get('result') or {}).get('value') or ''
            if title.startswith('ALC-FPS-DONE'):
                payload = title[len('ALC-FPS-DONE'):].strip()
                return json.loads(payload)
            if title.startswith('ALC-FPS-ERROR'):
                raise RuntimeError('page reported: %s' % title)
            await asyncio.sleep(0.5)

        # Timed out: report whatever the page managed to produce.
        result = await call('Runtime.evaluate',
                            {'expression': 'JSON.stringify(window.__ALC_FPS__ || null)',
                             'returnByValue': True})
        raise RuntimeError('timed out after %.0fs; partial=%s'
                           % (PAGE_TIMEOUT_S, (result.get('result') or {}).get('value')))


def main():
    edge = find_edge()
    if edge is None:
        print('no Edge binary found -- cannot measure')
        return 2
    if not (PERF_DIR / 'index.html').is_file():
        print('missing %s' % (PERF_DIR / 'index.html'))
        return 2

    print('edge:   %s' % edge)
    httpd, port = start_server(FRONTEND)
    debug_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix='alc-fps-profile-')
    print('server: http://127.0.0.1:%d/perf/index.html' % port)
    print('cdp:    %d' % debug_port)
    print()

    proc = subprocess.Popen(
        [edge, '--headless=new', '--disable-gpu', '--no-first-run',
         '--no-default-browser-check', '--disable-extensions',
         '--remote-debugging-port=%d' % debug_port,
         '--user-data-dir=%s' % profile_dir,
         '--window-size=1600,900',
         'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        payload = asyncio.run(drive(edge, 'http://127.0.0.1:%d/perf/index.html' % port,
                                    debug_port))
    except Exception as exc:  # noqa: BLE001 - report, always clean up
        print('FAILED: %s' % exc)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        httpd.shutdown()

    if not payload.get('ok'):
        print('page reported failure: %s' % payload.get('error'))
        return 1

    print('%-10s %9s %9s %9s %9s %9s %8s' %
          ('flights', 'mean ms', 'p50 ms', 'p95 ms', 'max ms', 'mean fps', '30fps'))
    worst_ok = True
    results = payload.get('results') or []
    for row in results:
        print('%-10d %9.3f %9.3f %9.3f %9.3f %9.1f %8s' %
              (row['flightCount'], row['meanMs'], row['p50Ms'], row['p95Ms'],
               row['maxMs'], row['meanFps'], 'ok' if row['meets30Fps'] else 'FAIL'))
        worst_ok = worst_ok and bool(row['meets30Fps'])

    out_dir = ROOT / 'artifacts'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'browser_fps.json'
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding='utf-8')
    print()
    print('wrote %s' % out_path)
    if not worst_ok:
        print('FAIL -- at least one fleet size missed the 30 FPS budget')
        return 1
    print('ok -- every fleet size held 30 FPS in the worst frame')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
