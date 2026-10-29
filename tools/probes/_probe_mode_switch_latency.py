"""量「切换气象通道 → 推演重建完成」的耗时，按阶段打点。

判据独立于被测对象：这里只发 HTTP 与读载荷，不去 import 后端模块；
时间取自本机墙钟，阶段名取自后端载荷自报的 `stage`（**不自己猜阶段**）。

只用读接口 + 切换接口，两者都不在每日配额名单里，不会花掉大模型额度。
"""
import json
import os
import sys
import time
import urllib.request
import uuid

BASE = os.environ.get('ALC_BASE', 'https://tianchuang.shuanzi.site')
WORKSPACE = os.environ.get('ALC_WS') or ('perf' + uuid.uuid4().hex[:12])
TIMEOUT = 30


def call(path, *, method='GET', body=None, attempts=4):
    """一次调用，对**瞬时网络错误**重试；HTTP 错误不重试（那是被测对象在答话）。

    重试是必要的：跨公网长轮询时偶发 SSLEOF，若当成"后端坏了"就会得出方向相反的结论。
    """
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(BASE + path, data=data, method=method)
        request.add_header('X-ALC-Workspace', WORKSPACE)
        if data:
            request.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001 - 传输层瞬时错误
            last = exc
            time.sleep(1.0 + attempt)
    raise last


def wait_ready(seed, scenario, label, limit=240):
    """轮询到 READY，返回（耗时秒, 阶段轨迹）。"""
    start = time.monotonic()
    track = []
    last = None
    while time.monotonic() - start < limit:
        payload = call(f'/api/traffic/session?seed={seed}&scenario={scenario}')
        now = time.monotonic() - start
        status = payload.get('status')
        stage = payload.get('stage')
        progress = payload.get('progress')
        key = (status, stage, progress)
        if key != last:
            track.append((round(now, 2), status, stage, progress, payload.get('message')))
            last = key
        if status == 'READY':
            return round(time.monotonic() - start, 2), track, payload
        if status == 'ERROR':
            return None, track, payload
        time.sleep(0.5)
    return None, track, None


def main():
    print(f'base      = {BASE}')
    print(f'workspace = {WORKSPACE}')
    print('')
    seed = 42
    scenario = 'live'

    print('=== 1) 冷启动整场构建（measured，默认）===')
    elapsed, track, payload = wait_ready(seed, scenario, 'cold')
    for row in track:
        print(f'   +{row[0]:>6.2f}s  {row[1]:<9} {str(row[2]):<28} {str(row[3]):<5} {row[4] or ""}')
    if elapsed is None:
        print('  FAILED:', json.dumps(payload, ensure_ascii=False)[:300] if payload else 'timeout')
        return 1
    print(f'   => 冷构建 {elapsed} 秒')
    flights = len(payload.get('flights') or [])
    print(f'   flights={flights}')
    print('')

    for target in ('virtual', 'measured'):
        print(f'=== 2) 切到 {target} 并等重建完成 ===')
        t0 = time.monotonic()
        switched = call('/api/traffic/weather/mode', method='POST',
                        body={'mode': target, 'actor': 'perf-probe', 'reason': '计时'})
        switch_s = round(time.monotonic() - t0, 2)
        print(f'   POST /weather/mode -> {switch_s} s, mode={switched.get("mode")}')
        elapsed, track, payload = wait_ready(seed, scenario, target)
        for row in track:
            print(f'   +{row[0]:>6.2f}s  {row[1]:<9} {str(row[2]):<28} {str(row[3]):<5} {row[4] or ""}')
        if elapsed is None:
            print(f'   FAILED: {json.dumps(payload, ensure_ascii=False)[:300] if payload else "timeout"}')
            return 1
        total = round(switch_s + elapsed, 2)
        print(f'   => 重建 {elapsed} 秒（含切换共 {total} 秒）')
        radar = (payload.get('weather') or {}).get('radar') if isinstance(payload.get('weather'), dict) else None
        print('')

    # 3) 单帧气象读取耗时（地图图层那条链路）
    print('=== 3) GET /api/traffic/weather 单帧耗时 ===')
    for i in range(3):
        t0 = time.monotonic()
        w = call(f'/api/traffic/weather?seed={seed}&scenario={scenario}&minute=60')
        print(f'   #{i + 1} {round(time.monotonic() - t0, 2)} s  '
              f'radar.available={w.get("radar", {}).get("available")} '
              f'radar.error={str(w.get("radar", {}).get("error"))[:60]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
