# -*- coding: utf-8 -*-
"""0.11.1 数据 ② 拉取三站 Open-Meteo 逐时值（**基线 + 特征**，不是标签）。

用途有两个，必须分清：
1. **基线**：手册 §8.6 要求"Open-Meteo 原始预报"作为三条基线之一 ——
   这是"不用 AI 的行业现状"，模型打不过它就没有存在价值；
2. **特征**：模式自己的能见度/阵风是强信号，允许模型用它，但**标签绝不取它**
   —— 标签只取 METAR 实测（`build_metar_dataset.py`）。

口径说明（写进模型卡，不许省）：
   `historical-forecast-api` 给的是**逐时值**，不带"起报时刻"。严格意义上它是
   "模式在 t 时刻对未来 t+1..t+3 的预报"，而不是"在 t 时刻起报的 3 小时预报"。
   拿它做基线是**近似**，比"没有基线"强，但必须在页面上写明这一条，不能写成
   "同一时次的业务预报"。

产出：data/training/metar/om-<ICAO>.csv
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'training' / 'metar'
HOST = 'https://historical-forecast-api.open-meteo.com/v1/forecast'

STATIONS = {
    'ZYTX': (41.6398, 123.4833),
    'ZYCC': (43.9962, 125.6853),
    'ZYHB': (45.6234, 126.2500),
}
HOURLY = ('visibility,wind_gusts_10m,wind_speed_10m,temperature_2m,'
          'dew_point_2m,pressure_msl,cloud_cover,precipitation')
YEARS = range(2019, 2026)


def fetch(lat: float, lon: float, year: int) -> dict:
    url = (f'{HOST}?latitude={lat}&longitude={lon}'
           f'&start_date={year}-01-01&end_date={year}-12-31'
           f'&hourly={HOURLY}&timezone=UTC&wind_speed_unit=ms')
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ALC-tianchuang/0.11.1'})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            if 'hourly' not in payload:
                raise ValueError(payload.get('reason', 'no hourly block'))
            return payload
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:  # noqa: PERF203
            last = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f'open-meteo {lat},{lon} {year} 失败: {last}')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for station, (lat, lon) in STATIONS.items():
        rows = []
        for year in YEARS:
            payload = fetch(lat, lon, year)
            h = payload['hourly']
            keys = ('visibility', 'wind_gusts_10m', 'wind_speed_10m', 'temperature_2m',
                    'dew_point_2m', 'pressure_msl', 'cloud_cover', 'precipitation')
            n = len(h['time'])
            for i in range(n):
                rows.append({
                    'timeUtc': h['time'][i].replace(' ', 'T') + ':00Z' if 'T' not in h['time'][i]
                               else h['time'][i][:19] + 'Z',
                    **{k: h[k][i] for k in keys},
                })
            print(f'{station} {year}: {n} rows', flush=True)
        path = OUT / f'om-{station}.csv'
        with path.open('w', encoding='utf-8', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['timeUtc', 'visibility', 'wind_gusts_10m',
                                                    'wind_speed_10m', 'temperature_2m', 'dew_point_2m',
                                                    'pressure_msl', 'cloud_cover', 'precipitation'])
            writer.writeheader()
            writer.writerows(rows)
        print(f'{station}: {len(rows)} rows → {path.name}', flush=True)


if __name__ == '__main__':
    main()
