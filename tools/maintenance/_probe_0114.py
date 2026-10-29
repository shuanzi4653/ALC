"""0.11.14 验收：H-1 / H-2③ / H-3 的机器判据（不依赖浏览器）。

对照《0.11.14 更新方案》§六 的自查清单：

  H-1  mapFlights.arrivalMax ≥ 470 · mode=CAR 条数 = 848 · 逐 60 分钟地图/列表 ≥ 0.4 且不为 0 · session ≤ 1.0 MB
  H-2③ 两个通道下 planRevision 不同（且都不是 traffic-plan 开头的算法串）
  H-3  flights?minute=0 与 =300 的 total 不同

用法：python tools/maintenance/_probe_0114.py
退出码：0 全过 / 1 有失败 / 2 无法测量（建场没就绪）
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

BASE = 'https://tianchuang.shuanzi.site'
WS = 'probe-0114v'


def get(path: str, timeout: int = 180):
    request = urllib.request.Request(BASE + path, headers={
        'X-ALC-Workspace': WS, 'X-ALC-Operator': 'admin'})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        raw = resp.read()
        return len(raw), json.loads(raw)


def post(path: str, body: dict):
    data = json.dumps(body).encode('utf-8')
    request = urllib.request.Request(BASE + path, data=data, method='POST', headers={
        'X-ALC-Workspace': WS, 'X-ALC-Operator': 'admin',
        'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.loads(resp.read())


def wait_ready(seed: int = 42, mode: str | None = None):
    query = f'/api/traffic/session?scenario=live&seed={seed}&fields=slim'
    if mode:
        query += f'&mode={mode}'
    for _ in range(30):
        size, payload = get(query)
        if payload.get('status') == 'READY':
            return size, payload
        time.sleep(8)
    return 0, {'status': 'TIMEOUT'}


def inflight(rows, minute: int) -> int:
    return sum(1 for r in rows
               if (r.get('departureMinute') or 0) <= minute < (r.get('arrivalMinute') or 0))


def main() -> int:
    size, session = wait_ready()
    if session.get('status') != 'READY':
        print('建场没有就绪，无法测量（%s）' % session.get('status'))
        return 2

    checks: list[tuple[str, bool, str]] = []
    maps = session.get('mapFlights') or []
    flights = session.get('flights') or []
    stats = session.get('flightStats') or {}

    # ---- H-1 ---------------------------------------------------------------
    arrivals = [r['arrivalMinute'] for r in maps if r.get('arrivalMinute') is not None]
    arrival_max = max(arrivals) if arrivals else 0
    checks.append(('H-1 mapFlights.arrivalMax ≥ 470', arrival_max >= 470,
                   '实测 %.1f，行数 %d' % (arrival_max, len(maps))))

    car_in_map = sum(1 for r in maps if r['mode'] == 'CAR')
    car_total = stats.get('carReturned')
    checks.append(('H-1 地图载客条数 = 载客全量', car_in_map == car_total,
                   '地图 %d / 全量 %s' % (car_in_map, car_total)))

    ratios = {}
    for minute in range(0, 481, 60):
        map_n, list_n = inflight(maps, minute), inflight(flights, minute)
        ratios[minute] = (map_n, list_n, (map_n / list_n) if list_n else None)
    worst = [(m, v) for m, v in ratios.items()
             if v[1] > 0 and (v[2] is None or v[2] < 0.4 or v[0] == 0)]
    checks.append(('H-1 逐 60 分钟 地图/列表 ≥ 0.4 且不为 0', not worst,
                   ('最差档：' + '，'.join('T+%d 地图%d/列表%d' % (m, v[0], v[1]) for m, v in worst[:3]))
                   if worst else '全部达标'))

    checks.append(('H-1 session ≤ 1.0 MB', size <= 1024 * 1024, '%.1f KB' % (size / 1024)))

    # ---- H-2③ --------------------------------------------------------------
    rev_measured = session.get('planRevision')
    post('/api/traffic/weather/mode', {'mode': 'virtual', 'actor': '验收', 'reason': 'H-2 三处之一'})
    time.sleep(1)
    _, virtual_session = wait_ready(mode='virtual')
    rev_virtual = virtual_session.get('planRevision')
    checks.append(('H-2③ 两通道 planRevision 不同',
                   bool(rev_measured) and bool(rev_virtual) and rev_measured != rev_virtual,
                   'measured=%s / virtual=%s' % (rev_measured, rev_virtual)))
    checks.append(('H-2③ 修订号是可读数字（不是算法串）',
                   str(rev_measured).isdigit() and str(rev_virtual).isdigit(),
                   '实测 %s / %s' % (rev_measured, rev_virtual)))
    checks.append(('H-2 虚拟通道真的换了计划',
                   virtual_session.get('weatherMode') == 'virtual'
                   and len(virtual_session.get('flights') or []) != len(flights),
                   'flights %d → %d' % (len(flights), len(virtual_session.get('flights') or []))))

    # 切回实测（不留状态）
    post('/api/traffic/weather/mode', {'mode': 'measured', 'actor': '验收·回滚', 'reason': '复原'})

    # ---- H-3 ---------------------------------------------------------------
    totals = {}
    for minute in (0, 300):
        _, page = get('/api/traffic/flights?seed=42&scenario=live&minute=%d' % minute)
        totals[minute] = page.get('total')
    checks.append(('H-3 flights?minute 生效', totals[0] != totals[300],
                   'minute=0 → %s 班，minute=300 → %s 班' % (totals[0], totals[300])))

    print('== 0.11.14 验收 ==')
    failed = 0
    for name, ok, detail in checks:
        print(('  PASS  ' if ok else '  FAIL  ') + name + '  |  ' + detail)
        failed += 0 if ok else 1
    print('\n裁决：', 'PASS' if failed == 0 else 'FAIL（%d 项）' % failed)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
