"""Probe the three services the way the browser actually does.

The user's symptom is "frontend waited over a minute with no flight data".
That can mean (a) a service is not listening, (b) it is listening but the plan
never finishes, or (c) it finished but the frontend never got told. These have
different fixes, so measure each separately rather than guessing.

`/traffic/session` is a start-and-poll endpoint: the first call returns
BUILDING and the caller must poll until READY before `/traffic/plan` etc. are
available. So a single call tells us almost nothing — this polls, and reports
the wall-clock breakdown between "service accepted the request" and "plan READY".
"""
import json
import time
import urllib.error
import urllib.request

# The sandbox sets HTTP_PROXY; without this, urllib routes 127.0.0.1 through the
# proxy and fails with a 502 that looks like the service being down.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, timeout=20):
    started = time.monotonic()
    try:
        with OPENER.open(url, timeout=timeout) as response:
            body = response.read().decode('utf-8', 'replace')
            return response.status, body, time.monotonic() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace'), time.monotonic() - started
    except Exception as error:  # noqa: BLE001 - report the kind, do not crash the probe
        return None, f'{type(error).__name__}: {error}', time.monotonic() - started


print('=== 存活探测 ===')
for name, url in [('Java 8085', 'http://127.0.0.1:8085/'),
                  ('Python 8600', 'http://127.0.0.1:8600/'),
                  ('Vite 5180', 'http://127.0.0.1:5180/')]:
    status, body, elapsed = get(url, timeout=8)
    print(f'  {name:<12} status={status!s:<22} {elapsed:5.2f}s  {body[:90]!r}')

print()
print('=== Python 交通接口：启动 + 轮询到 READY ===')
status, body, elapsed = get('http://127.0.0.1:8600/traffic/session', timeout=30)
print(f'  首调 status={status}  {elapsed:.2f}s')
print(f'  正文 {body[:400]}')

if status == 200:
    try:
        payload = json.loads(body)
    except Exception:
        payload = {}
    state = payload.get('status')
    print(f'  首次 status 字段 = {state!r}')
    if state == 'BUILDING':
        started = time.monotonic()
        for attempt in range(1, 121):
            time.sleep(2)
            status, body, _ = get('http://127.0.0.1:8600/traffic/session', timeout=30)
            if status != 200:
                print(f'  第 {attempt} 次轮询 status={status}，停止')
                break
            payload = json.loads(body)
            state = payload.get('status')
            waited = time.monotonic() - started
            if state == 'READY':
                flights = payload.get('flights') or payload.get('schedule') or []
                print(f'  READY 于第 {attempt} 次轮询，自首调起共 {waited:.1f}s，'
                      f'顶层字段 {sorted(payload.keys())}')
                print(f'  班次条目数 = {len(flights)}')
                break
            if attempt % 5 == 0:
                print(f'  轮询 {attempt}: status={state} progress={payload.get("progress")} '
                      f'已等 {waited:.1f}s')
        else:
            print('  轮询 120 次仍未 READY')

print()
print('=== READY 后各接口 ===')
for path in ['/traffic/plan', '/traffic/hubs', '/traffic/delivery']:
    status, body, elapsed = get(f'http://127.0.0.1:8600{path}', timeout=30)
    print(f'  {path:<18} status={status}  {elapsed:5.2f}s  {body[:120]}')
