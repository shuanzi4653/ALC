"""Diagnostic-only static server + API shim for rendering the built workbench.

Not part of the deliverable. It exists so the 0.9.24 layout and progress work can
be *looked at* rather than reasoned about (see M28: print the actual bounding box).

Why a shim instead of the real stack: the shipped topology is Vite(5180) ->
Spring(8085) -> Python(8600), and Spring needs a Maven build. For a layout check
only two things are needed: auth must not gate the page, and the Python endpoints
must answer. So this serves `frontend/dist` and forwards `/api/<rest>` to the
Python app on 8600 with the `/api` prefix stripped -- exactly what the gateway does.

Run:
    python tools/probes/_serve_dist_stub.py 10087
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
BACKEND = 'http://127.0.0.1:8600'

# `SHIM_HOLD_SESSION=1` answers the session endpoint with a synthetic BUILDING
# response that keeps climbing, so the progress overlay stays on screen long enough
# to be photographed. It is for *visual* inspection of the overlay only: the real
# per-phase percentages are verified against the live backend by
# tools/probes/_probe_build_progress.py, because a stub can only prove what the
# stub says.
HOLD = os.environ.get('SHIM_HOLD_SESSION') == '1'
_STAGES = ((0, '准备气象快照与空域目录'), (2, '生成运行班次'),
           (10, '读取雷达回波并展开时轴'), (32, '逐班次规划航路与间隔'))
_STARTED = time.monotonic()


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send(self, status, body, content_type='application/json; charset=utf-8'):
        payload = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/auth/status':
            # `store.auth.enabled === false` is what keeps LoginOverlay out of the
            # way. Nothing else about auth is exercised by a layout check.
            self._send(200, json.dumps({'enabled': False, 'authenticated': True}))
            return
        if HOLD and path == '/api/traffic/session':
            elapsed = time.monotonic() - _STARTED
            percent = min(99, 2 + int(elapsed * 1.5))
            stage = _STAGES[0][1]
            for threshold, label in _STAGES:
                if percent >= threshold:
                    stage = label
            self._send(200, json.dumps({'status': 'BUILDING', 'progress': percent,
                                        'stage': stage, 'sessionId': 'shim-hold'}))
            return
        if path.startswith('/api/'):
            self._forward('GET', None)
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split('?', 1)[0].startswith('/api/'):
            length = int(self.headers.get('Content-Length') or 0)
            self._forward('POST', self.rfile.read(length) if length else None)
            return
        self._send(405, json.dumps({'message': 'shim: POST only forwarded under /api'}))

    def _forward(self, method, payload):
        """Forward `/api/<rest>` to the Python app with the prefix stripped --
        which is what the Spring gateway does, minus the Maven build."""
        path = self.path[len('/api'):]
        try:
            request = urllib.request.Request(BACKEND + path, data=payload, method=method)
            for name in ('Content-Type', 'Accept'):
                if self.headers.get(name):
                    request.add_header(name, self.headers[name])
            with urllib.request.urlopen(request, timeout=300) as upstream:
                self._send(upstream.status, upstream.read(),
                           upstream.headers.get('Content-Type',
                                                'application/json; charset=utf-8'))
        except urllib.error.HTTPError as error:
            self._send(error.code, error.read() or b'{}')
        except Exception as error:  # noqa: BLE001 - diagnostic shim
            self._send(502, json.dumps({'message': f'shim: {error}'}))

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 10087
    handler = partial(Handler, directory=str(DIST))
    print(f'serving {DIST} on http://127.0.0.1:{port}/ (api -> {BACKEND})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), handler).serve_forever()


if __name__ == '__main__':
    main()
