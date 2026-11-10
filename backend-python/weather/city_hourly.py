# -*- coding: utf-8 -*-
"""逐市小时级气象（open-meteo hourly）：全国模型推理的输入。

为什么不用 `city_weather.py`
----------------------------
那个只取 `current`（温度/风速/能见度三项），够画屏，不够喂模型 ——
模型要露点、气压、云量、以及 3/6 小时的历史极值与趋势。这里一次取 48 小时
（过去 24 + 未来 24），把当前值与历史一起算好，供 `ml.national_model` 推理。

口径：open-meteo 是**模式输出**，不是观测；能见度尤其如此。所以全国模型输出的是
"模式能见度的低能见度概率"，界面上必须与 METAR 实测分开表述。

缓存：30 分钟（模式每小时才更新一次，取太勤没有意义）。
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

API = 'https://api.open-meteo.com/v1/forecast'
HOURLY = ('temperature_2m,dew_point_2m,relative_humidity_2m,wind_speed_10m,'
          'wind_gusts_10m,wind_direction_10m,surface_pressure,cloud_cover,visibility')
BATCH = 80
PAST_DAYS = 1
FORECAST_DAYS = 1
TTL_SECONDS = 1800.0
TIMEOUT = 60.0
CACHE_KEY = 'cities'

_lock = threading.Lock()
_cache: Dict[str, Any] = {'value': None, 'expires': 0.0, 'key': None}


def _cloud_base(temp: Optional[float], dew: Optional[float]) -> Optional[float]:
    if temp is None or dew is None:
        return None
    return max(0.0, 125.0 * (temp - dew))


def _features(city: Dict[str, Any], hourly: Dict[str, Any], elevation: Optional[float]) -> Optional[Dict[str, Any]]:
    times = hourly.get('time') or []
    if len(times) < 8:
        return None
    series = {key: hourly.get(key) or [] for key in
              ('temperature_2m', 'dew_point_2m', 'wind_speed_10m', 'wind_gusts_10m',
               'wind_direction_10m', 'surface_pressure', 'cloud_cover', 'visibility')}

    # 取"最后一个已发生的小时"：过去段里最后一格
    now_hour = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:00')
    index = max(6, len([t for t in times if t <= now_hour]) - 1)
    index = min(index, len(times) - 2)

    def at(key: str, offset: int = 0):
        values = series[key]
        position = index + offset
        return values[position] if 0 <= position < len(values) else None

    vis = at('visibility')
    if vis is None:
        return None
    temp, dew = at('temperature_2m'), at('dew_point_2m')
    wdir, gust = at('wind_direction_10m'), at('wind_gusts_10m')
    past_vis = [at('visibility', -k) for k in range(1, 7)]
    past_vis = [v for v in past_vis if v is not None]
    past_gust = [at('wind_gusts_10m', -k) for k in range(1, 4)]
    past_gust = [v for v in past_gust if v is not None]
    vis3, temp3, dew3 = at('visibility', -3), at('temperature_2m', -3), at('dew_point_2m', -3)
    qnh, qnh3 = at('surface_pressure'), at('surface_pressure', -3)
    hour = int(times[index][11:13])
    rad = hour * 2 * math.pi / 24.0
    base = _cloud_base(temp, dew)
    return {
        'visM': vis, 'gustMs': gust, 'windMs': at('wind_speed_10m'),
        'wdirSin': None if wdir is None else math.sin(math.radians(wdir)),
        'wdirCos': None if wdir is None else math.cos(math.radians(wdir)),
        'tempC': temp, 'dewC': dew,
        'dewSpread': None if (temp is None or dew is None) else temp - dew,
        'cloudBaseM': base, 'qnhHpa': qnh,
        'visMin3h': min(past_vis[:3]) if past_vis[:3] else None,
        'visMin6h': min(past_vis) if past_vis else None,
        'gustMax3h': max(past_gust) if past_gust else None,
        'windChange3h': None if (gust is None or not past_gust) else gust - past_gust[0],
        'qnhTendency3h': None if (qnh is None or qnh3 is None) else qnh - qnh3,
        'visChange3h': None if (vis is None or vis3 is None) else vis - vis3,
        'tempTendency3h': None if (temp is None or temp3 is None) else temp - temp3,
        'spreadTendency3h': None if (temp is None or dew is None or temp3 is None or dew3 is None)
                            else (temp - dew) - (temp3 - dew3),
        'hourSin': math.sin(rad), 'hourCos': math.cos(rad),
        'month': int(times[index][5:7]),
        'lat': city['lat'], 'lon': city['lon'], 'elevM': elevation,
        'miss_vis': 0.0,
        'miss_gust': 1.0 if gust is None else 0.0,
        'miss_cloud': 0.0 if base is not None else 1.0,
        'miss_temp': 1.0 if temp is None else 0.0,
        'observedAt': times[index],
    }


def fetch(rows: List[Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
    """批量取逐市小时数据并归约成特征。失败的城市留空，不补零。"""
    now = time.monotonic()
    with _lock:
        if not force and _cache['value'] and now < _cache['expires']:
            return _cache['value']

    started = time.time()
    out: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        params = {
            'latitude': ','.join(f"{row['lat']:.3f}" for row in chunk),
            'longitude': ','.join(f"{row['lon']:.3f}" for row in chunk),
            'hourly': HOURLY, 'past_days': PAST_DAYS, 'forecast_days': FORECAST_DAYS,
            'timezone': 'UTC',
        }
        try:
            response = httpx.get(API, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            bodies = payload if isinstance(payload, list) else [payload]
        except Exception as exc:  # noqa: BLE001 - 单批失败不该让整屏没数据
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            errors.append(f'batch {start // BATCH}: {str(exc)[:80]}')
            if status == 429:
                # 限流期间剩下的批次也一定失败，别把一次点击拖成 6 次超时
                errors.append('429 限流：剩余批次跳过，本次模型概率不可用（规则派生兜底）')
                break
            continue
        for city, body in zip(chunk, bodies):
            features = _features(city, body.get('hourly') or {}, body.get('elevation'))
            if features:
                out[city['name']] = features

    value = {
        'available': bool(out),
        'source': 'open-meteo hourly（公开、免密钥；模式输出，非观测）',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'cities': out, 'errors': errors,
        'elapsedMs': int((time.time() - started) * 1000),
    }
    with _lock:
        _cache.update({'value': value, 'expires': now + (TTL_SECONDS if out else 300.0)})
    return value
