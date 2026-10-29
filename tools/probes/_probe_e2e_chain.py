"""Drive the browser's exact request path and time it end to end.

The browser never talks to Python directly: Vite (5180) proxies /api to Java
(8085), which proxies /api/traffic/* to Python (8600). Timing the Python port
alone therefore understates what the user waits for, and a failure anywhere in
that chain looks identical from the browser -- a spinner that never advances.
This replays a cold build through all three hops.

A fresh seed is used so the build cannot be served from cache.
"""
import json
import sys
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SEED = sys.argv[1] if len(sys.argv) > 1 else '91357'

HOPS = [
    ('python direct', f'http://127.0.0.1:8600/traffic/session?seed={SEED}&scenario=moving'),
    ('via vite->java', f'http://127.0.0.1:5180/api/traffic/session?seed={SEED}&scenario=moving'),
]


def poll(label, url):
    started = time.monotonic()
    first_tick = None
    while time.monotonic() - started < 240:
        try:
            with OPENER.open(url, timeout=180) as response:
                payload = json.loads(response.read().decode('utf-8', 'replace'))
        except Exception as error:  # noqa: BLE001
            print(f'{label:16s} {time.monotonic() - started:6.1f}s  '
                  f'请求失败 {type(error).__name__}: {error}', flush=True)
            return None
        progress = payload.get('progress')
        status = payload.get('status')
        if first_tick is None:
            first_tick = time.monotonic() - started
            print(f'{label:16s} {first_tick:6.1f}s  首帧 status={status!r} '
                  f'progress={progress!r}', flush=True)
        if status == 'READY':
            elapsed = time.monotonic() - started
            flights = payload.get('flights') or []
            print(f'{label:16s} {elapsed:6.1f}s  READY 班次={len(flights)} '
                  f'hubs={len(payload.get("hubs") or [])} '
                  f'delivery={len(payload.get("deliveryPlan") or [])}', flush=True)
            return elapsed
        if status in ('ERROR', 'BUSY'):
            print(f'{label:16s} >>> {status}: {payload.get("message")}', flush=True)
            return None
        time.sleep(1.5)
    print(f'{label:16s} 超时', flush=True)
    return None


print(f'seed={SEED}\n')
results = {}
for label, url in HOPS:
    results[label] = poll(label, url)
    print()

print(json.dumps({'seed': SEED,
                  'elapsed_s': {k: (round(v, 1) if v else None) for k, v in results.items()}},
                 ensure_ascii=False))
