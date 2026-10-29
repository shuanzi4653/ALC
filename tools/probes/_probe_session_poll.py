"""Reproduce the browser's exact polling loop and report what it sees.

The frontend polls `/traffic/session` every 1500 ms until `status == 'READY'`.
From the dev log, 129 polls went out and every one returned 200 — so the plan
was answering, just never becoming READY. This replays that loop and prints the
status transition, which is the fact the browser console never showed.

Note the browser calls `/api/traffic/session` (a Vite/Java proxy path); the
Python service itself serves `/traffic/session`. Both are tried so the probe
reports which hop is failing rather than assuming.
"""
import json
import time
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, timeout=60):
    started = time.monotonic()
    try:
        with OPENER.open(url, timeout=timeout) as response:
            return response.status, response.read().decode('utf-8', 'replace'), time.monotonic() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace'), time.monotonic() - started
    except Exception as error:  # noqa: BLE001
        return None, f'{type(error).__name__}: {error}', time.monotonic() - started


def poll(url, label, max_polls=90, interval=1.5):
    print(f'--- {label} ---')
    print(f'    {url}')
    first = None
    for attempt in range(1, max_polls + 1):
        status, body, elapsed = get(url)
        if status is None:
            print(f'    第 {attempt} 次：连接失败 {body}')
            return None
        if status != 200:
            print(f'    第 {attempt} 次：HTTP {status}  {body[:200]}')
            return None
        try:
            payload = json.loads(body)
        except Exception:
            print(f'    第 {attempt} 次：非 JSON  {body[:200]}')
            return None
        state = payload.get('status')
        if first is None:
            first = time.monotonic()
            print(f'    首调 {elapsed:.2f}s  顶层字段={sorted(payload.keys())}')
        waited = time.monotonic() - first
        if state == 'READY':
            flights = payload.get('flights') or []
            print(f'    >>> READY  第 {attempt} 次轮询，自首调起 {waited:.1f}s，'
                  f'班次 {len(flights)} 条')
            return payload
        if state == 'ERROR':
            print(f'    >>> ERROR  {payload.get("message")}')
            return payload
        if attempt <= 3 or attempt % 10 == 0:
            print(f'    第 {attempt:>3} 次  status={state!r}  progress={payload.get("progress")}  '
                  f'已等 {waited:.1f}s  {({k: payload[k] for k in payload if k not in ("flights",)}) if len(str(payload)) < 400 else ""}')
    print(f'    >>> {max_polls} 次轮询后仍非 READY')
    return None


poll('http://127.0.0.1:8600/traffic/session?seed=42&scenario=moving', 'Python 直连 8600')
print()
poll('http://127.0.0.1:8085/api/traffic/session?seed=42&scenario=moving', 'Java 代理 8085 /api')
