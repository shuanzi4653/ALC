"""Watch one session build and report whether `progress` ever leaves 0.

The browser's symptom is a status pinned to BUILDING with progress 0 for over a
minute. Two very different causes look identical from outside:

  A. the job is queued and never starts (pool starvation / deadlock);
  B. the job is running and simply slow, but `progress` is never published
     during the expensive phase, so the UI has nothing to show.

Telling them apart matters because (A) needs a concurrency fix while (B) needs
a progress-reporting fix. This watches the raw status for the full duration and
prints every change with a timestamp, so the difference is visible.
"""
import json
import sys
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# The seed is taken from argv so a fresh seed forces a genuinely cold build:
# reusing a seed whose plan is already cached would measure a cache hit, not
# the compute this probe exists to time.
SEED = sys.argv[1] if len(sys.argv) > 1 else '4242'
URL = f'http://127.0.0.1:8600/traffic/session?seed={SEED}&scenario=moving'


def get(url):
    with OPENER.open(url, timeout=120) as response:
        return json.loads(response.read().decode('utf-8', 'replace'))


started = time.monotonic()
last = None
changes = []
while time.monotonic() - started < 240:
    try:
        payload = get(URL)
    except Exception as error:  # noqa: BLE001
        print(f'{time.monotonic() - started:7.1f}s  请求失败 {type(error).__name__}: {error}')
        time.sleep(2)
        continue
    state = (payload.get('status'), payload.get('progress'))
    if state != last:
        elapsed = time.monotonic() - started
        changes.append((elapsed, state))
        print(f'{elapsed:7.1f}s  status={state[0]!r} progress={state[1]!r}  '
              f'字段={sorted(payload.keys())[:8]}')
        last = state
    if payload.get('status') == 'READY':
        flights = payload.get('flights') or []
        print(f'{time.monotonic() - started:7.1f}s  >>> READY 班次 {len(flights)}')
        break
    if payload.get('status') in ('ERROR', 'BUSY'):
        print(f'{time.monotonic() - started:7.1f}s  >>> {payload}')
        break
    time.sleep(2)

print()
print('状态变化序列：')
for elapsed, state in changes:
    print(f'  {elapsed:7.1f}s  {state}')
print(f'总耗时 {time.monotonic() - started:.1f}s')
