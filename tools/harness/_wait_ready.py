"""Wait until all three services answer, printing per-probe timing.

The sandbox shell cannot run ``scripts/dev.ps1`` (it throws on duplicate
``Path``/``PATH``), so readiness is checked directly over HTTP. Proxies are
bypassed because a set ``HTTP_PROXY`` would route even 127.0.0.1 through it.
"""
import json
import time
import urllib.request
import urllib.error

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TARGETS = [
    ('python', 'http://127.0.0.1:8600/health'),
    ('java', 'http://127.0.0.1:8085/api/health/live'),
    ('vite', 'http://127.0.0.1:5180/'),
]

DEADLINE = time.time() + 120
pending = {name: url for name, url in TARGETS}

while pending and time.time() < DEADLINE:
    for name, url in list(pending.items()):
        try:
            with OPENER.open(url, timeout=3) as resp:
                body = resp.read(200).decode('utf-8', 'replace')
                print(f'{name:7s} READY  {resp.status}  {body[:80]!r}', flush=True)
                del pending[name]
        except Exception as exc:  # noqa: BLE001 - probe, any failure means not up yet
            print(f'{name:7s} waiting ({type(exc).__name__})', flush=True)
    if pending:
        time.sleep(3)

print(json.dumps({'remaining': list(pending), 'all_up': not pending}, ensure_ascii=False))
